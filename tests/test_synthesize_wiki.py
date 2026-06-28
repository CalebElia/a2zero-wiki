# tests/test_synthesize_wiki.py


def test_module_imports():
    """Smoke test: the module exists and exposes the expected public API."""
    from pipeline import synthesize_wiki
    assert hasattr(synthesize_wiki, "synthesize_wiki")
    assert callable(synthesize_wiki.synthesize_wiki)
    assert hasattr(synthesize_wiki, "ALL_STRATEGIES")
    assert len(synthesize_wiki.ALL_STRATEGIES) == 7
