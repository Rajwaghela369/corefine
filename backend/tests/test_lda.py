"""LDA in every adapter: the functional each code is told to use, and the read-back that verifies it."""

import json

import pytest
from ase.build import bulk

from app.config import get_settings
from app.dft import checks, structure, tools
from app.dft.codes import REGISTRY
from app.dft.request import CalcRequest

SI = structure.standard_primitive(bulk("Si", "diamond", a=5.431144))
LDA_UPF = ('<UPF version="2.0.1">\n<PP_HEADER generated="test" element="Si" pseudo_type="PAW" '
           'functional="SLA PW NOGX NOGC" z_valence="4.0"/>\n</UPF>\n')


def needs(attr: str):
    path = getattr(get_settings(), attr)
    return pytest.mark.skipif(not path or not path.exists(), reason=f"{attr} not configured")


def test_every_adapter_maps_lda():
    for name, adapter in REGISTRY.items():
        assert "LDA" in adapter.functionals(), name


def test_vasp_lda_sets_no_gga_tag_and_checks_lexch(tmp_path, monkeypatch):
    pp = tmp_path / "pp" / "potpaw" / "Si"
    pp.mkdir(parents=True)
    (pp / "POTCAR").write_text("  PAW Si 02Apr1999\n   TITEL  = PAW Si 02Apr1999\n   LEXCH  = CA\n   ENMAX  =  245.7\n End of Dataset\n")
    monkeypatch.setattr(get_settings(), "VASP_PP_PATH", tmp_path / "pp")
    v = REGISTRY["vasp"]
    req = CalcRequest(structure="x", codes=["vasp"], functional="LDA")
    info = v.write(SI, req, tmp_path / "run", get_settings(), "Si")
    assert "GGA" not in (tmp_path / "run" / "INCAR").read_text() and info["potcar"]["assembled"]
    report = checks.run_checks(SI, req, "227", {"vasp": v.read_back(tmp_path / "run", req)})
    assert report["passed"], report["results"]
    assert any("LEXCH" in r["check"] and r["ok"] for r in report["results"])


def test_vasp_lda_rejects_a_pbe_potcar(tmp_path, monkeypatch):
    pp = tmp_path / "pp" / "potpaw" / "Si"
    pp.mkdir(parents=True)
    (pp / "POTCAR").write_text("  PAW_PBE Si 05Jan2001\n   TITEL  = PAW_PBE Si 05Jan2001\n   LEXCH  = PE\n End of Dataset\n")
    monkeypatch.setattr(get_settings(), "VASP_PP_PATH", tmp_path / "pp")
    v = REGISTRY["vasp"]
    req = CalcRequest(structure="x", codes=["vasp"], functional="LDA")
    v.write(SI, req, tmp_path / "run", get_settings(), "Si")
    report = checks.run_checks(SI, req, "227", {"vasp": v.read_back(tmp_path / "run", req)})
    assert not report["passed"]


def test_qe_lda_from_a_cutoff_table_uses_pw_default_dual(tmp_path, monkeypatch):
    pdir = tmp_path / "pseudos"
    pdir.mkdir()
    (pdir / "Si.LDA-PW-paw.UPF").write_text(LDA_UPF)
    (pdir / "JTH_LDA_v1.1_cutoffs.json").write_text(json.dumps(
        {"Si": {"filename": "Si.LDA-PW-paw.UPF", "cutoff_wfc": 20.0, "cutoff_rho": None, "md5": None}}))
    monkeypatch.setattr(get_settings(), "QE_PSEUDO_DIR", pdir)
    qe = REGISTRY["espresso"]
    req = CalcRequest(structure="x", codes=["espresso"], functional="LDA")
    info = qe.write(SI, req, tmp_path / "run", get_settings(), "Si")
    assert info["defaults"]["values"]["ecutwfc_Ry"] == 20.0 and info["defaults"]["values"]["ecutrho_Ry"] == 80.0
    assert "pw.x default 4 x ecutwfc" in info["defaults"]["source"]
    report = checks.run_checks(SI, req, "227", {"espresso": qe.read_back(tmp_path / "run", req)})
    assert report["passed"], report["results"]


def test_qe_refuses_lda_with_pbe_pseudopotentials(tmp_path, monkeypatch):
    pdir = tmp_path / "pseudos"
    pdir.mkdir()
    (pdir / "Si.pbe.UPF").write_text(LDA_UPF.replace("SLA PW NOGX NOGC", "SLA PW PBX PBC"))
    monkeypatch.setattr(get_settings(), "QE_PSEUDO_DIR", pdir)
    req = CalcRequest(structure="x", codes=["espresso"], functional="LDA")
    with pytest.raises(Exception, match="not LDA"):
        REGISTRY["espresso"].write(SI, req, tmp_path / "run", get_settings(), "Si")


def test_lda_libraries_are_found_by_kind(local_env):
    for name, sub in (("jth-lda", "ATOMPAW-LDA-JTHv1.1"), ("pseudodojo-lda", "ONCVPSP-LDA-PDv0.4")):
        (tools.tools_dir() / "pseudos" / sub).mkdir(parents=True)
        tools._set(name, status="installed")
    assert tools.managed_pseudo_dir("LDA").name == "ATOMPAW-LDA-JTHv1.1"            # QE: UPF libraries
    assert tools.managed_pseudo_dir("LDA", kind="pseudodojo").name == "ONCVPSP-LDA-PDv0.4"  # ABINIT
    assert tools.managed_pseudo_dir("PBE") is None


@needs("QUESTAAL_BIN")
def test_questaal_lda_is_pw92_not_barth_hedin(tmp_path):
    q = REGISTRY["questaal"]
    req = CalcRequest(structure="x", codes=["questaal"], functional="LDA", kmesh=(2, 2, 2))
    info = q.write(SI, req, tmp_path, get_settings(), "Si")
    ctrl = next(tmp_path.glob("ctrl.*")).read_text()
    assert "0,1,12" in ctrl and "0,101,130" not in ctrl and "xcfun" in info["set_explicitly"]
    report = checks.run_checks(SI, req, "227", {"questaal": q.read_back(tmp_path, req)})
    assert report["passed"], [r for r in report["results"] if not r["ok"]]
