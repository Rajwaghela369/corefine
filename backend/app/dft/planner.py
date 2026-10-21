"""Plan a calculation for a chosen material: every decision is a typed field with a reason; code writes the files.

Two planners, same output:
  rules  always available; documented choices (k-mesh from a k-point spacing, smearing for known metals,
         refusal for magnetic orderings until spin polarisation is supported, warnings for large cells)
  agent  with an Anthropic key, Claude reads the person's goal and the rule plan, and may change the same
         fields (functional, k-mesh, codes, occupations) within limits, giving a reason for each change.
The plan never contains file contents; writers and checks stay deterministic.
"""

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from app.dft.request import CalcRequest

KSPACING = 0.3       # Å⁻¹ (2π included); CoRefine's default k-point density when the person gives no mesh
KMAX = 16
LAPTOP_SITES = 40
MAGNETIC = {"FM", "FiM", "AFM"}


class Decision(BaseModel):
    field: str
    value: str
    reason: str
    source: Literal["user", "rule", "agent", "materials_project"]


class Plan(BaseModel):
    request: CalcRequest
    decisions: list[Decision]
    warnings: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list, description="Reasons the plan should not run as is")
    planner: Literal["rules", "agent"] = "rules"


def kmesh_for(lattice: np.ndarray, spacing: float = KSPACING) -> tuple[int, int, int]:
    recip = 2 * math.pi * np.linalg.inv(lattice).T
    return tuple(int(min(KMAX, max(1, math.ceil(np.linalg.norm(b) / spacing)))) for b in recip)


def rule_plan(material: dict, lattice: np.ndarray, functional: str = "PBE", kmesh: tuple[int, int, int] | None = None,
              codes: list[str] | None = None) -> Plan:
    """material: an entry from materials.search (id, nsites, is_metal, ordering, band_gap_eV ...)."""
    d: list[Decision] = []
    warnings, blocked = [], []
    d.append(Decision(field="structure", value=f"mp:{material['id']}", source="user",
                      reason=f"{material.get('formula')} {material.get('spacegroup') or ''} chosen from Materials Project"))
    d.append(Decision(field="functional", value=functional, source="user" if functional != "PBE" else "rule",
                      reason="requested" if functional != "PBE" else "PBE: the functional Materials Project and SSSP use"))
    if kmesh:
        d.append(Decision(field="kmesh", value=" ".join(map(str, kmesh)), source="user", reason="requested"))
    else:
        kmesh = kmesh_for(lattice)
        d.append(Decision(field="kmesh", value=" ".join(map(str, kmesh)), source="rule",
                          reason=f"Γ-centred mesh with k-point spacing ≤ {KSPACING} Å⁻¹ (CoRefine default)"))
    occupations = "auto"
    if material.get("is_metal") is True:
        occupations = "smearing"
        d.append(Decision(field="occupations", value="smearing", source="materials_project",
                          reason="Materials Project lists this material as a metal"))
    elif material.get("is_metal") is False:
        d.append(Decision(field="occupations", value="code default", source="materials_project",
                          reason=f"insulator/semiconductor in Materials Project (PBE gap {material.get('band_gap_eV')} eV)"))
    else:
        d.append(Decision(field="occupations", value="code default, smearing if the code reports a metal", source="rule",
                          reason="metal or not is unknown without a Materials Project API key"))
    if material.get("ordering") in MAGNETIC:
        blocked.append(f"Materials Project lists a {material['ordering']} magnetic ground state; spin-polarised "
                       "calculations are not supported yet, and a non-magnetic run would describe the wrong state")
    elif material.get("is_magnetic") is False:
        d.append(Decision(field="spin", value="non-spin-polarised", source="materials_project",
                          reason="Materials Project lists the material as non-magnetic"))
    elif material.get("is_magnetic") is True:
        blocked.append("Materials Project lists the material as magnetic; spin-polarised calculations are not supported yet")
    else:
        warnings.append("magnetic ordering unknown (needs a Materials Project API key); the run is non-spin-polarised")
    if material.get("nsites", 0) > LAPTOP_SITES:
        warnings.append(f"{material['nsites']} atoms in the cell: expect long runs and high memory on a laptop")
    if (material.get("e_above_hull_eV") or 0) > 0.05:
        warnings.append(f"{material['e_above_hull_eV']:.3f} eV/atom above the convex hull: not the stable phase")
    req = CalcRequest(structure=f"mp:{material['id']}", functional=functional, kmesh=kmesh, codes=codes or [],
                      occupations=occupations)
    return Plan(request=req, decisions=d, warnings=warnings, blocked=blocked)


class AgentChange(BaseModel):
    field: Literal["functional", "kmesh", "codes", "occupations"]
    value: str = Field(description="functional: PBE|PBEsol|LDA; kmesh: 'n1 n2 n3'; codes: comma list; occupations: auto|fixed|smearing")
    reason: str


class AgentReview(BaseModel):
    changes: list[AgentChange] = Field(default_factory=list)
    notes: str = Field(default="", description="Anything the person should know; no numbers that are not in the inputs")


AGENT_SYSTEM = """You review a DFT ground-state plan made by rules, for a researcher's stated goal.
You may change only these fields: functional, kmesh, codes, occupations. Change something only when
the goal calls for it (e.g. "quick check" -> coarser k-mesh; "accurate gap" -> denser mesh); otherwise
return no changes. Never exceed a {kmax}x{kmax}x{kmax} mesh. Give a one-sentence reason per change.
Codes available here: {codes}."""


def agent_plan(goal: str, plan: Plan, material: dict, available_codes: list[str]) -> Plan:
    from app.agents import llm

    review = llm.parse(
        agent="dft_planner", effort="low", max_tokens=4000, output=AgentReview,
        system=AGENT_SYSTEM.format(kmax=KMAX, codes=", ".join(available_codes)),
        content=f"Goal: {goal}\n\nMaterial: {material}\n\nRule plan:\n{plan.model_dump_json(indent=2)}")
    req = plan.request.model_copy()
    decisions = list(plan.decisions)
    for ch in review.changes:
        try:
            if ch.field == "kmesh":
                k = tuple(int(x) for x in ch.value.split())
                if len(k) != 3 or not all(1 <= x <= KMAX for x in k):
                    continue
                req = req.model_copy(update={"kmesh": k})
            elif ch.field == "codes":
                codes = [c.strip() for c in ch.value.split(",") if c.strip() in available_codes]
                req = req.model_copy(update={"codes": codes})
            elif ch.field == "functional" and ch.value in ("PBE", "PBEsol", "LDA"):
                req = req.model_copy(update={"functional": ch.value})
            elif ch.field == "occupations" and ch.value in ("auto", "fixed", "smearing"):
                req = req.model_copy(update={"occupations": ch.value})
            else:
                continue
        except ValueError:
            continue
        decisions.append(Decision(field=ch.field, value=ch.value, reason=ch.reason, source="agent"))
    warnings = plan.warnings + ([review.notes] if review.notes else [])
    return Plan(request=req, decisions=decisions, warnings=warnings, blocked=plan.blocked, planner="agent")
