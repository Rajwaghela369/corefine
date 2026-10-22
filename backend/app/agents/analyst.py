"""Analyst: metrics + peaks table + plot + manifest reference values -> report.md with a classification."""

import json

from app.agents import llm, skills
from app.models.contracts import AnalystOutput, Manifest, Metric

SYSTEM = """You are the Analyst for CoRefine. You read the outputs of an executed analysis and write
a short, honest report for a researcher who does not write code. You look at the plot image too.

{report_rules}

---

{si_reference}

---

{other_references}
"""


def write_report(prompt: str, metrics: list[Metric], peaks_csv: str | None, plot_png: bytes | None,
                 manifests: list[Manifest], rule_class: str, rule_reasons: list[str], on_text=None) -> AnalystOutput:
    text = "\n\n".join([
        f"The user asked: {prompt}",
        "Metrics (from metrics.json and orchestrator comparisons):\n"
        + json.dumps([m.model_dump() for m in metrics], indent=2),
        "Manifests, including reference values:\n"
        + json.dumps([m.model_dump(exclude_none=True) for m in manifests], indent=2),
        f"peaks.csv:\n{peaks_csv}" if peaks_csv else "No peaks.csv was produced.",
        f"Rule-based classification (code): {rule_class}\nReasons: " + "; ".join(rule_reasons),
        "Write report_markdown now. Start with a level-1 heading naming the run's result.",
    ])
    content: list[dict] = []
    if plot_png:
        content.append(llm.image_block(plot_png))
    content.append({"type": "text", "text": text})
    return llm.parse(
        agent="analyst",
        system=SYSTEM.format(report_rules=skills.load("report_rules.md"), si_reference=skills.load("si_reference.md"),
                             other_references=skills.load("other_references.md")),
        content=content,
        output=AnalystOutput,
        effort="high",
        on_text=on_text,
    )
