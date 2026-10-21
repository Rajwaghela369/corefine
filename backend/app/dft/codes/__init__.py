"""Registry of DFT code adapters. To support a new code, add a module with a CodeAdapter and list it here."""

from app.config import Settings
from app.dft.codes.base import CodeAdapter, ReadBack
from app.dft.codes.exciting import ExcitingAdapter
from app.dft.codes.questaal import QuestaalAdapter

REGISTRY: dict[str, CodeAdapter] = {a.name: a for a in (ExcitingAdapter(), QuestaalAdapter())}


def available(s: Settings) -> list[str]:
    return [name for name, a in REGISTRY.items() if a.availability(s)[0]]


__all__ = ["REGISTRY", "CodeAdapter", "ReadBack", "available"]
