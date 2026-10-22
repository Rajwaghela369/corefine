"""Metadata completeness of a dataset, checked by code against its manifest and README.

Each check states what it looked for and what it found; there is no score. The checks cover what a
curator asks before a dataset can be reused: a persistent identifier, a licence, a checksum, the
instrument facts an analysis needs (radiation, wavelength and where it came from), temperature, and
where any reference value came from. Whether that makes a dataset "FAIR" is the curator's call.
"""

from app.models.contracts import Manifest
from app.storage import datasets
from app.storage.objects import ObjectStore, get_store

PID_HOSTS = ("doi.org/", "hdl.handle.net/", "identifiers.org/", "n2t.net/ark:")


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "ok": ok, "detail": detail}


def check(m: Manifest, store: ObjectStore | None = None) -> list[dict]:
    store = store or get_store()
    extra = m.model_extra or {}
    out = []
    src = m.source or ""
    out.append(_check("source recorded", bool(src), src or "no source in dataset.yaml"))
    out.append(_check("source is a persistent identifier", any(h in src for h in PID_HOSTS),
                      src if src else "no source"))
    lic = extra.get("license")
    out.append(_check("licence stated", bool(lic), str(lic) if lic else "no license field in dataset.yaml"))
    sums = {k: v for k, v in extra.items() if k.startswith("sha256")}
    out.append(_check("checksum of the original download", bool(sums), ", ".join(sums) if sums else "no sha256 field"))
    files = datasets.dataset_files(m, store)
    out.append(_check("declared files present in Storage", bool(files), f"{len(files)} file(s) match {m.files}"))
    readme = store.exists(f"{datasets.PREFIX}{m.id}/README.md")
    out.append(_check("README present", readme, "README.md" if readme else "no README.md in the dataset folder"))
    if m.role == "measured_pattern":
        inst = m.instrument.model_dump(exclude_none=True) if m.instrument else {}
        out.append(_check("radiation stated", bool(inst.get("radiation")), str(inst.get("radiation"))))
        out.append(_check("wavelength stated", inst.get("wavelength_A") is not None, f"{inst.get('wavelength_A')} Å"))
        out.append(_check("wavelength source stated", bool(inst.get("wavelength_source")), str(inst.get("wavelength_source"))))
        temp = m.temperature_C is not None or bool(extra.get("temperature_note"))
        out.append(_check("measurement temperature recorded", temp,
                          f"{m.temperature_C} °C" if m.temperature_C is not None else str(extra.get("temperature_note"))))
    if m.reference_values:
        ref = m.reference_values
        out.append(_check("reference value has a source", bool(ref.get("source")), str(ref.get("source"))))
        unc = [k for k in ref if "uncertainty" in k]
        out.append(_check("reference value has an uncertainty", bool(unc), ", ".join(unc) or "no *_uncertainty* field"))
    return out
