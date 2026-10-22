"""Bring your own powder scan: read a plain-text pattern and turn it into a dataset the whole app understands.

Instrument software exports many flavours of text: `2θ intensity` pairs with or without a header line, a
third σ column (`.xye`), commas or semicolons, comments. `parse_scan` reads them all the same way and
reports what the header says (wavelength, anode). `to_pdcif` writes the scan as a powder CIF, the one
format the agents, GSAS-II, MAUD, phase identification and the model comparison all read, so an
uploaded file needs no special cases downstream.

Nothing is guessed: a wavelength comes from the file header or from the person, never from a table.
"""

import re
from dataclasses import dataclass, field

import numpy as np

MIN_POINTS = 50
_PAIR = re.compile(r'([A-Za-z][\w ./()-]*?)\s*:\s*(?:"([^"]*)"|([^\s"]+))')
_SPLIT = re.compile(r"[,;\t ]+")


class ScanError(ValueError):
    """The file is not a usable powder pattern; the message says why, in plain words."""


@dataclass
class ParsedScan:
    x: np.ndarray                       # 2θ in degrees
    y: np.ndarray                       # intensity
    sigma: np.ndarray | None            # uncertainty, only if the file has a third column
    header: dict[str, str] = field(default_factory=dict)
    wavelength_A: float | None = None   # from the header, else None
    anode: str | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"n_points": int(self.x.size), "two_theta_min": float(self.x.min()), "two_theta_max": float(self.x.max()),
                "step_deg": float(np.median(np.diff(self.x))), "max_intensity": float(self.y.max()),
                "has_sigma": self.sigma is not None, "header": self.header,
                "wavelength_A": self.wavelength_A, "anode": self.anode, "notes": self.notes}


def _floats(line: str) -> list[float] | None:
    parts = [p for p in _SPLIT.split(line.strip()) if p]
    if len(parts) < 2:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def _header_pairs(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        for key, quoted, bare in _PAIR.findall(line.lstrip("#'\"; ")):
            out.setdefault(key.strip(), (quoted or bare).strip())
    return out


def parse_scan(text: str) -> ParsedScan:
    """Read `2θ intensity [σ]` rows; every non-numeric line before or between them is header text."""
    rows: list[list[float]] = []
    head: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        nums = _floats(line)
        if nums is None or line.lstrip().startswith("#"):
            head.append(line)
        else:
            rows.append(nums)
    if len(rows) < MIN_POINTS:
        raise ScanError(f"found {len(rows)} numeric rows; a powder pattern needs at least {MIN_POINTS} "
                        "(two columns: 2θ in degrees, then intensity)")
    width = max(set(len(r) for r in rows), key=[len(r) for r in rows].count)
    rows = [r for r in rows if len(r) == width]
    arr = np.array(rows, float)
    x, y = arr[:, 0], arr[:, 1]
    sigma = arr[:, 2] if width >= 3 and np.all(arr[:, 2] > 0) else None
    notes: list[str] = []
    if np.any(np.diff(x) <= 0):
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
        sigma = sigma[order] if sigma is not None else None
        keep = np.r_[True, np.diff(x) > 0]
        x, y = x[keep], y[keep]
        sigma = sigma[keep] if sigma is not None else None
        notes.append("2θ was not strictly increasing; rows were sorted and duplicate angles dropped")
    if not (0 < x.min() < x.max() <= 180):
        raise ScanError(f"first column runs {x.min():g} to {x.max():g}; expected 2θ in degrees between 0 and 180. "
                        "If it is d-spacing or q, convert it first")
    if np.any(y < 0):
        notes.append("negative intensities present (background-subtracted data)")
    header = _header_pairs(head)
    wl = None
    for k, v in header.items():
        if "wavelength" in k.lower():
            try:
                wl = float(v)
            except ValueError:
                continue
            if not 0.2 < wl < 5:
                notes.append(f"header wavelength {wl:g} is outside 0.2 to 5 Å and was ignored (units?)")
                wl = None
            break
    anode = next((v for k, v in header.items() if k.lower() == "anode"), None)
    return ParsedScan(x, y, sigma, header, wl, anode, notes)


def slug(name: str) -> str:
    """A dataset id from a file name: lowercase letters, digits and hyphens."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", name.rsplit("/", 1)[-1])
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    s = (s or "scan")[:60].strip("-") or "scan"
    return s if len(s) >= 2 else f"scan-{s}"


def to_pdcif(scan: ParsedScan, block: str, wavelength_A: float, radiation: str, source_file: str) -> str:
    """Write the scan as a powder CIF with the tags the rest of the app reads."""
    w = None
    if scan.sigma is not None:
        w = 1.0 / scan.sigma**2
    lines = [
        f"data_{block}",
        f"# Converted from {source_file} by CoRefine. The columns are exactly the ones in that file;",
        "# nothing was smoothed, rescaled or calibrated. Whether 2theta is zero-corrected is not known.",
        f"_diffrn_radiation_type '{radiation}'",
        f"_diffrn_radiation_wavelength {wavelength_A:.7g}",
        "_pd_meas_number_of_points " + str(scan.x.size),
        "",
        "loop_",
        "_pd_proc_2theta_corrected",
        "_pd_proc_intensity_total",
    ]
    if w is not None:
        lines.append("_pd_proc_ls_weight")
    for i in range(scan.x.size):
        row = f"{scan.x[i]:.6f} {scan.y[i]:.6g}"
        if w is not None:
            row += f" {w[i]:.6g}"
        lines.append(row)
    return "\n".join(lines) + "\n"


def manifest_for(dataset_id: str, scan: ParsedScan, material: str, wavelength_A: float, wavelength_source: str,
                 radiation: str, ka2_present: bool | None, source_file: str) -> dict:
    inst: dict = {"radiation": radiation, "wavelength_A": wavelength_A, "wavelength_source": wavelength_source,
                  "two_theta_zero_corrected": "unknown"}
    if ka2_present is not None:
        inst["ka2_present"] = ka2_present
    return {"id": dataset_id, "role": "measured_pattern", "technique": "xrd_powder", "material": material or "unknown",
            "format": "pdcif", "files": ["raw/*.cif"], "instrument": inst,
            "source": f"uploaded file {source_file}", "user_upload": True,
            "scan_header": scan.header or None}
