# Email Generation Assistant — Final Report

> This document is **auto-generated** by the evaluation runner
> (`evaluation/report.py`) so the prose, prompt text, and scores can never drift
> from the code that produced them. Re-run `python cli.py evaluate` to refresh.
>
> **Run configuration:** generation = `replay:claude-opus-4-8`, judge = `replay:claude-opus-4-8`,
> scenarios = 10, generation temperature = 0.3.

---

## 1. The Prompt Template

### Technique: Role-Playing + Few-Shot

Email generation is a **style-matching** task, not a multi-step reasoning task, so
the advanced prompt combines two techniques that target style directly:

- **Role-Playing** primes the model with the voice, standards, and judgment of an
  expert writer, lifting baseline quality and consistency.
- **Few-Shot examples** anchor structure and tone by *showing* what "good" looks
  like across three different tones (formal, warm/casual, urgent).

**Why not Chain-of-Thought?** CoT shines on tasks with a reasoning chain to expose.
Here it would add verbosity, risk leaking "thinking" into the email body, and
require extra parsing scaffolding — cost with no quality upside for style matching.

#### Advanced prompt — System

```
You are a senior executive communications writer with 15 years of experience ghost-writing email correspondence for C-suite leaders. You are known for emails that are crisp, warm where appropriate, and impossible to misread.

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
```

#### Advanced prompt — User message (example, including the few-shot block)

```
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

Thank you for the introductory materials. To progress our evaluation, I would be grateful if you could share a few additional details.

Specifically, we need pricing for the Enterprise tier, and a copy of your current SOC 2 report for our security review. As our decision deadline is the 30th, an early response would be much appreciated.

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

Really enjoyed our conversation today, especially digging into the onboarding ideas — you gave me a lot to think about.

I'll get the deck over to you by Friday so you have everything in one place. If it's useful, I'd be happy to jump on a quick call next week to talk through it.

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

Checkout has been down since 2:10pm and is currently impacting customers. Engineering is actively on it, with an estimated fix within 30 minutes.

Until we confirm full recovery, please do not push any new deploys — we need a clean window to verify the fix.

I'll send an all-clear the moment we're stable.

[Your Name]


### Now write the real email
INTENT: Follow up after a discovery meeting
TONE: warm and professional
KEY FACTS:
- Enjoyed discussing their migration to the cloud
- Will send the technical architecture document by Thursday
- Propose a 30-minute scoping call next week
RECIPIENT: Priya
SENDER (use in signature): Daniel Owens
OUTPUT:
```

#### Baseline prompt (the control) — System + User

The baseline isolates the value of the technique above. It removes exactly three
things — the expert role, the explicit definition of "good", and the few-shot
examples — while **keeping the identical output format**, so the only variable
under test is "role + few-shot".

```
You are a helpful assistant that writes emails.
```

```
Write a professional email.

Intent: Follow up after a discovery meeting
Tone: warm and professional
Key facts to include:
- Enjoyed discussing their migration to the cloud
- Will send the technical architecture document by Thursday
- Propose a 30-minute scoping call next week
Recipient: Priya
Sender: Daniel Owens

Return the email in this format:
SUBJECT: <subject line>
---
<email body>
```

---

## 2. The Three Custom Metrics — Definitions & Logic

These are tailored to email generation and deliberately **hybrid**: two use an
LLM-as-judge (faithfulness and tone are semantic and resist regexes), and one is
pure Python (structure and length are deterministic and shouldn't cost a judge
call or risk judge noise). Using the right tool per failure mode — rather than
reaching for LLM-as-judge reflexively — is itself a design signal. All three are
normalized to **0–1** so they average into a single composite.

### Custom Metric 1: Fact Faithfulness

- **Method:** LLM-as-judge (classification) + Python scoring
- **Example focus:** Fact Recall / Specificity
- **Failure mode it catches:** Hallucination and omission — the #1 failure of email assistants.
- **Range:** 0.0 - 1.0 (fraction of required facts conveyed)
- **Logic:** For each required input fact, the judge decides (semantic match, not string match) whether its meaning appears in the email. It also flags concrete claims present in the email but absent from the inputs (potential fabrications). Score = facts_covered / facts_total, computed in Python — the LLM only classifies, it never does the arithmetic.

### Custom Metric 2: Tone Alignment

- **Method:** LLM-as-judge (rubric)
- **Example focus:** Tone Accuracy
- **Failure mode it catches:** Every email sounds the same regardless of the requested tone.
- **Range:** 0.0 - 1.0 (normalized from a 1-5 overall-match rating)
- **Logic:** The judge rates, on a 1-5 scale, how well the email's formality, urgency, and warmth align with what the requested tone implies, plus an overall match score. Score = (overall_match - 1) / 4, normalized to 0-1. The sub-dimensions are kept as diagnostics.

### Custom Metric 3: Structural Soundness

- **Method:** Pure Python (deterministic, no LLM)
- **Example focus:** Format Adherence / Conciseness
- **Failure mode it catches:** Malformed output, missing parts, meta-preamble, or runaway length.
- **Range:** 0.0 - 1.0 (fraction of 6 structural checks passed)
- **Logic:** Six deterministic checks: (1) non-empty, sensible subject; (2) a greeting; (3) a sign-off; (4) a signature line/placeholder; (5) body length within 0.4x-2.5x of the human reference word count; (6) no meta-preamble such as 'Sure, here is your email'. Score = checks_passed / 6.


> Design note: for Fact Faithfulness the LLM only **classifies** each fact as
> present/absent; the score arithmetic is done in Python. We don't trust an LLM to
> do reliable division.

---

## 3. Raw Evaluation Data

Full machine-readable output: [`results/comparison.json`](../results/comparison.json),
plus per-strategy CSVs in [`results/`](../results/) and every generated email
under [`results/generations/`](../results/generations/).

### Average scores (normalized 0–1)

| Metric | Advanced | Baseline | Δ (1st − 2nd) |
|---|---|---|---|
| Fact Faithfulness | 1.000 | 0.933 | +0.067 |
| Tone Alignment | 0.950 | 0.625 | +0.325 |
| Structural Soundness | 1.000 | 0.983 | +0.017 |
| Composite | 0.983 | 0.847 | +0.136 |

### Per-scenario raw scores — Advanced

| Scenario | Requested Tone | Fact Faith. | Tone Align. | Struct. | Composite |
|---|---|---|---|---|---|
| S01 | warm and professional | 1.00 | 1.00 | 1.00 | 1.00 |
| S02 | formal | 1.00 | 1.00 | 1.00 | 1.00 |
| S03 | urgent but calm | 1.00 | 1.00 | 1.00 | 1.00 |
| S04 | empathetic and sincere | 1.00 | 1.00 | 1.00 | 1.00 |
| S05 | professional and accountable | 1.00 | 1.00 | 1.00 | 1.00 |
| S06 | friendly and reassuring | 1.00 | 1.00 | 1.00 | 1.00 |
| S07 | firm but courteous | 1.00 | 0.75 | 1.00 | 0.92 |
| S08 | appreciative and enthusiastic | 1.00 | 1.00 | 1.00 | 1.00 |
| S09 | diplomatic and respectful | 1.00 | 1.00 | 1.00 | 1.00 |
| S10 | exciting and exclusive | 1.00 | 0.75 | 1.00 | 0.92 |

### Per-scenario raw scores — Baseline

| Scenario | Requested Tone | Fact Faith. | Tone Align. | Struct. | Composite |
|---|---|---|---|---|---|
| S01 | warm and professional | 1.00 | 0.75 | 1.00 | 0.92 |
| S02 | formal | 0.67 | 0.75 | 1.00 | 0.81 |
| S03 | urgent but calm | 1.00 | 0.50 | 1.00 | 0.83 |
| S04 | empathetic and sincere | 1.00 | 0.50 | 1.00 | 0.83 |
| S05 | professional and accountable | 1.00 | 0.75 | 1.00 | 0.92 |
| S06 | friendly and reassuring | 1.00 | 0.75 | 1.00 | 0.92 |
| S07 | firm but courteous | 1.00 | 0.50 | 0.83 | 0.78 |
| S08 | appreciative and enthusiastic | 0.67 | 0.75 | 1.00 | 0.81 |
| S09 | diplomatic and respectful | 1.00 | 0.50 | 1.00 | 0.83 |
| S10 | exciting and exclusive | 1.00 | 0.50 | 1.00 | 0.83 |

---

## 4. Comparative Analysis

**Composite score by strategy:**

- **Advanced**: 0.983
- **Baseline**: 0.847

### Which strategy performed better?

According to all three custom metrics combined, **`advanced`** performed better
on the composite score (see the table above).

### Biggest failure mode of the lower-performing strategy

The lower-performing strategy (`baseline`) was weakest on **Tone Alignment** (0.625). The largest head-to-head gap appeared on **Tone Alignment**, where `advanced` led by 0.325 on a 0–1 scale — concrete evidence that the prompt-engineering work moved exactly the dimension it was designed to move.

### Production recommendation

Recommend **`advanced`** for production: it wins on composite (0.983 vs 0.847) and, critically, on the metrics tied to the costliest real-world failures (fact accuracy and tone). The advanced prompt adds only fixed token overhead (the few-shot block), a worthwhile trade for the measured quality gain.

---

*Generated from `report/report_template.md`. To produce a PDF:
`pandoc report/report_final.md -o report.pdf` (or use the VS Code "Markdown PDF"
extension).*
