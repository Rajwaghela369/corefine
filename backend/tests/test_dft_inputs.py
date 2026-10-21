"""DFT input generation. Uses the local Si CIF (no network); code-specific tests skip if a code is not configured."""

import re
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from ase.build import bulk
from conftest import SEED

from app.config import get_settings
from app.dft import checks, exciting, questaal, structure
from app.dft.pipeline import RequestError, prepare
from app.dft.request import CalcRequest

SI_CIF = SEED / "cod-9008565-si" / "raw" / "9008565.cif"


def needs(attr: str):
    path = getattr(get_settings(), attr)
    return pytest.mark.skipif(not path or not path.exists(), reason=f"{attr} not configured")


def test_standard_primitive_si():
    cell = structure.standard_primitive(bulk("Si", "diamond", a=5.431144, cubic=True))
    s = cell.summary()
    assert s["natoms"] == 2 and cell.spacegroup_number == 227
    assert cell.volume == pytest.approx(5.431144**3 / 4, rel=1e-12)
    assert not np.any(np.abs(cell.frac - np.round(cell.frac, 6)) > 1e-10)  # no float noise


def test_request_refusals():
    assert "no structure source" in CalcRequest().unsupported()[0]
    assert any("Questaal" in p for p in CalcRequest(structure="x.cif", functional="LDA").unsupported())
    with pytest.raises(RequestError):
        prepare(CalcRequest(), get_settings().LOCAL_DATA_DIR / "nope")


@needs("EXCITING_ROOT")
def test_exciting_roundtrip_and_schema(tmp_path):
    s = get_settings()
    cell = structure.standard_primitive(bulk("Si", "diamond", a=5.431144))
    req = CalcRequest(structure="local", codes=["exciting"], kmesh=(2, 2, 2))
    info = exciting.write(cell, req, tmp_path, s.EXCITING_ROOT, "Si")
    assert info["defaults_from_schema"]["rgkmax"] == "7.0d0"
    assert exciting.validate(tmp_path, s.EXCITING_ROOT)["ok"] is True
    report = checks.run_checks(cell, req, "227", exciting.read_back(tmp_path), None, None)
    assert report["passed"], report["results"]


@needs("EXCITING_ROOT")
def test_checks_catch_angstrom_bohr_slip(tmp_path):
    """Write the lattice in Å but leave exciting thinking it is bohr: the volume check must fail."""
    s = get_settings()
    cell = structure.standard_primitive(bulk("Si", "diamond", a=5.431144))
    req = CalcRequest(structure="local", codes=["exciting"])
    exciting.write(cell, req, tmp_path, s.EXCITING_ROOT, "Si")
    tree = ET.parse(tmp_path / "input.xml")
    for v, row_A in zip(tree.getroot().findall("structure/crystal/basevect"), cell.lattice):
        v.text = " ".join(str(float(x)) for x in row_A)  # Å written where exciting expects bohr
    tree.write(tmp_path / "input.xml")
    report = checks.run_checks(cell, req, "227", exciting.read_back(tmp_path), None, None)
    failed = [r["check"] for r in report["results"] if not r["ok"]]
    assert "exciting: volume per atom" in failed


@needs("QUESTAAL_BIN")
@needs("EXCITING_ROOT")
def test_full_pipeline_from_local_cif(tmp_path):
    result = prepare(CalcRequest(structure=str(SI_CIF), functional="PBE", kmesh=(2, 2, 2)), tmp_path)
    assert result["checks"]["passed"], [r for r in result["checks"]["results"] if not r["ok"]]
    ctrl = (tmp_path / "questaal" / "ctrl.si").read_text()
    assert re.search(r"nkabc=\s*2 2 2", ctrl) and "0,101,130" in ctrl and "gmax=   NULL" not in ctrl
    for f in ("provenance.json", "checks.json", "SUMMARY.md", "exciting/input.xml", "exciting/Si.xml"):
        assert (tmp_path / f).is_file(), f


def test_prompt_goes_through_llm_into_typed_request(monkeypatch):
    from app.agents import llm
    from app.dft.request import from_prompt

    seen = {}

    def fake_parse(*, agent, output, content, **kw):
        seen.update(agent=agent, content=content)
        return output(structure="mp:mp-149", functional="PBE", kmesh=(2, 2, 2))

    monkeypatch.setattr(llm, "parse", fake_parse)
    req = from_prompt("do DFT PBE for Si with a simple 222 k mesh, normal inputs")
    assert seen["agent"] == "dft_request" and req.kmesh == (2, 2, 2) and req.codes == ["exciting", "questaal"]


@pytest.mark.integration
@needs("QUESTAAL_BIN")
def test_materials_project_and_cod_sources(tmp_path):
    for src in ("mp:mp-149", "cod:9008565"):
        result = prepare(CalcRequest(structure=src), tmp_path / src.replace(":", "_"))
        assert result["checks"]["passed"]


def test_questaal_lmchk_parser():
    log = ("   alat = 7.256709  Cell vol = 270.211636\n MKSYM:  found 48 space group operations ... includes inversion\n"
           " OVMIN, 58 pairs:  fovl = 0   <ovlp> = 0%   max ovlp = 0%\n")
    assert questaal.parse_lmchk(log) == {"cell_volume_bohr3": 270.211636, "space_group_operations": 48,
                                         "max_sphere_overlap_percent": 0.0}
