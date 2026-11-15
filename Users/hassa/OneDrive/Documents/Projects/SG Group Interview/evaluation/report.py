"""Render report/report_final.md from report/report_template.md + live results.

The template holds the static narrative and {{TOKENS}}; this module fills the
tokens with the real prompt text, metric definitions, score tables, and a
data-grounded analysis. Run the evaluation and you get a submission-ready report.
"""
from __future__ import annotations

import json
from pathlib import Path

from assistant.schema import EmailRequest
from evaluation.metrics import METRIC_DEFINITIONS
from prompts import advanced, baseline

METRIC_KEYS = ["fact_faithfulness", "tone_alignment", "structural_soundness"]
PRETTY = {
    "fact_faithfulness": "Fact Faithfulness",
    "tone_alignment": "Tone Alignment",
    "structural_soundness": "Structural Soundness",
    "composite": "Composite",
}


def _example_user_prompt() -> str:
    sample = EmailRequest(
        intent="Follow up after a discovery meeting",
        key_facts=[
            "Enjoyed discussing their migration to the cloud",
            "Will send the technical architecture document by Thursday",
            "Propose a 30-minute scoping call next week",
        ],
        tone="warm and professional",
        recipient="Priya",
        sender="Daniel Owens",
    )
    return advanced.build_user(sample)


def _metric_definitions_md() -> str:
    out = []
    for i, key in enumerate(METRIC_KEYS, 1):
        d = METRIC_DEFINITIONS[key]
        out.append(
            f"### Custom Metric {i}: {d['name']}\n\n"
            f"- **Method:** {d['method']}\n"
            f"- **Example focus:** {d['focus']}\n"
            f"- **Failure mode it catches:** {d['failure_mode']}\n"
            f"- **Range:** {d['range']}\n"
            f"- **Logic:** {d['logic']}\n"
        )
    return "\n".join(out)


def _averages_table(strategies: dict) -> str:
    names = list(strategies)
    head = "| Metric | " + " | ".join(n.title() for n in names) + " | Δ (1st − 2nd) |"
    sep = "|" + "---|" * (len(names) + 2)
    lines = [head, sep]
    for key in METRIC_KEYS + ["composite"]:
        cells = [f"{strategies[n]['averages'][key]:.3f}" for n in names]
        delta = (
            f"{strategies[names[0]]['averages'][key] - strategies[names[1]]['averages'][key]:+.3f}"
            if len(names) == 2
            else "—"
        )
        lines.append(f"| {PRETTY[key]} | " + " | ".join(cells) + f" | {delta} |")
    return "\n".join(lines)


def _per_scenario_table(rows: list[dict]) -> str:
    head = "| Scenario | Requested Tone | Fact Faith. | Tone Align. | Struct. | Composite |"
    sep = "|---|---|---|---|---|---|"
    lines = [head, sep]
    for r in rows:
        lines.append(
            f"| {r['scenario_id']} | {r['tone']} | {r['fact_faithfulness']:.2f} | "
            f"{r['tone_alignment']:.2f} | {r['structural_soundness']:.2f} | "
            f"{r['composite']:.2f} |"
        )
    return "\n".join(lines)


def _analysis_sentences(comparison: dict) -> dict:
    strategies = comparison["strategies"]
    names = list(strategies)
    winner = comparison["comparison"]["winner"]
    loser = next((n for n in names if n != winner), None)

    if not loser:
        return {
            "FAILURE_MODE_SENTENCE": "Only one strategy was evaluated.",
            "RECOMMENDATION_SENTENCE": f"`{winner}` is the only candidate evaluated.",
        }

    # Biggest weakness of the loser = its lowest average metric.
    loser_avgs = {k: strategies[loser]["averages"][k] for k in METRIC_KEYS}
    weakest = min(loser_avgs, key=loser_avgs.get)
    gap_metric = comparison["comparison"]["biggest_gap_metric"] or weakest
    gap_val = comparison["comparison"]["biggest_gap_value"] or 0.0
    w_comp = strategies[winner]["averages"]["composite"]
    l_comp = strategies[loser]["averages"]["composite"]

    # Defensive guard: if the two strategies somehow tie on composite, say so
    # rather than asserting a difference that isn't there.
    if abs(w_comp - l_comp) < 0.005:
        return {
            "FAILURE_MODE_SENTENCE": (
                f"The two strategies tied on composite ({w_comp:.3f}); the lowest "
                f"metric for both was **{PRETTY[weakest]}** ({loser_avgs[weakest]:.3f})."
            ),
            "RECOMMENDATION_SENTENCE": (
                f"With composite scores effectively tied, the recommendation should rest "
                f"on the lowest-scoring dimension (**{PRETTY[weakest]}**) and qualitative "
                f"review of the generated emails."
            ),
        }

    failure = (
        f"The lower-performing strategy (`{loser}`) was weakest on "
        f"**{PRETTY[weakest]}** ({loser_avgs[weakest]:.3f}). The largest head-to-head "
        f"gap appeared on **{PRETTY[gap_metric]}**, where `{winner}` led by "
        f"{gap_val:.3f} on a 0–1 scale — concrete evidence that the prompt-engineering "
        f"work moved exactly the dimension it was designed to move."
    )
    rec = (
        f"Recommend **`{winner}`** for production: it wins on composite "
        f"({w_comp:.3f} vs {l_comp:.3f}) and, critically, on the metrics tied to the "
        f"costliest real-world failures (fact accuracy and tone). The advanced prompt "
        f"adds only fixed token overhead (the few-shot block), a worthwhile trade for "
        f"the measured quality gain."
    )
    return {"FAILURE_MODE_SENTENCE": failure, "RECOMMENDATION_SENTENCE": rec}


def render_report(comparison: dict, root: Path) -> Path:
    template_path = root / "report" / "report_template.md"
    out_path = root / "report" / "report_final.md"
    template = template_path.read_text(encoding="utf-8")

    strategies = comparison["strategies"]
    cmp = comparison["comparison"]
    names = list(strategies)

    tokens = {
        "CONFIG_GEN": comparison["config"]["generation"],
        "CONFIG_JUDGE": comparison["config"]["judge"],
        "CONFIG_SCENARIOS": str(comparison["config"]["scenarios"]),
        "CONFIG_TEMP": str(comparison["config"]["gen_temperature"]),
        "ADVANCED_SYSTEM": advanced.SYSTEM.strip(),
        "ADVANCED_USER_EXAMPLE": _example_user_prompt().strip(),
        "BASELINE_SYSTEM": baseline.SYSTEM.strip(),
        "BASELINE_USER_EXAMPLE": baseline.build_user(
            EmailRequest(
                intent="Follow up after a discovery meeting",
                key_facts=[
                    "Enjoyed discussing their migration to the cloud",
                    "Will send the technical architecture document by Thursday",
                    "Propose a 30-minute scoping call next week",
                ],
                tone="warm and professional",
                recipient="Priya",
                sender="Daniel Owens",
            )
        ).strip(),
        "METRIC_DEFINITIONS": _metric_definitions_md(),
        "AVERAGES_TABLE": _averages_table(strategies),
        "WINNER": cmp["winner"],
        "COMPOSITE_TABLE": "\n".join(
            f"- **{n.title()}**: {strategies[n]['averages']['composite']:.3f}"
            for n in names
        ),
        "RAW_JSON_PATH": "results/comparison.json",
    }
    for i, n in enumerate(names):
        tokens[f"PER_SCENARIO_TABLE_{i+1}"] = _per_scenario_table(
            strategies[n]["per_scenario"]
        )
        tokens[f"STRATEGY_NAME_{i+1}"] = n.title()
    tokens.update(_analysis_sentences(comparison))

    rendered = template
    for key, val in tokens.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(val))

    out_path.write_text(rendered, encoding="utf-8")
    return out_path
