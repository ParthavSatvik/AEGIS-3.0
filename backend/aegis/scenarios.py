"""Scenario loading. Splits each family into a public part (engine) and a truth part (simulator)."""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

from .models import ScenarioPublic, ScenarioTruth

DATA = Path(__file__).parent / "data"
FAULT_KINDS = ["grid_tie_trip", "b1_derate", "grid_trip_b1_derate"]


def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@lru_cache
def _raw() -> tuple[dict, list[dict]]:
    base = json.loads((DATA / "base.json").read_text(encoding="utf-8"))
    families = json.loads((DATA / "families.json").read_text(encoding="utf-8"))
    return base, families


def list_families() -> list[dict]:
    _, fams = _raw()
    return [{"id": f["id"], "title": f["title"], "description": f["description"], "demo": f.get("demo", False),
             "second_fault": f["truth"].get("second_fault")} for f in fams]


def load(family_id: str) -> tuple[ScenarioPublic, ScenarioTruth]:
    base, fams = _raw()
    fam = next((f for f in fams if f["id"] == family_id), None)
    if fam is None:
        raise KeyError(f"unknown scenario '{family_id}'")
    pub = _merge(base, fam.get("public_overrides", {}))
    pub.update(id=fam["id"], title=fam["title"], description=fam["description"])
    return ScenarioPublic.model_validate(pub), ScenarioTruth.model_validate(fam["truth"])
