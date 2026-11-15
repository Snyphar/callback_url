"""Deterministic tests — no API key required (parsing/structure are pure Python;
the integration test runs through the offline `replay` provider)."""
from __future__ import annotations

import json
from pathlib import Path

from assistant.client import LLMClient
from assistant.generator import generate, parse_email
from assistant.schema import EmailRequest, EmailResponse
from evaluation.metrics import (
    fact_faithfulness,
    structural_soundness,
    tone_alignment,
)

ROOT = Path(__file__).resolve().parents[1]
REPLAY = LLMClient(provider="replay", model="claude-opus-4-8")


def _scenario(sid: str) -> dict:
    data = json.loads((ROOT / "evaluation" / "scenarios.json").read_text(encoding="utf-8"))
    return next(s for s in data if s["id"] == sid)


# --------------------------------------------------------------------- parsing
def test_parse_email_with_separator():
    raw = "SUBJECT: Hello there\n---\nHi Jordan,\n\nBody text.\n\nBest,\nSam"
    subject, body = parse_email(raw)
    assert subject == "Hello there"
    assert body.startswith("Hi Jordan,")
    assert "SUBJECT" not in body


def test_parse_strips_preamble():
    raw = "Sure, here is your email:\nSUBJECT: Hi\n---\nHello,\n\nText.\n\nBest,\nSam"
    subject, body = parse_email(raw)
    assert subject == "Hi"
    assert not body.lower().startswith("sure")


# ------------------------------------------------- structural metric (pure py)
def test_structural_soundness_perfect():
    email = EmailResponse(
        subject="Following up",
        body="Hi Priya,\n\nGreat to chat today. I'll send the doc Thursday.\n\nBest regards,\nDaniel Owens",
    )
    req = EmailRequest(intent="Follow up", key_facts=["x"], tone="warm", sender="Daniel Owens")
    result = structural_soundness(req, email, reference_body=email.body)
    assert result["score"] == 1.0
    assert all(result["checks"].values())


def test_structural_flags_preamble_and_missing_parts():
    req = EmailRequest(intent="Follow up", key_facts=["x"], tone="warm")
    bad = EmailResponse(subject="", body="Sure, here is your email. Some text.")
    result = structural_soundness(req, bad, reference_body="x " * 40)
    assert result["score"] < 0.5
    assert result["checks"]["no_preamble"] is False
    assert result["checks"]["has_subject"] is False


# --------------------------------------------- end-to-end via replay provider
def test_replay_generate_and_score_advanced_s01():
    sc = _scenario("S01")
    req = EmailRequest(**sc["input"])

    email = generate(req, "advanced", REPLAY)
    assert email.subject
    assert email.provider == "replay"
    assert "Priya" in email.body  # recipient woven in

    assert fact_faithfulness(req, email, REPLAY)["score"] == 1.0
    assert tone_alignment(req, email, REPLAY)["score"] == 1.0
    assert structural_soundness(req, email, sc["reference"]["body"])["score"] == 1.0


def test_replay_baseline_is_weaker_on_tone():
    sc = _scenario("S03")  # "urgent but calm" — baseline reads flat
    req = EmailRequest(**sc["input"])

    advanced = tone_alignment(req, generate(req, "advanced", REPLAY), REPLAY)["score"]
    baseline = tone_alignment(req, generate(req, "baseline", REPLAY), REPLAY)["score"]
    assert advanced > baseline
