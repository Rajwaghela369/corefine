"""Idempotent setup: tables, bucket prefixes, Qdrant collections, seed datasets and notes.

    uv run python scripts/setup.py              # everything except the Daytona snapshot
    uv run python scripts/setup.py --snapshot   # also build the Daytona snapshot (cloud, once)

Seed data comes from ../data/<dataset-id>/ (dataset.yaml, README.md, raw/). Run
scripts/fetch_data.py first if raw/ is empty.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.models.db import init_db  # noqa: E402
from app.retrieval import index  # noqa: E402
from app.storage import datasets  # noqa: E402
from app.storage.objects import get_store  # noqa: E402

SANDBOX_LIBS = ["numpy", "scipy", "pandas", "matplotlib", "lmfit", "gemmi", "pymatgen", "ase", "pyyaml"]

NOTES = {
    "nist-srm-640f-certificate": (
        "NIST SRM 640f silicon powder: certified lattice parameter 0.5431144 nm ± 0.000008 nm (k = 2) at 22.5 °C. "
        "Certified with fundamental-parameters Pawley refinement in TOPAS using the Cu Kα spectrum of Mendenhall et al.; "
        "Johansson Ge 111 incident-beam monochromator. Table 1 peak positions use λ = 0.15405929 nm."),
    "method-peak-position-refinement": (
        "Peak-position refinement: fit each reflection with a pseudo-Voigt, convert centres via Bragg's law and refine "
        "the cubic lattice parameter with a zero-shift term by least squares. A symmetric profile ignores instrument "
        "asymmetry (axial divergence), which can bias centres; residuals trending with angle point to specimen "
        "displacement or another geometric correction."),
}


def seed_datasets() -> None:
    s, store = get_settings(), get_store()
    for folder in sorted(p for p in s.SEED_DATA_DIR.iterdir() if (p / "dataset.yaml").is_file()):
        m = datasets.parse_manifest((folder / "dataset.yaml").read_text(), folder.name)
        if (folder / "README.md").is_file():
            store.put(f"datasets/{m.id}/README.md", (folder / "README.md").read_bytes(), "text/markdown")
        raw = sorted((folder / "raw").glob("*")) if (folder / "raw").is_dir() else []
        if not raw:
            print(f"  ! {m.id}: raw/ is empty — run scripts/fetch_data.py")
        for f in raw:
            key = f"datasets/{m.id}/raw/{f.name}"
            if not store.exists(key):
                store.put(key, f.read_bytes())
        datasets.write_manifest(m, store)
        try:
            readme = (folder / "README.md").read_text() if (folder / "README.md").is_file() else None
            index.index_dataset(m.model_dump(exclude_none=True), readme)
        except Exception as e:
            print(f"  ! {m.id}: not indexed in Qdrant ({e})")
        print(f"  dataset {m.id}: {len(raw)} files")


def build_snapshot() -> None:
    from daytona import CreateSnapshotParams, Daytona, DaytonaConfig, Image, Resources

    s = get_settings()
    client = Daytona(DaytonaConfig(api_key=s.DAYTONA_API_KEY, **({"api_url": s.DAYTONA_API_URL} if s.DAYTONA_API_URL else {})))
    try:
        client.snapshot.get(s.DAYTONA_SNAPSHOT)
        print(f"  snapshot {s.DAYTONA_SNAPSHOT} exists")
        return
    except Exception:
        pass
    image = Image.debian_slim("3.13").pip_install(SANDBOX_LIBS)  # 3.13 is Daytona's newest supported series
    client.snapshot.create(CreateSnapshotParams(name=s.DAYTONA_SNAPSHOT, image=image,
                                                resources=Resources(cpu=1, memory=2, disk=5)),
                           on_logs=lambda line: print("   ", line))
    print(f"  snapshot {s.DAYTONA_SNAPSHOT} built")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true", help="build the Daytona snapshot")
    args = ap.parse_args()
    s = get_settings()
    print(f"mode: {s.COREFINE_MODE}")
    init_db()
    print("  tables ok")
    store = get_store()
    for prefix in ("datasets/", "runs/"):
        if not store.exists(prefix + ".keep"):
            store.put(prefix + ".keep", b"")
    print("  bucket prefixes ok")
    try:
        index.ensure_collections()
        for source, text in NOTES.items():
            index.index_note(source, "xrd_powder", "Si", text)
        print("  qdrant collections + notes ok")
    except Exception as e:
        print(f"  ! qdrant: {e}")
    seed_datasets()
    if args.snapshot:
        build_snapshot()


if __name__ == "__main__":
    main()
