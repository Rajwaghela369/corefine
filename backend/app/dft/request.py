"""What the user asked for, as a typed request. A prompt is turned into this by the LLM; code does the rest.

"Normal inputs" means each code's own documented defaults. Nothing in this file chooses physics
parameters the user did not ask for; the writers record which defaults were used.
"""

from typing import Literal

from pydantic import BaseModel, Field

Code = Literal["exciting", "questaal"]
Functional = Literal["PBE", "PBEsol", "LDA"]

# Verified mappings only: exciting from xml/schema/groundstate.xsd (xctype enumeration),
# Questaal from `blm --h` (--pbe, --pbesol switches). LDA for Questaal is left out until checked.
EXCITING_XC = {"PBE": "GGA_PBE", "PBEsol": "GGA_PBE_SOL", "LDA": "LDA_PW"}
QUESTAAL_XC_SWITCH = {"PBE": "--pbe", "PBEsol": "--pbesol"}
# libxc ids blm writes into xcfun (checked in libxc 6.2.2 xc_funcs.h): X_PBE 101, C_PBE 130, X_PBE_SOL 116, C_PBE_SOL 133
QUESTAAL_LIBXC_IDS = {"PBE": (101, 130), "PBEsol": (116, 133)}


class CalcRequest(BaseModel):
    structure: str | None = Field(default=None, description="Structure source: a .cif path, cod:<id> (e.g. cod:9008565) "
                                                            "or mp:<mp-id> (e.g. mp:mp-149 for silicon); null if not given")
    codes: list[Code] = Field(default_factory=lambda: ["exciting", "questaal"],
                              description="All-electron codes to prepare inputs for")
    functional: Functional = Field(default="PBE", description="Exchange-correlation functional")
    kmesh: tuple[int, int, int] = Field(default=(2, 2, 2), description="Monkhorst-Pack style k-mesh, e.g. 2 2 2")
    task: Literal["groundstate"] = Field(default="groundstate", description="Only ground-state SCF for now")
    notes: str = Field(default="", description="Anything in the request that could not be expressed in the fields above")

    def unsupported(self) -> list[str]:
        out = []
        if not self.structure:
            out.append("no structure source given (use a .cif path, cod:<id> or mp:<mp-id>)")
        if "questaal" in self.codes and self.functional not in QUESTAAL_XC_SWITCH:
            out.append(f"Questaal: functional {self.functional} not mapped yet (verified: {sorted(QUESTAAL_XC_SWITCH)})")
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
