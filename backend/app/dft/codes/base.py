"""The contract every DFT code adapter fulfils. Adding a code = one module implementing this + one registry line.

An adapter knows three things about its code:
  1. whether it can be used on this server (paths, binaries) and which functionals it maps,
  2. how to write a ground-state input from the standardized cell and the typed request,
  3. how to read that input back *the way the code itself will read it*, so the generic checks can
     compare every code against the source structure and against each other.
Physics settings an adapter does not get from the request must be the code's own defaults, and the
adapter reports them; it never invents values.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ase import Atoms

from app.config import Settings
from app.dft.request import CalcRequest
from app.dft.structure import Cell


@dataclass
class Results:
    """What a finished run produced, parsed from the code's own output files. Energies in eV."""
    converged: bool | None
    total_energy_eV: float | None
    fermi_eV: float | None = None
    gap_eV: float | None = None
    scf_iterations: int | None = None
    warnings: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class ReadBack:
    atoms: Atoms                       # structure as the code will see it, converted to Å
    kmesh: list[int] | None            # k-mesh as written in the code's own syntax, parsed back
    functional_ok: bool                # the functional tokens in the input mean what was requested
    functional_detail: str
    extra_checks: list[dict] = field(default_factory=list)  # {"check", "ok" (True/False, or None = not done), "detail"}


class CodeAdapter(ABC):
    name: str          # registry key, used in requests and folder names
    label: str         # display name
    method: str        # e.g. "FP-(L)APW+lo", "FP-LMTO", "plane waves + PAW"
    main_file: str     # the file a person opens first
    program: str       # executable the run step launches (path/launcher come from the compute target)
    restartable = False  # True if rerunning in the same folder continues from the saved density

    @abstractmethod
    def availability(self, s: Settings) -> tuple[bool, str]:
        """(usable, reason). Reason explains what is missing when not usable."""

    @abstractmethod
    def functionals(self) -> dict[str, str]:
        """Functional name in the request -> how this code spells it (only verified mappings)."""

    @abstractmethod
    def write(self, cell: Cell, req: CalcRequest, outdir: Path, s: Settings, title: str) -> dict:
        """Write the input files into outdir. Returns {"files", "set_explicitly", "defaults", ...} for provenance."""

    @abstractmethod
    def read_back(self, outdir: Path, req: CalcRequest) -> ReadBack:
        """Parse the written input the way the code will, independently of what write() meant to do."""

    @abstractmethod
    def run_args(self, outdir: Path) -> dict:
        """{"program", "args", "stdout"}: how to launch the ground-state run inside outdir."""

    @abstractmethod
    def parse_results(self, rundir: Path) -> "Results | None":
        """Parse a finished (or stopped) run; None if no output is there yet."""

    def local_env(self, s: Settings) -> dict[str, str]:
        """Extra environment the program needs when run on this server (e.g. library paths)."""
        return {}

    def problems(self, req: CalcRequest) -> list[str]:
        if req.functional not in self.functionals():
            return [f"{self.label}: functional {req.functional} is not mapped yet (verified: {sorted(self.functionals())})"]
        return []

    def describe(self, s: Settings) -> dict:
        ok, reason = self.availability(s)
        return {"name": self.name, "label": self.label, "method": self.method, "available": ok, "reason": reason,
                "functionals": sorted(self.functionals()), "program": self.program}
