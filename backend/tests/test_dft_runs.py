"""QE and VASP adapters, result parsers on real outputs, and the local and Slurm executors.

The Slurm path runs against fake ssh/rsync/sbatch/sacct shims, so no real cluster is touched.
"""

import json
import os
import shutil
import stat
from pathlib import Path

import pytest
from ase.build import bulk
from conftest import SEED

from app.config import get_settings
from app.dft import checks, execute, structure
from app.dft.codes import REGISTRY
from app.dft.pipeline import RequestError, prepare
from app.dft.request import CalcRequest

FIX = Path(__file__).parent / "fixtures"
SI_CIF = SEED / "cod-9008565-si" / "raw" / "9008565.cif"
SI = structure.standard_primitive(bulk("Si", "diamond", a=5.431144))


def needs(attr: str):
    path = getattr(get_settings(), attr)
    return pytest.mark.skipif(not path or not path.exists(), reason=f"{attr} not configured")


def fake_upf(path: Path, functional: str, wfc: float = 30.0, rho: float = 240.0):
    path.write_text(f'<UPF version="2.0.1">\n<PP_HEADER element="Si" functional="{functional}" '
                    f'wfc_cutoff="{wfc}" rho_cutoff="{rho}" z_valence="4.0"/>\n</UPF>\n')


# --- Quantum ESPRESSO --------------------------------------------------------------

def test_espresso_inputs_and_checks(tmp_path, monkeypatch):
    pseudo = tmp_path / "pseudo"
    pseudo.mkdir()
    fake_upf(pseudo / "Si.pbe-n-rrkjus_psl.1.0.0.UPF", "SLA  PW   PBX  PBC")
    monkeypatch.setattr(get_settings(), "QE_PSEUDO_DIR", pseudo)
    qe = REGISTRY["espresso"]
    assert qe.availability(get_settings())[0]
    req = CalcRequest(structure="local", codes=["espresso"], kmesh=(2, 2, 2))
    info = qe.write(SI, req, tmp_path / "qe", get_settings(), "Si")
    assert info["defaults"]["values"]["ecutwfc_Ry"] == 30.0 and "headers" in info["defaults"]["source"]
    text = (tmp_path / "qe" / "pw.in").read_text()
    assert "ecutwfc" in text and (tmp_path / "qe" / "Si.pbe-n-rrkjus_psl.1.0.0.UPF").is_file()
    report = checks.run_checks(SI, req, "227", {"espresso": qe.read_back(tmp_path / "qe", req)})
    assert report["passed"], [r for r in report["results"] if r["ok"] is False]


def test_espresso_refuses_wrong_functional_and_ambiguity(tmp_path, monkeypatch):
    pseudo = tmp_path / "pseudo"
    pseudo.mkdir()
    fake_upf(pseudo / "Si.pz-vbc.UPF", "SLA PZ NOGX NOGC")
    monkeypatch.setattr(get_settings(), "QE_PSEUDO_DIR", pseudo)
    qe = REGISTRY["espresso"]
    with pytest.raises(Exception, match="not PBE"):
        qe.write(SI, CalcRequest(structure="x", functional="PBE"), tmp_path / "a", get_settings(), "Si")
    fake_upf(pseudo / "Si.pbe-a.UPF", "SLA PW PBX PBC")
    fake_upf(pseudo / "Si.pbe-b.UPF", "SLA PW PBX PBC")
    with pytest.raises(Exception, match="several pseudopotentials"):
        qe.write(SI, CalcRequest(structure="x", functional="PBE"), tmp_path / "b", get_settings(), "Si")


def test_espresso_unavailable_without_pseudos(monkeypatch):
    monkeypatch.setattr(get_settings(), "QE_PSEUDO_DIR", None)
    ok, reason = REGISTRY["espresso"].availability(get_settings())
    assert not ok and "QE_PSEUDO_DIR" in reason
    with pytest.raises(RequestError, match="Quantum ESPRESSO is not available here"):
        prepare(CalcRequest(structure=str(SI_CIF), codes=["espresso"]), get_settings().LOCAL_DATA_DIR / "x")


# --- VASP --------------------------------------------------------------------------

def test_vasp_without_potcar_is_marked_not_done(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "VASP_PP_PATH", None)
    v = REGISTRY["vasp"]
    req = CalcRequest(structure="x", codes=["vasp"], kmesh=(2, 2, 2))
    info = v.write(SI, req, tmp_path, get_settings(), "Si")
    assert not info["potcar"]["assembled"] and not (tmp_path / "POTCAR").exists()
    assert (tmp_path / "INCAR").read_text().splitlines()[1] == "GGA = PE"
    report = checks.run_checks(SI, req, "227", {"vasp": v.read_back(tmp_path, req)})
    potcar = next(r for r in report["results"] if "POTCAR" in r["check"])
    assert potcar["ok"] is None and report["passed"]


def test_vasp_assembles_potcar_when_configured(tmp_path, monkeypatch):
    pp = tmp_path / "pp" / "potpaw_PBE" / "Si"
    pp.mkdir(parents=True)
    (pp / "POTCAR").write_text("  PAW_PBE Si 05Jan2001\n   TITEL  = PAW_PBE Si 05Jan2001\n   ENMAX  =  245.345\n End of Dataset\n")
    monkeypatch.setattr(get_settings(), "VASP_PP_PATH", tmp_path / "pp")
    v = REGISTRY["vasp"]
    req = CalcRequest(structure="x", codes=["vasp"])
    info = v.write(SI, req, tmp_path / "run", get_settings(), "Si")
    assert info["potcar"]["assembled"] and info["potcar"]["titles"] == ["PAW_PBE Si 05Jan2001"]
    report = checks.run_checks(SI, req, "227", {"vasp": v.read_back(tmp_path / "run", req)})
    assert report["passed"] and any(r["check"].endswith("POTCAR species match POSCAR order") and r["ok"] for r in report["results"])


# --- parsers on real output ---------------------------------------------------------

def test_exciting_parser_on_real_si_run():
    r = REGISTRY["exciting"].parse_results(FIX / "exciting_si")
    assert r.converged and r.scf_iterations == 12
    assert r.raw["total_energy_Ha"] == -579.97754227 and r.gap_eV == pytest.approx(0.6016, abs=1e-4)


def test_questaal_parser_reads_convergence_flag():
    r = REGISTRY["questaal"].parse_results(FIX / "questaal_si")
    assert r.converged and r.raw["ehf_Ry"] == -1159.9462377 and r.gap_eV == pytest.approx(0.61757)  # final BZINTS of the converged restart


def test_questaal_parser_flags_unconverged(tmp_path):
    shutil.copytree(FIX / "questaal_si", tmp_path / "q")
    save = tmp_path / "q" / "save.si"
    save.write_text("\n".join(save.read_text().splitlines()[:10]) + "\n")  # stop at the 'x' line
    r = REGISTRY["questaal"].parse_results(tmp_path / "q")
    assert r.converged is False and r.warnings


# --- executors ------------------------------------------------------------------------

def write_compute(tmp_path: Path, monkeypatch, targets: dict) -> None:
    import yaml

    cfg = tmp_path / "compute.yaml"
    cfg.write_text(yaml.safe_dump({"targets": targets}))
    monkeypatch.setattr(get_settings(), "COMPUTE_CONFIG", cfg)


@needs("QUESTAAL_BIN")
@needs("EXCITING_ROOT")
def test_local_questaal_run_restarts_until_converged(tmp_path, monkeypatch):
    write_compute(tmp_path, monkeypatch, {"local": {"kind": "local", "threads": 1, "codes": {
        "questaal": {"executable": "{QUESTAAL_BIN}/lmf", "max_restarts": 3}}}})
    out = tmp_path / "set"
    prepare(CalcRequest(structure=str(SI_CIF), codes=["questaal"]), out)
    st = execute.start(out, "questaal", "local", wait=True)
    st = execute.read_state(out, "questaal")
    assert st["status"] == "completed", st
    assert st["results"]["converged"] is True and st["attempts"] >= 1
    assert st["results"]["gap_eV"] == pytest.approx(0.618, abs=0.01)


def _shim(dirpath: Path, name: str, body: str) -> Path:
    p = dirpath / name
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


@needs("EXCITING_ROOT")
def test_slurm_flow_with_fake_cluster(tmp_path, monkeypatch):
    """ssh runs the command locally, rsync copies host:path as a local path, sbatch runs the job script."""
    bin_ = tmp_path / "fakebin"
    bin_.mkdir()
    remote_root = tmp_path / "remote"
    _shim(bin_, "fake-ssh", f'shift; export PATH="{bin_}:$PATH"; cd {remote_root} && bash -c "$*"\n')
    _shim(bin_, "fake-copy", 'args=(); for a in "$@"; do args+=("${a#fakehost:}"); done\n'
                             f'cd {remote_root} && mkdir -p "${{args[-1]}}" && cp -r "${{args[-2]}}". "${{args[-1]}}"\n')
    _shim(bin_, "sbatch", 'shift; bash job.sh; echo 4242\n')
    _shim(bin_, "sacct", "echo COMPLETED\n")
    _shim(bin_, "fake-exciting", f'cp {FIX / "exciting_si" / "INFO.OUT"} INFO.OUT; echo done\n')
    remote_root.mkdir()
    write_compute(tmp_path, monkeypatch, {"cluster": {
        "kind": "slurm", "host": "fakehost", "remote_dir": "runs", "poll_seconds": 0,
        "ssh_command": str(bin_ / "fake-ssh"), "copy_command": str(bin_ / "fake-copy"),
        "codes": {"exciting": {"executable": str(bin_ / "fake-exciting"),
                               "script": "#!/bin/bash\n#SBATCH --job-name={job_name}\n{command} > {stdout} 2>&1\n"}}}})
    out = tmp_path / "set"
    prepare(CalcRequest(structure=str(SI_CIF), codes=["exciting"]), out)
    execute.start(out, "exciting", "cluster", wait=True)
    st = execute.read_state(out, "exciting")
    assert st["status"] == "completed" and st["remote_job_id"] == "4242", json.dumps(st, indent=1)
    assert st["results"]["converged"] and st["results"]["scf_iterations"] == 12
    assert "#SBATCH --job-name=cf-" in (out / "exciting" / "job.sh").read_text()
    assert (remote_root / "runs" / out.name / "exciting" / "input.xml").is_file()


def test_unknown_target_and_missing_code_entry(tmp_path, monkeypatch):
    write_compute(tmp_path, monkeypatch, {"local": {"kind": "local", "codes": {}}})
    (tmp_path / "set" / "vasp").mkdir(parents=True)
    with pytest.raises(execute.ComputeConfigError, match="unknown compute target"):
        execute.start(tmp_path / "set", "vasp", "nope")
    with pytest.raises(execute.ComputeConfigError, match="no entry for vasp"):  # no VASP executable anywhere
        execute.start(tmp_path / "set", "vasp", "local")


def test_targets_listing_marks_remote_as_needing_confirmation(tmp_path, monkeypatch):
    write_compute(tmp_path, monkeypatch, {"local": {"kind": "local", "codes": {"questaal": {}}},
                                          "hpc": {"kind": "slurm", "host": "h", "codes": {"exciting": {"script": "x"}}}})
    t = {x["name"]: x for x in execute.describe_targets()}
    assert t["local"]["confirm"] is False and t["hpc"]["confirm"] is True and t["hpc"]["codes"] == ["exciting"]
    assert json.dumps(t)  # serialisable for the API
    assert os.environ.get("COREFINE_MODE") == "local"


@needs("EXCITING_ROOT")
def test_api_import_results_and_runs_in_job(seeded, no_index, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    write_compute(tmp_path, monkeypatch, {})
    with TestClient(app) as c:
        job = c.post("/dft/jobs", json={"structure": "dataset:cod-9008565-si", "codes": ["exciting", "vasp"]}).json()
        assert job["passed"], job
        r = c.post(f"/dft/jobs/{job['id']}/runs/exciting/import",
                   files=[("files", ("INFO.OUT", (FIX / "exciting_si" / "INFO.OUT").read_bytes(), "text/plain"))])
        assert r.status_code == 200 and r.json()["results"]["converged"], r.text
        detail = c.get(f"/dft/jobs/{job['id']}").json()
        assert detail["runs"]["exciting"]["target"] == "imported" and detail["runs"]["exciting"]["results"]["scf_iterations"] == 12
        bad = c.post(f"/dft/jobs/{job['id']}/runs/vasp/import", files=[("files", ("notes.txt", b"hello", "text/plain"))])
        assert bad.status_code == 400
        assert c.post(f"/dft/jobs/{job['id']}/runs", json={"code": "exciting", "target": "nope"}).status_code == 400
        assert all(t["kind"] == "local" for t in c.get("/dft/targets").json())  # only the implicit local target
