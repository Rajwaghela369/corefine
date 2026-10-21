"""Theory vs experiment for XRD: peak finding, lattice-scale fit, strain/pressure, phase identification."""

import numpy as np
import pytest
from ase.build import bulk

from app.xrd import analysis, patterns

WL = 1.5405929


def synthetic_scan(a: float, zero: float = 0.0):
    refl = patterns.simulate(bulk("Si", "diamond", a=a), WL, (20, 140))["peaks"]
    x = np.arange(20, 140, 0.005)
    shifted = [{**r, "two_theta": r["two_theta"] + zero} for r in refl]
    y = analysis.profile(shifted, x, 0.08) + 0.5
    return x, y


def test_finds_every_reflection_and_recovers_lattice_and_zero():
    x, y = synthetic_scan(5.431, zero=-0.02)
    peaks = analysis.find_measured_peaks(x, y)
    model = patterns.simulate(bulk("Si", "diamond", a=5.4696), WL, (20, 140))["peaks"]
    c = analysis.compare(peaks, model, WL, bulk_modulus_GPa=88.8)
    assert c["n_matched"] == len(peaks) >= 10
    assert c["lattice_scale"] == pytest.approx(5.431 / 5.4696, abs=2e-5)
    assert c["zero_shift_deg"] == pytest.approx(-0.02, abs=2e-3)
    assert c["pressure_equivalent_GPa"] == pytest.approx(-88.8 * ((5.431 / 5.4696) ** 3 - 1), rel=1e-3)


def test_identify_prefers_the_right_polymorph():
    x, y = synthetic_scan(5.431)
    peaks = analysis.find_measured_peaks(x, y)
    cands = {"diamond": patterns.simulate(bulk("Si", "diamond", a=5.44), WL, (20, 140))["peaks"],
             "fcc": patterns.simulate(bulk("Si", "fcc", a=3.85), WL, (20, 140))["peaks"],
             "bcc": patterns.simulate(bulk("Si", "bcc", a=3.08), WL, (20, 140))["peaks"]}
    ranked = analysis.identify(peaks, cands, WL)
    assert ranked[0]["candidate"] == "diamond" and ranked[0]["explained_fraction"] == 1.0


def test_compare_api_on_the_nist_scan(seeded, no_index):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.post("/xrd/compare", json={"dataset": "nist-srm-640f", "structure": "dataset:cod-9008565-si"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["n_matched"] == d["n_measured"] == 11 and d["wavelength_A"] == WL
        assert abs(d["linear_strain_percent"]) < 0.05 and d["rms_residual_deg"] < 0.01
        assert len(d["profile"]["x"]) == len(d["profile"]["y"]) == 3000
        bad = c.post("/xrd/compare", json={"dataset": "cod-9008565-si", "structure": "dataset:cod-9008565-si"})
        assert bad.status_code == 400
