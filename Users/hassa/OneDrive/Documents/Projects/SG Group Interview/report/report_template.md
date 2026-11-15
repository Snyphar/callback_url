# Email Generation Assistant — Final Report

> This document is **auto-generated** by the evaluation runner
> (`evaluation/report.py`) so the prose, prompt text, and scores can never drift
> from the code that produced them. Re-run `python cli.py evaluate` to refresh.
>
> **Run configuration:** generation = `{{CONFIG_GEN}}`, judge = `{{CONFIG_JUDGE}}`,
> scenarios = {{CONFIG_SCENARIOS}}, generation temperature = {{CONFIG_TEMP}}.

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
{{ADVANCED_SYSTEM}}
```

#### Advanced prompt — User message (example, including the few-shot block)

```
{{ADVANCED_USER_EXAMPLE}}
```

#### Baseline prompt (the control) — System + User

The baseline isolates the value of the technique above. It removes exactly three
things — the expert role, the explicit definition of "good", and the few-shot
examples — while **keeping the identical output format**, so the only variable
under test is "role + few-shot".

```
{{BASELINE_SYSTEM}}
```

```
{{BASELINE_USER_EXAMPLE}}
```

---

## 2. The Three Custom Metrics — Definitions & Logic

These are tailored to email generation and deliberately **hybrid**: two use an
LLM-as-judge (faithfulness and tone are semantic and resist regexes), and one is
pure Python (structure and length are deterministic and shouldn't cost a judge
call or risk judge noise). Using the right tool per failure mode — rather than
reaching for LLM-as-judge reflexively — is itself a design signal. All three are
normalized to **0–1** so they average into a single composite.

{{METRIC_DEFINITIONS}}

> Design note: for Fact Faithfulness the LLM only **classifies** each fact as
> present/absent; the score arithmetic is done in Python. We don't trust an LLM to
> do reliable division.

---

## 3. Raw Evaluation Data

Full machine-readable output: [`{{RAW_JSON_PATH}}`](../results/comparison.json),
plus per-strategy CSVs in [`results/`](../results/) and every generated email
under [`results/generations/`](../results/generations/).

### Average scores (normalized 0–1)

{{AVERAGES_TABLE}}

### Per-scenario raw scores — {{STRATEGY_NAME_1}}

{{PER_SCENARIO_TABLE_1}}

### Per-scenario raw scores — {{STRATEGY_NAME_2}}

{{PER_SCENARIO_TABLE_2}}

---

## 4. Comparative Analysis

**Composite score by strategy:**

{{COMPOSITE_TABLE}}

### Which strategy performed better?

According to all three custom metrics combined, **`{{WINNER}}`** performed better
on the composite score (see the table above).

### Biggest failure mode of the lower-performing strategy

{{FAILURE_MODE_SENTENCE}}

### Production recommendation

{{RECOMMENDATION_SENTENCE}}

---

*Generated from `report/report_template.md`. To produce a PDF:
`pandoc report/report_final.md -o report.pdf` (or use the VS Code "Markdown PDF"
extension).*
