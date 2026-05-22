"""Pytest fixtures for the Ezz Steel cost-engine test suite.

The baseline JSON state is loaded once per session and deep-copied per test
so mutations cannot bleed between tests.
"""

import copy
import json
import os
import sys

import pytest


_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_STATE_PATH = os.path.join(_PROJECT_ROOT, "model_initial_state.json")

# Make cost_engine importable when pytest is run from anywhere.
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


@pytest.fixture(scope="session")
def _baseline_state():
    with open(_STATE_PATH, "r") as f:
        return json.load(f)


@pytest.fixture
def state(_baseline_state):
    """Per-test deep copy with the reconciliation residual block seeded.

    The reconciliation block lives outside model_initial_state.json per brief
    §11 forward log; it will be persisted by state_manager.py (SQLite) in a
    later step. Seeding here keeps the JSON pristine while letting the engine
    pick up the structural Excel-to-engine residual that closes Other
    Conversion for EZDK billet (step 2 adjudication; see TESTING_NOTES.md).
    """
    s = copy.deepcopy(_baseline_state)
    s.setdefault("reconciliation", {})
    s["reconciliation"]["billet_EZDK_excel_to_engine_usd_t"] = 0.499
    return s
