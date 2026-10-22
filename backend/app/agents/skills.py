"""Skills are local markdown files loaded by name, never retrieved by search."""

from functools import lru_cache

from app.config import BACKEND_DIR

SKILLS_DIR = BACKEND_DIR / "skills"

INDEX = {
    "xrd_powder_refinement.md": "How to read the 640f scans, fit peaks and refine a cubic lattice parameter; worked example.",
    "step_contract.md": "Rules every generated script must follow (inputs, outputs, metrics.json).",
    "report_rules.md": "Report sections, citing metrics, the classification table. Analyst only.",
    "xrd_other_standards.md": "Differences for SRM 660c (LaB6, Kα1/Kα2 doublets) and SRM 1979 (ZnO, hexagonal a and c, "
                              "synchrotron); used with xrd_powder_refinement.md.",
    "si_reference.md": "Silicon structure facts and certificate values with sources. Analyst only.",
    "other_references.md": "LaB6 and ZnO structure facts and certificate values with sources. Analyst only.",
}
CODER_SKILLS = {"xrd_powder_refinement.md", "xrd_other_standards.md", "step_contract.md"}
# Skills that only describe differences from another skill; the Coder gets both
REQUIRES = {"xrd_other_standards.md": ["xrd_powder_refinement.md"]}


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


def for_step(name: str) -> list[str]:
    """The skill files a Coder step needs, in reading order."""
    return [*REQUIRES.get(name, []), name]


def index_text(names=None) -> str:
    return "\n".join(f"- {n}: {d}" for n, d in INDEX.items() if names is None or n in names)
