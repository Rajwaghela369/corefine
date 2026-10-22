"""Refinement engines (GSAS-II, MAUD) as runs: inputs, the run record, comparison groups, the story view, and gaps.

The real programs run only when they are installed in this checkout's tools folder; otherwise a stand-in engine
returns a fixed result so that everything around the engine is still tested.
"""

import json
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import BACKEND, SEED

REAL_TOOLS = BACKEND / ".local" / "tools"
HAS_GSAS2 = (REAL_TOOLS / "envs" / "gsas2" / "bin" / "python").is_file()
HAS_MAUD = (REAL_TOOLS / "apps" / "maud" / "Maud" / "jdk" / "bin" / "java").is_file()


@pytest.fixture
def lab6(seeded, no_index):
    if not any((SEED / "nist-srm-660c" / "raw").glob("*.cif")):
        pytest.skip("seed data missing; run scripts/fetch_data.py")
    from app.storage import datasets

    for folder in ("nist-srm-660c", "cod-1000057-lab6"):
        src = SEED / folder
        m = datasets.parse_manifest((src / "dataset.yaml").read_text(), folder)
        for f in sorted((src / "raw").glob("*"))[:1]:
            seeded.put(f"datasets/{folder}/raw/{f.name}", f.read_bytes())
        datasets.write_manifest(m, seeded)
    return seeded


def fake_result(engine: str, a: float) -> dict:
    x = np.linspace(20, 150, 50)
    return {"engine": engine, "cell": {"length_a": a, "length_b": a, "length_c": a, "angle_alpha": 90, "angle_beta": 90,
                                       "angle_gamma": 90}, "cell_esd": {"length_a": 2e-5}, "Rwp_percent": 18.2,
            "zero_deg": 0.0, "displacement_um": -12.0, "size_um": 0.6, "microstrain": 6.4e-4,
            "stages": [{"stage": "background and scale", "Rwp_percent": 32.1}, {"stage": "cell", "Rwp_percent": 18.2}],
            "settings": {"instrument": "test defaults"}, "warnings": [],
            "curve": {"x": x.tolist(), "observed": np.ones(50).tolist(), "calculated": np.ones(50).tolist(),
                      "background": np.zeros(50).tolist()} if engine == "gsas2" else None}


@pytest.fixture
def fake_engines(monkeypatch):
    from app.config import get_settings
    from app.xrd import engines

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # report written by code; no API call from a test
    get_settings.cache_clear()

    monkeypatch.setattr(engines, "available", lambda e: (True, "test"))
    monkeypatch.setattr(engines, "RUNNERS", {"gsas2": lambda pr: fake_result("gsas2", 4.15682),
                                             "maud": lambda pr: fake_result("maud", 4.15628)})


def test_prepare_reads_the_scan_and_the_manifest_facts(lab6, tmp_path):
    from app.xrd import engines

    ref = engines.reference_for("nist-srm-660c", [])
    assert ref == "cod-1000057-lab6"
    pr = engines.prepare("nist-srm-660c", ref, tmp_path / "w")
    data = np.loadtxt(pr.scan)
    assert data.shape[1] == 3 and data.shape[0] == 5332 and (data[:, 2] > 0).all()
    assert pr.wavelength_A == 1.5405929 and pr.ka2 is True and pr.source == "lab"
    assert "_cell_length_a" in pr.cif.read_text()                       # the reference structure, not the scan
    assert "data_cell_" not in Path(pr.scan).read_text()


def test_engine_group_runs_compare_and_tell_their_story(lab6, fake_engines):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    r = c.post("/runs", json={"prompt": "compare engines", "dataset_ids": ["nist-srm-660c", "cod-1000057-lab6"],
                              "engines": ["gsas2", "maud"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["ids"]) == 2 and body["group_id"]
    deadline = time.time() + 60
    while time.time() < deadline and any(c.get(f"/runs/{i}").json()["status"] not in ("done", "failed") for i in body["ids"]):
        time.sleep(0.2)
    for rid in body["ids"]:
        run = c.get(f"/runs/{rid}").json()
        assert run["status"] == "done", run["error"]
        names = {m["name"] for m in run["metrics"]}
        assert {"a_refined", "Rwp", "a_certified", "difference_from_certified"} <= names
        assert run["claim_check"]["passed"], run["claim_check"]
        assert c.get(f"/runs/{rid}/artifacts/report.md").text.startswith("# ")
    g = c.get(f"/runs/group/{body['group_id']}").json()
    assert [x["engine"] for x in g["runs"]] == ["gsas2", "maud"]
    assert "curve" in g["runs"][0] and "curve" not in g["runs"][1]
    assert g["runs"][1]["reflections"] and g["certified"]["a_A"] == 4.156826
    st = g["runs"][0]["story"]
    assert st["steps"][1]["name"].startswith("refine_") and st["stages"]
    assert any(e["agent"] in ("gsas2", "maud") for e in st["log"])


def test_unavailable_engine_is_refused(lab6):
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).post("/runs", json={"prompt": "x y z", "dataset_ids": ["nist-srm-660c"], "engines": ["maud"]})
    assert r.status_code == 400 and "not installed" in r.json()["detail"]


@pytest.mark.skipif(not HAS_GSAS2, reason="GSAS-II not installed in .local/tools")
def test_real_gsas2_refines_lab6_close_to_the_certificate(lab6, tmp_path, monkeypatch):
    from app.dft import tools
    from app.xrd import engines

    monkeypatch.setattr(tools, "managed_executable", lambda code: REAL_TOOLS / "envs" / "gsas2" / "bin" / "python")
    pr = engines.prepare("nist-srm-660c", "cod-1000057-lab6", tmp_path / "w")
    r = engines.run_gsas2(pr)
    assert r["cell"]["length_a"] == pytest.approx(4.156826, abs=5e-4)
    assert r["Rwp_percent"] < 30 and r["curve"] and len(r["stages"]) == 4


@pytest.mark.skipif(not HAS_MAUD, reason="MAUD not installed in .local/tools")
def test_real_maud_refines_lab6(lab6, tmp_path, monkeypatch):
    from app.dft import tools
    from app.xrd import engines

    monkeypatch.setattr(tools, "managed_executable", lambda code: REAL_TOOLS / "apps" / "maud" / "Maud" / "jdk" / "bin" / "java")
    pr = engines.prepare("nist-srm-660c", "cod-1000057-lab6", tmp_path / "w")
    r = engines.run_maud(pr)
    assert r["cell"]["length_a"] == pytest.approx(4.156826, abs=2e-3)
    assert [s["wizard"] for s in r["stages"]] == [0, 1, 2]


def test_maud_template_follows_the_manifest(tmp_path):
    import zipfile

    from app.xrd import engines

    home = tmp_path / "Maud"
    (home / "lib").mkdir(parents=True)
    par = ("_pd_proc_ls_weight_scheme sqrt\n_pd_instr_geometry 'Bragg-Brentano'\n#subordinateObject_Bragg-Brentano\n"
           "#end_subordinateObject_Bragg-Brentano\n_diffrn_radiation_wavelength 1.5405982 #min 0.1\n"
           "#subordinateObject_2\n_diffrn_radiation_wavelength 1.544497 #min 0.1\n#end_subordinateObject_2\n")
    with zipfile.ZipFile(home / "lib" / "Maud.jar", "w") as z:
        z.writestr("files/default.par", par)
    pr = engines.Prepared(tmp_path, tmp_path / "s.xye", tmp_path / "p.cif", 0.41419, False, "synchrotron", "f", "r")
    t = engines.maud_template(home, pr)
    assert "1.544497" not in t and "_diffrn_radiation_wavelength 0.41419" in t
    assert "'No Corrections'" in t and "weight_scheme Default" in t
    pr.ka2, pr.source, pr.wavelength_A = True, "lab", 1.5405929
    t = engines.maud_template(home, pr)
    assert "1.544497" in t and "Bragg-Brentano" in t


def test_init_db_adds_new_run_columns(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect, text

    from app.config import get_settings
    from app.models import db

    url = f"sqlite:///{tmp_path / 'old.db'}"
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE runs (id VARCHAR(64) PRIMARY KEY, prompt TEXT, dataset_ids JSON, status VARCHAR(16))"))
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.init_db()
    cols = {c["name"] for c in inspect(db.get_engine()).get_columns("runs")}
    assert {"engine", "group_id"} <= cols
    db.init_db()  # idempotent


def test_band_gap_parsers(tmp_path):
    from app.dft.codes.abinit import AbinitAdapter
    from app.dft.codes.vasp import outcar_gap

    (tmp_path / "abinito_EIG").write_text(
        " Eigenvalues (hartree) for nkpt=   2  k points:\n"
        " kpt#   1, nband=  6, wtk=  0.5, kpt=  0.0000  0.0000  0.0000 (reduced coord)\n"
        "  -0.20    0.10    0.15    0.16    0.30    0.40\n"
        " kpt#   2, nband=  6, wtk=  0.5, kpt=  0.5000  0.0000  0.0000 (reduced coord)\n"
        "  -0.10    0.05    0.12    0.18    0.25    0.41\n")
    abo = "electrons: {nelect:   8.00000000E+00, charge: 0, occopt:   1.00000000E+00, }"
    assert AbinitAdapter.gap(tmp_path, abo) == pytest.approx((0.25 - 0.18) * 27.211386, rel=1e-4)
    assert AbinitAdapter.gap(tmp_path, abo.replace("occopt:   1.", "occopt:   7.")) is None
    outcar = (" E-fermi :   5.0000\n k-point     1 :       0.0000    0.0000    0.0000\n"
              "  band No.  band energies     occupation\n      1      -5.0000      2.00000\n      2       4.5000      2.00000\n"
              "      3       5.2000      0.00000\n      4       6.0000      0.00000\n" + "-" * 104 + "\n")
    assert outcar_gap(outcar) == pytest.approx(0.7)


def test_qe_adds_empty_bands_so_the_gap_can_be_read(tmp_path, monkeypatch):
    from ase.build import bulk

    from app.config import get_settings
    from app.dft import structure
    from app.dft.codes import REGISTRY
    from app.dft.request import CalcRequest

    pdir = tmp_path / "pseudos"
    pdir.mkdir()
    (pdir / "Si.upf").write_text('<UPF version="2.0.1">\n<PP_HEADER element="Si" functional="SLA PW PBX PBC" '
                                 'z_valence="4.0" wfc_cutoff="30" rho_cutoff="240"/>\n</UPF>\n')
    monkeypatch.setattr(get_settings(), "QE_PSEUDO_DIR", pdir)
    si = structure.standard_primitive(bulk("Si", "diamond", a=5.431))
    info = REGISTRY["espresso"].write(si, CalcRequest(structure="x", codes=["espresso"]), tmp_path / "run", get_settings(), "Si")
    assert "nbnd" in info["set_explicitly"]
    assert "nbnd             = 8" in (tmp_path / "run" / "pw.in").read_text()  # 4 occupied + 4 empty
    json.dumps(info)
