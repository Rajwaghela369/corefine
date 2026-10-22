"""Simulation sets in the cloud record: files in object storage (without restart scratch), one database row, and a
local working copy only while something runs. Local store + SQLite stand in for S3 + Neon."""

import json

import pytest
from fastapi.testclient import TestClient

from app.dft import sets
from app.main import app
from app.storage.objects import get_store

SID = "dft-20261022-120000-abcd"


@pytest.fixture
def cloud_set(local_env, monkeypatch):
    from app.models.db import init_db

    init_db()
    monkeypatch.setattr(sets, "cloud", lambda: True)
    d = sets.local_root() / SID
    (d / "espresso" / "tmp" / "pwscf.save").mkdir(parents=True)
    (d / "runs").mkdir()
    (d / "provenance.json").write_text(json.dumps({
        "created": "2026-10-22T12:00:00+00:00", "cell": {"formula": "Si2"},
        "request": {"structure": "mp:mp-149", "functional": "PBE", "kmesh": [4, 4, 4], "codes": ["espresso"]}}))
    (d / "checks.json").write_text(json.dumps({"passed": True, "results": [{"ok": True}]}))
    (d / "espresso" / "pw.out").write_text("!    total energy              =     -15.8 Ry\n")
    (d / "espresso" / "tmp" / "pwscf.save" / "wfc1.hdf5").write_bytes(b"x" * 1000)  # restart scratch
    return d


def _state(d, status):
    (d / "runs" / "espresso.json").write_text(json.dumps({"code": "espresso", "status": status}))


def test_finished_set_goes_to_the_cloud_and_leaves_this_computer(cloud_set):
    _state(cloud_set, "completed")
    assert sets.settle(cloud_set) == "uploaded and removed locally"
    assert not cloud_set.exists()
    keys = get_store().list(f"dft/{SID}/")
    assert f"dft/{SID}/espresso/pw.out" in keys and not any("/tmp/" in k for k in keys)
    assert [x["id"] for x in sets.all_listings()] == [SID]

    c = TestClient(app)
    job = c.get(f"/dft/jobs/{SID}").json()
    assert job["runs"]["espresso"]["status"] == "completed" and "espresso/pw.out" in job["files"]
    assert "total energy" in c.get(f"/dft/jobs/{SID}/files/espresso/pw.out").text
    assert sets.read_file(SID, "../../datasets/x/dataset.yaml") is None  # no way out of the set's prefix
    assert c.get(f"/dft/jobs/{SID}/archive").status_code == 200

    with sets.working(SID) as d:  # new work brings the set back, without the scratch
        assert (d / "espresso" / "pw.out").is_file() and not (d / "espresso" / "tmp").exists()


def test_a_running_set_is_uploaded_but_stays_local(cloud_set):
    _state(cloud_set, "running")
    assert sets.settle(cloud_set) == "uploaded"
    assert cloud_set.is_dir() and get_store().exists(f"dft/{SID}/provenance.json")


def test_only_changed_files_are_uploaded_again(cloud_set):
    _state(cloud_set, "running")
    sets.push(cloud_set)
    (cloud_set / "espresso" / "pw.out").write_text("changed")
    assert sets.push(cloud_set) == {"uploaded": 1, "removed": 0}


def test_local_mode_keeps_everything_local(local_env):
    assert sets.settle(sets.local_root() / SID) == "skipped"


def test_restart_marks_dead_local_runs_failed_and_keeps_slurm(cloud_set, monkeypatch):
    _state(cloud_set, "running")
    (cloud_set / "runs" / "abinit.json").write_text(json.dumps({"status": "submitted", "kind": "slurm"}))
    study = cloud_set / "studies" / "convergence"
    study.mkdir(parents=True)
    (study / "study.json").write_text(json.dumps({"status": "running"}))
    monkeypatch.setattr(sets, "settle_soon", lambda p: None)
    assert sets.fail_interrupted() == [SID]
    assert json.loads((cloud_set / "runs" / "espresso.json").read_text())["status"] == "failed"
    assert json.loads((cloud_set / "runs" / "abinit.json").read_text())["status"] == "submitted"
    assert json.loads((study / "study.json").read_text())["status"] == "failed"
