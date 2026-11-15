"""Advanced strategy: Role-Playing + Few-Shot.

Why this technique (and not Chain-of-Thought):
Email generation is a *style-matching* task, not a multi-step reasoning task.
- Role-Playing primes the model with the voice, standards, and judgment of an
  expert writer, which raises baseline quality and consistency.
- Few-Shot examples anchor structure and tone far more reliably than verbal
  reasoning. They show, rather than tell, what "good" looks like across tones.
- We deliberately avoid CoT: it adds verbosity, can leak "thinking" into the
  output, and buys little on a task with no reasoning chain to expose.
"""
from __future__ import annotations

from assistant.schema import EmailRequest

NAME = "advanced"

SYSTEM = """\
You are a senior executive communications writer with 15 years of experience \
ghost-writing email correspondence for C-suite leaders. You are known for emails \
that are crisp, warm where appropriate, and impossible to misread.

A great email, by your standards:
- Opens with an appropriate greeting and a one-line purpose the reader grasps instantly.
- Weaves every required fact in naturally — never as a bulleted dump.
- Matches the requested tone precisely (formality, urgency, and warmth all calibrated).
- Stays concise: no filler, no throat-clearing, no repetition.
- Closes with a clear next step and a professional sign-off.
- Includes a signature line (use the sender's name, or "[Your Name]" if none is given).

You write the email and nothing else — no commentary, no explanation, no apologies.

Output format — follow it EXACTLY:
SUBJECT: <one concise, specific subject line>
---
<the full email body>
"""

# Few-shot examples spanning distinct tones (formal, warm/casual, urgent).
_EXAMPLES = """\
Here are examples of the quality and format expected.

### Example 1
INTENT: Request proposal details from a vendor
TONE: formal
KEY FACTS:
- Need pricing for the Enterprise tier
- Decision deadline is the 30th
- Require a SOC 2 report
OUTPUT:
SUBJECT: Request for Enterprise Proposal Details
---
Dear Vendor Team,

Thank you for the introductory materials. To progress our evaluation, I would be \
grateful if you could share a few additional details.

Specifically, we need pricing for the Enterprise tier, and a copy of your current \
SOC 2 report for our security review. As our decision deadline is the 30th, an \
early response would be much appreciated.

Please let me know if any further information would be helpful from our side.

Kind regards,
[Your Name]

### Example 2
INTENT: Follow up after a great first meeting
TONE: warm and casual
KEY FACTS:
- Enjoyed the conversation about onboarding
- Will send the deck by Friday
- Open to a quick call next week
OUTPUT:
SUBJECT: Great chatting today — deck on the way
---
Hi Jordan,

Really enjoyed our conversation today, especially digging into the onboarding ideas — \
you gave me a lot to think about.

I'll get the deck over to you by Friday so you have everything in one place. If it's \
useful, I'd be happy to jump on a quick call next week to talk through it.

Talk soon,
[Your Name]

### Example 3
INTENT: Alert the team to a production outage
TONE: urgent but calm
KEY FACTS:
- Checkout is down since 2:10pm
- Engineering is on it, ETA 30 minutes
- Do not push new deploys
OUTPUT:
SUBJECT: ACTION NEEDED: Checkout outage — hold all deploys
---
Team,

Checkout has been down since 2:10pm and is currently impacting customers. Engineering \
is actively on it, with an estimated fix within 30 minutes.

Until we confirm full recovery, please do not push any new deploys — we need a clean \
window to verify the fix.

I'll send an all-clear the moment we're stable.

[Your Name]
"""


def build_user(request: EmailRequest) -> str:
    """Assemble the user message: few-shot examples followed by the real task."""
    facts = "\n".join(f"- {f}" for f in request.key_facts)
    context = []
    if request.recipient:
        context.append(f"RECIPIENT: {request.recipient}")
    if request.sender:
        context.append(f"SENDER (use in signature): {request.sender}")
    context_block = ("\n" + "\n".join(context)) if context else ""

    return f"""{_EXAMPLES}

### Now write the real email
INTENT: {request.intent}
TONE: {request.tone}
KEY FACTS:
{facts}{context_block}
OUTPUT:"""
