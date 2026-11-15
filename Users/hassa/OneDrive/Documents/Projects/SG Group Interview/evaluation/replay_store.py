"""Replay provider backend (VCR-style).

Serves recorded LLM responses from `replay_data.json` so the full evaluation runs
offline and deterministically, through the exact same generator / metric / judge
code paths as a live API run. The recorded generations and judge verdicts were
produced by Claude (Anthropic) using the same prompts the code sends.

A single `respond(system, user)` has to cover three call types, so it routes by
content:
  - generation  -> identified by strategy (system prompt) + scenario (task INTENT)
  - fact judge  -> identified by the email body embedded in the prompt
  - tone judge  -> identified by the email body embedded in the prompt
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evaluation" / "replay_data.json"
SCENARIOS = ROOT / "evaluation" / "scenarios.json"


class ReplayStore:
    def __init__(self) -> None:
        from assistant.generator import parse_email

        self.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
        self.intent_to_id = {
            s["input"]["intent"].strip().lower(): s["id"] for s in scenarios
        }
        # Index parsed bodies so judge calls can be matched back to (strategy, id).
        self.bodies: list[tuple[str, str, str]] = []
        for strategy in ("advanced", "baseline"):
            for sid, raw in self.data["generations"][strategy].items():
                _, body = parse_email(raw)
                self.bodies.append((body, strategy, sid))

    def _scenario_from_intent(self, user: str) -> str:
        low = user.lower()
        idx = low.rfind("intent:")  # the real task INTENT is the last one (few-shot first)
        tail = user[idx + len("intent:") :].split("\n", 1)[0].strip().lower()
        sid = self.intent_to_id.get(tail)
        if sid is None:
            from assistant.client import LLMError

            raise LLMError(
                f"replay provider only knows the 10 recorded scenarios and cannot "
                f"generate for a new intent ({tail!r}). Use a real provider "
                f"(GEN_PROVIDER=gemini/openai/anthropic) with a key for new inputs."
            )
        return sid

    def _match_body(self, user: str) -> tuple[str, str]:
        best: tuple[str, str, str] | None = None
        for body, strategy, sid in self.bodies:
            if body and body in user and (best is None or len(body) > len(best[0])):
                best = (body, strategy, sid)
        if best is None:
            from assistant.client import LLMError

            raise LLMError("replay: could not match an email body to a recorded generation")
        return best[1], best[2]

    def respond(self, system: str, user: str) -> str:
        s = system.lower()
        if "fact-checker" in s:
            strategy, sid = self._match_body(user)
            return json.dumps(self.data["fact_verdicts"][strategy][sid])
        if "communications evaluator" in s:
            strategy, sid = self._match_body(user)
            return json.dumps(self.data["tone_verdicts"][strategy][sid])
        # Otherwise this is a generation call.
        strategy = "advanced" if "senior executive communications writer" in s else "baseline"
        sid = self._scenario_from_intent(user)
        return self.data["generations"][strategy][sid]


@lru_cache(maxsize=1)
def _store() -> ReplayStore:
    return ReplayStore()


def respond(system: str, user: str) -> str:
    return _store().respond(system, user)
