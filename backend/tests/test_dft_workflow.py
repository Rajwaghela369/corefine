"""Material search, planner rules and the end-to-end workflow, with Materials Project faked (no network)."""

import json

import numpy as np
import pytest
from ase.build import bulk

from app.config import get_settings
from app.dft import materials, planner, workflow
from app.dft.request import CalcRequest

SI = bulk("Si", "diamond", a=5.431)


def test_formula_normalisation():
    assert materials.optimade_formula("GaAs") == "AsGa"
    assert materials.optimade_formula("O3Fe2") == "Fe2O3"
    assert materials._filter("Ga, As") == 'elements HAS ALL "As", "Ga" AND nelements=2'
    with pytest.raises(materials.SearchError):
        materials.optimade_formula("not a formula!")


def test_search_ranks_stable_first(monkeypatch):
    def item(i, hull, nsites):
        return {"id": i, "attributes": {"chemical_formula_reduced": "Si", "nsites": nsites,
                                        "_mp_stability": {"gga_gga+u": {"energy_above_hull": hull}},
                                        "lattice_vectors": SI.cell[:].tolist(), "cartesian_site_positions": SI.positions.tolist(),
                                        "species_at_sites": ["Si", "Si"]}}

    class R:
        status_code = 200

        def json(self):
            return {"data": [item("mp-165", 0.013, 2), item("mp-149", 0.0, 2)]}

    monkeypatch.setattr(materials.httpx, "get", lambda *a, **k: R())
    out = materials.search("Si")
    assert [e["id"] for e in out] == ["mp-149", "mp-165"] and out[0]["stable"] and out[0]["spacegroup"] == "Fd-3m (227)"


def test_kmesh_from_spacing():
    assert planner.kmesh_for(SI.cell[:]) == (7, 7, 7)
    gan = bulk("GaN", "wurtzite", a=3.19, c=5.19)
    k = planner.kmesh_for(gan.cell[:])
    assert k[0] == k[1] and k[2] < k[0]  # shorter reciprocal vector along c
    assert all(1 <= x <= planner.KMAX for x in planner.kmesh_for(np.eye(3) * 0.5))


def test_rules_metal_magnetic_and_user_mesh():
    metal = planner.rule_plan({"id": "mp-30", "nsites": 1, "is_metal": True, "ordering": "NM"}, bulk("Cu", "fcc", 3.6).cell[:])
    assert metal.request.occupations == "smearing" and not metal.blocked
    fe = planner.rule_plan({"id": "mp-13", "nsites": 1, "is_metal": True, "ordering": "FM"}, bulk("Fe", "bcc", 2.87).cell[:])
    assert fe.blocked and "spin" in fe.blocked[0]
    user = planner.rule_plan({"id": "mp-149", "nsites": 2}, SI.cell[:], kmesh=(2, 2, 2))
    assert user.request.kmesh == (2, 2, 2) and any(d.field == "kmesh" and d.source == "user" for d in user.decisions)
    assert any("magnetic ordering unknown" in w for w in user.warnings)


def test_agent_changes_are_bounded(monkeypatch):
    from app.agents import llm

    plan = planner.rule_plan({"id": "mp-149", "nsites": 2}, SI.cell[:])

    def fake(*, output, **kw):
        return output(changes=[{"field": "kmesh", "value": "4 4 4", "reason": "quick check"},
                               {"field": "kmesh", "value": "99 99 99", "reason": "too dense, must be ignored"},
                               {"field": "codes", "value": "espresso, vasp_does_not_exist", "reason": "only QE"}])

    monkeypatch.setattr(llm, "parse", fake)
    out = planner.agent_plan("quick check", plan, {"id": "mp-149"}, ["espresso", "questaal"])
    assert out.request.kmesh == (4, 4, 4) and out.request.codes == ["espresso"] and out.planner == "agent"
    assert sum(d.source == "agent" for d in out.decisions) == 2


def test_workflow_blocks_magnetic_and_records_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow.materials, "get", lambda i: {"id": i, "formula": "Fe", "nsites": 1, "ordering": "FM",
                                                              "is_metal": True})
    monkeypatch.setattr(workflow.sources, "load", lambda s: type("S", (), {"atoms": bulk("Fe", "bcc", 2.87)})())
    with pytest.raises(Exception, match="spin-polarised"):
        workflow.start(tmp_path / "fe", "mp-13", run=False)
    assert json.loads((tmp_path / "fe" / "plan.json").read_text())["blocked"]


@pytest.mark.skipif(not get_settings().EXCITING_ROOT, reason="EXCITING_ROOT not configured")
def test_workflow_prepares_inputs_without_running(tmp_path, monkeypatch):
    from app.dft import sources

    monkeypatch.setattr(workflow.materials, "get", lambda i: {"id": i, "formula": "Si", "nsites": 2, "is_metal": False,
                                                              "band_gap_eV": 0.6, "ordering": "NM"})
    real_load = sources.load
    monkeypatch.setattr(workflow.sources, "load", lambda s, **kw: real_load(str(SEED_CIF), **kw))
    real_prepare = workflow.pipeline.prepare
    monkeypatch.setattr(workflow.pipeline, "prepare", lambda req, d: real_prepare(
        CalcRequest(**{**req.model_dump(), "structure": str(SEED_CIF), "codes": ["exciting"]}), d))
    out = workflow.start(tmp_path / "si", "mp-149", kmesh=(2, 2, 2), run=False)
    assert out["checks_passed"] and (tmp_path / "si" / "exciting" / "input.xml").is_file()
    plan = json.loads((tmp_path / "si" / "plan.json").read_text())
    assert any(d["field"] == "occupations" and d["source"] == "materials_project" for d in plan["decisions"])


from conftest import SEED  # noqa: E402

SEED_CIF = SEED / "cod-9008565-si" / "raw" / "9008565.cif"
