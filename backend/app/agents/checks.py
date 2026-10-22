"""Code-only checks. No LLM is involved here and no agent can override the result.

- check_step_outputs: the step contract (exit code, declared files, metrics.json shape, summary line)
- comparison_metrics: refined vs certified value, computed in code so the Analyst never does arithmetic
- rule_classification: the spec's classification table, applied in order
- claim_check: every decimal number in a report or chat answer must trace to an allowed value
"""

import io
import json
import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.models.contracts import Metric, PlanStep, StepResult

STDERR_TAIL_LINES = 60


@dataclass
class CheckResult:
    ok: bool
    message: str = ""
    metrics: list[Metric] = field(default_factory=list)
    retryable: bool = True


def tail(text: str, n: int = STDERR_TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-n:])


def check_step_outputs(step: PlanStep, result: StepResult) -> CheckResult:
    if result.timed_out:
        return CheckResult(False, "step timed out; timeouts are not retried", retryable=False)
    if result.exit_code != 0:
        return CheckResult(False, f"script exited with code {result.exit_code}. Last stderr lines:\n{tail(result.stderr)}")
    missing = [f for f in step.outputs if f not in result.files]
    if missing:
        return CheckResult(False, f"declared outputs not written to outputs/: {missing}")
    try:
        raw = json.loads(result.files["metrics.json"])
    except json.JSONDecodeError as e:
        return CheckResult(False, f"metrics.json is not valid JSON: {e}")
    if not isinstance(raw, list) or not raw:
        return CheckResult(False, "metrics.json must be a non-empty JSON list of {name, value, unit, uncertainty, method}")
    metrics = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not {"name", "value", "unit", "uncertainty", "method"} <= item.keys():
            return CheckResult(False, f"metrics.json item {i} must have keys name, value, unit, uncertainty, method")
        try:
            m = Metric.model_validate(item)
        except Exception as e:
            return CheckResult(False, f"metrics.json item {i} ({item.get('name')}): {e}")
        if isinstance(m.value, float) and not math.isfinite(m.value):
            return CheckResult(False, f"metric {m.name} is not finite: {m.value}")
        metrics.append(m)
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return CheckResult(False, "script must print a one-line summary as its last stdout line")
    return CheckResult(True, lines[-1].strip(), metrics)


# --- Comparison and classification -------------------------------------------

def _metric(metrics: list[Metric], name: str) -> Metric | None:
    return next((m for m in reversed(metrics) if m.name == name), None)


def comparison_metrics(metrics: list[Metric], reference: dict, target_A: float) -> list[Metric]:
    a = _metric(metrics, "a_refined")
    cert = reference.get("a_A")
    if a is None or cert is None or not isinstance(a.value, (int, float)):
        return []
    diff = float(a.value) - float(cert)
    out = [
        Metric(name="a_certified", value=float(cert), unit="angstrom", uncertainty=reference.get("a_uncertainty_A"),
               method=f"manifest reference_values ({reference.get('source', 'certificate')})"),
        Metric(name="difference_from_certified", value=diff, unit="angstrom", uncertainty=a.uncertainty,
               method="a_refined - a_certified (computed by orchestrator)"),
        Metric(name="difference_relative_percent", value=100 * diff / float(cert), unit="percent", uncertainty=None,
               method="100 * difference / a_certified (computed by orchestrator)"),
        Metric(name="success_target", value=target_A, unit="angstrom", uncertainty=None, method="spec success criterion"),
        Metric(name="within_target", value=abs(diff) <= target_A, unit=None, uncertainty=None,
               method="|difference| <= success_target"),
    ]
    if a.uncertainty:
        out.append(Metric(name="difference_in_sigma", value=diff / a.uncertainty, unit="sigma", uncertainty=None,
                          method="difference / a_refined uncertainty"))
    c, cert_c = _metric(metrics, "c_refined"), reference.get("c_A")  # hexagonal and tetragonal cells
    if c is not None and cert_c is not None and isinstance(c.value, (int, float)):
        dc = float(c.value) - float(cert_c)
        out += [Metric(name="c_certified", value=float(cert_c), unit="angstrom", uncertainty=reference.get("c_uncertainty_A"),
                       method=f"manifest reference_values ({reference.get('source', 'certificate')})"),
                Metric(name="c_difference_from_certified", value=dc, unit="angstrom", uncertainty=c.uncertainty,
                       method="c_refined - c_certified (computed by orchestrator)")]
    return out


@dataclass
class TrendStats:
    slope: float
    slope_err: float
    t: float
    n: int


def residual_trend(peaks_csv: bytes) -> TrendStats | None:
    df = pd.read_csv(io.BytesIO(peaks_csv))
    need = {"two_theta_obs", "residual_deg"}
    if not need <= set(df.columns) or len(df) < 4:
        return None
    w = None
    if "two_theta_obs_err" in df and df.two_theta_obs_err.gt(0).all():
        w = 1 / df.two_theta_obs_err.to_numpy()
    (slope, _), cov = np.polyfit(df.two_theta_obs, df.residual_deg, 1, w=w, cov=True)
    err = float(np.sqrt(cov[0, 0]))
    return TrendStats(float(slope), err, float(slope / err) if err else math.inf, len(df))


def rule_classification(metrics: list[Metric], peaks_csv: bytes | None, manifest_wavelength: float | None,
                        trend_t_threshold: float = 3.0, weak_peak_factor: float = 5.0) -> tuple[str, list[str]]:
    """Spec table, applied in order. Returns (classification, reasons)."""
    reasons = []
    trend = residual_trend(peaks_csv) if peaks_csv else None
    if trend:
        reasons.append(f"residual slope t-statistic {trend.t:.2f} over {trend.n} peaks (threshold {trend_t_threshold})")
        if abs(trend.t) > trend_t_threshold:
            return "missing_geometric_correction", reasons
    else:
        reasons.append("no peaks table with residuals; trend not checked")
    within = _metric(metrics, "within_target")
    if within is not None and within.value is True:
        return "agreement", reasons
    wl = _metric(metrics, "wavelength")
    if manifest_wavelength is None or wl is None or not math.isclose(float(wl.value), manifest_wavelength, rel_tol=1e-7):
        reasons.append("wavelength metric missing or not equal to the manifest value")
        return "metadata_issue", reasons
    if peaks_csv:
        df = pd.read_csv(io.BytesIO(peaks_csv))
        if "two_theta_obs_err" in df and len(df):
            med = df.two_theta_obs_err.median()
            if (df.two_theta_obs_err > weak_peak_factor * med).any():
                reasons.append(f"some peak-centre uncertainties exceed {weak_peak_factor}x the median")
                return "weak_or_overlapping_peaks", reasons
    return "unexplained", reasons


# --- Claim checker -----------------------------------------------------------

# Decimal numbers and scientific notation. Integers are not checked (hkl, counts, dates, step numbers).
_NUM = re.compile(r"(?<![\w.\-])[-−+]?(\d+(?:\.\d+)?\s?[×x]\s?10\^?\(?[-−]?\d+\)?|\d+(?:\.\d+)?[eE][-+]?\d+|\d+\.\d+)")
_SCALES = [10.0**k for k in range(-4, 5)]


def _parse(token: str) -> tuple[float, float] | None:
    """Return (value, half-unit-in-last-place tolerance) for a printed number."""
    t = token.replace("−", "-").replace(" ", "")
    m = re.fullmatch(r"([-+]?\d+(?:\.(\d+))?)[×x]10\^?\(?([-]?\d+)\)?", t)
    if m:
        dec = len(m.group(2) or "")
        exp = int(m.group(3))
        return float(m.group(1)) * 10**exp, 0.5 * 10 ** (exp - dec)
    m = re.fullmatch(r"([-+]?\d+(?:\.(\d+))?)[eE]([-+]?\d+)", t)
    if m:
        dec, exp = len(m.group(2) or ""), int(m.group(3))
        return float(m.group(1)) * 10**exp, 0.5 * 10 ** (exp - dec)
    m = re.fullmatch(r"[-+]?\d+\.(\d+)", t)
    if m:
        return float(t), 0.5 * 10 ** -len(m.group(1))
    return None


def _sig_digits(token: str) -> int:
    digits = re.sub(r"[eE×x].*$", "", token).replace("-", "").replace("+", "").replace(".", "").lstrip("0")
    return len(digits)


def allowed_values(metrics: list[Metric], manifests: list[dict], extra: list[float] = ()) -> list[float]:
    vals: list[float] = list(extra)
    for m in metrics:
        for v in (m.value, m.uncertainty):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(float(v))

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            vals.append(float(x))

    for mf in manifests:
        walk(mf)
    return vals


def numbers_in(text: str) -> list[float]:
    return [p[0] for tok in _NUM.findall(text) if (p := _parse(tok))]


def claim_check(text: str, allowed: list[float]) -> dict:
    untraced, checked = [], 0
    for lineno, line in enumerate(text.splitlines(), 1):
        for match in _NUM.finditer(line):
            token = match.group(0).strip()
            parsed = _parse(match.group(1))
            if parsed is None:
                continue
            checked += 1
            x, tol = parsed
            x = abs(x)
            scales = _SCALES if _sig_digits(match.group(1)) >= 3 else [1.0]
            if not any(abs(x - abs(v) * s) <= tol * (1 + 1e-9) + 1e-15 for v in allowed for s in scales):
                untraced.append({"number": token, "line": lineno, "context": line.strip()[:160]})
    return {"passed": not untraced, "checked": checked, "untraced": untraced}
