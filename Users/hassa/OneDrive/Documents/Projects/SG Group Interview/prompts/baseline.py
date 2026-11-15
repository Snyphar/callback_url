"""Baseline strategy: Zero-Shot.

This is the control in our Part 3 comparison. It isolates the value of the
prompt-engineering work in `advanced.py` by removing exactly three things:
  1. the expert role / persona,
  2. the explicit definition of what "good" looks like,
  3. the few-shot examples.

It KEEPS the same output-format instruction, so both strategies are parseable
and the only variable under test is "role + few-shot", not formatting.
"""
from __future__ import annotations

from assistant.schema import EmailRequest

NAME = "baseline"

SYSTEM = "You are a helpful assistant that writes emails."


def build_user(request: EmailRequest) -> str:
    facts = "\n".join(f"- {f}" for f in request.key_facts)
    context = []
    if request.recipient:
        context.append(f"Recipient: {request.recipient}")
    if request.sender:
        context.append(f"Sender: {request.sender}")
    context_block = ("\n" + "\n".join(context)) if context else ""

    return f"""Write a professional email.

Intent: {request.intent}
Tone: {request.tone}
Key facts to include:
{facts}{context_block}

Return the email in this format:
SUBJECT: <subject line>
---
<email body>"""
