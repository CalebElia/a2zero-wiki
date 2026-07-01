import os
import anthropic
import openai

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

_VALID_PROVIDERS = ("anthropic", "openai", "azure")


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").lower()


def _model(hint: str) -> str:
    override = os.environ.get("LLM_MODEL_OVERRIDE", "").strip()
    if override:
        return override
    provider = _provider()
    if provider == "azure":
        # Azure addresses models by deployment name, not model ID — deployment
        # names are chosen when the deployment is created in the Azure portal
        # and don't necessarily match OpenAI's own model IDs.
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
        if not deployment:
            raise ValueError(
                "LLM_PROVIDER=azure requires AZURE_OPENAI_DEPLOYMENT to be set "
                "to the deployment name configured in your Azure OpenAI resource."
            )
        return deployment
    if provider not in _MODEL_MAP:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider!r}. Expected one of {_VALID_PROVIDERS}."
        )
    if hint not in _MODEL_MAP[provider]:
        raise ValueError(
            f"Unknown model_hint: {hint!r}. Valid hints: {list(_MODEL_MAP[provider].keys())}"
        )
    return _MODEL_MAP[provider][hint]


def _azure_client() -> "openai.OpenAI":
    """Client for Azure AI Foundry's unified /openai/v1 endpoint.

    This is the newer OpenAI-compatible surface (base_url + Bearer auth) —
    not the classic https://<resource>.openai.azure.com surface that the
    AzureOpenAI SDK class and api-version query param were built for. No
    api-version is needed here; the endpoint itself already encodes /openai/v1.
    """
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    missing = [
        name for name, val in (
            ("AZURE_OPENAI_ENDPOINT", endpoint),
            ("AZURE_OPENAI_API_KEY", api_key),
        ) if not val
    ]
    if missing:
        raise ValueError(
            f"LLM_PROVIDER=azure requires {', '.join(missing)} to be set. "
            "See .env.example."
        )
    return openai.OpenAI(base_url=endpoint, api_key=api_key)


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

    if provider in ("openai", "azure"):
        clean_messages = _strip_cache_control(messages)
        oai_messages = [{"role": "system", "content": system}] + clean_messages
        client = _azure_client() if provider == "azure" else openai.OpenAI()
        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            temperature=temperature,
            messages=oai_messages,
        )
        return response.choices[0].message.content

    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}. Expected one of {_VALID_PROVIDERS}."
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

    if provider in ("openai", "azure"):
        clean_messages = _strip_cache_control(messages)
        oai_messages = [{"role": "system", "content": system}] + clean_messages
        client = _azure_client() if provider == "azure" else openai.OpenAI()
        collected = []
        with client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
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
        f"Unknown LLM_PROVIDER: {provider!r}. Expected one of {_VALID_PROVIDERS}."
    )
