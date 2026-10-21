"""Remove answer-bearing blocks from measured powder-CIF files before they reach the sandbox.

The NIST 640f scans carry the certified lattice parameter (a `data_cell_*` block) and NIST's own
fitted pattern (a block ending `_calc`). If the Coder could read either, it could copy the answer
and the claim checker would still pass, because the number really is in a file.
"""

import re

_DATA_LINE = re.compile(r"^data_(\S+)", re.MULTILINE)
DROP_PREFIXES = ("cell_",)
DROP_SUFFIXES = ("_calc",)


def is_dropped(block_name: str) -> bool:
    return block_name.startswith(DROP_PREFIXES) or block_name.endswith(DROP_SUFFIXES)


def sanitize_pdcif(text: str) -> tuple[str, list[str]]:
    """Return the CIF text without dropped data blocks, and the names of the blocks removed."""
    starts = [(m.start(), m.group(1)) for m in _DATA_LINE.finditer(text)]
    if not starts:
        return text, []
    kept = [text[: starts[0][0]]]
    dropped = []
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        if is_dropped(name):
            dropped.append(name)
        else:
            kept.append(text[pos:end])
    return "".join(kept), dropped
