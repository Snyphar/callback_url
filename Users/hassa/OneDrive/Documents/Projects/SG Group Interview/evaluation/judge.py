"""LLM-as-judge helper: call a model and parse strict JSON back, robustly.

We force a JSON object out of the judge, then defend against the usual failure
modes (markdown fences, leading prose) before json.loads. One retry covers a
flaky parse.
"""
from __future__ import annotations

import json
import re

from assistant.client import LLMClient

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response."""
    if not text:
        raise ValueError("empty judge response")
    fenced = _FENCE.search(text)
    candidate = fenced.group(1) if fenced else text
    # Narrow to the outermost {...} if there is surrounding prose.
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]
    return json.loads(candidate)


def judge_json(
    client: LLMClient,
    system: str,
    user: str,
    temperature: float = 0.0,
    retries: int = 1,
) -> dict:
    """Run the judge and return parsed JSON; retry once on parse failure."""
    last_err: Exception | None = None
    for _ in range(retries + 1):
        raw = client.complete(system, user, temperature=temperature, json_mode=True)
        try:
            return extract_json(raw)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise ValueError(f"judge did not return valid JSON: {last_err}")
