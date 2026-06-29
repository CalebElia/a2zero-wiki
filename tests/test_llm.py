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
    from pipeline.llm import chat
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        chat(system="s", messages=[], max_tokens=10, model_hint="extraction")


def test_strip_cache_control_is_importable():
    from pipeline.llm import _strip_cache_control
    assert callable(_strip_cache_control)


# ── _strip_cache_control (behavioral) ────────────────────────────────────────

def test_strip_cache_control_removes_key_from_content_blocks():
    from pipeline.llm import _strip_cache_control
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello", "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "world"},
            ],
        }
    ]
    result = _strip_cache_control(messages)
    block = result[0]["content"][0]
    assert "cache_control" not in block
    assert block["text"] == "hello"
    # Second block (no cache_control) is unchanged
    assert result[0]["content"][1] == {"type": "text", "text": "world"}


def test_strip_cache_control_leaves_string_content_untouched():
    from pipeline.llm import _strip_cache_control
    messages = [{"role": "user", "content": "just a string"}]
    result = _strip_cache_control(messages)
    assert result == messages


# ── chat() — OpenAI ───────────────────────────────────────────────────────────

def test_chat_openai_returns_text(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import chat
    with patch("pipeline.llm.openai") as mock_openai:
        choice = MagicMock()
        choice.message.content = "openai response"
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = (
            MagicMock(choices=[choice])
        )
        result = chat(
            system="You are a test.",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=100,
            model_hint="extraction",
        )
    assert result == "openai response"


def test_chat_openai_prepends_system_message(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import chat
    with patch("pipeline.llm.openai") as mock_openai:
        choice = MagicMock()
        choice.message.content = "ok"
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = (
            MagicMock(choices=[choice])
        )
        chat(system="Be helpful.", messages=[{"role": "user", "content": "q"}],
             max_tokens=100, model_hint="extraction")
        call_kwargs = mock_openai.OpenAI.return_value.chat.completions.create.call_args[1]
    assert call_kwargs["messages"][0] == {"role": "system", "content": "Be helpful."}
    assert call_kwargs["messages"][1] == {"role": "user", "content": "q"}


def test_chat_openai_strips_cache_control(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import chat
    with patch("pipeline.llm.openai") as mock_openai:
        choice = MagicMock()
        choice.message.content = "ok"
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = (
            MagicMock(choices=[choice])
        )
        chat(
            system="s",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "doc", "cache_control": {"type": "ephemeral"}}
            ]}],
            max_tokens=100,
            model_hint="extraction",
        )
        call_kwargs = mock_openai.OpenAI.return_value.chat.completions.create.call_args[1]
    # The system message is first; user message is second
    user_msg = call_kwargs["messages"][1]
    assert "cache_control" not in user_msg["content"][0]


def test_chat_openai_uses_correct_model(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import chat
    with patch("pipeline.llm.openai") as mock_openai:
        choice = MagicMock()
        choice.message.content = "ok"
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = (
            MagicMock(choices=[choice])
        )
        chat(system="s", messages=[{"role": "user", "content": "u"}],
             max_tokens=100, model_hint="extraction")
        call_kwargs = mock_openai.OpenAI.return_value.chat.completions.create.call_args[1]
    assert call_kwargs["model"] == "gpt-5.4"


# ── stream_chat() — OpenAI ────────────────────────────────────────────────────

def test_stream_chat_openai_returns_text(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import stream_chat

    def _make_chunks(words):
        for w in words:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = w
            yield chunk

    with patch("pipeline.llm.openai") as mock_openai:
        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=_make_chunks(["hello", " ", "world"]))
        stream_ctx.__exit__ = MagicMock(return_value=False)
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = stream_ctx
        result = stream_chat(
            system="You are a test.",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1000,
            model_hint="synthesis",
        )
    assert result == "hello world"


def test_stream_chat_openai_strips_cache_control(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL_OVERRIDE", raising=False)
    from pipeline.llm import stream_chat

    def _single_chunk(text):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
        yield chunk

    with patch("pipeline.llm.openai") as mock_openai:
        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=_single_chunk("ok"))
        stream_ctx.__exit__ = MagicMock(return_value=False)
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = stream_ctx
        stream_chat(
            system="s",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "doc", "cache_control": {"type": "ephemeral"}}
            ]}],
            max_tokens=100,
            model_hint="synthesis",
        )
        call_kwargs = mock_openai.OpenAI.return_value.chat.completions.create.call_args[1]
    # The system message is first (index 0); user message is second (index 1)
    user_msg = call_kwargs["messages"][1]
    assert "cache_control" not in user_msg["content"][0]
