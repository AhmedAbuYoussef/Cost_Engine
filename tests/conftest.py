"""Pytest fixtures for the Ezz Steel cost-engine test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from state_manager import load_state  # noqa: E402


@pytest.fixture(scope="session")
def state() -> dict:
    """Loaded model_initial_state.json with sourcing_decision defaults seeded.

    Session-scoped and treated as read-only by tests. Tests that need to
    simulate violations must deepcopy first.
    """
    return load_state(ROOT / "model_initial_state.json")
