"""The engine reproduces the reference workbook cell for cell."""

import pytest

import excel_io
from conftest import REFERENCE_WORKBOOK
from oracle import compare

# Mapped cells as of the first green run; the count may only grow.
MIN_COMPARED_CELLS = 2075


def test_every_mapped_cell_matches_excel(reference_state, reference_expected):
    compared, bad = compare(reference_state, reference_expected)
    assert compared >= MIN_COMPARED_CELLS
    assert not bad, "\n".join(f"{c}: excel={e!r} engine={v!r}" for c, e, v in bad[:40])


@pytest.mark.parametrize("sheet", [
    "Billet", "Rebar", "Wire", "Flat", "DRI", "Market Share", "Production Requirments",
    "Fixed Cost", "P&L $ Monthly", "P&L LE Monthly", "P&L $ Annual", "P&L LE Annual",
])
def test_summary_sheets_fully_covered(sheet, reference_state, reference_expected):
    """Every numeric formula cell on the visible summary sheets is checked, apart from
    page counters and the documented scratch cells."""
    import cost_engine
    import excel_map
    outputs = cost_engine.compute_all(reference_state)
    mapped = {c for c, _ in excel_map.excel_cells(outputs, reference_state)}
    allowed = {"Billet!K33", "Billet!K34", "P&L LE Monthly!P49", "P&L LE Monthly!P50",
               "P&L LE Annual!S15", "P&L LE Annual!S33"}
    missing = [c for c in reference_expected
               if c.startswith(sheet + "!") and c not in mapped and c not in allowed
               and not excel_io._IGNORED_FORMULA_CELLS.search(c)]
    assert not missing, missing


def test_reference_workbook_matches_its_own_signature():
    assert excel_io.check_same_model(REFERENCE_WORKBOOK, REFERENCE_WORKBOOK) == []


def test_key_headline_numbers(reference_state):
    """A readable spot-check of headline figures (values copied from Excel's cache:
    DRI!E22, Billet!E30, Billet!G44, Rebar!G19, 'P&L $ Monthly'!R43 and H23)."""
    import cost_engine
    o = cost_engine.compute_all(reference_state)
    assert o["dri"]["EZDK"]["summary_usd_t"]["total_variable_cost"] == pytest.approx(262.42129, abs=1e-5)
    assert o["billet"]["EZDK"]["total_variable_cost"] == pytest.approx(438.89980, abs=1e-5)
    assert o["billet"]["tradeoff"]["minimum"]["ERM"] == pytest.approx(429.88)
    assert o["rebar"]["ERM"]["sc1"]["total_variable_cost"] == pytest.approx(460.00958, abs=1e-5)
    usd = o["pnl"]["usd_monthly"]["columns"]
    assert usd["Total"]["ebt"] == pytest.approx(-10.86977, abs=1e-5)
    assert usd["EZDK/Sub-Total"]["contribution_margin"] == pytest.approx(21.05703, abs=1e-5)
    # the workbook fails two checks: unbalanced blends and a typed-in matrix cell / DRI gain
    assert {c["check"] for c in cost_engine.failed_errors(o)} == {"blending_100", "no_hardcoded_results"}
