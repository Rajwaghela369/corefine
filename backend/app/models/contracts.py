"""Typed contracts shared by the API, the agents and the orchestrator."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DatasetRole = Literal["measured_pattern", "reference_structure", "reference_value"]
DatasetFormat = Literal["pdcif", "xy", "csv", "cif"]
StepStatus = Literal["pending", "running", "retrying", "done", "failed"]
RunStatus = Literal["queued", "planning", "running", "analysing", "done", "failed"]
Classification = Literal[
    "missing_geometric_correction", "agreement", "metadata_issue", "weak_or_overlapping_peaks", "unexplained",
]


# --- Data -------------------------------------------------------------------

RADIATION_SOURCES = ("sealed X-ray tube", "rotating-anode X-ray tube", "synchrotron", "nuclear reactor",
                     "spallation source", "electron microscope")  # the coreCIF _diffrn_source examples


class Instrument(BaseModel):
    """Named after coreCIF: radiation = _diffrn_radiation_type (Siegbahn notation, e.g. 'Cu K\\a~1~' or CuKa1),
    radiation_source = _diffrn_source (tube, synchrotron, reactor ...), probe = _diffrn_radiation_probe."""

    model_config = ConfigDict(extra="allow")
    radiation: str | None = None
    radiation_source: str | None = None
    probe: Literal["x-ray", "neutron", "electron", "gamma"] | None = None
    wavelength_A: float | None = None
    wavelength_source: str | None = None

    @model_validator(mode="after")
    def _source_given_as_radiation(self):
        # older manifests (and NIST's 11-BM files) put the source in the radiation type: "synchrotron"
        if self.radiation_source is None and self.radiation and self.radiation.strip().lower() == "synchrotron":
            self.radiation_source, self.radiation = "synchrotron", None
        return self

    @property
    def synchrotron(self) -> bool:
        return (self.radiation_source or "").lower() == "synchrotron"


class Manifest(BaseModel):
    """dataset.yaml. `reference_values` is hidden from the Planner and Coder."""

    model_config = ConfigDict(extra="allow")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    role: DatasetRole
    technique: str
    material: str
    format: DatasetFormat
    files: list[str] = Field(min_length=1)
    instrument: Instrument | None = None
    temperature_C: float | None = None
    source: str | None = None
    reference_values: dict | None = None

    @model_validator(mode="after")
    def _measured_needs_instrument(self):
        if self.role == "measured_pattern" and self.instrument is None:
            raise ValueError("a measured_pattern manifest needs an instrument section (radiation, wavelength_A)")
        return self

    def for_agents(self) -> dict:
        """What the Planner and Coder may see: everything except the answer."""
        return self.model_dump(exclude={"reference_values"}, exclude_none=True)


# --- Runs -------------------------------------------------------------------

Engine = Literal["agents", "gsas2", "maud"]


class RunRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    dataset_ids: list[str] = Field(min_length=1)
    parent_run_id: str | None = None
    session_id: str | None = None
    # agents = Claude writes the analysis; gsas2 / maud = that program refines the scan. Several engines start one run
    # each, sharing a group_id, so their results can be compared.
    engines: list[Engine] = Field(default_factory=lambda: ["agents"], min_length=1)
    engine: Engine = "agents"           # set per run by the API
    group_id: str | None = None


class PlanStep(BaseModel):
    idx: int = Field(ge=1)
    name: str = Field(pattern=r"^[a-z0-9_]{2,40}$", description="snake_case, used in file names")
    goal: str = Field(description="What this step must achieve, in one or two sentences")
    dataset_ids: list[str] = Field(description="Datasets this step reads (subset of the selected ones)")
    uses_previous_outputs: list[str] = Field(default_factory=list, description="Files from earlier steps it reads")
    outputs: list[str] = Field(description="Files it must write; always includes metrics.json")
    skill: str = Field(description="Skill file name the Coder should load, e.g. xrd_powder_refinement.md")

    @field_validator("outputs")
    @classmethod
    def _metrics_required(cls, v: list[str]) -> list[str]:
        if "metrics.json" not in v:
            v = [*v, "metrics.json"]
        for name in v:
            if "/" in name or name.startswith("."):
                raise ValueError(f"output must be a bare file name, got {name!r}")
        return v


class Plan(BaseModel):
    title: str
    summary: str
    steps: list[PlanStep] = Field(min_length=1)

    def check_against(self, selected: set[str], max_steps: int) -> None:
        if len(self.steps) > max_steps:
            raise ValueError(f"plan has {len(self.steps)} steps; limit is {max_steps}")
        if [s.idx for s in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("step idx must run 1..n in order")
        produced: set[str] = set()
        for s in self.steps:
            unknown = set(s.dataset_ids) - selected
            if unknown:
                raise ValueError(f"step {s.idx} uses datasets not selected for this run: {sorted(unknown)}")
            missing = set(s.uses_previous_outputs) - produced
            if missing:
                raise ValueError(f"step {s.idx} reads {sorted(missing)} which no earlier step writes")
            produced |= set(s.outputs)


class Metric(BaseModel):
    name: str
    value: float | int | str | bool
    unit: str | None = None
    uncertainty: float | None = None
    method: str | None = None


class StepResult(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    files: dict[str, bytes] = Field(default_factory=dict, repr=False)
    duration_s: float = 0.0


class CoderOutput(BaseModel):
    code: str = Field(description="The complete Python script for this step")
    notes: str = Field(description="One or two sentences: what the script does, or what was fixed on retry")


class AnalystOutput(BaseModel):
    classification: Classification
    agrees_with_rule: bool = Field(description="True if you agree with the rule-based classification given")
    report_markdown: str


class RunSummary(BaseModel):
    id: str
    prompt: str
    status: RunStatus
    dataset_ids: list[str]
    parent_run_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    headline: dict | None = None
