"""Pytest configuration: load the initial state once per session.

Seeds the ``sourcing_decision`` field in finished_products at fixture-load
time per brief §4.3 / acknowledgement (c). The on-disk JSON is not mutated.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

INITIAL_STATE_PATH = ROOT / "model_initial_state.json"


def _seed_sourcing_decision(state: dict) -> dict:
    finished = state.get("finished_products", {})
    for product, companies in finished.items():
        for company, payload in companies.items():
            if not isinstance(payload, dict):
                continue
            payload["sourcing_decision"] = "market" if company == "ERM" else "own"
    return state


@pytest.fixture(scope="session")
def state() -> dict:
    with open(INITIAL_STATE_PATH) as fh:
        s = json.load(fh)
    return _seed_sourcing_decision(s)


@pytest.fixture
def state_copy(state) -> dict:
    return copy.deepcopy(state)
