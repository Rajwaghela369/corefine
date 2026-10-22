"""Coder: one plan step -> one Python script. On retry it gets its last code, the stderr tail and the
checker message, and returns a corrected script."""

import json

from app.agents import llm, skills
from app.models.contracts import CoderOutput, Manifest, Plan, PlanStep

SYSTEM = """You write one Python script for one step of a CoRefine analysis run. The script runs in
an isolated sandbox with no network. Follow the step contract exactly. Use the skill notes; they
record library calls and file tags that are known to work on this data.

Never hard-code reference values or physical constants that belong in an input (wavelength,
lattice parameter). Never print or write a value you did not compute or read from an input.

Skill notes follow.

{skill_text}
"""


def write_step(plan: Plan, step: PlanStep, manifests: list[Manifest], previous_outputs: list[str],
               last_code: str | None = None, last_error: str | None = None, on_text=None) -> CoderOutput:
    skill_text = "\n\n---\n\n".join(skills.load(n) for n in ("step_contract.md", *skills.for_step(step.skill)))
    parts = [
        f"Run plan: {plan.title}\n{plan.summary}",
        f"Write the script for step {step.idx} '{step.name}':\n{step.goal}",
        "Datasets for this step (manifests, as found under inputs/<id>/dataset.yaml):\n"
        + json.dumps([m.for_agents() for m in manifests if m.id in step.dataset_ids], indent=2),
        f"Files available in inputs/previous/: {previous_outputs or 'none'}",
        f"Files this step must write to outputs/: {step.outputs}",
    ]
    if last_code is not None:
        parts += [
            "Your previous attempt failed. Fix it and return the complete corrected script.",
            f"Previous script:\n```python\n{last_code}\n```",
            f"Failure:\n{last_error}",
        ]
    return llm.parse(
        agent="coder",
        system=SYSTEM.format(skill_text=skill_text),
        content="\n\n".join(parts),
        output=CoderOutput,
        effort="high",
        max_tokens=32000,
        on_text=on_text,
    )
