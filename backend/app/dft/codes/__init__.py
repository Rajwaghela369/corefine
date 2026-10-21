"""Registry of DFT code adapters. To support a new code, add a module with a CodeAdapter and list it here."""

from app.config import Settings
from app.dft.codes.base import CodeAdapter, ReadBack, Results
from app.dft.codes.espresso import EspressoAdapter
from app.dft.codes.exciting import ExcitingAdapter
from app.dft.codes.questaal import QuestaalAdapter
from app.dft.codes.vasp import VaspAdapter

REGISTRY: dict[str, CodeAdapter] = {a.name: a for a in (ExcitingAdapter(), QuestaalAdapter(), EspressoAdapter(), VaspAdapter())}


def available(s: Settings) -> list[str]:
    return [name for name, a in REGISTRY.items() if a.availability(s)[0]]


__all__ = ["REGISTRY", "CodeAdapter", "ReadBack", "Results", "available"]
