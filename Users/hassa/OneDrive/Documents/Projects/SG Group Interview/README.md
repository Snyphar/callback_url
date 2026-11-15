# Email Generation Assistant

An LLM-powered assistant that turns **intent + key facts + tone** into a polished,
professional email — plus a rigorous, custom-built evaluation harness that measures
how good those emails actually are.

Built for the AI Engineer assessment. It demonstrates four things end to end:
real prompt engineering, a thoughtfully designed evaluation strategy, clean and
reproducible code, and a data-driven recommendation.

---

## Highlights

- **Advanced prompting:** Role-Playing + Few-Shot, with a documented rationale for
  *why not* Chain-of-Thought ([`prompts/advanced.py`](prompts/advanced.py)).
- **Three custom metrics**, deliberately **hybrid** — two LLM-as-judge + one pure
  Python — each tied to a specific real-world failure mode
  ([`evaluation/metrics.py`](evaluation/metrics.py)).
- **Provider-agnostic client:** OpenAI, Google Gemini, or Anthropic, selected via
  `.env`; SDKs are imported lazily ([`assistant/client.py`](assistant/client.py)).
- **Offline `replay` provider:** reproduces the *entire* evaluation from recorded
  model outputs with no API key, so the results are deterministic and testable in CI.
- **Self-writing report:** the runner fills [`report/report_template.md`](report/report_template.md)
  with the real prompts, scores, and analysis — the report can never drift from the code.
- **Three entry points, one contract:** CLI, FastAPI `/generate`, and the evaluator
  all share the same validated pydantic `EmailRequest`/`EmailResponse`.

---

## Quick start

```bash
# 1. Install
python -m venv .venv
.venv\Scripts\activate            # Windows  (use: source .venv/bin/activate  on macOS/Linux)
pip install -r requirements.txt

# 2. Reproduce the committed evaluation offline — NO API key needed
python cli.py evaluate --provider replay
pytest -q

# 3. (Optional) Run against a live API instead
copy .env.example .env            # cp on macOS/Linux
#   edit .env: set GEN_PROVIDER / JUDGE_PROVIDER and the matching API key

# 4. Run the live evaluation (writes results/ + report/report_final.md)
python cli.py evaluate
```

> `--provider replay` reproduces the exact committed results from recorded model
> outputs (see "How the committed results were produced" below). To re-run against
> a live API, configure a provider key in `.env` and drop the `--provider` flag.

---

## Configuration (`.env`)

| Variable | Purpose | Example |
|---|---|---|
| `GEN_PROVIDER` | Provider for email generation | `gemini` \| `openai` \| `anthropic` \| `replay` |
| `JUDGE_PROVIDER` | Provider for the LLM-as-judge metrics | `gemini` |
| `GEN_MODEL` / `JUDGE_MODEL` | Optional model override | `gemini-2.5-flash` |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | Key for your provider | — |
| `GEN_TEMPERATURE` | Generation sampling temp (low = reproducible) | `0.3` |
| `JUDGE_TEMPERATURE` | Judge temp (0 = deterministic scoring) | `0.0` |

Default models per provider: `openai → gpt-4o-mini`, `gemini → gemini-2.5-flash`,
`anthropic → claude-haiku-4-5-20251001`.

### How the committed results were produced (`replay` provider)

The results in [`results/`](results/) and [`report/report_final.md`](report/report_final.md)
were generated with the **`replay`** provider: recorded model generations and
judge verdicts (produced by **Claude / Anthropic** using the exact prompts the
code sends) are served from [`evaluation/replay_data.json`](evaluation/replay_data.json)
through the *same* runner, metrics, and report code as a live API run. This makes
the evaluation **fully reproducible offline at zero API cost** — a VCR/cassette
pattern. Structural Soundness is still computed live in Python over the recorded
emails; only the two LLM-as-judge metrics read recorded verdicts.

To regenerate against a live API instead, set `GEN_PROVIDER`/`JUDGE_PROVIDER` to
`gemini`/`openai`/`anthropic` with a key and re-run `python cli.py evaluate`.

---

## Usage

### Generate a single email (CLI)

```bash
python cli.py generate \
  --intent "Follow up after a discovery meeting" \
  --fact "Enjoyed discussing their cloud migration" \
  --fact "Will send the architecture doc by Thursday" \
  --fact "Propose a 30-minute scoping call next week" \
  --tone "warm and professional" \
  --recipient "Priya" --sender "Daniel Owens" \
  --strategy advanced            # or: baseline
```

### Run the evaluation

```bash
python cli.py evaluate                       # advanced vs baseline, all 10 scenarios
python cli.py evaluate --limit 3             # quick subset
python cli.py evaluate --strategies advanced # single strategy
```

Outputs to `results/`: `advanced_results.csv`, `baseline_results.csv`,
`comparison.json` (definitions + averages + head-to-head), and the raw generated
emails under `results/generations/`. It then renders `report/report_final.md`.

### Run the API

```bash
python cli.py serve                          # or: uvicorn api.app:app --reload
# POST http://127.0.0.1:8000/generate  •  interactive docs at /docs
```

```bash
curl -X POST "http://127.0.0.1:8000/generate?strategy=advanced" \
  -H "Content-Type: application/json" \
  -d '{"intent":"Request a deadline extension","key_facts":["Need two more days","All other sections are on track"],"tone":"professional and accountable","sender":"Marcus"}'
```

### Produce the PDF report

```bash
pandoc report/report_final.md -o report.pdf      # or VS Code "Markdown PDF" extension
```

---

## The three custom metrics

| # | Metric | Method | Catches |
|---|---|---|---|
| 1 | **Fact Faithfulness** | LLM-judge classifies each fact; Python scores | Hallucination & omission |
| 2 | **Tone Alignment** | LLM-judge, 1–5 rubric over formality/urgency/warmth | "Every email sounds the same" |
| 3 | **Structural Soundness** | Pure Python, 6 deterministic checks | Malformed output, preamble, runaway length |

The hybrid is deliberate: faithfulness and tone are semantic (judge them), while
structure and length are deterministic (a regex is cheaper and more reliable than a
judge, and never hallucinates). For Fact Faithfulness the LLM only *classifies* —
the division is done in Python, because LLMs are unreliable at arithmetic. Full
definitions and logic live in [`evaluation/metrics.py`](evaluation/metrics.py) and
are echoed verbatim into the generated report.

---

## Part 3 — what's being compared

**Advanced prompt (role + few-shot) vs. a zero-shot baseline, same model.** This
isolates the value of the prompt-engineering work: the baseline removes exactly the
role, the definition of "good", and the few-shot examples, while keeping the
identical output format. The only variable under test is the technique itself.
(Because the client is provider-agnostic, a cross-provider comparison is also one
`.env` change away.)

---

## Project structure

```
.
├── cli.py                     # generate | evaluate | serve
├── assistant/
│   ├── schema.py              # pydantic EmailRequest / EmailResponse (the shared contract)
│   ├── client.py              # provider-agnostic LLM client + retry (OpenAI/Gemini/Anthropic/replay)
│   └── generator.py           # prompt assembly + output parsing
├── prompts/
│   ├── advanced.py            # Role-Playing + Few-Shot
│   └── baseline.py            # Zero-shot control
├── evaluation/
│   ├── scenarios.json         # 10 scenarios + human reference emails
│   ├── judge.py               # LLM-as-judge helper (robust JSON parsing)
│   ├── metrics.py             # the 3 custom metrics
│   ├── runner.py              # orchestration -> CSV + comparison.json
│   ├── report.py              # fills report_template.md with live results
│   ├── replay_store.py        # offline replay provider backend
│   └── replay_data.json       # recorded generations + judge verdicts
├── api/app.py                 # FastAPI POST /generate
├── tests/test_pipeline.py     # deterministic tests (no API key)
├── report/                    # report_template.md -> report_final.md (generated)
└── results/                   # CSVs, comparison.json, generations/ (generated)
```

---

## Design decisions worth calling out

- **Why role + few-shot, not CoT?** Email writing is style-matching, not reasoning.
  Few-shot anchors tone and structure by example; CoT adds verbosity and can leak
  "thinking" into the body for no quality gain.
- **Why a hybrid metric suite?** It shows judgment about *when* LLM-as-judge is the
  right tool — and when it isn't. Blindly judging everything is a common anti-pattern.
- **Why provider-agnostic?** One interface (`complete`) behind a factory keeps the
  generator, judge, and API identical regardless of vendor, and makes swapping
  providers a config change rather than a code change.
- **Why a self-writing report?** Prompts and scores in a hand-written report rot
  immediately. Generating it from the same modules guarantees the report reflects
  exactly what ran.
