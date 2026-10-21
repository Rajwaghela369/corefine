import json

from app.agents import checks
from app.models.contracts import Metric, PlanStep, StepResult
from app.storage.sanitize import sanitize_pdcif

STEP = PlanStep(idx=1, name="fit", goal="g", dataset_ids=[], outputs=["peaks.csv"], skill="step_contract.md")
GOOD_METRICS = json.dumps([{"name": "a_refined", "value": 5.43, "unit": "angstrom", "uncertainty": 1e-4,
                            "method": "lsq"}]).encode()


def result(**kw):
    base = dict(exit_code=0, stdout="done\n", stderr="", files={"metrics.json": GOOD_METRICS, "peaks.csv": b"x"})
    return StepResult(**{**base, **kw})


def test_output_check_passes():
    r = checks.check_step_outputs(STEP, result())
    assert r.ok and r.metrics[0].name == "a_refined" and r.message == "done"


def test_missing_metrics_json_is_named():
    r = checks.check_step_outputs(STEP, result(files={"peaks.csv": b"x"}))
    assert not r.ok and "metrics.json" in r.message and r.retryable


def test_bad_metric_shape():
    bad = json.dumps([{"name": "a", "value": 1}]).encode()
    r = checks.check_step_outputs(STEP, result(files={"metrics.json": bad, "peaks.csv": b"x"}))
    assert not r.ok and "name, value, unit, uncertainty, method" in r.message


def test_nonzero_exit_returns_stderr_tail():
    r = checks.check_step_outputs(STEP, result(exit_code=1, stderr="\n".join(f"line{i}" for i in range(100))))
    assert not r.ok and "line99" in r.message and "line10\n" not in r.message


def test_timeout_not_retryable():
    r = checks.check_step_outputs(STEP, result(exit_code=None, timed_out=True))
    assert not r.ok and not r.retryable


def test_missing_summary_line():
    assert not checks.check_step_outputs(STEP, result(stdout="")).ok


def test_claim_checker_flags_invented_number():
    allowed = [5.430862, 3.5e-5, 5.431144]
    ok = checks.claim_check("a = 5.430862 ± 0.000035 Å; certified 5.431144 Å; (111) peak; 11 peaks", allowed)
    bad = checks.claim_check("a = 5.430862 Å but really 5.4312 Å and 2.6 × 10^-6", allowed)
    assert ok["passed"] and ok["checked"] == 3
    assert not bad["passed"] and [u["number"] for u in bad["untraced"]] == ["5.4312", "2.6 × 10^-6"]


def test_claim_checker_allows_rounding_and_units():
    allowed = [5.431144]
    assert checks.claim_check("5.4311 Å or 0.5431144 nm", allowed)["passed"]
    assert not checks.claim_check("5.4312 Å", allowed)["passed"]


def test_rule_classification_agreement_on_gold():
    from conftest import BACKEND

    gold = BACKEND / "skills" / "examples" / "gold_outputs"
    ms = [Metric.model_validate(m) for m in json.loads((gold / "metrics.json").read_text())]
    cmp = checks.comparison_metrics(ms, {"a_A": 5.431144}, 0.0005)
    cls, _ = checks.rule_classification(ms + cmp, (gold / "peaks.csv").read_bytes(), 1.5405929)
    assert cls == "agreement"


def test_rule_classification_trend():
    rows = "two_theta_obs,residual_deg,two_theta_obs_err\n" + "\n".join(
        f"{t},{0.0001 * t},0.0004" for t in (28, 47, 56, 69, 76, 88, 95))
    ms = [Metric(name="within_target", value=True)]
    cls, _ = checks.rule_classification(ms, rows.encode(), 1.54)
    assert cls == "missing_geometric_correction"


def test_rule_classification_default_wavelength():
    ms = [Metric(name="within_target", value=False), Metric(name="wavelength", value=1.5406)]
    assert checks.rule_classification(ms, None, 1.5405929)[0] == "metadata_issue"


def test_sanitize_drops_answer_blocks():
    cif = "#\ndata_cell_SRM\n_cell_length_a 5.431144\ndata_pd_proc_x_meas\nloop_\n_a\n1\ndata_pd_proc_x_calc\nloop_\n_a\n2\n"
    out, dropped = sanitize_pdcif(cif)
    assert "5.431144" not in out and "_calc" not in out and "_meas" in out
    assert dropped == ["cell_SRM", "pd_proc_x_calc"]
