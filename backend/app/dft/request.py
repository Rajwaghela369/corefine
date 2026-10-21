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
    task: Literal["groundstate"] = Field(default="groundstate", description="Only ground-state SCF for now")
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
