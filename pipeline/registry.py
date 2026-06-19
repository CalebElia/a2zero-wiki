import json
import re
from pathlib import Path


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^\w\s-]", "", s)   # remove punctuation except hyphen
    s = re.sub(r"[\s_]+", "-", s)     # spaces/underscores → hyphen
    s = re.sub(r"-+", "-", s)         # collapse multiple hyphens
    return s.strip("-")


TYPE_PREFIX = {
    "actor": "actors",
    "organization": "organizations",
    "initiative": "initiatives",
    "funding": "funding",
    "topic": "topics",
    "location": "locations",
    "technology": "technologies",
}


class EntityRegistry:
    def __init__(self, path: str):
        self.path = Path(path)
        self._data: dict = json.loads(self.path.read_text())

    def _save(self):
        self.path.write_text(json.dumps(self._data, indent=2))

    def register(self, name: str, entity_type: str) -> str:
        existing = self.resolve(name)
        if existing:
            return existing
        prefix = TYPE_PREFIX.get(entity_type, entity_type + "s")
        slug = f"{prefix}/{slugify(name)}"
        self._data[name] = {
            "canonical": slug,
            "type": entity_type,
            "aliases": [],
        }
        self._save()
        return slug

    def add_alias(self, alias: str, canonical: str) -> str:
        for entry in self._data.values():
            if entry["canonical"] == canonical:
                if alias not in entry["aliases"]:
                    entry["aliases"].append(alias)
                self._save()
                return canonical
        raise ValueError(f"canonical not found: {canonical}")

    def resolve(self, name: str) -> str | None:
        if name in self._data:
            return self._data[name]["canonical"]
        for entry in self._data.values():
            if name in entry.get("aliases", []):
                return entry["canonical"]
        return None
