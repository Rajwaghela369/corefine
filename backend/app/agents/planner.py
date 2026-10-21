"""Planner: prompt + selected manifests + skills index -> validated plan.json and plan.md."""

import json

from app.agents import llm, skills
from app.models.contracts import Manifest, Plan

SYSTEM = """You plan data-analysis runs for CoRefine. A run is a short sequence of Python scripts
(steps) that a separate Coder agent writes and a sandbox executes. You do not write code.

Rules:
- Use only the datasets listed as selected. Refer to them by id.
- At most {max_steps} steps; fewer is better. Two to four steps is typical. Each step must be
  independently runnable and produce files; a step reads earlier outputs only through
  `uses_previous_outputs`, listing exact file names an earlier step declared.
- Every step writes metrics.json. The final step must write metrics.json containing a_refined
  (or the run's headline quantity), plus peaks.csv and fit.png when the task is a refinement.
- Choose the skill each step should load from the index (Coder-visible skills only).
- If the request cannot be done with the selected data, still return a one-step plan whose goal
  explains what is missing; the run will then fail with that reason.

Coder-visible skills:
{skills_index}
"""


def make_plan(prompt: str, manifests: list[Manifest], max_steps: int,
              parent_context: str | None = None) -> Plan:
    content = [
        f"Request:\n{prompt}",
        "Selected datasets (manifests):\n" + json.dumps([m.for_agents() for m in manifests], indent=2),
    ]
    if parent_context:
        content.append("This is a follow-up run. Parent run's plan and experiment log:\n" + parent_context
                       + "\nChange only what the request asks for; keep everything else the same.")
    plan = llm.parse(
        agent="planner",
        system=SYSTEM.format(max_steps=max_steps, skills_index=skills.index_text(skills.CODER_SKILLS)),
        content="\n\n".join(content),
        output=Plan,
        effort="medium",
    )
    plan.check_against({m.id for m in manifests}, max_steps)
    for step in plan.steps:
        if step.skill not in skills.CODER_SKILLS:
            step.skill = "xrd_powder_refinement.md"
    return plan


def plan_markdown(plan: Plan) -> str:
    lines = [f"# {plan.title}", "", plan.summary, ""]
    for s in plan.steps:
        lines += [
            f"## Step {s.idx}: {s.name}", "", s.goal, "",
            f"- datasets: {', '.join(s.dataset_ids) or '—'}",
            f"- reads from earlier steps: {', '.join(s.uses_previous_outputs) or '—'}",
            f"- writes: {', '.join(s.outputs)}",
            f"- skill: {s.skill}", "",
        ]
    return "\n".join(lines)
