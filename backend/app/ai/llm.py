"""
Shared LLM client.

Primary: Groq (Llama 3.3 70B). Fallback: NVIDIA NIM (Llama 3.1 70B).
Both speak the OpenAI chat-completions format, including tool calling.
Every attempt (success, error, or skipped provider) is recorded in the
observability store with latency and token usage.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

import logging
import os

from app.ai import observability

app_logger = logging.getLogger("uvicorn.error")


class _Settings:
    """LLM settings read from the environment at call time (so tests can patch them)."""

    @property
    def GROQ_API_KEY(self) -> str:
        return os.environ.get("GROQ_API_KEY", "")

    @property
    def GROQ_MODEL(self) -> str:
        return os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    @property
    def NVIDIA_NIM_API_KEY(self) -> str:
        return os.environ.get("NVIDIA_NIM_API_KEY", "")

    @property
    def NVIDIA_NIM_MODEL(self) -> str:
        return os.environ.get("NVIDIA_NIM_MODEL", "meta/llama-3.1-70b-instruct")


settings = _Settings()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
NVIDIA_NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
SYSTEM_JSON = "You are a precise assistant for an electricity-distribution analytics tool. Return valid JSON when asked."


@dataclass
class Provider:
    name: str
    url: str
    key: Callable[[], str]
    model: Callable[[], str]


PROVIDERS: List[Provider] = [
    Provider("groq", GROQ_URL, lambda: settings.GROQ_API_KEY, lambda: settings.GROQ_MODEL),
    Provider("nvidia_nim", NVIDIA_NIM_URL, lambda: settings.NVIDIA_NIM_API_KEY, lambda: settings.NVIDIA_NIM_MODEL),
]

# Tests replace this to avoid network calls: (provider, payload) -> response JSON.
Transport = Callable[[Provider, Dict[str, Any]], Dict[str, Any]]


def _http_transport(provider: Provider, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = httpx.post(
        provider.url,
        headers={"Authorization": f"Bearer {provider.key()}", "Content-Type": "application/json"},
        json=payload,
        timeout=25.0,
    )
    response.raise_for_status()
    return response.json()


transport: Transport = _http_transport


@dataclass
class ChatResult:
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)  # [{id, name, arguments(dict)}]
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: float = 0.0
    errors: List[str] = field(default_factory=list)  # failures of earlier providers in this call


def configured_providers() -> List[str]:
    return [p.name for p in PROVIDERS if p.key()]


def has_any_provider() -> bool:
    return bool(configured_providers())


def chat(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> Optional[ChatResult]:
    """One chat completion, trying each configured provider in order. None if all fail."""
    errors: List[str] = []
    for provider in PROVIDERS:
        if not provider.key():
            continue
        payload: Dict[str, Any] = {
            "model": provider.model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        started = time.perf_counter()
        try:
            data = transport(provider, payload)
            latency = (time.perf_counter() - started) * 1000
            msg = data["choices"][0]["message"]
            calls = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": fn.get("arguments")}
                calls.append({"id": tc.get("id") or f"call_{len(calls)}", "name": fn.get("name"), "arguments": args})
            usage = data.get("usage") or {}
            observability.record_llm_call(
                provider.name, provider.model(), "ok", latency,
                usage.get("prompt_tokens"), usage.get("completion_tokens"), len(calls))
            return ChatResult((msg.get("content") or "").strip(), calls, provider.name, provider.model(),
                              latency, errors)
        except Exception as exc:  # network, HTTP status, malformed body
            latency = (time.perf_counter() - started) * 1000
            reason = _describe(exc)
            errors.append(f"{provider.name}: {reason}")
            observability.record_llm_call(provider.name, provider.model(), "error", latency, error=reason)
            app_logger.warning(f"{provider.name} request failed: {reason}")
    return None


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return type(exc).__name__ + (f": {exc}" if str(exc) else "")


def _strip_code_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.startswith("json"):
                candidate = candidate[4:]
            return candidate.strip()
    return text


def extract_json(text: str) -> Any:
    cleaned = _strip_code_fence(text)
    if not (cleaned.startswith("{") or cleaned.startswith("[")):
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
        cleaned = match.group(1).strip() if match else cleaned
    return json.loads(cleaned)


def generate_text_with_fallback(
    prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (text, provider) for a single-prompt completion."""
    result = chat([{"role": "system", "content": SYSTEM_JSON}, {"role": "user", "content": prompt}],
                  temperature=temperature, max_tokens=max_tokens)
    if result is None or not result.content:
        return None, None
    return result.content, result.provider


def generate_json_with_fallback(
    prompt: str,
    default: Any,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> Tuple[Any, Optional[str]]:
    """Return (parsed_json, provider); `default` if no provider answered or the JSON didn't parse."""
    text, provider = generate_text_with_fallback(prompt, temperature=temperature, max_tokens=max_tokens)
    if not text:
        return default, None
    try:
        return extract_json(text), provider
    except Exception as exc:
        app_logger.warning(f"Failed to parse JSON from {provider}: {exc}")
        return default, provider
