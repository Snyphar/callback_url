"""Three custom metrics for email-generation quality.

Design principle: hybrid by intent. Two metrics use an LLM-as-judge (because
faithfulness and tone are semantic and resist regexes), and one is pure Python
(because structure and length are deterministic and should NOT cost a judge call
or risk judge noise). Mixing the two shows we pick the right tool per failure mode
instead of reaching for LLM-as-judge reflexively.

Every metric returns a dict with a normalized `score` in [0, 1] plus diagnostic
detail. Normalization lets us average the three into one composite per email.

  M1  Fact Faithfulness     LLM-judge   coverage of required facts (+ hallucination flag)
  M2  Tone Alignment        LLM-judge   1-5 match to requested tone, 3 sub-dimensions
  M3  Structural Soundness  Python      greeting/closing/signature/subject/length/no-preamble
"""
from __future__ import annotations

import re

from assistant.client import LLMClient
from assistant.schema import EmailRequest, EmailResponse
from evaluation.judge import judge_json

# Single source of truth for the report + comparison.json.
METRIC_DEFINITIONS = {
    "fact_faithfulness": {
        "name": "Fact Faithfulness",
        "method": "LLM-as-judge (classification) + Python scoring",
        "focus": "Fact Recall / Specificity",
        "failure_mode": "Hallucination and omission — the #1 failure of email assistants.",
        "logic": (
            "For each required input fact, the judge decides (semantic match, not "
            "string match) whether its meaning appears in the email. It also flags "
            "concrete claims present in the email but absent from the inputs "
            "(potential fabrications). Score = facts_covered / facts_total, computed "
            "in Python — the LLM only classifies, it never does the arithmetic."
        ),
        "range": "0.0 - 1.0 (fraction of required facts conveyed)",
    },
    "tone_alignment": {
        "name": "Tone Alignment",
        "method": "LLM-as-judge (rubric)",
        "focus": "Tone Accuracy",
        "failure_mode": "Every email sounds the same regardless of the requested tone.",
        "logic": (
            "The judge rates, on a 1-5 scale, how well the email's formality, urgency, "
            "and warmth align with what the requested tone implies, plus an overall "
            "match score. Score = (overall_match - 1) / 4, normalized to 0-1. The "
            "sub-dimensions are kept as diagnostics."
        ),
        "range": "0.0 - 1.0 (normalized from a 1-5 overall-match rating)",
    },
    "structural_soundness": {
        "name": "Structural Soundness",
        "method": "Pure Python (deterministic, no LLM)",
        "focus": "Format Adherence / Conciseness",
        "failure_mode": "Malformed output, missing parts, meta-preamble, or runaway length.",
        "logic": (
            "Six deterministic checks: (1) non-empty, sensible subject; (2) a greeting; "
            "(3) a sign-off; (4) a signature line/placeholder; (5) body length within "
            "0.4x-2.5x of the human reference word count; (6) no meta-preamble such as "
            "'Sure, here is your email'. Score = checks_passed / 6."
        ),
        "range": "0.0 - 1.0 (fraction of 6 structural checks passed)",
    },
}

# --------------------------------------------------------------------------- M3
_GREETING = re.compile(
    r"^\s*(dear|hi|hello|hey|good\s+(morning|afternoon|evening)|greetings|to\s+whom|team\b)",
    re.IGNORECASE,
)
_CLOSING = re.compile(
    r"\b(regards|best|sincerely|cheers|thank you|thanks|with thanks|warm regards|"
    r"kind regards|respectfully|with respect|respect|appreciation|gratitude|gratefully|"
    r"talk soon|looking forward|all the best|yours)\b",
    re.IGNORECASE,
)
_SIGNATURE = re.compile(r"\[\s*your name\s*\]|\[\s*name\s*\]|\[\s*signature\s*\]", re.IGNORECASE)
_PREAMBLE = re.compile(
    r"^\s*(sure|certainly|of course|here(?:'s| is)|below is|i'd be happy|as an ai)",
    re.IGNORECASE,
)


def _words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def structural_soundness(
    request: EmailRequest, email: EmailResponse, reference_body: str
) -> dict:
    """Pure-Python structural checks. No LLM, fully deterministic."""
    body = email.body or ""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    tail = "\n".join(lines[-4:]) if lines else ""

    ref_w = max(_words(reference_body), 1)
    out_w = _words(body)
    length_ratio = out_w / ref_w

    has_signature = bool(_SIGNATURE.search(body)) or bool(request.sender and request.sender in body)

    checks = {
        "has_subject": bool(email.subject and 3 <= len(email.subject.strip()) <= 120),
        "has_greeting": bool(lines and _GREETING.search(lines[0])),
        "has_closing": bool(_CLOSING.search(tail)),
        "has_signature": has_signature,
        "length_in_band": 0.4 <= length_ratio <= 2.5,
        "no_preamble": not bool(_PREAMBLE.search(body)),
    }
    passed = sum(checks.values())
    return {
        "score": round(passed / len(checks), 4),
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
        "length_ratio": round(length_ratio, 2),
        "word_count": out_w,
    }


# --------------------------------------------------------------------------- M1
_FACT_JUDGE_SYSTEM = """\
You are a meticulous fact-checker evaluating whether an email faithfully includes \
a set of required facts. For each fact, decide whether its MEANING is conveyed in \
the email (semantic match — paraphrase counts, exact wording is not required).

Also list any CONCRETE claims the email asserts that were NOT in the provided facts \
and are not generic pleasantries (these are potential fabrications).

Respond with ONLY a JSON object, no prose, in exactly this shape:
{"facts": [{"id": 1, "present": true, "evidence": "<short quote or empty>"}],
 "fabricated_claims": ["<claim>", "..."]}"""


def fact_faithfulness(
    request: EmailRequest, email: EmailResponse, client: LLMClient
) -> dict:
    """M1: fraction of required facts semantically present (judge classifies, Python scores)."""
    numbered = "\n".join(f"{i+1}. {f}" for i, f in enumerate(request.key_facts))
    user = (
        f"REQUIRED FACTS:\n{numbered}\n\n"
        f"EMAIL UNDER REVIEW:\n\"\"\"\n{email.body}\n\"\"\"\n\n"
        f"Return the JSON object."
    )
    try:
        data = judge_json(client, _FACT_JUDGE_SYSTEM, user)
        facts = data.get("facts", [])
        total = len(request.key_facts)
        covered = sum(1 for f in facts if f.get("present"))
        # Guard against a judge that returns the wrong number of items.
        covered = min(covered, total)
        fabricated = data.get("fabricated_claims", []) or []
        return {
            "score": round(covered / total, 4) if total else 0.0,
            "facts_covered": covered,
            "facts_total": total,
            "fabricated_claims": fabricated,
            "facts": facts,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "score": 0.0,
            "facts_covered": 0,
            "facts_total": len(request.key_facts),
            "fabricated_claims": [],
            "facts": [],
            "error": str(exc),
        }


# --------------------------------------------------------------------------- M2
_TONE_JUDGE_SYSTEM = """\
You are an expert communications evaluator. You score how well an email matches a \
REQUESTED tone. Judge three sub-dimensions and an overall match, each on a 1-5 \
integer scale where 5 = perfectly aligned with the requested tone and 1 = clearly \
misaligned.

Respond with ONLY a JSON object, no prose, in exactly this shape:
{"formality": 1-5, "urgency": 1-5, "warmth": 1-5, "overall_match": 1-5,
 "reasoning": "<one or two sentences>"}"""


def tone_alignment(
    request: EmailRequest, email: EmailResponse, client: LLMClient
) -> dict:
    """M2: how well the email matches the requested tone (1-5 -> normalized 0-1)."""
    user = (
        f"REQUESTED TONE: {request.tone}\n\n"
        f"EMAIL UNDER REVIEW:\n\"\"\"\n{email.body}\n\"\"\"\n\n"
        f"Return the JSON object."
    )
    try:
        data = judge_json(client, _TONE_JUDGE_SYSTEM, user)
        overall = float(data.get("overall_match", 0))
        overall = max(1.0, min(5.0, overall))
        return {
            "score": round((overall - 1) / 4, 4),
            "overall_match_5": overall,
            "formality": data.get("formality"),
            "urgency": data.get("urgency"),
            "warmth": data.get("warmth"),
            "reasoning": data.get("reasoning", ""),
        }
    except Exception as exc:  # noqa: BLE001
        return {"score": 0.0, "overall_match_5": 0, "reasoning": "", "error": str(exc)}


# --------------------------------------------------------------------------- all
def evaluate_email(
    request: EmailRequest,
    email: EmailResponse,
    reference_body: str,
    judge_client: LLMClient,
) -> dict:
    """Run all three metrics and the composite for a single email."""
    m1 = fact_faithfulness(request, email, judge_client)
    m2 = tone_alignment(request, email, judge_client)
    m3 = structural_soundness(request, email, reference_body)
    composite = round((m1["score"] + m2["score"] + m3["score"]) / 3, 4)
    return {
        "fact_faithfulness": m1,
        "tone_alignment": m2,
        "structural_soundness": m3,
        "composite": composite,
    }
