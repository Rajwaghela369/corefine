"""Theory against experiment for powder XRD, deterministic (no LLM): find, match, scale, identify.

find_peaks      peaks in a measured scan: candidates from scipy.signal.find_peaks on the scan, then a
                pseudo-Voigt + linear background fit per peak for the centre and its uncertainty
compare         match measured peaks to a structure's reflections, then least-squares fit of an isotropic
                lattice scale s (a_exp = s * a_model) and a zero shift: implied lattice constants, strain
                and, given a bulk modulus (e.g. from a DFT equation of state), the equivalent pressure
                P = -B0 * (V_exp / V_model - 1) to first order
identify        score candidate structures (e.g. every Materials Project polymorph) by how many measured
                peaks they explain after their own scale fit, and the scale they need
profile         simulated reflections broadened with pseudo-Voigt peaks of the width measured in the scan,
                for visual comparison only (no Kα2, no instrument asymmetry)
"""

import math

import numpy as np
from lmfit.models import LinearModel, PseudoVoigtModel
from scipy.optimize import least_squares
from scipy.signal import find_peaks

DEFAULT_TOL_DEG = 0.25     # matching window after the scale fit; CoRefine's choice, shown with the result


def _two_theta(d: np.ndarray, wavelength: float) -> np.ndarray:
    x = np.clip(wavelength / (2 * d), -1, 1)
    return np.degrees(2 * np.arcsin(x))


def find_measured_peaks(x: np.ndarray, y: np.ndarray, max_peaks: int = 40, min_rel_height: float = 0.005,
                        window_deg: float = 0.6) -> list[dict]:
    """Peaks with fitted centres. Prominence threshold relative to the strongest peak (default 0.5 %)."""
    order = np.argsort(x)
    x, y = x[order], y[order]
    step = float(np.median(np.diff(x))) if len(x) > 1 else 0.01
    base = np.percentile(y, 20)
    idx, props = find_peaks(y, prominence=(y.max() - base) * min_rel_height, distance=max(1, int(0.15 / step)))
    idx = idx[np.argsort(props["prominences"])[::-1][:max_peaks]]
    peaks = []
    for i in sorted(idx):
        m = np.abs(x - x[i]) < window_deg / 2
        if m.sum() < 7:
            continue
        xs, ys = x[m], y[m]
        model = PseudoVoigtModel(prefix="pv_") + LinearModel(prefix="bg_")
        params = model.make_params(pv_center=x[i], pv_sigma=0.02, pv_amplitude=(ys.max() - ys.min()) * 0.05,
                                   pv_fraction=0.5, bg_slope=0.0, bg_intercept=float(np.min(ys)))
        params["pv_fraction"].set(min=0, max=1)
        params["pv_sigma"].set(min=step / 2, max=window_deg)
        params["pv_center"].set(min=xs.min(), max=xs.max())
        try:
            fit = model.fit(ys, params, x=xs)
        except Exception:
            continue
        c = fit.params["pv_center"]
        peaks.append({"two_theta": float(c.value), "two_theta_err": float(c.stderr) if c.stderr else None,
                      "height": float(fit.params["pv_height"].value), "fwhm": float(fit.params["pv_fwhm"].value)})
    hmax = max((p["height"] for p in peaks), default=1.0)
    for p in peaks:
        p["rel_intensity"] = 100 * p["height"] / hmax
    return peaks


def compare(measured: list[dict], reflections: list[dict], wavelength: float, tol_deg: float = DEFAULT_TOL_DEG,
            bulk_modulus_GPa: float | None = None) -> dict:
    """Match measured peaks to model reflections and fit an isotropic lattice scale + zero shift."""
    if not measured or not reflections:
        return {"matched": [], "n_matched": 0, "error": "no peaks or no reflections"}
    d_model = np.array([r["d_A"] for r in reflections])
    obs = np.array([p["two_theta"] for p in measured])

    def assign(scale: float, zero: float) -> list[tuple[int, int]]:
        calc = _two_theta(d_model * scale, wavelength) + zero
        pairs, used = [], set()
        for i, t in enumerate(obs):
            j = int(np.argmin(np.abs(calc - t)))
            if abs(calc[j] - t) <= tol_deg and j not in used:
                pairs.append((i, j))
                used.add(j)
        return pairs

    # coarse scan of the scale (±5 %) to start from the assignment that explains most peaks
    best = max(np.linspace(0.95, 1.05, 401), key=lambda s: (len(assign(s, 0.0)), -abs(s - 1)))
    scale, zero = best, 0.0
    for _ in range(3):
        pairs = assign(scale, zero)
        if len(pairs) < 2:
            break
        i_obs, i_ref = map(np.array, zip(*pairs))
        res = least_squares(lambda p: _two_theta(d_model[i_ref] * p[0], wavelength) + p[1] - obs[i_obs], x0=[scale, zero])
        scale, zero = res.x
    pairs = assign(scale, zero)
    rows = []
    for i, j in pairs:
        r = reflections[j]
        calc_model = float(_two_theta(np.array([r["d_A"]]), wavelength)[0])
        calc_fit = float(_two_theta(np.array([r["d_A"] * scale]), wavelength)[0] + zero)
        rows.append({"hkl": r["hkl"], "two_theta_obs": measured[i]["two_theta"], "two_theta_model": calc_model,
                     "two_theta_fit": calc_fit, "delta_model_deg": measured[i]["two_theta"] - calc_model,
                     "residual_deg": measured[i]["two_theta"] - calc_fit, "rel_intensity_obs": measured[i]["rel_intensity"],
                     "rel_intensity_model": r["intensity"]})
    strain = scale - 1
    out = {"matched": sorted(rows, key=lambda r: r["two_theta_obs"]), "n_matched": len(rows), "n_measured": len(measured),
           "lattice_scale": float(scale), "linear_strain_percent": 100 * strain,
           "volume_ratio": float(scale ** 3), "zero_shift_deg": float(zero), "tol_deg": tol_deg,
           "rms_residual_deg": float(np.sqrt(np.mean([r["residual_deg"] ** 2 for r in rows]))) if rows else None,
           "unmatched_measured": [p["two_theta"] for k, p in enumerate(measured) if k not in {i for i, _ in pairs}]}
    if bulk_modulus_GPa:
        out["pressure_equivalent_GPa"] = float(-bulk_modulus_GPa * (scale ** 3 - 1))
        out["pressure_note"] = ("pressure that would bring the model to the measured volume, first order in the volume change, "
                                "using the bulk modulus given")
    return out


def identify(measured: list[dict], candidates: dict[str, list[dict]], wavelength: float, strong: float = 5.0) -> list[dict]:
    """Rank candidate structures: share of strong measured peaks explained after each candidate's own scale fit."""
    strong_peaks = [p for p in measured if p["rel_intensity"] >= strong] or measured
    ranked = []
    for name, refl in candidates.items():
        c = compare(strong_peaks, refl, wavelength)
        if "error" in c:
            continue
        frac = c["n_matched"] / len(strong_peaks)
        # weak lines count too: a phase that explains the small peaks as well as the big ones is the better candidate
        call = compare(measured, refl, wavelength)
        frac_all = call["n_matched"] / len(measured) if "error" not in call else 0.0
        # reflections strong in the model but absent in the scan count against a candidate
        calc = _two_theta(np.array([r["d_A"] for r in refl]) * c["lattice_scale"], wavelength) + c["zero_shift_deg"]
        obs = np.array([p["two_theta"] for p in measured])
        lo, hi = obs.min() - 1, obs.max() + 1
        missing = [r["hkl"] for r, t in zip(refl, calc) if r["intensity"] >= 20 and lo <= t <= hi
                   and np.min(np.abs(obs - t)) > c["tol_deg"]]
        # a big low-symmetry cell has so many lines that it "explains" any peak by luck: the share of the measured range
        # lying within the tolerance of one of its lines is the chance that a random peak is matched
        in_range = calc[(calc >= lo) & (calc <= hi)]
        chance = float(min(1.0, in_range.size * 2 * c["tol_deg"] / (hi - lo)))
        ranked.append({"candidate": name, "explained_fraction": frac, "n_matched": c["n_matched"], "n_strong": len(strong_peaks),
                       "lattice_scale": c["lattice_scale"], "rms_residual_deg": c["rms_residual_deg"],
                       "strong_model_lines_missing": missing,
                       "chance_match": chance,
                       "explained_fraction_all_peaks": frac_all,
                       "score": (frac + 0.5 * frac_all) * (1 - chance) - 0.1 * len(missing) - 2 * abs(c["lattice_scale"] - 1)})
    return sorted(ranked, key=lambda r: r["score"], reverse=True)


def profile(reflections: list[dict], x: np.ndarray, fwhm_deg: float, eta: float = 0.5) -> np.ndarray:
    """Pseudo-Voigt broadening of stick reflections on grid x (peak max = relative intensity)."""
    y = np.zeros_like(x, dtype=float)
    s = fwhm_deg / (2 * math.sqrt(2 * math.log(2)))
    g = fwhm_deg / 2
    for r in reflections:
        dx = x - r["two_theta"]
        y += r["intensity"] * (eta * g ** 2 / (dx ** 2 + g ** 2) + (1 - eta) * np.exp(-dx ** 2 / (2 * s ** 2)))
    return y
