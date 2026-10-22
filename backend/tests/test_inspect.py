"""Pre-filling the Add-dataset form from a file's own CIF tags: only literal values, each with its tag."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.storage.inspect import inspect_cif

DATA = Path(__file__).resolve().parents[2] / "data"


def test_lab_scan_gives_radiation_and_probe_but_no_wavelength():
    f = next((DATA / "nist-srm-640f" / "raw").glob("*.cif"))
    r = inspect_cif(f.read_text(errors="replace"))
    assert r["format"] == "pdcif" and r["role"] == "measured_pattern"
    assert r["found"]["radiation"] == {"value": "Cu K\\a", "tag": "_diffrn_radiation_type"}
    assert r["found"]["probe"]["value"] == "x-ray"
    assert "wavelength_A" not in r["found"]  # the 640f files do not state it; the certificate does


def test_synchrotron_scan_moves_source_out_of_radiation_type():
    f = next((DATA / "nist-srm-1979-15nm" / "raw").glob("*.cif"))
    found = inspect_cif(f.read_text(errors="replace"))["found"]
    assert found["radiation_source"] == {"value": "synchrotron", "tag": "_diffrn_radiation_type"}
    assert "radiation" not in found
    assert found["wavelength_A"]["value"] == 0.41419


def test_structure_cif_endpoint():
    f = DATA / "cod-2300450-zno" / "raw" / "2300450.cif"
    r = TestClient(app).post("/datasets/inspect", files={"file": ("2300450.cif", f.read_bytes())}).json()
    assert r["role"] == "reference_structure" and r["format"] == "cif"
    assert r["found"]["material"] == {"value": "ZnO", "tag": "_chemical_formula_sum"}
    assert r["found"]["wavelength_A"]["value"] == 1.5418


def test_cod_import_keeps_the_published_cif(no_index, monkeypatch):
    import hashlib

    import httpx

    from app.storage import datasets
    from app.storage.objects import get_store

    cif = (DATA / "cod-2300450-zno" / "raw" / "2300450.cif").read_bytes()
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(200, content=cif, request=httpx.Request("GET", url)))
    r = TestClient(app).post("/xrd/import/cod", json={"cod_id": "2300450"})
    assert r.status_code == 200, r.text
    m = datasets.load_manifest(r.json()["dataset"])
    assert m.id == "cod-2300450-zno" and m.material == "ZnO" and m.role == "reference_structure"
    assert get_store().get("datasets/cod-2300450-zno/raw/2300450.cif") == cif
    assert m.model_extra["sha256_download"] == hashlib.sha256(cif).hexdigest()
    assert TestClient(app).post("/xrd/import/cod", json={"cod_id": "abc"}).status_code == 400
