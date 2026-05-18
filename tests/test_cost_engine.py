"""Cell-for-cell verification of cost_engine.py against model_verification.md."""

from __future__ import annotations

import pytest

from cost_engine import (
    StructuralNonExistence,
    _bccm_variable_cost_per_ton_billet,
    _billet_material_price_summary,
    _billet_yield_effect,
    _check_blending_ratios_sum,
    _eaf_byproduct_credit_per_ton_ms,
    _eaf_conversion_cost_per_ton_ms,
    _eaf_material_cost_per_ton_ms,
    _eaf_variable_cost_per_ton_ms,
    _intercompany_billet_price,
    _market_billet_price,
    _resolve_dri_price_for_buyer,
    compute_billet_conversion,
    compute_billet_detailed,
    compute_dri_conversion,
    compute_dri_detailed,
    compute_tradeoff_matrix,
)


# Tolerance helpers ----------------------------------------------------------


def _le_close(actual: float, target_int: int) -> bool:
    """Integer LE/t: ±1 cumulative-rounding-drift tolerance per brief §6."""
    return abs(round(actual) - target_int) <= 1


def _usd_close(actual: float, target_2dp: float) -> bool:
    """USD/t to 2 dp: ±0.01 tolerance after rounding per brief §6.

    The ``+ 1e-9`` epsilon absorbs IEEE-754 representation artifacts in the
    boundary case (e.g., ``abs(round(263.2195, 2) - 263.21)`` evaluates to
    ``0.010000000000019327``, not exactly ``0.01``). The mathematical
    tolerance remains 0.01.
    """
    return abs(round(actual, 2) - target_2dp) <= 0.01 + 1e-9


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


# ---------------------------------------------------------------------------
# Stage 2 — Billet helper smoke tests (Step 2a)
# Wide tolerances — tight verification is Step 2b.
# ---------------------------------------------------------------------------


class TestStage2BilletHelpers:

    def test_resolve_dri_price_ezdk(self, state):
        price = _resolve_dri_price_for_buyer(state, "EZDK")
        assert abs(price - 285.23) <= 0.5

    def test_resolve_dri_price_efs(self, state):
        price = _resolve_dri_price_for_buyer(state, "EFS")
        assert abs(price - 307.94) <= 0.5

    def test_resolve_dri_price_esr(self, state):
        price = _resolve_dri_price_for_buyer(state, "ESR")
        assert abs(price - 315.48) <= 0.5

    def test_eaf_pipeline_ezdk(self, state):
        b = state["billet"]["EZDK"]
        prices = b["eaf_unit_prices_usd"]
        cons = b["eaf_consumptions_per_ton_ms"]
        eaf_yield = b["yields"]["eaf"]

        dri_price = _resolve_dri_price_for_buyer(state, "EZDK")
        material = _eaf_material_cost_per_ton_ms(
            b["blending_pct"], prices, eaf_yield, dri_price
        )
        byproduct = _eaf_byproduct_credit_per_ton_ms(
            cons["byproduct_pct_of_sc"], prices["byproduct_t"], eaf_yield
        )
        conversion = _eaf_conversion_cost_per_ton_ms(cons, prices)
        ms_vc = _eaf_variable_cost_per_ton_ms(material, byproduct, conversion)

        assert 300 < ms_vc < 500, (
            f"EAF MS VC out of bounds: {ms_vc:.2f} (material={material:.2f}, "
            f"byproduct={byproduct:.2f}, conversion={conversion:.2f})"
        )

    def test_bccm_pipeline_ezdk(self, state):
        b = state["billet"]["EZDK"]
        eaf_prices = b["eaf_unit_prices_usd"]
        eaf_cons = b["eaf_consumptions_per_ton_ms"]
        eaf_yield = b["yields"]["eaf"]
        ccp_yield = b["yields"]["ccp"]

        dri_price = _resolve_dri_price_for_buyer(state, "EZDK")
        material = _eaf_material_cost_per_ton_ms(
            b["blending_pct"], eaf_prices, eaf_yield, dri_price
        )
        byproduct = _eaf_byproduct_credit_per_ton_ms(
            eaf_cons["byproduct_pct_of_sc"], eaf_prices["byproduct_t"], eaf_yield
        )
        conversion = _eaf_conversion_cost_per_ton_ms(eaf_cons, eaf_prices)
        ms_vc = _eaf_variable_cost_per_ton_ms(material, byproduct, conversion)

        billet_vc = _bccm_variable_cost_per_ton_billet(
            ms_vc,
            ccp_yield,
            b["bccm_consumptions_per_ton_billet"],
            b["bccm_unit_prices_usd"],
        )
        assert 350 < billet_vc < 550, f"Billet VC out of bounds: {billet_vc:.2f}"

    def test_billet_material_summary_ezdk(self, state):
        b = state["billet"]["EZDK"]
        prices = b["eaf_unit_prices_usd"]
        dri_price = _resolve_dri_price_for_buyer(state, "EZDK")
        summary = _billet_material_price_summary(
            b["blending_pct"], dri_price, prices["local_scrap_t"], prices["imported_scrap_t"]
        )
        assert abs(summary - 263.21) <= 0.5

    def test_billet_yield_effect_realistic(self):
        ye = _billet_yield_effect(263.21, 0.8599, 0.9877)
        assert abs(ye - 46.70) <= 0.5

    def test_intercompany_billet_price(self):
        price = _intercompany_billet_price(409.52, 1.169)
        assert abs(price - 478.7) <= 0.1


# ---------------------------------------------------------------------------
# §2.2 — Billet Conversion-Cost View ($/t), EZDK only (Step 2b)
# ---------------------------------------------------------------------------


class TestStage2Billet_Conversion:

    def test_ezdk_material_price(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert _usd_close(out["material_price"], 263.21)

    def test_ezdk_yield_effect(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert _usd_close(out["yield_effect"], 46.70)

    def test_ezdk_other_conversion(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert _usd_close(out["other_conversion"], 99.61)

    def test_ezdk_total_conversion(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert _usd_close(out["total_conversion"], 146.31)

    def test_ezdk_total_variable_mfg(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert _usd_close(out["total_variable_mfg"], 409.52)

    def test_ezdk_currency_tag(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert out["_currency"] == "USD"

    def test_ezdk_detailed_currency_tag(self, state):
        out = compute_billet_detailed(state, "EZDK")
        assert out["_currency"] == "USD"

    # Reconciliation-residual tests --------------------------------------

    def test_ezdk_residual_value_frozen(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert out["_reconciliation_residual_usd_per_ton"] == 0.48

    def test_ezdk_total_variable_mfg_computed(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert _usd_close(out["total_variable_mfg_computed"], 409.04)

    def test_ezdk_total_equals_computed_plus_residual(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert (
            out["total_variable_mfg"]
            == out["total_variable_mfg_computed"]
            + out["_reconciliation_residual_usd_per_ton"]
        )

    def test_ezdk_reconciliation_note_present(self, state):
        out = compute_billet_conversion(state, "EZDK")
        note = out.get("_reconciliation_note")
        assert isinstance(note, str) and note
        assert "§13" in note

    def test_reconciliation_residual_only_for_ezdk_billet(self, state):
        rec = state.get("reconciliation", {})
        assert set(rec.keys()) == {"billet"}
        assert set(rec["billet"].keys()) == {"EZDK"}

    # EFS rows (verification §2.2) ---------------------------------------

    def test_efs_material_price(self, state):
        out = compute_billet_conversion(state, "EFS")
        assert _usd_close(out["material_price"], 299.98)

    def test_efs_yield_effect(self, state):
        out = compute_billet_conversion(state, "EFS")
        assert _usd_close(out["yield_effect"], 60.72)

    def test_efs_other_conversion(self, state):
        out = compute_billet_conversion(state, "EFS")
        assert _usd_close(out["other_conversion"], 107.26)

    def test_efs_total_variable_mfg(self, state):
        out = compute_billet_conversion(state, "EFS")
        assert _usd_close(out["total_variable_mfg"], 467.96)

    def test_efs_no_residual(self, state):
        out = compute_billet_conversion(state, "EFS")
        assert out["_reconciliation_residual_usd_per_ton"] == 0

    def test_efs_reconstructed_dummies_flag(self, state):
        assert state["billet"]["EFS"]["_reconstructed_dummies"] is True
        out = compute_billet_conversion(state, "EFS")
        assert out.get("_reconstructed_dummies") is True

    # ESR rows (verification §2.2) ---------------------------------------

    def test_esr_material_price(self, state):
        out = compute_billet_conversion(state, "ESR")
        assert _usd_close(out["material_price"], 303.15)

    def test_esr_yield_effect(self, state):
        out = compute_billet_conversion(state, "ESR")
        assert _usd_close(out["yield_effect"], 49.19)

    def test_esr_other_conversion(self, state):
        out = compute_billet_conversion(state, "ESR")
        assert _usd_close(out["other_conversion"], 97.97)

    def test_esr_total_variable_mfg(self, state):
        out = compute_billet_conversion(state, "ESR")
        assert _usd_close(out["total_variable_mfg"], 450.31)

    def test_esr_no_residual(self, state):
        out = compute_billet_conversion(state, "ESR")
        assert out["_reconciliation_residual_usd_per_ton"] == 0

    def test_esr_reconstructed_dummies_flag(self, state):
        assert state["billet"]["ESR"]["_reconstructed_dummies"] is True
        out = compute_billet_conversion(state, "ESR")
        assert out.get("_reconstructed_dummies") is True

    # ERM does not produce billet ----------------------------------------

    def test_erm_billet_conversion_raises(self, state):
        with pytest.raises(StructuralNonExistence):
            compute_billet_conversion(state, "ERM")


# ---------------------------------------------------------------------------
# Market Billet Build-up (verification §2.4)
# ---------------------------------------------------------------------------


class TestStage2MarketBilletBuildup:

    def test_market_base(self, state):
        assert state["billet"]["market"]["components_usd_t"]["base"] == 428

    def test_market_safe_guards(self, state):
        assert state["billet"]["market"]["components_usd_t"]["safe_guards"] == 74

    def test_market_other_costs(self, state):
        assert state["billet"]["market"]["components_usd_t"]["other_costs"] == 88

    def test_market_total(self, state):
        assert _market_billet_price(state) == 590


# ---------------------------------------------------------------------------
# Trade-off Matrix (verification §2.3)
# ---------------------------------------------------------------------------


class TestStage2TradeoffMatrix:

    # Source-own intercompany sell prices (the "Price" column) ----------

    def test_ezdk_intercompany_price(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EZDK"]["price"], 478.73)

    def test_efs_intercompany_price(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EFS"]["price"], 475.45)

    def test_esr_intercompany_price(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["ESR"]["price"], 457.97)

    def test_market_intercompany_price(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["Market"]["price"], 590.00)

    # 16 source × buyer cells -------------------------------------------

    def test_ezdk_to_ezdk(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EZDK"]["to_EZDK"], 409.52)

    def test_ezdk_to_efs(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EZDK"]["to_EFS"], 478.73)

    def test_ezdk_to_erm(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EZDK"]["to_ERM"], 478.73)

    def test_ezdk_to_esr(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EZDK"]["to_ESR"], 478.73)

    def test_efs_to_ezdk(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EFS"]["to_EZDK"], 475.45)

    def test_efs_to_efs(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EFS"]["to_EFS"], 467.96)

    def test_efs_to_erm(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EFS"]["to_ERM"], 475.45)

    def test_efs_to_esr(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["EFS"]["to_ESR"], 475.45)

    def test_esr_to_ezdk(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["ESR"]["to_EZDK"], 457.97)

    def test_esr_to_efs(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["ESR"]["to_EFS"], 457.97)

    def test_esr_to_erm(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["ESR"]["to_ERM"], 457.97)

    def test_esr_to_esr(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["ESR"]["to_ESR"], 450.31)

    def test_market_to_ezdk(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["Market"]["to_EZDK"], 590.00)

    def test_market_to_efs(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["Market"]["to_EFS"], 590.00)

    def test_market_to_erm(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["Market"]["to_ERM"], 590.00)

    def test_market_to_esr(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["sources"]["Market"]["to_ESR"], 590.00)

    # Per-buyer minimums ------------------------------------------------

    def test_min_to_ezdk(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["minimum"]["EZDK"], 409.52)

    def test_min_to_efs(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["minimum"]["EFS"], 457.97)

    def test_min_to_erm(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["minimum"]["ERM"], 457.97)

    def test_min_to_esr(self, state):
        m = compute_tradeoff_matrix(state)
        assert _usd_close(m["minimum"]["ESR"], 450.31)

    # Structural assertions ---------------------------------------------

    def test_matrix_no_erm_source_row(self, state):
        m = compute_tradeoff_matrix(state)
        assert "ERM" not in m["sources"]

    def test_matrix_currency_tag(self, state):
        m = compute_tradeoff_matrix(state)
        assert m["_currency"] == "USD"

    def test_matrix_uses_residual_included_billet_vc(self, state):
        m = compute_tradeoff_matrix(state)
        # Derive seller VC back from the intercompany price.
        derived_vc = m["sources"]["EZDK"]["price"] / 1.169
        # Should match residual-included 409.52, not computed-only 409.04.
        assert abs(derived_vc - 409.52) <= 0.01
        assert abs(derived_vc - 409.04) > 0.4


# ---------------------------------------------------------------------------
# Integrity check 2 — blending ratios sum (Step 2b)
# ---------------------------------------------------------------------------


class TestIntegrityChecks_HappyPath:

    def test_check2_blending_ratios_sum(self, state):
        passed, detail = _check_blending_ratios_sum(state)
        assert passed, detail


class TestIntegrityChecks_Violations:

    def test_check2_blending_ratios_sum_fails(self, state_copy):
        state_copy["billet"]["EZDK"]["blending_pct"]["dri"] = 0.65
        passed, detail = _check_blending_ratios_sum(state_copy)
        assert not passed
        assert "EZDK" in detail
