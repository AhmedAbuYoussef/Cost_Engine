import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import excel_io  # noqa: E402

REFERENCE_WORKBOOK = os.path.join(ROOT, "tests", "fixtures", "New_Corp_Model_v8_30-12-19.xlsx")


@pytest.fixture(scope="session")
def reference_state():
    return excel_io.extract_state(REFERENCE_WORKBOOK)


@pytest.fixture(scope="session")
def reference_expected():
    return excel_io.extract_expected(REFERENCE_WORKBOOK)


@pytest.fixture
def state(reference_state):
    """A private copy tests may mutate."""
    return copy.deepcopy(reference_state)
