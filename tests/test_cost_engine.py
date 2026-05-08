"""Cell-for-cell verification of cost_engine.py against model_verification.md."""

from __future__ import annotations

from cost_engine import compute_dri_conversion, compute_dri_detailed


# Tolerance helpers ----------------------------------------------------------


def _le_close(actual: float, target_int: int) -> bool:
    """Integer LE/t: ±1 cumulative-rounding-drift tolerance per brief §6."""
    return abs(round(actual) - target_int) <= 1


def _usd_close(actual: float, target_2dp: float) -> bool:
    """USD/t to 2 dp: ±0.01 tolerance after rounding per brief §6."""
    return abs(round(actual, 2) - target_2dp) <= 0.01


# ---------------------------------------------------------------------------
# §1.2 — DRI Detailed (LE/t)
# ---------------------------------------------------------------------------


class TestStage1DRI_Detailed:

    # EZDK rows ------------------------------------------------------------

    def test_ezdk_iop_cost(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["iop_cost"], 3624)

    def test_ezdk_electricity(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["electricity"], 38)

    def test_ezdk_natural_gas(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["natural_gas"], 772)

    def test_ezdk_oxygen(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["oxygen"], 0)

    def test_ezdk_nitrogen(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["nitrogen"], 16)

    def test_ezdk_water(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["water"], 5)

    def test_ezdk_chemicals(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["chemicals"], 25)

    def test_ezdk_spare_parts(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["spare_parts"], 0)

    def test_ezdk_external_services(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["external_services"], 43)

    def test_ezdk_other(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["other"], 20)

    def test_ezdk_variable_cost(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["variable_cost"], 4541)

    def test_ezdk_labor(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["labor"], 351)

    def test_ezdk_depreciation(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["depreciation"], 1559)

    def test_ezdk_other_fixed(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["other_fixed"], 353)

    def test_ezdk_fixed_cost(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["fixed_cost"], 2264)

    def test_ezdk_manuf_cost(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["manuf_cost"], 6805)

    def test_ezdk_selling_price(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["selling_price"], 6465)

    def test_ezdk_gross_margin(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert _le_close(out["gross_margin"], -339)

    def test_ezdk_currency_tag(self, state):
        out = compute_dri_detailed(state, "EZDK")
        assert out["_currency"] == "EGP"

    # ERM rows -------------------------------------------------------------

    def test_erm_iop_cost(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["iop_cost"], 3968)

    def test_erm_electricity(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["electricity"], 25)

    def test_erm_natural_gas(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["natural_gas"], 852)

    def test_erm_oxygen(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["oxygen"], 0)

    def test_erm_nitrogen(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["nitrogen"], 10)

    def test_erm_water(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["water"], 5)

    def test_erm_chemicals(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["chemicals"], 16)

    def test_erm_spare_parts(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["spare_parts"], 0)

    def test_erm_external_services(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["external_services"], 27)

    def test_erm_other(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["other"], 0)

    def test_erm_variable_cost(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["variable_cost"], 4902)

    def test_erm_labor(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["labor"], 785)

    def test_erm_depreciation(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["depreciation"], 3484)

    def test_erm_other_fixed(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["other_fixed"], 788)

    def test_erm_fixed_cost(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["fixed_cost"], 5057)

    def test_erm_manuf_cost(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["manuf_cost"], 9959)

    def test_erm_selling_price(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["selling_price"], 6465)

    def test_erm_gross_margin(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert _le_close(out["gross_margin"], -3494)

    def test_erm_currency_tag(self, state):
        out = compute_dri_detailed(state, "ERM")
        assert out["_currency"] == "EGP"


# ---------------------------------------------------------------------------
# §1.3 — DRI Conversion-Cost View ($/t)
# ---------------------------------------------------------------------------


class TestStage1DRI_Conversion:

    def test_ezdk_material_price(self, state):
        out = compute_dri_conversion(state, "EZDK")
        assert _usd_close(out["material_price"], 154.84)

    def test_ezdk_mrmr_effect(self, state):
        out = compute_dri_conversion(state, "EZDK")
        assert _usd_close(out["mrmr_effect"], 72.77)

    def test_ezdk_other_conversion(self, state):
        out = compute_dri_conversion(state, "EZDK")
        assert _usd_close(out["other_conversion"], 57.62)

    def test_ezdk_total_conversion(self, state):
        out = compute_dri_conversion(state, "EZDK")
        assert _usd_close(out["total_conversion"], 130.39)

    def test_ezdk_total_variable_mfg(self, state):
        out = compute_dri_conversion(state, "EZDK")
        assert _usd_close(out["total_variable_mfg"], 285.23)

    def test_ezdk_currency_tag(self, state):
        out = compute_dri_conversion(state, "EZDK")
        assert out["_currency"] == "USD"

    def test_erm_material_price(self, state):
        out = compute_dri_conversion(state, "ERM")
        assert _usd_close(out["material_price"], 174.31)

    def test_erm_mrmr_effect(self, state):
        out = compute_dri_conversion(state, "ERM")
        assert _usd_close(out["mrmr_effect"], 74.95)

    def test_erm_other_conversion(self, state):
        out = compute_dri_conversion(state, "ERM")
        assert _usd_close(out["other_conversion"], 58.68)

    def test_erm_total_conversion(self, state):
        out = compute_dri_conversion(state, "ERM")
        assert _usd_close(out["total_conversion"], 133.63)

    def test_erm_total_variable_mfg(self, state):
        out = compute_dri_conversion(state, "ERM")
        assert _usd_close(out["total_variable_mfg"], 307.94)

    def test_erm_currency_tag(self, state):
        out = compute_dri_conversion(state, "ERM")
        assert out["_currency"] == "USD"
