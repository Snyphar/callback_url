"""Provider-agnostic LLM client.

A single `complete(system, user)` interface dispatches to OpenAI, Google Gemini,
or Anthropic. SDKs are imported lazily so you only need the one you actually use.
The offline `replay` provider serves recorded responses for reproducible evals.

Retries with exponential backoff cover transient network / rate-limit errors.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",  # 2.0-flash free tier was retired; 2.5-flash is current
    "anthropic": "claude-haiku-4-5-20251001",
    # `replay` serves recorded LLM generations + judge verdicts from a fixture so the
    # full evaluation runs offline, deterministically, without an API key (VCR-style).
    "replay": "claude-opus-4-8",
}

# Providers that need no API key and never hit the network.
_OFFLINE = {"replay"}

# Env var holding the API key for each provider (with a friendly fallback for Google).
_KEY_ENV = {
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
}

SUPPORTED = set(DEFAULT_MODELS)


class LLMError(RuntimeError):
    """Raised when a provider call cannot be completed."""


def _resolve_key(provider: str) -> Optional[str]:
    for var in _KEY_ENV.get(provider, ()):
        val = os.getenv(var)
        if val:
            return val
    return None


@dataclass
class LLMClient:
    provider: str
    model: str
    api_key: Optional[str] = None

    # ------------------------------------------------------------------ factory
    @classmethod
    def from_env(cls, role: str = "gen") -> "LLMClient":
        """Build a client from env vars for a given role: 'gen' or 'judge'."""
        prefix = "JUDGE" if role == "judge" else "GEN"
        provider = (os.getenv(f"{prefix}_PROVIDER") or "replay").strip().lower()
        if provider not in SUPPORTED:
            raise LLMError(
                f"Unknown {prefix}_PROVIDER={provider!r}. Supported: {sorted(SUPPORTED)}"
            )
        model = (os.getenv(f"{prefix}_MODEL") or "").strip() or DEFAULT_MODELS[provider]
        api_key = None if provider in _OFFLINE else _resolve_key(provider)
        if provider not in _OFFLINE and not api_key:
            wanted = " or ".join(_KEY_ENV[provider])
            raise LLMError(
                f"{prefix}_PROVIDER={provider} but no API key found. Set {wanted} in .env."
            )
        return cls(provider=provider, model=model, api_key=api_key)

    # ------------------------------------------------------------------ public
    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 1200,
        json_mode: bool = False,
    ) -> str:
        """Return the model's text completion for a (system, user) pair."""
        if self.provider == "replay":
            from evaluation.replay_store import respond

            return respond(system, user)
        try:
            return self._complete_with_retry(system, user, temperature, max_tokens, json_mode)
        except Exception as exc:  # noqa: BLE001 - surface a uniform error type upward
            from tenacity import RetryError

            # Unwrap tenacity's RetryError so the message is the real provider error
            # (e.g. the 429 quota text) instead of "RetryError[<Future ...>]".
            cause = exc
            if isinstance(exc, RetryError) and exc.last_attempt is not None:
                cause = exc.last_attempt.exception() or exc
            raise LLMError(f"{self.provider} call failed: {cause}") from cause

    # Up to 5 attempts with backoff to ~45s, so a single free-tier per-minute
    # rate-limit (429) is ridden out rather than aborting a full evaluation run.
    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=4, max=45))
    def _complete_with_retry(self, system, user, temperature, max_tokens, json_mode) -> str:
        dispatch = {
            "openai": self._openai,
            "gemini": self._gemini,
            "anthropic": self._anthropic,
        }[self.provider]
        return dispatch(system, user, temperature, max_tokens, json_mode)

    # ---------------------------------------------------------------- providers
    def _openai(self, system, user, temperature, max_tokens, json_mode) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        kwargs = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return (resp.choices[0].message.content or "").strip()

    def _gemini(self, system, user, temperature, max_tokens, json_mode) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        cfg = dict(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        resp = client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(**cfg),
        )
        return (resp.text or "").strip()

    def _anthropic(self, system, user, temperature, max_tokens, json_mode) -> str:
        # Anthropic has no JSON mode; we rely on prompt instructions + robust parsing.
        from anthropic import Anthropic

        client = Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [block.text for block in resp.content if getattr(block, "type", None) == "text"]
        return "".join(parts).strip()

    # ------------------------------------------------------------------ helpers
    def label(self) -> str:
        return f"{self.provider}:{self.model}"
