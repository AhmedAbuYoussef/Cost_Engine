"""Differential test: perturb every input of the workbook, let LibreOffice recalculate
the real formulas, and require the engine to match the recalculated values.  This
proves the engine implements the *formulas*, not just one set of numbers."""

import os

import pytest

import excel_io
from conftest import REFERENCE_WORKBOOK
from oracle import compare, perturb_workbook, recalc_with_libreoffice, soffice

SEEDS = (1, 2, 3)

pytestmark = pytest.mark.skipif(soffice() is None, reason="LibreOffice not installed")


@pytest.fixture(scope="module")
def recalculated(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("lo")
    src = [str(tmp / f"perturbed_{s}.xlsx") for s in SEEDS]
    for path, seed in zip(src, SEEDS):
        assert perturb_workbook(REFERENCE_WORKBOOK, path, seed) > 500
    out = tmp / "recalc"
    out.mkdir()
    return recalc_with_libreoffice(src, str(out), str(tmp / "profile"))


def test_libreoffice_reproduces_reference_cache(tmp_path):
    """Sanity check of the oracle itself: recalculating the untouched workbook gives
    Excel's cached values."""
    (out,) = recalc_with_libreoffice([REFERENCE_WORKBOOK], str(tmp_path), str(tmp_path / "p"))
    ref, lo = excel_io.extract_expected(REFERENCE_WORKBOOK), excel_io.extract_expected(out)
    bad = [c for c, v in ref.items() if abs(lo.get(c, float("nan")) - v) > 1e-9 * max(1, abs(v))]
    assert not bad, bad[:20]


@pytest.mark.parametrize("index", range(len(SEEDS)))
def test_engine_matches_recalculated_perturbed_workbook(recalculated, index):
    path = recalculated[index]
    assert os.path.exists(path)
    compared, bad = compare(excel_io.extract_state(path), excel_io.extract_expected(path))
    assert compared >= 2075
    assert not bad, "\n".join(f"{c}: excel={e!r} engine={v!r}" for c, e, v in bad[:40])
