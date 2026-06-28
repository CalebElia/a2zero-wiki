# tests/test_synthesize_wiki.py
import pytest
from unittest.mock import MagicMock


def test_module_imports():
    """Smoke test: the module exists and exposes the expected public API."""
    from pipeline import synthesize_wiki
    assert hasattr(synthesize_wiki, "synthesize_wiki")
    assert callable(synthesize_wiki.synthesize_wiki)
