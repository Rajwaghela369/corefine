"""Bring-your-own-scan: a text pattern becomes a dataset every analysis can read."""

import numpy as np
import pytest

from app.xrd import ingest, patterns

HEADER = '\'Id: "demo" Comment: "" Anode: "Cu" Wavelength: "1.5406" Scantype: "2Theta (Coupled TwoTheta/Theta)" \n'


def _scan(header=HEADER, sigma=False, n=120):
    x = np.linspace(20, 80, n)
    y = 100 + 900 * np.exp(-((x - 47.3) ** 2) / 0.05)
    rows = [f"{a:.6f} {b:.3f}" + (f" {np.sqrt(b):.3f}" if sigma else "") for a, b in zip(x, y)]
    return header + "\n".join(rows) + "\n"


def test_parse_reads_header_with_quoted_values():
    s = ingest.parse_scan(_scan())
    assert s.x.size == 120 and s.wavelength_A == 1.5406 and s.anode == "Cu"
    assert s.header["Scantype"] == "2Theta (Coupled TwoTheta/Theta)"
    assert s.sigma is None


def test_parse_handles_csv_comments_and_sigma():
    text = "# exported\n" + "\n".join(f"{a},{100 + a},{10.0}" for a in np.linspace(10, 90, 80))
    s = ingest.parse_scan(text)
    assert s.sigma is not None and s.wavelength_A is None


def test_parse_rejects_non_patterns_with_a_reason():
    with pytest.raises(ingest.ScanError, match="at least"):
        ingest.parse_scan("a b\n1 2\n3 4\n")
    with pytest.raises(ingest.ScanError, match="2θ in degrees"):
        ingest.parse_scan("\n".join(f"{a} 5" for a in np.linspace(200, 400, 80)))


def test_unsorted_rows_are_sorted_and_noted():
    lines = _scan().splitlines()
    s = ingest.parse_scan("\n".join(lines[:1] + lines[1:][::-1]))
    assert np.all(np.diff(s.x) > 0) and any("sorted" in n for n in s.notes)


def test_pdcif_round_trips_through_the_pattern_reader(local_env):
    s = ingest.parse_scan(_scan(sigma=True))
    cif = ingest.to_pdcif(s, "demo", 1.5406, "Cu Kα", "demo.xy")
    import gemmi
    block = gemmi.cif.read_string(cif).sole_block()
    assert np.allclose(np.array(block.find_values("_pd_proc_2theta_corrected"), float), s.x, atol=1e-6)
    assert len(block.find_values("_pd_proc_ls_weight")) == s.x.size


@pytest.fixture
def client(local_env, no_index):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_import_makes_a_dataset_the_analysis_code_can_read(client):
    files = {"file": ("My Scan 1.xy", _scan(), "text/plain")}
    pre = client.post("/datasets/scan/preview", files=files).json()
    assert pre["wavelength_A"] == 1.5406 and pre["suggested_id"] == "my-scan-1"
    r = client.post("/datasets/scan/import", files=files, data={"material": "Si", "ka2_present": "true"})
    assert r.status_code == 200, r.text
    m = r.json()["manifest"]
    assert m["format"] == "pdcif" and m["instrument"]["wavelength_A"] == 1.5406 and m["instrument"]["ka2_present"] is True
    assert "header" in m["instrument"]["wavelength_source"]
    x, y, wl, _, _ = patterns.measured_full("my-scan-1")
    assert x.size == 120 and wl == 1.5406
    assert client.get("/xrd/measured/my-scan-1").json()["n_points"] == 120
    assert client.post("/datasets/scan/import", files=files).status_code == 409   # same id again


def test_import_without_any_wavelength_asks_instead_of_guessing(client):
    files = {"file": ("bare.xy", _scan(header=""), "text/plain")}
    r = client.post("/datasets/scan/import", files=files)
    assert r.status_code == 400 and "wavelength" in r.json()["detail"]
    ok = client.post("/datasets/scan/import", files=files, data={"wavelength_A": "1.7889"})
    assert ok.status_code == 200 and "entered" in ok.json()["manifest"]["instrument"]["wavelength_source"]


def test_identify_needs_to_know_the_sample(client):
    files = {"file": ("xx.xy", _scan(), "text/plain")}
    client.post("/datasets/scan/import", files=files)
    r = client.post("/xrd/identify", json={"dataset": "xx"})
    assert r.status_code == 400 and "what the sample is" in r.json()["detail"]


def test_engines_refused_up_front_without_a_reference_and_group_view_survives(client):
    client.post("/datasets/scan/import", files={"file": ("nr.xy", _scan(), "text/plain")})
    r = client.post("/runs", json={"prompt": "refine", "dataset_ids": ["nr"], "engines": ["gsas2"]})
    assert r.status_code == 400 and "reference structure" in r.json()["detail"]
    from app.orchestration.engine_run import group_view
    assert group_view("does-not-exist")["runs"] == []
