"""Skills are local markdown files loaded by name, never retrieved by search."""

from functools import lru_cache

from app.config import BACKEND_DIR

SKILLS_DIR = BACKEND_DIR / "skills"

INDEX = {
    "xrd_powder_refinement.md": "How to read the 640f scans, fit peaks and refine a cubic lattice parameter; worked example.",
    "step_contract.md": "Rules every generated script must follow (inputs, outputs, metrics.json).",
    "report_rules.md": "Report sections, citing metrics, the classification table. Analyst only.",
    "si_reference.md": "Silicon structure facts and certificate values with sources. Analyst only.",
}
CODER_SKILLS = {"xrd_powder_refinement.md", "step_contract.md"}


class UnknownSkill(ValueError):
    pass


@lru_cache
def load(name: str) -> str:
    if name not in INDEX:
        raise UnknownSkill(f"no skill named {name!r}; available: {sorted(INDEX)}")
    text = (SKILLS_DIR / name).read_text()
    if "{{GOLD_ANALYSIS}}" in text:
        text = text.replace("{{GOLD_ANALYSIS}}", (SKILLS_DIR / "examples" / "gold_analysis.py").read_text().strip())
    return text


def index_text(names=None) -> str:
    return "\n".join(f"- {n}: {d}" for n, d in INDEX.items() if names is None or n in names)
