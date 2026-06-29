import os
import pytest
from unittest.mock import MagicMock, patch


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_anthropic_response(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.stop_reason = "end_turn"
    return msg


def _make_stream_ctx(text: str):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.get_final_message.return_value = _make_anthropic_response(text)
    return ctx


# ── chat() — Anthropic ────────────────────────────────────────────────────────

def test_chat_anthropic_returns_text(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import chat
    with patch("pipeline.llm.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value.messages.create.return_value = (
            _make_anthropic_response("hello world")
        )
        result = chat(
            system="You are a test.",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=100,
            model_hint="extraction",
        )
    assert result == "hello world"


def test_chat_uses_correct_anthropic_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import chat
    with patch("pipeline.llm.anthropic") as mock_anthropic:
        mock_client = mock_anthropic.Anthropic.return_value
        mock_client.messages.create.return_value = _make_anthropic_response("ok")
        chat(system="s", messages=[{"role": "user", "content": "u"}],
             max_tokens=100, model_hint="extraction")
        call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-sonnet-4-6"


def test_chat_model_override_bypasses_map(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL_OVERRIDE", "claude-haiku-4-5-20251001")
    from pipeline.llm import chat
    with patch("pipeline.llm.anthropic") as mock_anthropic:
        mock_client = mock_anthropic.Anthropic.return_value
        mock_client.messages.create.return_value = _make_anthropic_response("ok")
        chat(system="s", messages=[{"role": "user", "content": "u"}],
             max_tokens=100, model_hint="extraction")
        call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"


# ── stream_chat() — Anthropic ─────────────────────────────────────────────────

def test_stream_chat_anthropic_returns_text(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import stream_chat
    with patch("pipeline.llm.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value.messages.stream.return_value = (
            _make_stream_ctx("streamed response")
        )
        result = stream_chat(
            system="You are a test.",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1000,
            model_hint="synthesis",
        )
    assert result == "streamed response"


def test_stream_chat_returns_none_on_max_tokens(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import stream_chat
    with patch("pipeline.llm.anthropic") as mock_anthropic:
        truncated = _make_anthropic_response("partial...")
        truncated.stop_reason = "max_tokens"
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.get_final_message.return_value = truncated
        mock_anthropic.Anthropic.return_value.messages.stream.return_value = ctx
        result = stream_chat(
            system="s", messages=[{"role": "user", "content": "u"}],
            max_tokens=100, model_hint="synthesis",
        )
    assert result is None


def test_chat_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    # Reload to pick up new env (functions cache _provider() at call time via os.environ)
    from pipeline import llm as llm_module
    import importlib
    importlib.reload(llm_module)
    from pipeline.llm import chat
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        chat(system="s", messages=[], max_tokens=10, model_hint="extraction")


def test_strip_cache_control_is_importable():
    from pipeline.llm import _strip_cache_control
    assert callable(_strip_cache_control)
