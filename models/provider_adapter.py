# -*- coding: utf-8 -*-
"""
Provider adapter layer for Otomater AI.

Each adapter function takes a normalized `config` dict and a list of
normalized `messages` ([{"role": "user"/"assistant"/"system", "content": str}])
and returns a normalized dict:

    {
        "content": str,
        "tokens_input": int,
        "tokens_output": int,
        "raw": dict,   # raw provider response, for debugging/audit
    }

Adapters raise `ProviderError` on any failure (bad key, timeout, malformed
response, HTTP error) so the calling model can log it to the audit trail
and surface a clean message to the user instead of a traceback.

This module intentionally has NO dependency on the Odoo ORM so it can be
unit tested in isolation and reused by the future REST API / scheduled
agents layers.
"""

import json
import logging

import requests

_logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Raised whenever a provider call cannot be completed."""


def _post_json(url, headers, payload, timeout):
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise ProviderError("Request timed out after %s seconds" % timeout) from exc
    except requests.exceptions.ConnectionError as exc:
        raise ProviderError("Could not connect to provider endpoint: %s" % exc) from exc
    except requests.exceptions.RequestException as exc:
        raise ProviderError("Network error contacting provider: %s" % exc) from exc

    if response.status_code >= 400:
        detail = response.text[:500]
        raise ProviderError(
            "Provider returned HTTP %s: %s" % (response.status_code, detail)
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("Provider returned non-JSON response") from exc


def call_openai(config, messages):
    base_url = (config.get("api_base_url") or "https://api.openai.com/v1").rstrip("/")
    url = "%s/chat/completions" % base_url
    headers = {
        "Authorization": "Bearer %s" % config["api_key"],
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.get("model") or "gpt-4o-mini",
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 1024),
    }
    data = _post_json(url, headers, payload, config.get("timeout", 60))
    try:
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_input = usage.get("prompt_tokens", 0)
        tokens_output = usage.get("completion_tokens", 0)
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected OpenAI response shape: %s" % exc) from exc
    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "raw": data,
    }


def call_azure_openai(config, messages):
    # Azure requires a deployment-scoped endpoint of the form:
    # https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version=...
    base_url = (config.get("api_base_url") or "").rstrip("/")
    if not base_url:
        raise ProviderError(
            "Azure OpenAI requires the full deployment endpoint URL in "
            "'API Base URL' (https://<resource>.openai.azure.com/openai/deployments/<deployment>)"
        )
    api_version = config.get("api_version") or "2024-06-01"
    url = "%s/chat/completions?api-version=%s" % (base_url, api_version)
    headers = {
        "api-key": config["api_key"],
        "Content-Type": "application/json",
    }
    payload = {
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 1024),
    }
    data = _post_json(url, headers, payload, config.get("timeout", 60))
    try:
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_input = usage.get("prompt_tokens", 0)
        tokens_output = usage.get("completion_tokens", 0)
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected Azure OpenAI response shape: %s" % exc) from exc
    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "raw": data,
    }


def call_anthropic(config, messages):
    base_url = (config.get("api_base_url") or "https://api.anthropic.com/v1").rstrip("/")
    url = "%s/messages" % base_url
    headers = {
        "x-api-key": config["api_key"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    # Anthropic wants system prompt separated out from the messages list.
    system_prompt = ""
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_prompt = (system_prompt + "\n" + msg["content"]).strip()
        else:
            chat_messages.append({"role": msg["role"], "content": msg["content"]})
    payload = {
        "model": config.get("model") or "claude-sonnet-4-6",
        "max_tokens": config.get("max_tokens", 1024),
        "temperature": config.get("temperature", 0.7),
        "messages": chat_messages,
    }
    if system_prompt:
        payload["system"] = system_prompt
    data = _post_json(url, headers, payload, config.get("timeout", 60))
    try:
        content_blocks = data.get("content", [])
        content = "".join(
            block.get("text", "") for block in content_blocks if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        tokens_input = usage.get("input_tokens", 0)
        tokens_output = usage.get("output_tokens", 0)
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected Claude response shape: %s" % exc) from exc
    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "raw": data,
    }


def call_gemini(config, messages):
    base_url = (
        config.get("api_base_url") or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    model = config.get("model") or "gemini-2.0-flash"
    url = "%s/models/%s:generateContent?key=%s" % (base_url, model, config["api_key"])
    headers = {"Content-Type": "application/json"}

    contents = []
    system_instruction = None
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = {"parts": [{"text": msg["content"]}]}
            continue
        gemini_role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": msg["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": config.get("temperature", 0.7),
            "maxOutputTokens": config.get("max_tokens", 1024),
        },
    }
    if system_instruction:
        payload["systemInstruction"] = system_instruction

    data = _post_json(url, headers, payload, config.get("timeout", 60))
    try:
        candidate = data["candidates"][0]
        parts = candidate.get("content", {}).get("parts", [])
        content = "".join(part.get("text", "") for part in parts)
        usage = data.get("usageMetadata", {})
        tokens_input = usage.get("promptTokenCount", 0)
        tokens_output = usage.get("candidatesTokenCount", 0)
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected Gemini response shape: %s" % exc) from exc
    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "raw": data,
    }


def call_ollama(config, messages):
    base_url = (config.get("api_base_url") or "http://localhost:11434").rstrip("/")
    url = "%s/api/chat" % base_url
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": config.get("model") or "llama3.1",
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": config.get("temperature", 0.7),
        },
    }
    data = _post_json(url, headers, payload, config.get("timeout", 120))
    try:
        content = data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise ProviderError("Unexpected Ollama response shape: %s" % exc) from exc
    # Ollama reports token counts as eval_count / prompt_eval_count.
    tokens_input = data.get("prompt_eval_count", 0)
    tokens_output = data.get("eval_count", 0)
    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "raw": data,
    }


def call_openrouter(config, messages):
    base_url = (config.get("api_base_url") or "https://openrouter.ai/api/v1").rstrip("/")
    url = "%s/chat/completions" % base_url
    headers = {
        "Authorization": "Bearer %s" % config["api_key"],
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.get("model") or "openai/gpt-4o-mini",
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 1024),
    }
    data = _post_json(url, headers, payload, config.get("timeout", 60))
    try:
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_input = usage.get("prompt_tokens", 0)
        tokens_output = usage.get("completion_tokens", 0)
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected OpenRouter response shape: %s" % exc) from exc
    return {
        "content": content,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "raw": data,
    }


# Registry mapping ai.provider `code` selection values to their adapter
# function. Adding a new provider in a later phase means adding one entry
# here plus the corresponding selection value on ai.provider - no other
# code path needs to change.
ADAPTERS = {
    "openai": call_openai,
    "azure_openai": call_azure_openai,
    "anthropic": call_anthropic,
    "gemini": call_gemini,
    "ollama": call_ollama,
    "openrouter": call_openrouter,
}


def call_provider(code, config, messages):
    """Dispatch to the correct adapter, raising ProviderError for unknown codes."""
    adapter = ADAPTERS.get(code)
    if not adapter:
        raise ProviderError("No adapter implemented for provider code '%s'" % code)
    if not config.get("api_key") and code != "ollama":
        raise ProviderError("No API key configured for this provider")
    return adapter(config, messages)


# ---------------------------------------------------------------------
# Embeddings (Phase 4 - Knowledge Base)
#
# Not every chat provider also offers an embeddings endpoint (Anthropic
# and OpenRouter do not, as of this writing) - only the four below are
# wired up. Pick one of these as the dedicated "embedding provider" on
# ai.provider even if a different provider is used for chat.
# ---------------------------------------------------------------------

def call_openai_embedding(config, texts):
    base_url = (config.get("api_base_url") or "https://api.openai.com/v1").rstrip("/")
    url = "%s/embeddings" % base_url
    headers = {
        "Authorization": "Bearer %s" % config["api_key"],
        "Content-Type": "application/json",
    }
    payload = {"model": config.get("model") or "text-embedding-3-small", "input": texts}
    data = _post_json(url, headers, payload, config.get("timeout", 60))
    try:
        ordered = sorted(data["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in ordered]
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected OpenAI embeddings response shape: %s" % exc) from exc


def call_azure_openai_embedding(config, texts):
    base_url = (config.get("api_base_url") or "").rstrip("/")
    if not base_url:
        raise ProviderError(
            "Azure OpenAI embeddings require the full deployment endpoint URL in "
            "'API Base URL' (https://<resource>.openai.azure.com/openai/deployments/<embedding-deployment>)"
        )
    api_version = config.get("api_version") or "2024-06-01"
    url = "%s/embeddings?api-version=%s" % (base_url, api_version)
    headers = {"api-key": config["api_key"], "Content-Type": "application/json"}
    payload = {"input": texts}
    data = _post_json(url, headers, payload, config.get("timeout", 60))
    try:
        ordered = sorted(data["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in ordered]
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected Azure OpenAI embeddings response shape: %s" % exc) from exc


def call_gemini_embedding(config, texts):
    base_url = (
        config.get("api_base_url") or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    model = config.get("model") or "text-embedding-004"
    url = "%s/models/%s:batchEmbedContents?key=%s" % (base_url, model, config["api_key"])
    headers = {"Content-Type": "application/json"}
    payload = {
        "requests": [
            {"model": "models/%s" % model, "content": {"parts": [{"text": t}]}}
            for t in texts
        ]
    }
    data = _post_json(url, headers, payload, config.get("timeout", 60))
    try:
        return [item["values"] for item in data["embeddings"]]
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected Gemini embeddings response shape: %s" % exc) from exc


def call_ollama_embedding(config, texts):
    base_url = (config.get("api_base_url") or "http://localhost:11434").rstrip("/")
    url = "%s/api/embeddings" % base_url
    headers = {"Content-Type": "application/json"}
    model = config.get("model") or "nomic-embed-text"
    vectors = []
    # Ollama's embeddings endpoint takes one prompt per request.
    for text in texts:
        data = _post_json(
            url, headers, {"model": model, "prompt": text}, config.get("timeout", 60)
        )
        try:
            vectors.append(data["embedding"])
        except KeyError as exc:
            raise ProviderError("Unexpected Ollama embeddings response shape: %s" % exc) from exc
    return vectors


EMBEDDING_ADAPTERS = {
    "openai": call_openai_embedding,
    "azure_openai": call_azure_openai_embedding,
    "gemini": call_gemini_embedding,
    "ollama": call_ollama_embedding,
}


def call_embedding_provider(code, config, texts):
    adapter = EMBEDDING_ADAPTERS.get(code)
    if not adapter:
        raise ProviderError(
            "Provider '%s' does not support embeddings here. Use OpenAI, Azure "
            "OpenAI, Gemini, or Ollama as the dedicated embedding provider." % code
        )
    if not config.get("api_key") and code != "ollama":
        raise ProviderError("No API key configured for this embedding provider")
    return adapter(config, texts)
