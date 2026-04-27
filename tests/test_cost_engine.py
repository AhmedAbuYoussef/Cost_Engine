"""Tests for cost_engine — every assertion is grounded in model_verification.md."""

from __future__ import annotations

import pytest

from cost_engine import compute_dri_detailed, compute_dri_conversion


# Tolerances per Step 1 brief §6.
TOL_USD_PER_T = 0.01    # USD/t values displayed to 2 dp
TOL_LE_PER_T_INT = 1    # LE/t values displayed as integers; allow ±1 for cumulative drift


def _approx_int(value: float, expected: int, tol: int = TOL_LE_PER_T_INT) -> None:
    assert abs(round(value) - expected) <= tol, f"{round(value)} vs {expected}"


def _approx_2dp(value: float, expected: float, tol: float = TOL_USD_PER_T) -> None:
    assert abs(round(value, 2) - expected) <= tol, f"{round(value, 2)} vs {expected}"


# ---------------------------------------------------------------------------
# Verification §1.2 — DRI Detailed (LE/t)
# ---------------------------------------------------------------------------

class TestStage1DRI_Detailed:
    """Cell-for-cell against verification §1.2 (LE/t)."""

    def test_currency_tag(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert out["_currency"] == "EGP"

    # ----- EZDK column -----
    def test_ezdk_iop_cost(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["iop_cost"], 3624)

    def test_ezdk_electricity(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["Electricity"], 38)

    def test_ezdk_natural_gas(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["Natural Gas"], 772)

    def test_ezdk_oxygen(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["Oxygen"], 0)

    def test_ezdk_nitrogen(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["Nitrogen"], 16)

    def test_ezdk_water(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["Water"], 5)

    def test_ezdk_chemicals(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["Chemicals"], 25)

    def test_ezdk_spare_parts(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["Spare Parts"], 0)

    def test_ezdk_external_services(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["External Services"], 43)

    def test_ezdk_other(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["items"]["Other"], 20)

    def test_ezdk_variable_cost(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["variable_cost"], 4541)

    def test_ezdk_labor(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["labor"], 351)

    def test_ezdk_depreciation(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["depreciation"], 1559)

    def test_ezdk_other_fixed(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["other_fixed"], 353)

    def test_ezdk_fixed_cost(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["fixed_cost"], 2264)

    def test_ezdk_manufacturing_cost(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["manufacturing_cost"], 6805)

    def test_ezdk_selling_price(self, state):
        _approx_int(compute_dri_detailed(state, "EZDK")["selling_price"], 6465)

    def test_ezdk_gross_margin(self, state):
        # Verification shows (339); formula: 6465 - 6805 = -340. Within ±1 LE drift.
        _approx_int(compute_dri_detailed(state, "EZDK")["gross_margin"], -339)

    # ----- ERM column -----
    def test_erm_iop_cost(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["iop_cost"], 3968)

    def test_erm_electricity(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["Electricity"], 25)

    def test_erm_natural_gas(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["Natural Gas"], 852)

    def test_erm_oxygen(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["Oxygen"], 0)

    def test_erm_nitrogen(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["Nitrogen"], 10)

    def test_erm_water(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["Water"], 5)

    def test_erm_chemicals(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["Chemicals"], 16)

    def test_erm_spare_parts(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["Spare Parts"], 0)

    def test_erm_external_services(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["External Services"], 27)

    def test_erm_other(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["items"]["Other"], 0)

    def test_erm_variable_cost(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["variable_cost"], 4902)

    def test_erm_labor(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["labor"], 785)

    def test_erm_depreciation(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["depreciation"], 3484)

    def test_erm_other_fixed(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["other_fixed"], 788)

    def test_erm_fixed_cost(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["fixed_cost"], 5057)

    def test_erm_manufacturing_cost(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["manufacturing_cost"], 9959)

    def test_erm_selling_price(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["selling_price"], 6465)

    def test_erm_gross_margin(self, state):
        _approx_int(compute_dri_detailed(state, "ERM")["gross_margin"], -3494)


# ---------------------------------------------------------------------------
# Verification §1.3 — DRI Conversion ($/t)
# ---------------------------------------------------------------------------

class TestStage1DRI_Conversion:
    """Cell-for-cell against verification §1.3 ($/t)."""

    def test_currency_tag(self, state):
        out = compute_dri_conversion(state, "EZDK")
        assert out["_currency"] == "USD"

    def test_ezdk_material_price(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["material_price"], 154.84)

    def test_ezdk_mrmr_effect(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["mrmr_effect"], 72.77)

    def test_ezdk_other_conversion(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["other_conversion_cost"], 57.62)

    def test_ezdk_total_conversion(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["total_conversion_cost"], 130.39)

    def test_ezdk_total_variable_mfg_cost(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["total_variable_mfg_cost"], 285.23)

    def test_erm_material_price(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["material_price"], 174.31)

    def test_erm_mrmr_effect(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["mrmr_effect"], 74.95)

    def test_erm_other_conversion(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["other_conversion_cost"], 58.68)

    def test_erm_total_conversion(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["total_conversion_cost"], 133.63)

    def test_erm_total_variable_mfg_cost(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["total_variable_mfg_cost"], 307.94)


# ---------------------------------------------------------------------------
# Strict-field-access guardrail
# ---------------------------------------------------------------------------

class TestStrictFieldAccess:
    """Engine must raise on missing fields rather than default silently."""

    def test_dri_detailed_raises_on_unknown_company(self, state):
        with pytest.raises(Exception):
            compute_dri_detailed(state, "Acme")

    def test_dri_detailed_raises_on_non_producer(self, state):
        with pytest.raises(Exception):
            compute_dri_detailed(state, "EFS")  # EFS does not produce DRI
