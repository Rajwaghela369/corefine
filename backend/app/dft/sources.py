"""Where a crystal structure comes from. Every structure carries its provenance.

Sources (the `source` string):
  path/to/file.cif     a local CIF
  cod:<id>             Crystallography Open Database, downloaded as CIF (open, no key)
  dataset:<id>         a reference_structure dataset in CoRefine storage (its first .cif file)
  mp:<mp-id>           Materials Project, via its public OPTIMADE endpoint (no key needed);
                       with MP_API_KEY set, the official mp-api client is used instead if installed
"""

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
from ase import Atoms
from ase.io import read as ase_read

COD_URL = "https://www.crystallography.net/cod/{id}.cif"
MP_OPTIMADE = "https://optimade.materialsproject.org/v1/structures"
TIMEOUT = 30


class SourceError(ValueError):
    pass


@dataclass
class Sourced:
    atoms: Atoms
    source: str
    url: str | None = None
    sha256: str | None = None
    declared_spacegroup: str | None = None   # what the source itself claims, for cross-checking
    notes: list[str] = field(default_factory=list)


def load(source: str, cache_dir: Path | None = None) -> Sourced:
    source = source.strip()
    if source.startswith("cod:"):
        return _from_cod(source[4:], cache_dir)
    if source.startswith("mp:"):
        return _from_mp(source[3:])
    if source.startswith("dataset:"):
        return _from_dataset(source[8:])
    p = Path(source).expanduser()
    if p.suffix.lower() == ".json" and p.is_file():  # ASE JSON written by CoRefine itself (e.g. displaced phonon cells)
        atoms = ase_read(p)
        return Sourced(atoms=atoms, source=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    if p.suffix.lower() == ".cif" and p.is_file():
        data = p.read_bytes()
        return _from_cif_bytes(data, source=str(p), url=None)
    raise SourceError(f"unknown structure source {source!r}; use a .cif path, cod:<id> or mp:<mp-id>")


def _from_cif_bytes(data: bytes, source: str, url: str | None) -> Sourced:
    text = data.decode("utf-8", errors="replace")
    try:
        atoms = ase_read(io.StringIO(text), format="cif")
    except Exception as e:  # ASE raises several types for malformed CIFs
        raise SourceError(f"{source}: could not read CIF ({e})") from e
    return Sourced(atoms=atoms, source=source, url=url, sha256=hashlib.sha256(data).hexdigest(),
                   declared_spacegroup=_cif_spacegroup(text))


def _cif_spacegroup(text: str) -> str | None:
    import gemmi

    block = gemmi.cif.read_string(text).sole_block()
    for tag in ("_space_group_IT_number", "_symmetry_Int_Tables_number"):
        v = block.find_value(tag)
        if v and v not in ("?", "."):
            return v.strip("'\"")
    return None


def _from_cod(cod_id: str, cache_dir: Path | None) -> Sourced:
    if not cod_id.isdigit():
        raise SourceError(f"COD ids are numeric, got {cod_id!r}")
    url = COD_URL.format(id=cod_id)
    cached = cache_dir / f"cod-{cod_id}.cif" if cache_dir else None
    if cached and cached.is_file():
        data = cached.read_bytes()
    else:
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        if r.status_code != 200:
            raise SourceError(f"COD {cod_id}: HTTP {r.status_code}")
        data = r.content
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
    return _from_cif_bytes(data, source=f"cod:{cod_id}", url=url)


def _from_mp(mp_id: str) -> Sourced:
    if not mp_id.startswith("mp-"):
        raise SourceError(f"Materials Project ids look like mp-149, got {mp_id!r}")
    params = {"filter": f'id="{mp_id}"',
              "response_fields": "lattice_vectors,cartesian_site_positions,species_at_sites,space_group_it_number"}
    r = httpx.get(MP_OPTIMADE, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SourceError(f"Materials Project OPTIMADE: HTTP {r.status_code}")
    data = r.json().get("data") or []
    if not data:
        raise SourceError(f"Materials Project has no structure {mp_id}")
    a = data[0]["attributes"]
    atoms = Atoms(symbols=a["species_at_sites"], positions=np.array(a["cartesian_site_positions"]),
                  cell=np.array(a["lattice_vectors"]), pbc=True)
    sg = a.get("space_group_it_number")
    return Sourced(atoms=atoms, source=f"mp:{mp_id}", url=str(r.url),
                   sha256=hashlib.sha256(r.content).hexdigest(),
                   declared_spacegroup=str(sg) if sg else None,
                   notes=["Materials Project structures are relaxed with GGA(+U); lattice constants are "
                          "typically larger than experiment for PBE."])


def _from_dataset(dataset_id: str) -> Sourced:
    from app.storage import datasets
    from app.storage.objects import get_store

    store = get_store()
    try:
        m = datasets.load_manifest(dataset_id, store)
    except datasets.ManifestError as e:
        raise SourceError(str(e)) from e
    cifs = [k for k in datasets.dataset_files(m, store) if k.lower().endswith(".cif")]
    if m.format != "cif" or not cifs:
        raise SourceError(f"dataset {dataset_id!r} has no structure CIF (format {m.format})")
    s = _from_cif_bytes(store.get(cifs[0]), source=f"dataset:{dataset_id}", url=m.source)
    s.notes.append(f"from storage file {cifs[0]}")
    return s
