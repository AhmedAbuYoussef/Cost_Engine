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
    return copy.deepcopy(_baseline_state)
