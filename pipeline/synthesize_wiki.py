"""Phase C of the ingest cycle: build the L1 strategy synthesis sections
and the L2 wiki/digest.md from the clean post-lint entity layer.

See docs/architecture/knowledge-synthesis-architecture.md for design rationale.
"""
from pathlib import Path


ALL_STRATEGIES = [
    "strategies/strategy-1-renewable-grid",
    "strategies/strategy-2-electrification",
    "strategies/strategy-3-building-efficiency",
    "strategies/strategy-4-vmt-reduction",
    "strategies/strategy-5-materials-waste",
    "strategies/strategy-6-resilience",
    "strategies/strategy-7-engagement",
]


def synthesize_wiki(
    wiki_root: str,
    strategies: list[str] | None = None,
    digest_only: bool = False,
    aliases_path: str = "registry/entity_aliases.json",
) -> dict:
    """Phase C orchestration: rebuild L1 synthesis sections + write digest.md.

    Args:
        wiki_root: vault root path (typically "wiki").
        strategies: optional list of strategy slugs to rebuild. If None,
            rebuild all 7 strategy pages.
        digest_only: skip L1 rebuild, just regenerate digest.md from existing
            synthesis: blocks.

    Returns:
        dict with keys: `strategies_rebuilt` (list of slugs), `digest_path`.
    """
    raise NotImplementedError("Pending tasks 2-9")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="A2Zero wiki synthesis — Phase C of the ingest cycle"
    )
    parser.add_argument("--wiki-root", default="wiki")
    parser.add_argument(
        "--strategy",
        action="append",
        dest="strategies",
        help="rebuild only this strategy (repeatable). Default: all 7.",
    )
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="skip L1 rebuild; regenerate digest.md from existing synthesis: blocks",
    )
    args = parser.parse_args()

    result = synthesize_wiki(
        wiki_root=args.wiki_root,
        strategies=args.strategies,
        digest_only=args.digest_only,
    )
    print(f"[synthesize_wiki] rebuilt {len(result['strategies_rebuilt'])} strategies")
    print(f"[synthesize_wiki] wrote digest → {result['digest_path']}")
