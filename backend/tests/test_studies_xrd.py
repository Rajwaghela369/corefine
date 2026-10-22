"""Studies (convergence rule, EOS fit, Delta, WIEN2k reference), XRD patterns and Storage imports. No DFT runs."""

import json

import numpy as np
import pytest
from ase.build import bulk

from app.dft import structure, studies
from app.xrd import patterns


def test_converged_index_needs_a_confirming_point():
    assert studies.converged_index([-1.0, -1.003, -1.0045]) is None          # 1.5 meV: only the last point is within 1 meV
    assert studies.converged_index([-1.0, -1.0040, -1.00445, -1.0045]) == 1  # 0.5 meV, confirmed by two more points
    assert studies.converged_index([-1.0, None, -1.0]) is None


def test_bm_fit_and_delta_against_wien2k_si():
    v = np.linspace(0.94, 1.06, 7) * 20.453
    ref = {"V0_A3_per_atom": 20.453, "B0_GPa": 88.545, "B0_prime": 4.31}
    from ase.units import GPa

    eta = (ref["V0_A3_per_atom"] / v) ** (2 / 3)
    b = ref["B0_GPa"] * GPa
    e = -5 + 9 * ref["V0_A3_per_atom"] * b / 16 * ((eta - 1) ** 3 * ref["B0_prime"] + (eta - 1) ** 2 * (6 - 4 * eta))
    fit = studies.fit_bm(list(v), list(e))
    assert fit["V0_A3_per_atom"] == pytest.approx(20.453, rel=1e-6) and fit["B0_GPa"] == pytest.approx(88.545, rel=1e-4)
    assert studies.delta_gauge(fit, ref) < 1e-3


def test_wien2k_reference_only_for_same_elemental_phase():
    si = structure.standard_primitive(bulk("Si", "diamond", a=5.431))
    ref = studies.wien2k_reference(si)
    assert ref["V0_A3_per_atom"] == 20.453 and studies.cubic_a0(si, ref["V0_A3_per_atom"]) == pytest.approx(5.4695, abs=1e-4)
    assert studies.wien2k_reference(structure.standard_primitive(bulk("Si", "fcc", a=3.8))) is None   # different phase
    assert studies.wien2k_reference(structure.standard_primitive(bulk("GaAs", "zincblende", a=5.65))) is None


def test_volume_scaling_keeps_symmetry():
    si = structure.standard_primitive(bulk("Si", "diamond", a=5.431))
    s = structure.scaled(si, 1.06)
    assert s.volume == pytest.approx(si.volume * 1.06) and structure.spacegroup_of(s.atoms)[0] == 227


def test_decimation_keeps_peak_tops():
    x = np.linspace(0, 100, 30000)
    y = np.exp(-((x - 37.123) / 0.02) ** 2) * 1000 + 1
    xs, ys = patterns.decimate(x, y, 2000)
    assert len(xs) <= 2000 and max(ys) == pytest.approx(y.max())


def test_measured_pattern_from_storage_hides_answer(seeded):
    m = patterns.measured("nist-srm-640f")
    assert m["n_points"] == 28099 and m["wavelength_A"] == 1.5405929 and len(m["x"]) <= patterns.MAX_POINTS
    assert 28.3 < m["x"][int(np.argmax(m["y"]))] < 28.6  # (111) is the strongest line
    with pytest.raises(patterns.PatternError):
        patterns.measured("cod-9008565-si")


def test_simulated_si_matches_certificate_positions():
    r = patterns.simulate(bulk("Si", "diamond", a=5.431144), 1.5405929, (20, 140))
    first = r["peaks"][0]
    assert first["hkl"] == "1 1 1" and first["two_theta"] == pytest.approx(28.441, abs=0.002)  # certificate Table 1


def test_save_computed_structure_into_storage(seeded, tmp_path):
    from conftest import SEED

    from app.storage import datasets
    from app.storage.imports import save_computed_structure

    set_dir = tmp_path / "set"
    (set_dir / "studies" / "eos").mkdir(parents=True)
    cif = str(SEED / "cod-9008565-si" / "raw" / "9008565.cif")
    (set_dir / "provenance.json").write_text(json.dumps({"request": {"structure": cif, "functional": "PBE"}}))
    (set_dir / "studies" / "eos" / "study.json").write_text(json.dumps({"codes": {"espresso": {
        "settings": {"kmesh": [10, 10, 10], "basis_scale": 1.25},
        "fit": {"V0_A3_per_atom": 20.4542, "B0_GPa": 88.8, "B0_prime": 4.25, "V0_over_source": 20.4542 / 20.0206}}}}))
    m = save_computed_structure(set_dir, "espresso")
    assert m.role == "reference_structure" and m.model_extra["computed"]["by"] == "espresso"
    atoms = patterns.atoms_from_dataset(m.id)
    assert atoms.get_volume() / len(atoms) == pytest.approx(20.4542, rel=1e-4)
    assert m.id in [n.id for n in datasets.tree() if n.valid]


def test_convergence_explanation_follows_the_rule():
    from app.dft.studies import explain_convergence

    def pts(key, vals, es):
        return [{key: v, "ok": True, "e_per_atom_eV": e, "scf_iterations": 8} for v, e in zip(vals, es)]

    st = {"tol_meV_per_atom": 1.0, "kmeshes": [[4, 4, 4], [6, 6, 6], [8, 8, 8]], "basis_scales": [1.0, 1.5, 2.0],
          "codes": {"espresso": {"kpoints": pts("kmesh", [[4, 4, 4], [6, 6, 6], [8, 8, 8]], [-10.0, -10.0102, -10.0105]),
                                 "basis": pts("basis_scale", [1.0, 1.5, 2.0], [-10.0, -10.02, -10.04]),
                                 "converged_kmesh": [6, 6, 6], "converged_basis_scale": None}}}
    r = explain_convergence(st)["codes"]["espresso"]
    assert r["kpoints"]["chosen"] == "6×6×6" and "cheapest k-mesh" in r["kpoints"]["verdict"]
    assert "4×4×4" in r["kpoints"]["verdict"] and "outside the tolerance" in r["kpoints"]["verdict"]
    rows = r["kpoints"]["rows"]
    assert rows[1]["within"] and not rows[0]["within"] and rows[2]["is_reference"]
    assert abs(rows[1]["delta_to_most_accurate_meV"] - 0.3) < 1e-6
    assert r["basis"]["chosen"] is None and "Not shown within this series" in r["basis"]["verdict"]
    assert r["use"] == "k-mesh 6×6×6, basis ×2.0 (most accurate; not confirmed)" and r["done"]
