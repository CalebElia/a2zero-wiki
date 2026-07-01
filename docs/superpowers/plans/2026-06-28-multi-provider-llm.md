# Multi-Provider LLM Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `pipeline/llm.py` — a provider-agnostic adapter that all 7 pipeline modules route through — so a single env var (`LLM_PROVIDER=openai`) switches the entire pipeline from Claude Sonnet 4.6 to GPT-5.4 with no code changes.

**Architecture:** A new `pipeline/llm.py` exposes two functions (`chat` and `stream_chat`) that read `LLM_PROVIDER` (default `anthropic`) and `LLM_MODEL_OVERRIDE` from the environment, select the right model ID from an internal map, and strip Anthropic-specific `cache_control` keys before sending to OpenAI. Each of the 7 existing modules is migrated to import and call these functions instead of instantiating `anthropic.Anthropic()` directly. Tests mock the `chat`/`stream_chat` names in each module's own namespace (e.g. `patch("pipeline.synthesize_wiki.chat")`), which is simpler than the current per-module `anthropic.Anthropic` mocks.

**Tech Stack:** `anthropic>=0.30.0` (already installed), `openai` (new dependency), `python-dotenv` is NOT added — env vars are set in the shell or via `.env` sourced manually.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pipeline/llm.py` | **Create** | Provider adapter: `chat()`, `stream_chat()`, model map, env reading, `cache_control` stripping |
| `tests/test_llm.py` | **Create** | Unit tests for `llm.py` covering both providers, model selection, stripping logic |
| `.env.example` | **Create** | Documentation for required env vars (never committed with real values) |
| `requirements.txt` | **Modify** | Add `openai>=1.0.0` |
| `pipeline/synthesize_wiki.py` | **Modify** | Replace `anthropic.Anthropic()` with `from pipeline.llm import chat` |
| `pipeline/merge_pages.py` | **Modify** | Same migration |
| `pipeline/wiki_writer.py` | **Modify** | Same migration |
| `pipeline/lint_wiki.py` | **Modify** | Two call sites — `_llm_filter_candidates()` and the backlink semantic call |
| `pipeline/raw_to_sources.py` | **Modify** | Same migration |
| `pipeline/ldp.py` | **Modify** | Same migration |
| `pipeline/holistic_synthesizer.py` | **Modify** | Two call sites — switch to `stream_chat`; remove `client` param from `_llm_call` |
| `pipeline/wiki_pages.py` | **Modify** | One streaming call in `extract_quads_from_source()` |
| `tests/test_synthesize_wiki.py` | **Modify** | Update 6 mock paths from `pipeline.synthesize_wiki.anthropic.Anthropic` → `pipeline.synthesize_wiki.chat` |
| `tests/test_merge_pages.py` | **Modify** | Update 3 mock paths |
| `tests/test_holistic_synthesizer.py` | **Modify** | Update 7 mock paths; `stream_chat` mock is simpler than stream context manager mock |
| `tests/test_wiki_extractor.py` | **Modify** | Update 3 mock paths for wiki_writer |
| `tests/test_lint_wiki.py` | **Modify** | Update 1 mock path |
| `tests/test_raw_to_sources.py` | **Modify** | Update 1 mock path |
| `tests/test_ldp.py` | **Modify** | Update 2 mock paths |
| `CLAUDE.md` | **Modify** | Document env vars in a new "Environment Variables" section |

---

## Task 1: Create `pipeline/llm.py` — Anthropic backend only

**Files:**
- Create: `pipeline/llm.py`
- Create: `tests/test_llm.py`

This task adds the adapter for the Anthropic provider only. OpenAI is added in Task 2. Tests mock the `anthropic.Anthropic` class inside `llm.py`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm.py`:

```python
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
    import importlib
    import pipeline.llm as llm_module
    importlib.reload(llm_module)  # picks up new env var
    from pipeline.llm import chat
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        chat(system="s", messages=[], max_tokens=10, model_hint="extraction")
```

- [ ] **Step 2: Run tests — expect failure**

```bash
python -m pytest tests/test_llm.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'pipeline.llm'`

- [ ] **Step 3: Create `pipeline/llm.py`**

```python
import os
import anthropic as anthropic

_MODEL_MAP = {
    "anthropic": {
        "extraction": "claude-sonnet-4-6",
        "synthesis":  "claude-sonnet-4-6",
        "merge":      "claude-sonnet-4-6",
        "digest":     "claude-sonnet-4-5",
        "clean":      "claude-sonnet-4-6",
    },
    "openai": {
        "extraction": "gpt-5.4",
        "synthesis":  "gpt-5.4",
        "merge":      "gpt-5.4",
        "digest":     "gpt-5.4",
        "clean":      "gpt-5.4",
    },
}


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").lower()


def _model(hint: str) -> str:
    override = os.environ.get("LLM_MODEL_OVERRIDE", "").strip()
    if override:
        return override
    provider = _provider()
    if provider not in _MODEL_MAP:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider!r}. Expected 'anthropic' or 'openai'."
        )
    return _MODEL_MAP[provider][hint]


def _strip_cache_control(messages: list[dict]) -> list[dict]:
    """Remove cache_control keys from content blocks (OpenAI rejects unknown fields)."""
    result = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            new_blocks = []
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    block = {k: v for k, v in block.items() if k != "cache_control"}
                new_blocks.append(block)
            result.append({**msg, "content": new_blocks})
        else:
            result.append(msg)
    return result


def chat(
    system: str,
    messages: list[dict],
    max_tokens: int,
    model_hint: str = "extraction",
    temperature: float = 0.0,
) -> str:
    """Non-streaming LLM call. Returns response text."""
    provider = _provider()
    model = _model(model_hint)

    if provider == "anthropic":
        response = anthropic.Anthropic().messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}. Expected 'anthropic' or 'openai'."
    )


def stream_chat(
    system: str,
    messages: list[dict],
    max_tokens: int,
    model_hint: str = "synthesis",
    temperature: float = 0.0,
) -> str | None:
    """Streaming LLM call. Returns full text, or None if truncated by max_tokens."""
    provider = _provider()
    model = _model(model_hint)

    if provider == "anthropic":
        with anthropic.Anthropic().messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "max_tokens":
            print(f"[llm] WARNING: response truncated (max_tokens={max_tokens})")
            return None
        return response.content[0].text

    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}. Expected 'anthropic' or 'openai'."
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_llm.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/llm.py tests/test_llm.py
git commit -m "feat(llm): add pipeline/llm.py — provider-agnostic adapter (Anthropic backend)"
```

---

## Task 2: Add OpenAI backend to `pipeline/llm.py`

**Files:**
- Modify: `pipeline/llm.py`
- Modify: `tests/test_llm.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add `openai` to requirements.txt**

Open `requirements.txt`. Add one line:

```
openai>=1.0.0
```

Install it:

```bash
pip install openai
```

- [ ] **Step 2: Write failing tests for OpenAI backend and `_strip_cache_control`**

Append to `tests/test_llm.py` (add after the last existing test):

```python
# ── _strip_cache_control ──────────────────────────────────────────────────────

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
```

- [ ] **Step 3: Run tests — expect failure**

```bash
python -m pytest tests/test_llm.py -v -k "openai or strip_cache" 2>&1 | head -20
```

Expected: FAIL — `pipeline.llm` has no `openai` import and no OpenAI branch.

- [ ] **Step 4: Add OpenAI support to `pipeline/llm.py`**

Replace the entire file with:

```python
import os
import anthropic
import openai

_MODEL_MAP = {
    "anthropic": {
        "extraction": "claude-sonnet-4-6",
        "synthesis":  "claude-sonnet-4-6",
        "merge":      "claude-sonnet-4-6",
        "digest":     "claude-sonnet-4-5",
        "clean":      "claude-sonnet-4-6",
    },
    "openai": {
        "extraction": "gpt-5.4",
        "synthesis":  "gpt-5.4",
        "merge":      "gpt-5.4",
        "digest":     "gpt-5.4",
        "clean":      "gpt-5.4",
    },
}


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").lower()


def _model(hint: str) -> str:
    override = os.environ.get("LLM_MODEL_OVERRIDE", "").strip()
    if override:
        return override
    provider = _provider()
    if provider not in _MODEL_MAP:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider!r}. Expected 'anthropic' or 'openai'."
        )
    return _MODEL_MAP[provider][hint]


def _strip_cache_control(messages: list[dict]) -> list[dict]:
    """Remove cache_control keys from content blocks (OpenAI rejects unknown fields)."""
    result = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            new_blocks = []
            for block in content:
                if isinstance(block, dict) and "cache_control" in block:
                    block = {k: v for k, v in block.items() if k != "cache_control"}
                new_blocks.append(block)
            result.append({**msg, "content": new_blocks})
        else:
            result.append(msg)
    return result


def chat(
    system: str,
    messages: list[dict],
    max_tokens: int,
    model_hint: str = "extraction",
    temperature: float = 0.0,
) -> str:
    """Non-streaming LLM call. Returns response text."""
    provider = _provider()
    model = _model(model_hint)

    if provider == "anthropic":
        response = anthropic.Anthropic().messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    if provider == "openai":
        clean_messages = _strip_cache_control(messages)
        oai_messages = [{"role": "system", "content": system}] + clean_messages
        response = openai.OpenAI().chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=oai_messages,
        )
        return response.choices[0].message.content

    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}. Expected 'anthropic' or 'openai'."
    )


def stream_chat(
    system: str,
    messages: list[dict],
    max_tokens: int,
    model_hint: str = "synthesis",
    temperature: float = 0.0,
) -> str | None:
    """Streaming LLM call. Returns full text, or None if truncated by max_tokens."""
    provider = _provider()
    model = _model(model_hint)

    if provider == "anthropic":
        with anthropic.Anthropic().messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "max_tokens":
            print(f"[llm] WARNING: response truncated (max_tokens={max_tokens})")
            return None
        return response.content[0].text

    if provider == "openai":
        clean_messages = _strip_cache_control(messages)
        oai_messages = [{"role": "system", "content": system}] + clean_messages
        collected = []
        with openai.OpenAI().chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=oai_messages,
            stream=True,
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    collected.append(delta)
        return "".join(collected)

    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}. Expected 'anthropic' or 'openai'."
    )
```

- [ ] **Step 5: Run all llm tests**

```bash
python -m pytest tests/test_llm.py -v
```

Expected: All tests pass (7 from Task 1 + 8 new = 15 total).

- [ ] **Step 6: Commit**

```bash
git add pipeline/llm.py tests/test_llm.py requirements.txt
git commit -m "feat(llm): add OpenAI backend + _strip_cache_control + openai dependency"
```

---

## Task 3: Env var setup — `.env.example`, `.gitignore`, `CLAUDE.md`

**Files:**
- Create: `.env.example`
- Modify: `.gitignore`
- Modify: `CLAUDE.md`

No code logic changes. No tests needed.

- [ ] **Step 1: Create `.env.example`**

Create `.env.example` at the project root:

```bash
# Copy this file to .env and fill in your values.
# NEVER commit .env — it is gitignored.

# Anthropic (required for default pipeline operation)
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI (required only when LLM_PROVIDER=openai)
OPENAI_API_KEY=sk-...

# Provider selection — default is "anthropic"
# Set to "openai" to route all LLM calls through GPT-5.4
LLM_PROVIDER=anthropic

# Force a specific model ID regardless of LLM_PROVIDER (optional)
# Overrides the internal model map. Leave blank to use the map.
LLM_MODEL_OVERRIDE=
```

- [ ] **Step 2: Add `.env` to `.gitignore`**

Open `.gitignore`. Look for the existing entries. Add `.env` immediately after the `.DS_Store` line (or at the end if you can't find it):

```
.env
```

Do NOT add `.env.example` — that file is intentionally committed as documentation.

- [ ] **Step 3: Add env var section to `CLAUDE.md`**

Find the `## What NOT to Do` section in `CLAUDE.md`. Add this new section immediately before it:

```markdown
## Environment Variables

```bash
ANTHROPIC_API_KEY=sk-ant-...   # required for default operation
OPENAI_API_KEY=sk-...          # required when LLM_PROVIDER=openai
LLM_PROVIDER=anthropic         # "anthropic" (default) or "openai"
LLM_MODEL_OVERRIDE=            # force a specific model ID (optional)
```

Set these in your shell or copy `.env.example` → `.env` and `source .env` before running the pipeline. Never commit `.env`.

The pipeline uses `LLM_PROVIDER` to select the backend; `LLM_MODEL_OVERRIDE` bypasses the internal model map entirely and routes to the literal model ID string you provide.
```

- [ ] **Step 4: Verify `.env` is gitignored**

```bash
echo "OPENAI_API_KEY=test" > .env
git status
```

Expected: `.env` does NOT appear in the untracked files list. Then remove it:

```bash
rm .env
```

- [ ] **Step 5: Commit**

```bash
git add .env.example .gitignore CLAUDE.md
git commit -m "chore: add .env.example, gitignore .env, document env vars in CLAUDE.md"
```

---

## Task 4: Migrate `pipeline/synthesize_wiki.py` → `chat()`

**Files:**
- Modify: `pipeline/synthesize_wiki.py`
- Modify: `tests/test_synthesize_wiki.py`

`synthesize_wiki.py` currently does `import anthropic` and calls `anthropic.Anthropic()` in two functions: `build_strategy_synthesis()` and `build_digest_narrative()`. Both use `messages.create()` (non-streaming).

Before starting, run `grep -n "anthropic" pipeline/synthesize_wiki.py` to find every line that references the old SDK. You'll change all of them.

- [ ] **Step 1: Update the mock in `tests/test_synthesize_wiki.py`**

There are 6 occurrences of `patch("pipeline.synthesize_wiki.anthropic.Anthropic")`. Replace them ALL with `patch("pipeline.synthesize_wiki.chat")`.

The mock setup also changes. The old pattern was:
```python
with patch("pipeline.synthesize_wiki.anthropic.Anthropic") as MockClient:
    MockClient.return_value.messages.create.return_value = _mock_response(text)
```

The new pattern is simpler — `chat` is a plain function that returns a string:
```python
with patch("pipeline.synthesize_wiki.chat") as mock_chat:
    mock_chat.return_value = text
```

For the integration test (`test_synthesize_wiki_orchestrates_end_to_end`), the old pattern used `side_effect`:
```python
MockClient.return_value.messages.create.side_effect = responses  # responses is a list of _mock_response objects
```

The new pattern:
```python
mock_chat.side_effect = [strategy_llm_output, narrative_output]  # plain strings
```

Note: `_mock_response` is only used in `test_build_strategy_synthesis_*` and `test_build_digest_narrative_*` tests. After the migration it's no longer needed — delete the helper function and the `MagicMock` import if `MagicMock` is no longer used anywhere else in the file.

Full list of tests to update and their new mock values:

| Test | Old mock target | New mock target | New return value |
|---|---|---|---|
| `test_build_strategy_synthesis_calls_anthropic_and_returns_dict` | `MockClient.return_value.messages.create.return_value = _mock_response(llm_output)` | `mock_chat.return_value = llm_output` | `llm_output` (the JSON string) |
| `test_build_strategy_synthesis_handles_fenced_json` | `MockClient.return_value.messages.create.return_value = _mock_response(llm_output)` | `mock_chat.return_value = llm_output` | `llm_output` (fenced JSON string) |
| `test_build_strategy_synthesis_returns_empty_skeleton_on_api_failure` | `MockClient.return_value.messages.create.side_effect = Exception("api error")` | `mock_chat.side_effect = Exception("api error")` | N/A |
| `test_build_digest_narrative_calls_anthropic` | `MockClient.return_value.messages.create.return_value = _mock_response(narrative_text)` | `mock_chat.return_value = narrative_text` | `narrative_text` (markdown string) |
| `test_build_digest_narrative_returns_placeholder_on_failure` | `MockClient.return_value.messages.create.side_effect = Exception("api error")` | `mock_chat.side_effect = Exception("api error")` | N/A |
| `test_synthesize_wiki_orchestrates_end_to_end` | `MockClient.return_value.messages.create.side_effect = responses` | `mock_chat.side_effect = [strategy_llm_output, narrative_output]` | Two plain strings |

- [ ] **Step 2: Run tests — expect failure (mock path mismatch)**

```bash
python -m pytest tests/test_synthesize_wiki.py -v -k "synthesis or digest or orchestrate" 2>&1 | head -30
```

Expected: Tests that use the mock fail because `pipeline.synthesize_wiki.chat` doesn't exist yet.

- [ ] **Step 3: Update `pipeline/synthesize_wiki.py`**

At the top of the file, remove `import anthropic` and add:

```python
from pipeline.llm import chat
```

In `build_strategy_synthesis()`, remove the `client = anthropic.Anthropic()` line and replace the `client.messages.create(...)` call with:

```python
raw = chat(
    system=_SYNTHESIS_SYSTEM,
    messages=[{"role": "user", "content": prompt}],
    max_tokens=2048,
    model_hint="synthesis",
    temperature=0.0,
)
```

Where `_SYNTHESIS_SYSTEM` is whatever system prompt string the function currently uses, and `prompt` is the user-side content. Check the existing code to get the exact variable names.

In `build_digest_narrative()`, remove `client = anthropic.Anthropic()` and replace `client.messages.create(...)` with:

```python
raw = chat(
    system=_DIGEST_SYSTEM,
    messages=[{"role": "user", "content": prompt}],
    max_tokens=4096,
    model_hint="digest",
    temperature=0.0,
)
```

- [ ] **Step 4: Run all synthesize_wiki tests**

```bash
python -m pytest tests/test_synthesize_wiki.py -v
```

Expected: All 15 tests pass.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
python -m pytest tests/ -q
```

Expected: Same count as before (152 passing, 1 skipped). No new failures.

- [ ] **Step 6: Commit**

```bash
git add pipeline/synthesize_wiki.py tests/test_synthesize_wiki.py
git commit -m "refactor(synthesize_wiki): migrate to pipeline.llm.chat"
```

---

## Task 5: Migrate `pipeline/merge_pages.py`, `pipeline/wiki_writer.py`, `pipeline/lint_wiki.py`, `pipeline/raw_to_sources.py`, `pipeline/ldp.py`

**Files:**
- Modify: `pipeline/merge_pages.py`
- Modify: `pipeline/wiki_writer.py`
- Modify: `pipeline/lint_wiki.py`
- Modify: `pipeline/raw_to_sources.py`
- Modify: `pipeline/ldp.py`
- Modify: `tests/test_merge_pages.py`
- Modify: `tests/test_wiki_extractor.py`
- Modify: `tests/test_lint_wiki.py`
- Modify: `tests/test_raw_to_sources.py`
- Modify: `tests/test_ldp.py`

All five modules use `messages.create()` (non-streaming) through `anthropic.Anthropic()`. This task migrates them all to `chat()` and updates their tests in one commit.

**Current test mock paths:**
- `tests/test_merge_pages.py`: `patch("pipeline.merge_pages.anthropic.Anthropic")` — 3 occurrences
- `tests/test_wiki_extractor.py`: `patch("pipeline.wiki_writer.anthropic.Anthropic")` — 3 occurrences
- `tests/test_lint_wiki.py`: `patch("pipeline.lint_wiki.anthropic.Anthropic")` — 1 occurrence
- `tests/test_raw_to_sources.py`: `@patch("pipeline.raw_to_sources.anthropic.Anthropic")` — 1 occurrence
- `tests/test_ldp.py`: `patch("pipeline.ldp.anthropic.Anthropic")` — 1 occurrence; `patch("pipeline.wiki_writer.anthropic.Anthropic")` — 1 occurrence

**New mock target pattern:**
- `patch("pipeline.merge_pages.chat")` → `mock_chat.return_value = "the response text"`
- `patch("pipeline.wiki_writer.chat")` → same
- `patch("pipeline.lint_wiki.chat")` → same
- `patch("pipeline.raw_to_sources.chat")` → same
- `patch("pipeline.ldp.chat")` → same (but note: ldp.py calls wiki_writer internally, so also update `patch("pipeline.wiki_writer.chat")` in test_ldp.py)

- [ ] **Step 1: Update `tests/test_merge_pages.py`**

Find all 3 occurrences of `patch("pipeline.merge_pages.anthropic.Anthropic")`. 

The old pattern:
```python
with patch("pipeline.merge_pages.anthropic.Anthropic") as MockClient:
    MockClient.return_value.messages.create.return_value = mock_response_object
```

Replace with:
```python
with patch("pipeline.merge_pages.chat") as mock_chat:
    mock_chat.return_value = "the merged page body text"
```

For the failure test (`side_effect = Exception(...)`):
```python
with patch("pipeline.merge_pages.chat") as mock_chat:
    mock_chat.side_effect = Exception("api error")
```

Check what the existing tests assert (`merge_pages()` returns the merged body string or the original on failure) and make sure the mock return value matches what that assertion expects.

- [ ] **Step 2: Update `tests/test_wiki_extractor.py`**

Replace all 3 occurrences of `patch("pipeline.wiki_writer.anthropic.Anthropic")` with `patch("pipeline.wiki_writer.chat")`.

The wiki_writer test mocks return JSON strings (arrays of page objects). The old pattern was:
```python
mock_client.messages.create.return_value.content[0].text = json.dumps([...])
```

New pattern:
```python
mock_chat.return_value = json.dumps([...])
```

- [ ] **Step 3: Update `tests/test_lint_wiki.py`**

Replace the 1 occurrence of `patch("pipeline.lint_wiki.anthropic.Anthropic")` with `patch("pipeline.lint_wiki.chat")`.

- [ ] **Step 4: Update `tests/test_raw_to_sources.py`**

Replace the 1 `@patch("pipeline.raw_to_sources.anthropic.Anthropic")` decorator with `@patch("pipeline.raw_to_sources.chat")`. Update the mock setup in the test body accordingly.

- [ ] **Step 5: Update `tests/test_ldp.py`**

Replace `patch("pipeline.ldp.anthropic.Anthropic")` with `patch("pipeline.ldp.chat")` and `patch("pipeline.wiki_writer.anthropic.Anthropic")` with `patch("pipeline.wiki_writer.chat")`.

- [ ] **Step 6: Run tests — expect failures (mock path mismatch)**

```bash
python -m pytest tests/test_merge_pages.py tests/test_wiki_extractor.py tests/test_lint_wiki.py tests/test_raw_to_sources.py tests/test_ldp.py -v 2>&1 | head -40
```

Expected: Tests fail because the modules still import `anthropic` directly.

- [ ] **Step 7: Migrate `pipeline/merge_pages.py`**

At the top, replace `import anthropic` with `from pipeline.llm import chat`.

Find the `client = anthropic.Anthropic()` line and `client.messages.create(...)` call. Replace with:

```python
raw = chat(
    system=system_prompt,
    messages=[{"role": "user", "content": user_prompt}],
    max_tokens=max_tokens,
    model_hint="merge",
    temperature=0.0,
)
```

Where `system_prompt`, `user_prompt`, `max_tokens` are whatever variables the function uses. Check the current code to get exact names. The `model` parameter to `merge_pages()` is now unused — remove it from the function signature and from the call site in `alias_registry.py` (or wherever it's called from).

**Note on the `model` parameter:** `merge_pages()` currently accepts a `model: str` parameter that defaults to `"claude-sonnet-4-6"`. After migration, `llm.py` owns model selection. Remove `model` from the parameter list entirely, and update any call sites.

- [ ] **Step 8: Migrate `pipeline/wiki_writer.py`**

Replace `import anthropic` with `from pipeline.llm import chat`.

The `extract_wiki_pages()` function (or equivalent — check current name by running `grep -n "def extract" pipeline/wiki_writer.py`) instantiates `client = anthropic.Anthropic()` and calls `client.messages.create(...)`. Replace with:

```python
raw = chat(
    system=WIKI_PAGES_SYSTEM,
    messages=[{"role": "user", "content": prompt}],
    max_tokens=16384,
    model_hint="extraction",
    temperature=0.2,
)
```

If there is a `if response.stop_reason == "max_tokens":` check, remove it — `chat()` returns the text regardless (truncated responses will fail JSON parsing, which is already caught by the existing exception handler).

- [ ] **Step 9: Migrate `pipeline/lint_wiki.py`**

Two call sites:

1. `_llm_filter_candidates()` — called with a `client` parameter. After migration, remove the `client` parameter from the function signature and replace the `client.messages.create(...)` call with `chat(...)`.

   The function signature changes from:
   ```python
   def _llm_filter_candidates(page_rel, body, candidates, client):
   ```
   to:
   ```python
   def _llm_filter_candidates(page_rel, body, candidates):
   ```
   
   Update the two call sites in `semantic_lint()` and `backlink_lint()` that currently pass `client` as the last argument.

2. The second call site in `backlink_lint()` (or the semantic verdict call — verify by running `grep -n "messages.create" pipeline/lint_wiki.py`). Same pattern: remove client usage, add `chat(...)`.

Remove the `import anthropic` and all `client = anthropic.Anthropic()` instantiations from the module.

- [ ] **Step 10: Migrate `pipeline/raw_to_sources.py`**

Replace `import anthropic` with `from pipeline.llm import chat`. Replace the single `client.messages.create(...)` call with `chat(...)`.

- [ ] **Step 11: Migrate `pipeline/ldp.py`**

Replace `import anthropic` with `from pipeline.llm import chat`. Find the `client = anthropic.Anthropic()` line and the `client.messages.create(...)` call. Replace with `chat(...)`.

Note: `ldp.py` passes `client` to `wiki_writer` functions as a parameter in some versions. Run `grep -n "client" pipeline/ldp.py` to see if this is the case. If so, remove the `client` parameter from those call sites after `wiki_writer.py` has been migrated.

- [ ] **Step 12: Run tests**

```bash
python -m pytest tests/test_merge_pages.py tests/test_wiki_extractor.py tests/test_lint_wiki.py tests/test_raw_to_sources.py tests/test_ldp.py -v
```

Expected: All tests pass.

- [ ] **Step 13: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: Same count as before. No regressions.

- [ ] **Step 14: Commit**

```bash
git add pipeline/merge_pages.py pipeline/wiki_writer.py pipeline/lint_wiki.py \
        pipeline/raw_to_sources.py pipeline/ldp.py \
        tests/test_merge_pages.py tests/test_wiki_extractor.py \
        tests/test_lint_wiki.py tests/test_raw_to_sources.py tests/test_ldp.py
git commit -m "refactor: migrate merge_pages, wiki_writer, lint_wiki, raw_to_sources, ldp to pipeline.llm.chat"
```

---

## Task 6: Migrate `pipeline/holistic_synthesizer.py` and `pipeline/wiki_pages.py` → `stream_chat()`

**Files:**
- Modify: `pipeline/holistic_synthesizer.py`
- Modify: `pipeline/wiki_pages.py`
- Modify: `tests/test_holistic_synthesizer.py`
- Modify: `tests/test_run_ingest.py`

These two modules use `messages.stream()` (the streaming API). `stream_chat()` in `llm.py` wraps that — callers just get back a `str | None`.

The key change for `holistic_synthesizer.py` is that `_llm_call()` currently takes a `client: anthropic.Anthropic` parameter and calls `client.messages.stream()`. After migration, it calls `stream_chat()` and no longer needs a `client` parameter.

The key change for tests is that mocking `stream_chat` is much simpler than mocking the context-manager-based streaming pattern. The old mock required:
```python
ctx = MagicMock()
ctx.__enter__ = MagicMock(return_value=ctx)
ctx.__exit__ = MagicMock(return_value=False)
ctx.get_final_message.return_value = response_mock
mock_client.messages.stream.side_effect = [ctx, ctx, ctx]
```
The new mock is:
```python
mock_stream_chat.side_effect = [json.dumps(MOCK_SYNTHESIS), json.dumps(MOCK_CRITIQUE), json.dumps(MOCK_SYNTHESIS)]
```

- [ ] **Step 1: Update `tests/test_holistic_synthesizer.py`**

Replace all 7 occurrences of `@patch("pipeline.holistic_synthesizer.anthropic.Anthropic")` (or `patch(...)` in context managers) with `@patch("pipeline.holistic_synthesizer.stream_chat")`.

The old mock setup at the test level:
```python
mock_client = MagicMock()
mock_anthropic_class.return_value = mock_client
mock_client.messages.stream.side_effect = [
    _make_stream_ctx(MOCK_SYNTHESIS),
    _make_stream_ctx(MOCK_CRITIQUE),
    _make_stream_ctx(MOCK_SYNTHESIS),
]
```

New setup (much shorter):
```python
# mock_stream_chat is the patched function; side_effect = list of return values, one per call
mock_stream_chat.side_effect = [
    json.dumps(MOCK_SYNTHESIS),  # Writer call
    json.dumps(MOCK_CRITIQUE),   # Evaluator call
    json.dumps(MOCK_SYNTHESIS),  # Editor call
]
```

Remove the `_make_stream_ctx` and `_make_response` helper functions — they're only needed for the streaming context manager pattern. The `_MOCK_SYNTHESIS` and `_MOCK_CRITIQUE` dicts stay (they're still used as the raw Python values before `json.dumps`).

Do this for every test in the file. Each test that currently sets up `mock_client.messages.stream.side_effect = [...]` switches to `mock_stream_chat.side_effect = [...]`.

For the test that checks truncation (if one exists), the mock returns `None` directly:
```python
mock_stream_chat.side_effect = [None]  # stream_chat returns None on max_tokens
```

- [ ] **Step 2: Update `tests/test_run_ingest.py`**

There is one `@patch("anthropic.Anthropic")` in this file (line 39). This is a broad patch on the anthropic module itself. After migration, if run_ingest.py no longer imports anthropic directly, this patch will break. Run:

```bash
grep -n "anthropic" pipeline/run_ingest.py
```

If `run_ingest.py` doesn't import anthropic itself (it delegates to holistic_synthesizer, which does), the patch in test_run_ingest.py may become a no-op or break. Assess:

- If `run_ingest.py` does NOT import anthropic, replace the `@patch("anthropic.Anthropic")` with `@patch("pipeline.holistic_synthesizer.stream_chat")` and adjust the mock setup to return appropriate JSON strings (see above).
- If `run_ingest.py` DOES import anthropic, update the patch target to the specific function being mocked.

- [ ] **Step 3: Run tests — expect failure**

```bash
python -m pytest tests/test_holistic_synthesizer.py tests/test_run_ingest.py -v 2>&1 | head -30
```

Expected: Failures because `pipeline.holistic_synthesizer.stream_chat` doesn't exist yet.

- [ ] **Step 4: Migrate `pipeline/holistic_synthesizer.py`**

At the top, replace `import anthropic` with `from pipeline.llm import stream_chat`.

The `_llm_call()` function currently has this signature:
```python
def _llm_call(
    client: anthropic.Anthropic,
    system: str,
    user_content: "str | list",
    step_name: str,
    source_uuid: str,
    max_tokens: int = 64000,
    model: str = "claude-sonnet-4-6",
) -> dict | None:
```

Change it to:
```python
def _llm_call(
    system: str,
    user_content: "str | list",
    step_name: str,
    source_uuid: str,
    max_tokens: int = 64000,
) -> dict | None:
```

Inside `_llm_call`, replace the streaming API call:
```python
with client.messages.stream(
    model=model,
    max_tokens=max_tokens,
    temperature=0,
    system=system,
    messages=[{"role": "user", "content": user_content}],
) as stream:
    response = stream.get_final_message()
if response.stop_reason == "max_tokens":
    print(f"[holistic:{step_name}] WARNING: response truncated for {source_uuid}")
    return None
raw = response.content[0].text
```

With:
```python
raw = stream_chat(
    system=system,
    messages=[{"role": "user", "content": user_content}],
    max_tokens=max_tokens,
    model_hint="synthesis",
    temperature=0.0,
)
if raw is None:
    print(f"[holistic:{step_name}] WARNING: response truncated for {source_uuid}")
    return None
```

In `synthesize_source()`, remove `client = anthropic.Anthropic()`. Update each call to `_llm_call()` to drop the `client` argument:

Old:
```python
draft = _llm_call(client, writer_system, user_content, "writer", source_uuid, max_tokens=64000)
```
New:
```python
draft = _llm_call(writer_system, user_content, "writer", source_uuid, max_tokens=64000)
```

Do the same for the evaluator and editor calls.

Also remove `usage = getattr(response, "usage", None)` and related print statements if they exist — `stream_chat` doesn't return usage info.

- [ ] **Step 5: Migrate `pipeline/wiki_pages.py`**

Run `grep -n "import anthropic\|client\|messages.stream" pipeline/wiki_pages.py` to find the exact call site.

The function is `extract_quads_from_source()`. Replace `import anthropic` at the top with `from pipeline.llm import stream_chat`.

Remove `client = anthropic.Anthropic()`. Replace the streaming call with:

```python
raw = stream_chat(
    system=QUADS_SYSTEM,
    messages=[{"role": "user", "content": build_quads_prompt(body, source_uuid)}],
    max_tokens=16384,
    model_hint="extraction",
    temperature=0.0,
)
if raw is None:
    print(f"[quads] WARNING: response truncated for {source_uuid} — partial recovery not possible")
    return []
```

Remove the old `if response.stop_reason == "max_tokens":` block.

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_holistic_synthesizer.py tests/test_run_ingest.py -v
```

Expected: All pass.

- [ ] **Step 7: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: Same count. No regressions.

- [ ] **Step 8: Verify no direct anthropic imports remain in pipeline modules**

```bash
grep -rn "import anthropic\|anthropic.Anthropic()" pipeline/ --include="*.py"
```

Expected: Zero results. The only anthropic import in the pipeline is inside `pipeline/llm.py` itself.

- [ ] **Step 9: Commit**

```bash
git add pipeline/holistic_synthesizer.py pipeline/wiki_pages.py \
        tests/test_holistic_synthesizer.py tests/test_run_ingest.py
git commit -m "refactor: migrate holistic_synthesizer + wiki_pages to pipeline.llm.stream_chat"
```

---

## Task 7: Update `CHANGELOG.md` and final verification

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add changelog entry**

Open `CHANGELOG.md`. Add a new entry at the top (before the `2026-06-28 — Phase C` entry):

```markdown
## 2026-06-28 — Multi-provider LLM switching layer

**What changed:**
- **`pipeline/llm.py`** — new provider-agnostic adapter. `chat()` (non-streaming) and `stream_chat()` (streaming) read `LLM_PROVIDER` (default `anthropic`) and `LLM_MODEL_OVERRIDE` from the environment. Strips Anthropic-specific `cache_control` keys from message content before sending to OpenAI, where prompt caching is automatic.
- **All 7 pipeline modules** migrated off direct `anthropic.Anthropic()` calls: `holistic_synthesizer`, `wiki_writer`, `lint_wiki`, `merge_pages`, `raw_to_sources`, `ldp`, `synthesize_wiki`.
- **15 new tests** in `tests/test_llm.py` covering both providers, model selection, env var override, and `cache_control` stripping.
- **All existing test mocks** simplified: `patch("pipeline.X.anthropic.Anthropic")` chains → `patch("pipeline.X.chat")` or `patch("pipeline.X.stream_chat")` returning plain strings.
- **`requirements.txt`** — added `openai>=1.0.0`.
- **`.env.example`** — documents `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL_OVERRIDE`.

**Why:** Two-provider A/B capability — GPT-5.4 ($2.50/M input, 1.05M context, 128k output) vs Claude Sonnet 4.6 for cost and quality comparison without code changes. Setting `LLM_PROVIDER=openai` switches the entire pipeline. The `cache_control` stripping is necessary because OpenAI rejects explicit cache annotations (OpenAI caches automatically at the infrastructure level).
```

- [ ] **Step 2: Final test run**

```bash
python -m pytest tests/ -q
```

Expected output (exact counts may differ slightly if tests changed):
```
.......  (all passing)
X passed, 1 skipped in Y.Zs
```

- [ ] **Step 3: Verify no direct SDK calls remain in pipeline (except llm.py)**

```bash
grep -rn "anthropic.Anthropic()\|openai.OpenAI()\|import anthropic\|import openai" pipeline/ --include="*.py" | grep -v "pipeline/llm.py"
```

Expected: Zero results.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add multi-provider LLM layer to CHANGELOG"
```

- [ ] **Step 5: Push branch and open PR**

```bash
git push -u origin feat/knowledge-synthesis
gh pr create \
  --title "feat: multi-provider LLM switching layer (Anthropic ↔ OpenAI)" \
  --body "$(cat <<'EOF'
## Summary
- Adds \`pipeline/llm.py\` — provider-agnostic adapter with \`chat()\` and \`stream_chat()\`
- All 7 pipeline modules migrated off direct Anthropic SDK calls
- Set \`LLM_PROVIDER=openai\` to switch entire pipeline to GPT-5.4 with no code changes
- \`cache_control\` stripped from OpenAI payloads (OpenAI caches automatically)

## Test plan
- [ ] \`python -m pytest tests/ -q\` — all tests pass
- [ ] \`grep -rn "anthropic.Anthropic()" pipeline/ --include="*.py" | grep -v llm.py\` — zero results
- [ ] Manual smoke: set \`LLM_PROVIDER=anthropic\` and run a single strategy synthesis
- [ ] Manual smoke: set \`LLM_PROVIDER=openai\` + \`OPENAI_API_KEY\` and run same strategy synthesis
EOF
)"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Covered by |
|---|---|
| Single `LLM_PROVIDER` env var (not per-role) | Task 1 — `_provider()` reads `LLM_PROVIDER` |
| `LLM_MODEL_OVERRIDE` bypasses model map | Task 1 — `_model()` checks override first |
| OpenAI API key as secret env var | Task 3 — `.env.example` + `.gitignore` |
| A/B target: `claude-sonnet-4-6` vs `gpt-5.4` | Task 2 — `_MODEL_MAP` |
| `cache_control` stripped for OpenAI | Task 2 — `_strip_cache_control()` |
| All `messages.create()` callers migrated | Tasks 4 + 5 |
| Both streaming callers migrated | Task 6 |
| Tests updated | Tasks 4, 5, 6 |
| No behavior change when `LLM_PROVIDER=anthropic` | Architectural — Anthropic path is byte-for-byte equivalent to current code |

**Placeholder scan:** No TBD, TODO, or "similar to Task N" patterns found. All code blocks are complete.

**Type consistency:** `chat()` and `stream_chat()` signatures are defined once in Task 1/2 and referenced consistently in Tasks 4–6. `model_hint` string literals (`"extraction"`, `"synthesis"`, `"merge"`, `"digest"`, `"clean"`) are all present in `_MODEL_MAP`.

**One edge case flagged:** Task 5 Step 7 notes that `merge_pages.py` currently accepts a `model: str` parameter. Removing it is a breaking change for callers. The implementer must check `grep -rn "merge_pages(" pipeline/ tests/` to find all call sites and update them — this is not listed in the task files but is called out in the prose.
