import pytest
from pydantic import ValidationError

from app.config import MissingSettingError, Settings
from app.models.contracts import Manifest, Plan, RunRequest

STEP = {"idx": 1, "name": "refine", "goal": "g", "dataset_ids": ["nist-srm-640f"], "outputs": ["peaks.csv"],
        "skill": "xrd_powder_refinement.md"}


def test_plan_adds_metrics_json():
    p = Plan(title="t", summary="s", steps=[STEP])
    assert "metrics.json" in p.steps[0].outputs


def test_plan_rejects_unselected_dataset():
    p = Plan(title="t", summary="s", steps=[STEP])
    with pytest.raises(ValueError, match="not selected"):
        p.check_against({"cod-9008565-si"}, 6)


def test_plan_rejects_too_many_steps():
    steps = [{**STEP, "idx": i, "name": f"s{i}"} for i in range(1, 8)]
    with pytest.raises(ValueError, match="limit is 6"):
        Plan(title="t", summary="s", steps=steps).check_against({"nist-srm-640f"}, 6)


def test_plan_rejects_reading_unproduced_file():
    steps = [STEP, {**STEP, "idx": 2, "name": "second", "uses_previous_outputs": ["nope.csv"]}]
    with pytest.raises(ValueError, match="no earlier step writes"):
        Plan(title="t", summary="s", steps=steps).check_against({"nist-srm-640f"}, 6)


def test_plan_rejects_path_outputs():
    with pytest.raises(ValidationError):
        Plan(title="t", summary="s", steps=[{**STEP, "outputs": ["../x.csv"]}])


def test_manifest_measured_needs_instrument():
    with pytest.raises(ValidationError, match="instrument"):
        Manifest(id="abc", role="measured_pattern", technique="xrd_powder", material="Si", format="pdcif", files=["raw/*"])


def test_manifest_hides_reference_values_from_agents():
    m = Manifest(id="abc", role="measured_pattern", technique="x", material="Si", format="pdcif", files=["raw/*"],
                 instrument={"wavelength_A": 1.5}, reference_values={"a_A": 5.43})
    assert "reference_values" not in m.for_agents()


def test_run_request_needs_dataset():
    with pytest.raises(ValidationError):
        RunRequest(prompt="refine it", dataset_ids=[])


def test_cloud_mode_names_missing_keys(monkeypatch):
    monkeypatch.setenv("COREFINE_MODE", "cloud")
    with pytest.raises(MissingSettingError, match="S3_BUCKET") as e:
        Settings(_env_file=None)
    assert "DAYTONA_API_KEY" in str(e.value)
