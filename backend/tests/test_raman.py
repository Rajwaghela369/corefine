"""Raman/IR selection rules from characters, and the Γ-phonon pipeline on a spring model (no DFT)."""

import numpy as np
from ase import Atoms
from ase.build import bulk
from phonopy import Phonopy
from phonopy.structure.atoms import PhonopyAtoms

from app.dft import raman


def spring_phonopy(atoms: Atoms, k: float = 10.0) -> Phonopy:
    unit = PhonopyAtoms(symbols=atoms.get_chemical_symbols(), cell=atoms.cell[:], scaled_positions=atoms.get_scaled_positions())
    ph = Phonopy(unit, supercell_matrix=np.eye(3, dtype=int) * 2, primitive_matrix=None)
    ph.generate_displacements(distance=0.01)
    ref = Atoms(symbols=ph.supercell.symbols, cell=ph.supercell.cell, scaled_positions=ph.supercell.scaled_positions, pbc=True)
    forces = []
    for sc in ph.supercells_with_displacements:
        a = Atoms(symbols=sc.symbols, cell=sc.cell, scaled_positions=sc.scaled_positions, pbc=True)
        vec = a.get_all_distances(mic=True, vector=True)
        r0 = ref.get_all_distances(mic=True)
        f = np.zeros((len(a), 3))
        nn = r0[r0 > 1e-6].min() * 1.05
        for i in range(len(a)):
            for j in range(len(a)):
                if i != j and r0[i, j] < nn:
                    d = np.linalg.norm(vec[i, j])
                    f[i] += k * (d - r0[i, j]) * vec[i, j] / d
        forces.append(f)
    ph.forces = forces
    ph.produce_force_constants()
    return ph


def test_selection_rules_follow_symmetry():
    si = {m["label"]: m for m in raman.gamma_modes(spring_phonopy(bulk("Si", "diamond", a=5.43))) if not m["acoustic"]}
    assert si["T2g"]["raman_active"] and not si["T2g"]["ir_active"]          # centrosymmetric: Raman xor IR
    zb = [m for m in raman.gamma_modes(spring_phonopy(bulk("GaAs", "zincblende", a=5.65))) if not m["acoustic"]]
    assert zb and all(m["raman_active"] and m["ir_active"] for m in zb)      # no inversion: both
    rs = [m for m in raman.gamma_modes(spring_phonopy(bulk("MgO", "rocksalt", a=4.21))) if not m["acoustic"]]
    assert rs and all(m["ir_active"] and not m["raman_active"] for m in rs)  # rock salt: IR only


def test_spectrum_only_shows_raman_active_modes():
    modes = [{"frequency_cm1": 500.0, "degeneracy": 3, "raman_active": True},
             {"frequency_cm1": 300.0, "degeneracy": 3, "raman_active": False}]
    sp = raman.spectrum(modes)
    x, y = np.array(sp["x"]), np.array(sp["y"])
    assert abs(x[np.argmax(y)] - 500) < 1 and y[np.argmin(abs(x - 300))] < 0.01 * y.max()
