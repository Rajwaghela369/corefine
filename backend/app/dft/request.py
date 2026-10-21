"""What the user asked for, as a typed request. A prompt is turned into this by the LLM; code does the rest.

"Normal inputs" means each code's own documented defaults. Nothing here chooses physics parameters
the user did not ask for; each code adapter maps the request to its own syntax and records the
defaults it relies on.
"""

from typing import Literal

from pydantic import BaseModel, Field

Functional = Literal["PBE", "PBEsol", "LDA"]


class CalcRequest(BaseModel):
    structure: str | None = Field(default=None, description="Structure source: a .cif path, cod:<id> (e.g. cod:9008565) "
                                                            "or mp:<mp-id> (e.g. mp:mp-149 for silicon); null if not given")
    codes: list[str] = Field(default_factory=list,
                             description="Codes to prepare inputs for, by registry name (e.g. exciting, questaal); "
                                         "empty = every code available on this server")
    functional: Functional = Field(default="PBE", description="Exchange-correlation functional")
    kmesh: tuple[int, int, int] = Field(default=(2, 2, 2), description="Monkhorst-Pack style k-mesh, e.g. 2 2 2")
    occupations: Literal["auto", "fixed", "smearing"] = Field(
        default="auto", description="auto = each code's default (QE retries with smearing if it reports a metal); "
                                    "smearing = request smearing up front (metals)")
    task: Literal["groundstate"] = Field(default="groundstate", description="Only ground-state SCF for now")
    # Used by convergence and equation-of-state studies; 1.0 = the structure and basis as planned
    volume_scale: float = Field(default=1.0, gt=0.5, lt=1.5, description="Cell volume relative to the source structure")
    basis_scale: float = Field(default=1.0, ge=0.5, le=4.0,
                               description="Basis size relative to the code's default/recommended cutoff energy")
    keep_cell: bool = Field(default=False, description="Use the structure exactly as given (no symmetry standardisation); "
                                                       "needed for displaced cells, e.g. phonons")
    forces: bool = Field(default=False, description="Ask the code to compute and print atomic forces")
    sphere_ref_scale: float | None = Field(default=None, description="All-electron codes: choose muffin-tin radii as at this "
                                                                     "volume scale (smallest volume of an EOS), so they stay fixed")
    notes: str = Field(default="", description="Anything in the request that could not be expressed in the fields above")

    def unsupported(self) -> list[str]:
        """Problems that do not depend on a particular code; adapters add their own."""
        out = []
        if not self.structure:
            out.append("no structure source given (use a .cif path, cod:<id>, mp:<mp-id> or dataset:<id>)")
        if any(k < 1 for k in self.kmesh):
            out.append(f"k-mesh must be positive, got {self.kmesh}")
        return out


PROMPT_SYSTEM = """Turn a researcher's request for a DFT calculation into structured settings.
Fill only what the request states or clearly implies; use the field defaults otherwise, and
put anything you could not represent into `notes`. Never invent a structure source: if the
request names a material but no source, use the Materials Project id only when you are sure
of it (silicon is mp:mp-149), otherwise leave structure null and say so in notes."""


def from_prompt(prompt: str) -> CalcRequest:
    from app.agents import llm

    return llm.parse(agent="dft_request", system=PROMPT_SYSTEM, content=prompt, output=CalcRequest, effort="low",
                     max_tokens=2000)
