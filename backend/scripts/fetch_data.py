"""Download the seed data into ../data (raw files are not in git).

- NIST SRM 640f scans: mds2-2251 zip, checked against NIST's SHA-256
- COD 9008565 silicon structure
"""

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
ZIP_URL = "https://data.nist.gov/od/ds/mds2-2251/srm640f_cifs_20200601a.zip"
ZIP_SHA256 = "f135999e3c1639a9825b3d09c464756db569fab7d690ef028992daad8ffe0b96"
COD_URL = "https://www.crystallography.net/cod/9008565.cif"


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main() -> None:
    raw = DATA / "nist-srm-640f" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    blob = get(ZIP_URL)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != ZIP_SHA256:
        sys.exit(f"640f zip checksum mismatch: {digest}")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1]
            if base.endswith(".cif") and not name.startswith("__MACOSX") and not base.startswith("._"):
                (raw / base).write_bytes(z.read(name))
    print(f"640f: {len(list(raw.glob('*.cif')))} scans")
    cod = DATA / "cod-9008565-si" / "raw"
    cod.mkdir(parents=True, exist_ok=True)
    (cod / "9008565.cif").write_bytes(get(COD_URL))
    print("COD 9008565: ok")


if __name__ == "__main__":
    main()
