"""Symmetry analysis and the standard primitive cell, via spglib. One cell feeds every code."""

from dataclasses import dataclass

import numpy as np
import spglib
from ase import Atoms

SYMPREC = 1e-3     # Å; CIF coordinates are usually given to 4-5 decimals
ROUND = 10         # decimals kept in fractional coordinates, to drop float noise like 0.24999999999999994


class SymmetryError(ValueError):
    pass


@dataclass
class Cell:
    """A standardized primitive cell: lattice rows in Å, fractional positions, symbols."""
    lattice: np.ndarray
    frac: np.ndarray
    symbols: list[str]
    spacegroup_number: int
    spacegroup_symbol: str

    @property
    def atoms(self) -> Atoms:
        return Atoms(symbols=self.symbols, scaled_positions=self.frac, cell=self.lattice, pbc=True)

    @property
    def volume(self) -> float:
        return float(abs(np.linalg.det(self.lattice)))

    def summary(self) -> dict:
        lengths = np.linalg.norm(self.lattice, axis=1)
        a = self.atoms
        d = a.get_all_distances(mic=True)
        nn = float(np.min(d[d > 1e-6])) if len(a) > 1 else float(min(lengths))
        return {
            "formula": a.get_chemical_formula(mode="metal"), "natoms": len(a),
            "spacegroup": f"{self.spacegroup_symbol} ({self.spacegroup_number})",
            "volume_A3": round(self.volume, 6), "volume_per_atom_A3": round(self.volume / len(a), 6),
            "lattice_lengths_A": [round(float(x), 6) for x in lengths],
            "nearest_neighbour_A": round(nn, 6),
        }


def spacegroup_of(atoms: Atoms, symprec: float = SYMPREC) -> tuple[int, str]:
    ds = spglib.get_symmetry_dataset((atoms.cell[:], atoms.get_scaled_positions(), atoms.numbers), symprec=symprec)
    if ds is None:
        raise SymmetryError("spglib could not determine the symmetry")
    return int(ds.number), str(ds.international)


def spacegroup_operations(atoms: Atoms, symprec: float = SYMPREC) -> int:
    ds = spglib.get_symmetry_dataset((atoms.cell[:], atoms.get_scaled_positions(), atoms.numbers), symprec=symprec)
    if ds is None:
        raise SymmetryError("spglib could not determine the symmetry")
    return len(ds.rotations)


def standard_primitive(atoms: Atoms, symprec: float = SYMPREC) -> Cell:
    cell = (atoms.cell[:], atoms.get_scaled_positions(), atoms.numbers)
    std = spglib.standardize_cell(cell, to_primitive=True, no_idealize=False, symprec=symprec)
    if std is None:
        raise SymmetryError("spglib could not standardize the cell")
    lattice, frac, numbers = std
    frac = np.round(np.mod(frac, 1.0), ROUND) % 1.0
    prim = Atoms(numbers=numbers, scaled_positions=frac, cell=lattice, pbc=True)
    number, symbol = spacegroup_of(prim, symprec)
    return Cell(lattice=np.asarray(lattice, float), frac=frac, symbols=prim.get_chemical_symbols(),
                spacegroup_number=number, spacegroup_symbol=symbol)


def scaled(cell: Cell, volume_scale: float) -> Cell:
    """Same crystal with every length multiplied by volume_scale^(1/3) (isotropic strain)."""
    return Cell(lattice=cell.lattice * volume_scale ** (1 / 3), frac=cell.frac.copy(), symbols=list(cell.symbols),
                spacegroup_number=cell.spacegroup_number, spacegroup_symbol=cell.spacegroup_symbol)


def as_given(atoms: Atoms, symprec: float = SYMPREC) -> Cell:
    """The cell exactly as given (no standardisation), e.g. a displaced cell for phonons."""
    number, symbol = spacegroup_of(atoms, symprec)
    return Cell(lattice=np.asarray(atoms.cell[:], float), frac=atoms.get_scaled_positions(wrap=False),
                symbols=atoms.get_chemical_symbols(), spacegroup_number=number, spacegroup_symbol=symbol)
