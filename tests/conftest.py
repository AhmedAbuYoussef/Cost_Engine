"""Test fixtures for cost_engine.

Loads model_initial_state.json once per session and seeds sourcing_decision
fields per step1_brief §4.3 Q2 (producers → "own"; ERM → "market"). Only
combinations the production matrix in Rulebook §1.4 actually lists are seeded —
the engine reads sourcing_decision strictly and must fail loud on illegal paths.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _REPO_ROOT / "model_initial_state.json"

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Production matrix (Rulebook §1.4) × Q2 sourcing defaults.
_SOURCING_DEFAULTS = {
    "Rebar":    {"EZDK": "own", "EFS": "own", "ERM": "market", "ESR": "own"},
    "Wire Rod": {"EZDK": "own"},
    "HRC":      {"EZDK": "own", "EFS": "own"},
}


def _seed_sourcing_decisions(state: dict) -> None:
    """Inject sourcing_decision in place. No silent defaults — only listed combos."""
    for product, by_company in _SOURCING_DEFAULTS.items():
        for company, decision in by_company.items():
            state["finished_products"][product][company]["sourcing_decision"] = decision


@pytest.fixture(scope="session")
def _raw_state() -> dict:
    with _STATE_PATH.open() as f:
        return json.load(f)


@pytest.fixture
def state(_raw_state) -> dict:
    s = copy.deepcopy(_raw_state)
    _seed_sourcing_decisions(s)
    return s
