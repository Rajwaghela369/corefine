"""Theory <-> experiment aggregation: XRD refinement + certified value next to DFT EOS lattice constants."""

import json

import pytest


def test_bridge_joins_xrd_runs_and_dft_eos(seeded, no_index):
    from fastapi.testclient import TestClient

    from app.api.dft import jobs_dir
    from app.main import app
    from app.models.db import MetricRow, RunRow, get_sessionmaker

    with get_sessionmaker()() as db, db.begin():
        db.add(RunRow(id="run-x", prompt="p", dataset_ids=["nist-srm-640f", "cod-9008565-si"], status="done"))
        db.add(MetricRow(run_id="run-x", name="a_refined", value=5.430862, uncertainty=3.5e-5, unit="angstrom", source_key="k"))
    sets = (("dft-20261021-000000-0001", {"espresso": 5.4700}), ("dft-20261021-000001-0002", {"espresso": 5.4696, "gpaw": 5.4757}))
    for name, fits in sets:
        d = jobs_dir() / name
        (d / "studies" / "eos").mkdir(parents=True)
        (d / "provenance.json").write_text(json.dumps({"cell": {"formula": "Si2"}, "request": {"functional": "PBE"}}))
        (d / "studies" / "eos" / "study.json").write_text(json.dumps({"codes": {c: {
            "fit": {"a0_conventional_A": a, "B0_GPa": 88.8}, "settings": {"kmesh": [10, 10, 10]}} for c, a in fits.items()}}))
    with TestClient(app) as c:
        b = c.get("/bridge", params={"material": "Si"}).json()
    assert b["experiment"][0]["a_A"] == 5.430862 and b["certified"][0]["a_A"] == 5.431144
    qe = [t for t in b["theory"] if t["code"] == "espresso"]
    assert len(qe) == 1 and qe[0]["a0_A"] == 5.4696                      # newest set only
    assert qe[0]["vs_experiment_percent"] == pytest.approx(100 * (5.4696 / 5.430862 - 1))
    assert qe[0]["pressure_equivalent_GPa"] == pytest.approx(-88.8 * ((5.430862 / 5.4696) ** 3 - 1))
