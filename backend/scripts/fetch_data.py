"""Download the seed data into ../data (raw files are not in git).

- NIST SRM 640f (Si) scans: mds2-2251 zip
- NIST SRM 660c (LaB6) scans: mds2-2315 zip
- NIST SRM 1979 (ZnO, 15 nm and 60 nm) synchrotron scans: mds2-2269 zip, split by crystallite size
- COD structures: 9008565 (Si), 1000057 (LaB6), 2300450 (ZnO)

Every NIST zip is checked against the SHA-256 that NIST publishes with it (also kept in the dataset folder).
"""

import fnmatch
import hashlib
import http.client
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
NIST = "https://data.nist.gov/od/ds"
# (url, sha256, {dataset folder: file-name pattern})
ZIPS = [
    (f"{NIST}/mds2-2251/srm640f_cifs_20200601a.zip", "f135999e3c1639a9825b3d09c464756db569fab7d690ef028992daad8ffe0b96",
     {"nist-srm-640f": "*.cif"}),
    (f"{NIST}/mds2-2315/srm_660c_cifs_20201029_081700.zip", "92034d06498161db365420831fe35d91ec18bad4ed17385329a1761658da2c42",
     {"nist-srm-660c": "*.cif"}),
    (f"{NIST}/mds2-2269/srm_1979_cifs_20201110a.zip", "1642638f56c36d7fd77929762638b794f3d3684e9bdc69301fc09496881d9544",
     {"nist-srm-1979-15nm": "*_15_nm_*.cif", "nist-srm-1979-60nm": "*_60_nm_*.cif"}),
]
COD = {"cod-9008565-si": 9008565, "cod-1000057-lab6": 1000057, "cod-2300450-zno": 2300450}


def get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                return r.read()
        except (OSError, http.client.HTTPException) as e:  # NIST's server sometimes cuts long downloads short
            if i == tries - 1:
                raise
            print(f"  retry {url} ({e})")
    raise AssertionError


def main() -> None:
    for url, sha, targets in ZIPS:
        blob = get(url)
        digest = hashlib.sha256(blob).hexdigest()
        if digest != sha:
            sys.exit(f"{url.rsplit('/', 1)[-1]}: checksum mismatch ({digest}); not extracted")
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for folder, pattern in targets.items():
                raw = DATA / folder / "raw"
                raw.mkdir(parents=True, exist_ok=True)
                for name in z.namelist():
                    base = name.rsplit("/", 1)[-1]
                    if fnmatch.fnmatch(base, pattern) and not name.startswith("__MACOSX") and not base.startswith("._"):
                        (raw / base).write_bytes(z.read(name))
                print(f"{folder}: {len(list(raw.glob('*.cif')))} scans")
    for folder, cod_id in COD.items():
        raw = DATA / folder / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / f"{cod_id}.cif").write_bytes(get(f"https://www.crystallography.net/cod/{cod_id}.cif"))
        print(f"COD {cod_id}: ok")


if __name__ == "__main__":
    main()
