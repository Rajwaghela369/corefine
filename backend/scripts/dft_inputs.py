"""Generate and sanity-check all-electron DFT inputs (exciting + Questaal) from a structure source.

    uv run python scripts/dft_inputs.py --source cod:9008565 --xc PBE --kmesh 2 2 2 --out runs/si-pbe
    uv run python scripts/dft_inputs.py --source mp:mp-149 --out runs/si-mp
    uv run python scripts/dft_inputs.py --prompt "do DFT PBE for Si (mp-149) with a simple 2x2x2 k-mesh, normal inputs"

--prompt needs ANTHROPIC_API_KEY (the LLM only fills the typed request; code writes the inputs).
Flags given together with --prompt override what the LLM extracted.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.dft.pipeline import RequestError, prepare  # noqa: E402
from app.dft.request import CalcRequest, from_prompt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", help="plain-language request, parsed by the LLM into the typed request")
    ap.add_argument("--source", help=".cif path, cod:<id> or mp:<mp-id>")
    ap.add_argument("--codes", nargs="+", choices=["exciting", "questaal"])
    ap.add_argument("--xc", choices=["PBE", "PBEsol", "LDA"])
    ap.add_argument("--kmesh", nargs=3, type=int, metavar=("K1", "K2", "K3"))
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    a = ap.parse_args()

    req = from_prompt(a.prompt) if a.prompt else CalcRequest()
    overrides = {k: v for k, v in {"structure": a.source, "codes": a.codes, "functional": a.xc,
                                    "kmesh": tuple(a.kmesh) if a.kmesh else None}.items() if v}
    req = req.model_copy(update=overrides)
    print("request:", req.model_dump_json())
    try:
        result = prepare(req, a.out)
    except RequestError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    report = result["checks"]
    for r in report["results"]:
        print(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['check']}: {r['detail']}")
    print(json.dumps({"passed": report["passed"], "outdir": result["outdir"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
