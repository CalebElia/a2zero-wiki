import json
import tempfile
import os
import pytest
from pipeline.registry import EntityRegistry


@pytest.fixture
def tmp_registry(tmp_path):
    path = tmp_path / "entity_aliases.json"
    path.write_text(json.dumps({}))
    return EntityRegistry(str(path))


def test_register_new_entity(tmp_registry):
    slug = tmp_registry.register("Missy Stults", entity_type="actor")
    assert slug == "actors/missy-stults"


def test_register_returns_same_slug_for_same_name(tmp_registry):
    slug1 = tmp_registry.register("Missy Stults", entity_type="actor")
    slug2 = tmp_registry.register("Missy Stults", entity_type="actor")
    assert slug1 == slug2


def test_register_alias_returns_canonical(tmp_registry):
    tmp_registry.register("Missy Stults", entity_type="actor")
    slug = tmp_registry.add_alias("missy-stults-director", "actors/missy-stults")
    assert slug == "actors/missy-stults"


def test_resolve_known_alias(tmp_registry):
    tmp_registry.register("Missy Stults", entity_type="actor")
    tmp_registry.add_alias("Stults", "actors/missy-stults")
    assert tmp_registry.resolve("Stults") == "actors/missy-stults"


def test_resolve_unknown_returns_none(tmp_registry):
    assert tmp_registry.resolve("Unknown Person") is None


def test_registry_persists_to_disk(tmp_path):
    path = tmp_path / "entity_aliases.json"
    path.write_text(json.dumps({}))
    reg = EntityRegistry(str(path))
    reg.register("OSI", entity_type="organization")
    # reload from disk
    reg2 = EntityRegistry(str(path))
    assert reg2.resolve("OSI") == "organizations/osi"


def test_slugify_handles_special_chars(tmp_registry):
    slug = tmp_registry.register("U.S. DOE", entity_type="organization")
    assert slug == "organizations/us-doe"
