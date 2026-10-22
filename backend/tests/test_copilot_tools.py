"""The co-pilot's read-only tools on real seed data, the metadata checks, and chat without a key."""

import json

import pytest
from conftest import SEED

NEW = ("nist-srm-660c", "nist-srm-1979-60nm", "cod-1000057-lab6", "cod-2300450-zno")


@pytest.fixture
def more_seeded(seeded):
    if not all(any((SEED / f / "raw").glob("*.cif")) for f in NEW):
        pytest.skip("seed data missing; run scripts/fetch_data.py")
    from app.storage import datasets

    for folder in NEW:
        src = SEED / folder
        m = datasets.parse_manifest((src / "dataset.yaml").read_text(), folder)
        for f in sorted((src / "raw").glob("*"))[:1]:
            seeded.put(f"datasets/{folder}/raw/{f.name}", f.read_bytes())
        seeded.put(f"datasets/{folder}/README.md", (src / "README.md").read_bytes())
        datasets.write_manifest(m, seeded)
    return seeded


def test_seed_manifests_are_valid_and_sourced():
    from app.storage import datasets

    for folder in sorted(p for p in SEED.iterdir() if (p / "dataset.yaml").is_file()):
        m = datasets.parse_manifest((folder / "dataset.yaml").read_text(), folder.name)
        if m.role == "measured_pattern":
            assert m.instrument.wavelength_A and m.instrument.wavelength_source, m.id
            assert m.reference_values and m.reference_values.get("source"), m.id


def test_dataset_tools_and_metadata_checks(more_seeded, no_index):
    from app.agents import copilot

    ids = {d["id"] for d in json.loads(copilot.list_datasets.invoke({}))}
    assert set(NEW) <= ids
    ds = json.loads(copilot.get_dataset.invoke({"dataset_id": "nist-srm-660c"}))
    assert ds["manifest"]["instrument"]["ka2_present"] is True and ds["readme"] and ds["n_files"] == 1
    assert "reference_values" in ds["manifest"]  # the co-pilot may see certified values; only the Coder may not
    nist = json.loads(copilot.check_dataset_metadata.invoke({"dataset_id": "nist-srm-1979-60nm"}))
    assert nist["missing"] == []
    cod = json.loads(copilot.check_dataset_metadata.invoke({"dataset_id": "cod-2300450-zno"}))
    assert "licence stated" in cod["missing"] and "source is a persistent identifier" in cod["missing"]
    assert "error" in json.loads(copilot.get_dataset.invoke({"dataset_id": "no-such-dataset"}))


def test_compare_pattern_tool_on_lab6(more_seeded, no_index):
    from app.agents import copilot

    r = json.loads(copilot.compare_pattern.invoke({"dataset_id": "nist-srm-660c", "structure": "dataset:cod-1000057-lab6"}))
    assert r["n_matched"] >= 10 and "profile" not in r
    assert r["implied_lattice_A"][0] == pytest.approx(4.1568, abs=0.002)


def test_chat_without_key_saves_nothing(local_env, monkeypatch):
    from sqlalchemy import func, select

    from app.agents import copilot
    from app.config import get_settings
    from app.models.db import MessageRow, get_sessionmaker

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        list(copilot.chat("sess-nokey", "Is the dataset FAIR?"))
    with get_sessionmaker()() as db:
        assert db.scalar(select(func.count()).select_from(MessageRow)) == 0


def test_c_parameter_compared_with_certificate():
    from app.agents import checks
    from app.models.contracts import Metric

    ms = [Metric(name="a_refined", value=3.2499, unit="angstrom", uncertainty=1e-4, method="fit"),
          Metric(name="c_refined", value=5.2070, unit="angstrom", uncertainty=2e-4, method="fit")]
    out = {m.name: m for m in checks.comparison_metrics(ms, {"a_A": 3.249828, "c_A": 5.20675}, 0.0005)}
    assert out["c_difference_from_certified"].value == pytest.approx(0.00025, abs=1e-9)


def test_new_skill_brings_its_base_recipe():
    from app.agents import skills

    assert skills.for_step("xrd_other_standards.md") == ["xrd_powder_refinement.md", "xrd_other_standards.md"]
    assert "Kα2" in skills.load("xrd_other_standards.md") and skills.load("other_references.md")
