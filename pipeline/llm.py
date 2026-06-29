import os
import anthropic

_MODEL_MAP = {
    "anthropic": {
        "extraction": "claude-sonnet-4-6",
        "synthesis":  "claude-sonnet-4-6",
        "merge":      "claude-sonnet-4-6",
        "digest":     "claude-sonnet-4-5",  # sonnet-4-5 sufficient for cross-strategy narrative; lower cost
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
    if hint not in _MODEL_MAP[provider]:
        raise ValueError(
            f"Unknown model_hint: {hint!r}. Valid hints: {list(_MODEL_MAP[provider].keys())}"
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
