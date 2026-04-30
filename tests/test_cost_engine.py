"""Cell-by-cell verification against model_verification.md.

Step 1 covers Verification §1.2 (DRI detailed, LE/t) and §1.3 (DRI conversion, $/t).
Tolerances per step1_brief §6.
"""

from __future__ import annotations

import pytest

import cost_engine


# ─────────────────────────────────────────────────────────────────────────────
# Tolerance helpers (brief §6)
# ─────────────────────────────────────────────────────────────────────────────


def _assert_le_int(engine_val: float, expected_int: int, tol: int = 1) -> None:
    """Integer LE/t: round to nearest int, |diff| ≤ 1 for cumulative drift."""
    actual = round(engine_val)
    assert abs(actual - expected_int) <= tol, (
        f"engine={actual} expected={expected_int} delta={actual - expected_int}"
    )


def _assert_usd_2dp(engine_val: float, expected: float, tol: float = 0.01) -> None:
    """2dp USD/t: round to 2dp, |diff| ≤ 0.01."""
    actual = round(engine_val, 2)
    assert abs(actual - expected) <= tol, (
        f"engine={actual:.4f} expected={expected:.4f} delta={actual - expected:+.4f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Verification §1.2 — DRI detailed (LE/t)
# ─────────────────────────────────────────────────────────────────────────────


DRI_DETAILED_EXPECTED = {
    "EZDK": {
        "iop_cost_le_t":            3624,
        "electricity_le_t":           38,
        "natural_gas_le_t":          772,
        "oxygen_le_t":                 0,
        "nitrogen_le_t":              16,
        "water_le_t":                  5,
        "chemicals_le_t":             25,
        "spare_parts_le_t":            0,
        "external_services_le_t":     43,
        "other_le_t":                 20,
        "variable_cost_le_t":       4541,
        "labor_le_t":                351,
        "depreciation_le_t":        1559,
        "other_fixed_le_t":          353,
        "fixed_cost_le_t":          2264,
        "manufacturing_cost_le_t":  6805,
        "dri_selling_price_le_t":   6465,
        "gross_margin_le_t":        -339,
    },
    "ERM": {
        "iop_cost_le_t":            3968,
        "electricity_le_t":           25,
        "natural_gas_le_t":          852,
        "oxygen_le_t":                 0,
        "nitrogen_le_t":              10,
        "water_le_t":                  5,
        "chemicals_le_t":             16,
        "spare_parts_le_t":            0,
        "external_services_le_t":     27,
        "other_le_t":                  0,
        "variable_cost_le_t":       4902,
        "labor_le_t":                785,
        "depreciation_le_t":        3484,
        "other_fixed_le_t":          788,
        "fixed_cost_le_t":          5057,
        "manufacturing_cost_le_t":  9959,
        "dri_selling_price_le_t":   6465,
        "gross_margin_le_t":       -3494,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Verification §1.3 — DRI conversion view ($/t)
# ─────────────────────────────────────────────────────────────────────────────


DRI_CONVERSION_EXPECTED = {
    "EZDK": {
        "material_price_usd_t":           154.84,
        "mrmr_effect_usd_t":               72.77,
        "other_conversion_cost_usd_t":     57.62,
        "total_conversion_cost_usd_t":    130.39,
        "total_variable_mfg_cost_usd_t":  285.23,
    },
    "ERM": {
        "material_price_usd_t":           174.31,
        "mrmr_effect_usd_t":               74.95,
        "other_conversion_cost_usd_t":     58.68,
        "total_conversion_cost_usd_t":    133.63,
        "total_variable_mfg_cost_usd_t":  307.94,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Test classes
# ─────────────────────────────────────────────────────────────────────────────


class TestStage1DRI_Detailed:
    """Verification §1.2 — DRI detailed (LE/t)."""

    @pytest.mark.parametrize("company", ["EZDK", "ERM"])
    def test_currency_tag(self, state, company):
        out = cost_engine.compute_dri_detailed(state, company)
        assert out["_currency"] == "EGP"

    @pytest.mark.parametrize(
        "company,key,expected",
        [(c, k, v) for c, cells in DRI_DETAILED_EXPECTED.items() for k, v in cells.items()],
    )
    def test_cell(self, state, company, key, expected):
        out = cost_engine.compute_dri_detailed(state, company)
        _assert_le_int(out[key], expected)


class TestStage1DRI_Conversion:
    """Verification §1.3 — DRI conversion view ($/t)."""

    @pytest.mark.parametrize("company", ["EZDK", "ERM"])
    def test_currency_tag(self, state, company):
        out = cost_engine.compute_dri_conversion(state, company)
        assert out["_currency"] == "USD"

    @pytest.mark.parametrize(
        "company,key,expected",
        [(c, k, v) for c, cells in DRI_CONVERSION_EXPECTED.items() for k, v in cells.items()],
    )
    def test_cell(self, state, company, key, expected):
        out = cost_engine.compute_dri_conversion(state, company)
        _assert_usd_2dp(out[key], expected)
