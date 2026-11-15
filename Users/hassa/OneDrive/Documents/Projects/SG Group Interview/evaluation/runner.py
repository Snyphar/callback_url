"""Evaluation runner: generate emails for every scenario under each strategy,
score them with the 3 custom metrics, and write structured outputs.

Outputs (all under results/):
  <strategy>_results.csv     raw per-scenario scores for the 3 metrics + composite
  comparison.json            metric definitions, per-strategy averages, head-to-head
  generations/<strategy>/    the raw generated email for every scenario (inspection)

It then renders report/report_final.md with the real numbers filled in.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from assistant.client import LLMClient
from assistant.generator import generate
from assistant.schema import EmailRequest
from evaluation.metrics import METRIC_DEFINITIONS, evaluate_email
from evaluation.report import render_report

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
SCENARIOS_PATH = ROOT / "evaluation" / "scenarios.json"

METRIC_KEYS = ["fact_faithfulness", "tone_alignment", "structural_soundness"]


def _load_scenarios() -> list[dict]:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def run_strategy(
    strategy: str,
    scenarios: list[dict],
    gen_client: LLMClient,
    judge_client: LLMClient,
    temperature: float,
) -> list[dict]:
    """Generate + score every scenario for one strategy. Returns flat row dicts."""
    rows: list[dict] = []
    gen_dir = RESULTS / "generations" / strategy
    gen_dir.mkdir(parents=True, exist_ok=True)

    for sc in scenarios:
        req = EmailRequest(**sc["input"])
        email = generate(req, strategy, gen_client, temperature=temperature)
        scores = evaluate_email(req, email, sc["reference"]["body"], judge_client)

        (gen_dir / f"{sc['id']}.txt").write_text(
            f"SUBJECT: {email.subject}\n\n{email.body}\n", encoding="utf-8"
        )

        m1, m2, m3 = (scores[k] for k in METRIC_KEYS)
        rows.append(
            {
                "scenario_id": sc["id"],
                "intent": req.intent,
                "tone": req.tone,
                "strategy": strategy,
                "fact_faithfulness": m1["score"],
                "tone_alignment": m2["score"],
                "structural_soundness": m3["score"],
                "composite": scores["composite"],
                "facts_covered": m1.get("facts_covered"),
                "facts_total": m1.get("facts_total"),
                "fabricated_count": len(m1.get("fabricated_claims", [])),
                "tone_overall_5": m2.get("overall_match_5"),
                "struct_checks_passed": m3.get("checks_passed"),
                "length_ratio": m3.get("length_ratio"),
                "word_count": m3.get("word_count"),
            }
        )
        print(
            f"  [{strategy:8}] {sc['id']}  "
            f"fact={m1['score']:.2f} tone={m2['score']:.2f} "
            f"struct={m3['score']:.2f} -> composite={scores['composite']:.2f}"
        )
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _averages(rows: list[dict]) -> dict:
    avgs = {k: _mean([r[k] for r in rows]) for k in METRIC_KEYS}
    avgs["composite"] = _mean([r["composite"] for r in rows])
    return avgs


def run_evaluation(
    strategies: Optional[list[str]] = None,
    limit: Optional[int] = None,
) -> dict:
    """Full evaluation across strategies. Returns the comparison dict and writes files."""
    load_dotenv(ROOT / ".env")
    strategies = strategies or ["advanced", "baseline"]
    scenarios = _load_scenarios()
    if limit:
        scenarios = scenarios[:limit]

    gen_client = LLMClient.from_env("gen")
    judge_client = LLMClient.from_env("judge")
    temperature = float((_env("GEN_TEMPERATURE") or "0.3"))

    print(
        f"Generation: {gen_client.label()} | Judge: {judge_client.label()} | "
        f"{len(scenarios)} scenarios | strategies: {', '.join(strategies)}\n"
    )

    RESULTS.mkdir(exist_ok=True)
    per_strategy: dict[str, dict] = {}

    for strategy in strategies:
        rows = run_strategy(strategy, scenarios, gen_client, judge_client, temperature)
        _write_csv(RESULTS / f"{strategy}_results.csv", rows)
        per_strategy[strategy] = {"averages": _averages(rows), "per_scenario": rows}
        print(f"  -> wrote results/{strategy}_results.csv\n")

    comparison = _build_comparison(
        per_strategy, gen_client, judge_client, temperature, len(scenarios)
    )
    (RESULTS / "comparison.json").write_text(
        json.dumps(comparison, indent=2), encoding="utf-8"
    )
    print("  -> wrote results/comparison.json")

    report_path = render_report(comparison, ROOT)
    print(f"  -> wrote {report_path.relative_to(ROOT)}")
    _print_summary(comparison)
    return comparison


def _build_comparison(per_strategy, gen_client, judge_client, temperature, n_scenarios) -> dict:
    composites = {s: per_strategy[s]["averages"]["composite"] for s in per_strategy}
    winner = max(composites, key=composites.get) if composites else None

    deltas, biggest_metric, biggest_val = {}, None, -1.0
    if len(per_strategy) == 2:
        a, b = list(per_strategy)  # first is the "advanced"-style strategy by convention
        for k in METRIC_KEYS + ["composite"]:
            d = round(
                per_strategy[a]["averages"][k] - per_strategy[b]["averages"][k], 4
            )
            deltas[k] = d
            if k in METRIC_KEYS and abs(d) > biggest_val:
                biggest_val, biggest_metric = abs(d), k

    return {
        "config": {
            "generation": gen_client.label(),
            "judge": judge_client.label(),
            "gen_temperature": temperature,
            "scenarios": n_scenarios,
        },
        "metric_definitions": METRIC_DEFINITIONS,
        "strategies": per_strategy,
        "comparison": {
            "winner": winner,
            "composite_by_strategy": composites,
            "deltas_first_minus_second": deltas,
            "biggest_gap_metric": biggest_metric,
            "biggest_gap_value": round(biggest_val, 4) if biggest_metric else None,
        },
    }


def _env(name: str) -> Optional[str]:
    import os

    return os.getenv(name)


def _print_summary(comparison: dict) -> None:
    print("\n" + "=" * 64)
    print("SUMMARY (average normalized score, 0-1)")
    print("=" * 64)
    header = f"{'metric':<24}" + "".join(
        f"{s:>14}" for s in comparison["strategies"]
    )
    print(header)
    for k in METRIC_KEYS + ["composite"]:
        line = f"{k:<24}"
        for s in comparison["strategies"]:
            line += f"{comparison['strategies'][s]['averages'][k]:>14.3f}"
        print(line)
    w = comparison["comparison"]["winner"]
    print("-" * 64)
    print(f"Winner by composite: {w}")
    print("=" * 64)
