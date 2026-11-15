"""Email generation: turn an EmailRequest into a parsed EmailResponse.

Handles two things:
  1. Prompt assembly via the chosen strategy module.
  2. Robust parsing of the model's "SUBJECT: ... --- body" output.
"""
from __future__ import annotations

import re

from assistant.client import LLMClient
from assistant.schema import EmailRequest, EmailResponse
from prompts import get_strategy

# Preambles models sometimes prepend; we strip them so parsing stays robust.
_PREAMBLE = re.compile(
    r"^\s*(sure|certainly|of course|here(?:'s| is)|below is|i'd be happy)[^\n]*\n",
    re.IGNORECASE,
)


def parse_email(raw: str) -> tuple[str, str]:
    """Parse '(SUBJECT: ...)\\n---\\n<body>' into (subject, body), tolerantly."""
    text = (raw or "").strip()
    text = _PREAMBLE.sub("", text).strip()

    subject = ""
    subj_match = re.search(r"^\s*subject\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if subj_match:
        subject = subj_match.group(1).strip()

    # Body = everything after the first '---' separator, else after the subject line.
    if "---" in text:
        body = text.split("---", 1)[1].strip()
    elif subj_match:
        body = text[subj_match.end():].strip()
    else:
        body = text

    # Strip any stray leading 'Body:' label or leftover subject line in the body.
    body = re.sub(r"^\s*body\s*:\s*", "", body, flags=re.IGNORECASE)
    body = re.sub(r"^\s*subject\s*:.*$\n?", "", body, flags=re.IGNORECASE | re.MULTILINE).strip()
    return subject, body


def generate(
    request: EmailRequest,
    strategy_name: str,
    client: LLMClient,
    temperature: float = 0.3,
) -> EmailResponse:
    """Generate an email for `request` using the named strategy and given client."""
    strategy = get_strategy(strategy_name)
    raw = client.complete(
        system=strategy.SYSTEM,
        user=strategy.build_user(request),
        temperature=temperature,
        max_tokens=1200,
    )
    subject, body = parse_email(raw)
    return EmailResponse(
        subject=subject,
        body=body,
        strategy=strategy_name,
        provider=client.provider,
        model=client.model,
        raw=raw,
    )
