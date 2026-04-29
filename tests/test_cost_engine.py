"""Tests for cost_engine — every assertion is grounded in model_verification.md."""

from __future__ import annotations

import pytest

import copy

from cost_engine import (
    compute_dri_detailed,
    compute_dri_conversion,
    compute_billet_detailed,
    compute_billet_conversion,
    compute_tradeoff_matrix,
    _market_billet_price,
    compute_finished_sc1,
    compute_finished_sc2,
    compute_hrc_summary,
    compute_all,
    run_integrity_checks,
    IntegrityError,
    _check_fixed_distribution_sums,
    _check_blending_ratios_sum,
    _check_sales_drive_production,
    _check_currency_consistency,
    _long_line_cascade,
    _flat_line_cascade,
    _erm_dri_supply_aggregation,
    compute_production_cascade,
    compute_sales_summary,
    compute_market_share,
)


# Tolerances per Step 1 brief §6.
TOL_USD_PER_T = 0.01    # USD/t values displayed to 2 dp
TOL_LE_PER_T_INT = 1    # LE/t values displayed as integers; allow ±1 for cumulative drift

# Widened tolerance for USD/t cells that aggregate sums of LE/t conversion items
# whose source consumptions are stored at 1 dp in model_initial_state.json while
# the Excel model carries finer precision. Rulebook §13 already documents this
# data gap. See TESTING_NOTES.md "Tolerance widening — DRI conversion view".
# Tighten back to ±0.01 once real consumption decimals replace the dummies.
TOL_USD_PER_T_LE_AGGREGATE = 0.10


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
    """Cell-for-cell against verification §1.3 ($/t).

    Material Price and MRMR Effect are computed directly from
    `iop_landed_usd_ton` and `mrmr` and assert at the strict 0.01 tolerance.

    Other Conversion / Total Conversion / Total VC aggregate the nine LE/t
    conversion items and divide by FX. The JSON stores consumptions at 1 dp
    while the Excel model carried finer precision, producing a bounded
    cumulative drift of up to ~0.05 USD/t against the verification numbers.
    Rulebook §13 documents this as a known data gap (back-calculated dummies
    for ERM Nitrogen/Water; analogous issue for EZDK). The engine keeps full
    precision per brief §5 — we widen the tolerance to ±0.10 on the six
    affected cells and tighten back to ±0.01 once real consumption decimals
    replace the dummies. Tracked in TESTING_NOTES.md.
    """

    def test_currency_tag(self, state):
        out = compute_dri_conversion(state, "EZDK")
        assert out["_currency"] == "USD"

    def test_ezdk_material_price(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["material_price"], 154.84)

    def test_ezdk_mrmr_effect(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["mrmr_effect"], 72.77)

    def test_ezdk_other_conversion(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["other_conversion_cost"],
                    57.62, tol=TOL_USD_PER_T_LE_AGGREGATE)

    def test_ezdk_total_conversion(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["total_conversion_cost"],
                    130.39, tol=TOL_USD_PER_T_LE_AGGREGATE)

    def test_ezdk_total_variable_mfg_cost(self, state):
        _approx_2dp(compute_dri_conversion(state, "EZDK")["total_variable_mfg_cost"],
                    285.23, tol=TOL_USD_PER_T_LE_AGGREGATE)

    def test_erm_material_price(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["material_price"], 174.31)

    def test_erm_mrmr_effect(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["mrmr_effect"], 74.95)

    def test_erm_other_conversion(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["other_conversion_cost"],
                    58.68, tol=TOL_USD_PER_T_LE_AGGREGATE)

    def test_erm_total_conversion(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["total_conversion_cost"],
                    133.63, tol=TOL_USD_PER_T_LE_AGGREGATE)

    def test_erm_total_variable_mfg_cost(self, state):
        _approx_2dp(compute_dri_conversion(state, "ERM")["total_variable_mfg_cost"],
                    307.94, tol=TOL_USD_PER_T_LE_AGGREGATE)


# ---------------------------------------------------------------------------
# Strict-field-access guardrail
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Verification §2.2 — Billet Conversion ($/t)
# ---------------------------------------------------------------------------

# Material Price and Yield Effect are direct functions of headline blending,
# yields, and unit prices and stay at the strict ±0.10 tolerance.
#
# Other Conversion / Total Conversion / Total VC aggregate ~11 EAF + ~8 BCCM
# conversion items where the JSON stores consumption decimals at 1–3 dp
# precision while the Excel model carried finer underlying precision. The
# resulting cumulative drift is bounded by:
#     19_items × 0.025_per_item / ccp_yield × max_tradeoff_ratio
#       ≈ 19 × 0.025 / 0.9877 × 1.169
#       ≈ 0.56 USD/t
# Rounded up to ±0.60 for headroom. Applies to the §2.2 aggregating cells
# and the §2.3 trade-off matrix entries (which inherit this drift through
# `own_vc × tradeoff_ratio`). Tightens back to ±0.10 once real-precision
# consumption decimals replace the JSON values. See TESTING_NOTES.md.
TOL_BILLET_HEADLINE = 0.10
TOL_BILLET_AGGREGATE = 0.60


class TestStage2Billet_Conversion:

    def test_currency_tag(self, state):
        out = compute_billet_conversion(state, "EZDK")
        assert out["_currency"] == "USD"

    def test_ezdk_material_price(self, state):
        _approx_2dp(compute_billet_conversion(state, "EZDK")["material_price"], 263.21, TOL_BILLET_HEADLINE)

    def test_ezdk_yield_effect(self, state):
        _approx_2dp(compute_billet_conversion(state, "EZDK")["yield_effect"], 46.70, TOL_BILLET_HEADLINE)

    def test_ezdk_other_conversion(self, state):
        _approx_2dp(compute_billet_conversion(state, "EZDK")["other_conversion_cost"], 99.61, TOL_BILLET_AGGREGATE)

    def test_ezdk_total_conversion(self, state):
        _approx_2dp(compute_billet_conversion(state, "EZDK")["total_conversion_cost"], 146.31, TOL_BILLET_AGGREGATE)

    def test_ezdk_total_variable_mfg_cost(self, state):
        _approx_2dp(compute_billet_conversion(state, "EZDK")["total_variable_mfg_cost"], 409.52, TOL_BILLET_AGGREGATE)

    def test_efs_material_price(self, state):
        _approx_2dp(compute_billet_conversion(state, "EFS")["material_price"], 299.98, TOL_BILLET_HEADLINE)

    def test_efs_yield_effect(self, state):
        _approx_2dp(compute_billet_conversion(state, "EFS")["yield_effect"], 60.72, TOL_BILLET_HEADLINE)

    def test_efs_total_variable_mfg_cost(self, state):
        _approx_2dp(compute_billet_conversion(state, "EFS")["total_variable_mfg_cost"], 467.96, TOL_BILLET_AGGREGATE)

    def test_esr_material_price(self, state):
        _approx_2dp(compute_billet_conversion(state, "ESR")["material_price"], 303.15, TOL_BILLET_HEADLINE)

    def test_esr_yield_effect(self, state):
        _approx_2dp(compute_billet_conversion(state, "ESR")["yield_effect"], 49.19, TOL_BILLET_HEADLINE)

    def test_esr_total_variable_mfg_cost(self, state):
        _approx_2dp(compute_billet_conversion(state, "ESR")["total_variable_mfg_cost"], 450.31, TOL_BILLET_AGGREGATE)

    def test_efs_carries_dummy_warning(self, state):
        out = compute_billet_conversion(state, "EFS")
        assert "warning" in out and "reconstructed dummies" in out["warning"]

    def test_esr_carries_dummy_warning(self, state):
        out = compute_billet_conversion(state, "ESR")
        assert "warning" in out and "reconstructed dummies" in out["warning"]

    def test_ezdk_no_dummy_warning(self, state):
        # EZDK has real data; no dummy warning expected.
        assert "warning" not in compute_billet_conversion(state, "EZDK")

    def test_ezdk_residual_is_zero(self, state):
        # Regression anchor: EZDK has real data; residual must stay 0.
        assert state["billet"]["EZDK"]["_reconciliation_residual_usd_per_ton"] == 0.0


# ---------------------------------------------------------------------------
# Verification §2.3 — Trade-off Matrix
# ---------------------------------------------------------------------------

class TestStage2TradeoffMatrix:

    def test_ezdk_external_offer(self, state):
        m = compute_tradeoff_matrix(state)
        _approx_2dp(m["rows"]["EZDK"]["price_external_usd_t"], 478.73, TOL_BILLET_AGGREGATE)

    def test_efs_external_offer(self, state):
        m = compute_tradeoff_matrix(state)
        _approx_2dp(m["rows"]["EFS"]["price_external_usd_t"], 475.45, TOL_BILLET_AGGREGATE)

    def test_esr_external_offer(self, state):
        m = compute_tradeoff_matrix(state)
        _approx_2dp(m["rows"]["ESR"]["price_external_usd_t"], 457.97, TOL_BILLET_AGGREGATE)

    def test_market_offer(self, state):
        m = compute_tradeoff_matrix(state)
        assert m["rows"]["Market"]["price_external_usd_t"] == 590.00

    def test_diagonal_ezdk(self, state):
        m = compute_tradeoff_matrix(state)
        _approx_2dp(m["rows"]["EZDK"]["to"]["EZDK"], 409.52, TOL_BILLET_AGGREGATE)

    def test_diagonal_efs(self, state):
        m = compute_tradeoff_matrix(state)
        _approx_2dp(m["rows"]["EFS"]["to"]["EFS"], 467.96, TOL_BILLET_AGGREGATE)

    def test_diagonal_esr(self, state):
        m = compute_tradeoff_matrix(state)
        _approx_2dp(m["rows"]["ESR"]["to"]["ESR"], 450.31, TOL_BILLET_AGGREGATE)

    def test_offdiagonal_ezdk_to_efs(self, state):
        m = compute_tradeoff_matrix(state)
        _approx_2dp(m["rows"]["EZDK"]["to"]["EFS"], 478.73, TOL_BILLET_AGGREGATE)

    def test_offdiagonal_esr_to_efs(self, state):
        m = compute_tradeoff_matrix(state)
        _approx_2dp(m["rows"]["ESR"]["to"]["EFS"], 457.97, TOL_BILLET_AGGREGATE)

    def test_minimum_to_ezdk(self, state):
        _approx_2dp(compute_tradeoff_matrix(state)["minima"]["EZDK"], 409.52, TOL_BILLET_AGGREGATE)

    def test_minimum_to_efs(self, state):
        _approx_2dp(compute_tradeoff_matrix(state)["minima"]["EFS"], 457.97, TOL_BILLET_AGGREGATE)

    def test_minimum_to_erm(self, state):
        _approx_2dp(compute_tradeoff_matrix(state)["minima"]["ERM"], 457.97, TOL_BILLET_AGGREGATE)

    def test_minimum_to_esr(self, state):
        _approx_2dp(compute_tradeoff_matrix(state)["minima"]["ESR"], 450.31, TOL_BILLET_AGGREGATE)


# ---------------------------------------------------------------------------
# Verification §2.4 — Market Billet Build-up
# ---------------------------------------------------------------------------

class TestStage2MarketBilletBuildup:

    def test_base(self, state):
        assert _market_billet_price(state)["base"] == 428

    def test_safe_guards(self, state):
        assert _market_billet_price(state)["safe_guards"] == 74

    def test_other_costs(self, state):
        assert _market_billet_price(state)["other_costs"] == 88

    def test_market_price(self, state):
        assert _market_billet_price(state)["market_price"] == 590


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

    def test_billet_raises_on_non_producer(self, state):
        with pytest.raises(Exception):
            compute_billet_conversion(state, "ERM")  # ERM does not produce billet


# ---------------------------------------------------------------------------
# Verification §3.1 — Rebar (Sc1 + Sc2, all four companies)
# ---------------------------------------------------------------------------

# Long-line Sc1 Total VC inherits billet drift (own_VC carries up to ±0.45 for
# EZDK after the JSON-precision widening) and adds the long-line own-conversion
# drift (~5 items × 0.025 ≈ 0.13 USD/t). The bound is roughly:
#     billet_drift × (1 + 1/yield_amplification) + finishing_drift
#       ≈ 0.45 × 1.06 + 0.15  ≈  0.63 USD/t
# We use ±0.80 for Sc1 Total VC. Sc2 cuts the billet-drift inheritance
# (Material is fixed at $590), so Sc2 Total VC is bounded at ±0.20.
# Material/Yield/HomeScrap/OtherConv (line items) stay at ±0.10.
TOL_FINISHED_HEADLINE = 0.10
TOL_FINISHED_TOTAL_CONVERSION = 0.15  # = yield_effect_drift + home_scrap_drift + other_conv_drift
TOL_FINISHED_SC1_TOTAL = 0.80
TOL_FINISHED_SC2_TOTAL = 0.20


class TestStage3Rebar_Sc1:

    def test_currency_tag(self, state):
        assert compute_finished_sc1(state, "EZDK", "Rebar")["_currency"] == "USD"

    def test_ezdk_material_price(self, state):
        _approx_2dp(compute_finished_sc1(state, "EZDK", "Rebar")["material_price"], 409.52, TOL_FINISHED_SC1_TOTAL)

    def test_ezdk_yield_effect(self, state):
        _approx_2dp(compute_finished_sc1(state, "EZDK", "Rebar")["yield_effect"], 23.19, TOL_FINISHED_HEADLINE)

    def test_ezdk_home_scrap(self, state):
        _approx_2dp(compute_finished_sc1(state, "EZDK", "Rebar")["home_scrap_deduction"], -14.48, TOL_FINISHED_HEADLINE)

    def test_ezdk_other_conversion(self, state):
        _approx_2dp(compute_finished_sc1(state, "EZDK", "Rebar")["other_conversion_cost"], 16.29, TOL_FINISHED_HEADLINE)

    def test_ezdk_total_conversion(self, state):
        _approx_2dp(compute_finished_sc1(state, "EZDK", "Rebar")["total_conversion_cost"], 25.00, TOL_FINISHED_TOTAL_CONVERSION)

    def test_ezdk_total_vc(self, state):
        _approx_2dp(compute_finished_sc1(state, "EZDK", "Rebar")["total_variable_mfg_cost"], 434.52, TOL_FINISHED_SC1_TOTAL)

    def test_efs_material_price(self, state):
        _approx_2dp(compute_finished_sc1(state, "EFS", "Rebar")["material_price"], 467.96, TOL_FINISHED_SC1_TOTAL)

    def test_efs_total_vc(self, state):
        _approx_2dp(compute_finished_sc1(state, "EFS", "Rebar")["total_variable_mfg_cost"], 486.07, TOL_FINISHED_SC1_TOTAL)

    def test_erm_material_price_is_market(self, state):
        # ERM defaults to "market" sourcing.
        _approx_2dp(compute_finished_sc1(state, "ERM", "Rebar")["material_price"], 590.00, TOL_FINISHED_HEADLINE)

    def test_erm_total_vc(self, state):
        _approx_2dp(compute_finished_sc1(state, "ERM", "Rebar")["total_variable_mfg_cost"], 614.10, TOL_FINISHED_SC1_TOTAL)

    def test_esr_material_price(self, state):
        _approx_2dp(compute_finished_sc1(state, "ESR", "Rebar")["material_price"], 450.31, TOL_FINISHED_SC1_TOTAL)

    def test_esr_total_vc(self, state):
        _approx_2dp(compute_finished_sc1(state, "ESR", "Rebar")["total_variable_mfg_cost"], 477.81, TOL_FINISHED_SC1_TOTAL)


class TestStage3Rebar_Sc2:

    def test_ezdk_yield_effect(self, state):
        _approx_2dp(compute_finished_sc2(state, "EZDK", "Rebar")["yield_effect"], 33.42, TOL_FINISHED_HEADLINE)

    def test_ezdk_home_scrap(self, state):
        _approx_2dp(compute_finished_sc2(state, "EZDK", "Rebar")["home_scrap_deduction"], -14.48, TOL_FINISHED_HEADLINE)

    def test_ezdk_total_vc(self, state):
        _approx_2dp(compute_finished_sc2(state, "EZDK", "Rebar")["total_variable_mfg_cost"], 625.23, TOL_FINISHED_SC2_TOTAL)

    def test_efs_total_vc(self, state):
        _approx_2dp(compute_finished_sc2(state, "EFS", "Rebar")["total_variable_mfg_cost"], 611.76, TOL_FINISHED_SC2_TOTAL)

    def test_erm_total_vc(self, state):
        _approx_2dp(compute_finished_sc2(state, "ERM", "Rebar")["total_variable_mfg_cost"], 614.10, TOL_FINISHED_SC2_TOTAL)

    def test_esr_total_vc(self, state):
        _approx_2dp(compute_finished_sc2(state, "ESR", "Rebar")["total_variable_mfg_cost"], 622.09, TOL_FINISHED_SC2_TOTAL)

    def test_ezdk_difference_sc1_minus_sc2(self, state):
        sc1 = compute_finished_sc1(state, "EZDK", "Rebar")["total_variable_mfg_cost"]
        sc2 = compute_finished_sc2(state, "EZDK", "Rebar")["total_variable_mfg_cost"]
        _approx_2dp(sc1 - sc2, -190.71, TOL_FINISHED_SC1_TOTAL)

    def test_erm_difference_sc1_equals_sc2(self, state):
        # ERM defaults to market; Sc1 should equal Sc2.
        sc1 = compute_finished_sc1(state, "ERM", "Rebar")["total_variable_mfg_cost"]
        sc2 = compute_finished_sc2(state, "ERM", "Rebar")["total_variable_mfg_cost"]
        assert abs(sc1 - sc2) < 1e-9


# ---------------------------------------------------------------------------
# Verification §3.2 — Wire Rod (EZDK only)
# ---------------------------------------------------------------------------

class TestStage3WireRod:
    """§3.2 has no specific Total VC target ('can be calculated on demand');
    we verify formula chain runs cleanly and produces the expected currency
    tag, residual = 0, and yield effect derived from the Wire Rod yield."""

    def test_currency_tag(self, state):
        assert compute_finished_sc1(state, "EZDK", "Wire Rod")["_currency"] == "USD"

    def test_yield_effect(self, state):
        # Yield effect = own billet VC × (1/0.9778 - 1) ≈ 9.30 with TOL
        out = compute_finished_sc1(state, "EZDK", "Wire Rod")
        _approx_2dp(out["yield_effect"], 9.30, 0.20)

    def test_residual_is_zero(self, state):
        # Wire Rod EZDK has no verification target; residual stays 0.
        assert state["finished_products"]["Wire Rod"]["EZDK"]["_reconciliation_residual_usd_per_ton"] == 0.0


# ---------------------------------------------------------------------------
# Verification §3.3 — HRC (EZDK + EFS)
# ---------------------------------------------------------------------------

class TestStage3HRC:

    def test_ezdk_currency_tag(self, state):
        assert compute_hrc_summary(state, "EZDK")["_currency"] == "USD"

    def test_ezdk_material_price(self, state):
        _approx_2dp(compute_hrc_summary(state, "EZDK")["material_price"], 280.73, TOL_FINISHED_HEADLINE)

    def test_ezdk_yield_effect(self, state):
        _approx_2dp(compute_hrc_summary(state, "EZDK")["yield_effect"], 59.92, TOL_FINISHED_HEADLINE)

    def test_ezdk_total_vc(self, state):
        _approx_2dp(compute_hrc_summary(state, "EZDK")["total_variable_mfg_cost"], 449.52, TOL_FINISHED_SC2_TOTAL)

    def test_efs_material_price(self, state):
        _approx_2dp(compute_hrc_summary(state, "EFS")["material_price"], 299.96, TOL_FINISHED_HEADLINE)

    def test_efs_yield_effect(self, state):
        _approx_2dp(compute_hrc_summary(state, "EFS")["yield_effect"], 68.26, TOL_FINISHED_HEADLINE)

    def test_efs_total_vc(self, state):
        _approx_2dp(compute_hrc_summary(state, "EFS")["total_variable_mfg_cost"], 496.83, TOL_FINISHED_SC2_TOTAL)

    def test_ezdk_carries_dummy_warning(self, state):
        out = compute_hrc_summary(state, "EZDK")
        assert "warning" in out

    def test_efs_carries_dummy_warning(self, state):
        out = compute_hrc_summary(state, "EFS")
        assert "warning" in out


# ---------------------------------------------------------------------------
# Sourcing-decision dispatch (Step 1 brief §4.3)
# ---------------------------------------------------------------------------

class TestSc1SourcingDispatch:

    def test_default_own_uses_billet_vc(self, state):
        # EZDK default = "own" → material price = own billet VC (~409.52)
        assert state["finished_products"]["Rebar"]["EZDK"]["sourcing_decision"] == "own"
        out = compute_finished_sc1(state, "EZDK", "Rebar")
        _approx_2dp(out["material_price"], 409.52, TOL_FINISHED_SC1_TOTAL)

    def test_default_market_uses_590(self, state):
        # ERM default = "market" → material price = $590
        assert state["finished_products"]["Rebar"]["ERM"]["sourcing_decision"] == "market"
        assert compute_finished_sc1(state, "ERM", "Rebar")["material_price"] == 590

    def test_internal_minimum_dispatch(self, state):
        # Switch ERM to internal_minimum; should pick the cheapest external
        # offer in the trade-off matrix (excluding own = no own for ERM).
        # Per verification §2.3, the minimum offer to ERM is 457.97 (from ESR).
        s = copy.deepcopy(state)
        s["finished_products"]["Rebar"]["ERM"]["sourcing_decision"] = "internal_minimum"
        out = compute_finished_sc1(s, "ERM", "Rebar")
        _approx_2dp(out["material_price"], 457.97, TOL_FINISHED_SC1_TOTAL)

    def test_unknown_sourcing_raises(self, state):
        s = copy.deepcopy(state)
        s["finished_products"]["Rebar"]["EZDK"]["sourcing_decision"] = "bogus"
        with pytest.raises(Exception):
            compute_finished_sc1(s, "EZDK", "Rebar")

    def test_own_for_non_producer_raises(self, state):
        # ERM doesn't produce billet; "own" is illegal even though defaults
        # send it to "market". Verifying the engine catches an explicit override.
        s = copy.deepcopy(state)
        s["finished_products"]["Rebar"]["ERM"]["sourcing_decision"] = "own"
        with pytest.raises(Exception):
            compute_finished_sc1(s, "ERM", "Rebar")


# ---------------------------------------------------------------------------
# Integrity checks (Rulebook §12 / Step 1 brief §4.7)
# ---------------------------------------------------------------------------

class TestIntegrityChecks_HappyPath:

    def test_fixed_distribution_sums_passes(self, state):
        ok, _ = _check_fixed_distribution_sums(state)
        assert ok

    def test_blending_ratios_sum_passes(self, state):
        ok, _ = _check_blending_ratios_sum(state)
        assert ok

    def test_sales_drive_production_passes(self, state):
        ok, _ = _check_sales_drive_production(state)
        assert ok

    def test_currency_consistency_passes(self, state):
        out = compute_dri_conversion(state, "EZDK")
        ok, _ = _check_currency_consistency(out)
        assert ok

    def test_intercompany_reconciliation_deferred(self, state):
        # Stub returns True with "DEFERRED" detail — structure preserved
        # for when the P&L stage lands.
        results = run_integrity_checks(state)
        # Check 6 is the 5th result entry (1, 2, 4, 5-stub, 6, 7-stub)
        # but ordering is: [1, 2, 4, 5, 6, 7]
        ok, detail = results[4]
        assert ok and "DEFERRED" in detail

    def test_break_even_deferred(self, state):
        results = run_integrity_checks(state)
        ok, detail = results[5]
        assert ok and ("DEFERRED" in detail or "skipped" in detail)


class TestIntegrityChecks_Violations:
    """Each check fires on a deliberately broken state. Tests deepcopy first."""

    def test_fixed_distribution_violation_fires(self, state):
        s = copy.deepcopy(state)
        s["fixed_costs"]["EZDK"]["distribution_pct"]["Rebar"] = 0  # was 25, total now 75
        ok, detail = _check_fixed_distribution_sums(s)
        assert not ok
        assert "EZDK" in detail and "75" in detail

    def test_blending_violation_fires(self, state):
        s = copy.deepcopy(state)
        s["billet"]["EZDK"]["blending_pct"]["dri"] = 0.50  # was 0.60
        ok, detail = _check_blending_ratios_sum(s)
        assert not ok
        assert "EZDK" in detail

    def test_sales_drive_production_violation_fires(self, state):
        s = copy.deepcopy(state)
        # Inject an orphan production qty that doesn't derive from sales.
        s["finished_products"]["Rebar"]["EZDK"]["production_qty_tons"] = 99999
        ok, detail = _check_sales_drive_production(s)
        assert not ok
        assert "production_qty_tons" in detail

    def test_currency_consistency_violation_missing_tag(self, state):
        bad = {"some_value": 100.0}  # no _currency tag
        ok, _ = _check_currency_consistency(bad)
        assert not ok

    def test_currency_consistency_violation_unknown_tag(self, state):
        bad = {"_currency": "BTC", "some_value": 100.0}
        ok, _ = _check_currency_consistency(bad)
        assert not ok

    def test_compute_all_raises_on_state_violation(self, state):
        s = copy.deepcopy(state)
        s["fixed_costs"]["ERM"]["distribution_pct"]["DRI"] = 50  # was 70, total now 80
        with pytest.raises(IntegrityError):
            compute_all(s)


# ---------------------------------------------------------------------------
# Stage F — Verification §5.1 Long-line cascade (Rulebook §6.4)
# ---------------------------------------------------------------------------

# Cascade values in verification display to 2 dp Ktons. Engine math is direct
# division/multiplication of clean inputs (yields, blending fractions, MRMR);
# ±0.01 Kt is the structural tolerance.
TOL_KT = 0.01


class TestLongLineCascade:
    """§5.1 cells per producer. Each helper invocation is the cell-by-cell
    column for one company in the verification table."""

    def _ezdk_cascade(self, state):
        b = state["billet"]["EZDK"]
        return _long_line_cascade(
            rebar_qty_kt=70.0, wire_qty_kt=80.0,
            rebar_yield=state["finished_products"]["Rebar"]["EZDK"]["rebar_yield"],
            wire_yield=state["finished_products"]["Wire Rod"]["EZDK"]["wire_yield"],
            eaf_yield=b["yields"]["eaf"], ccp_yield=b["yields"]["ccp"],
            blending_pct=b["blending_pct"],
            mrmr=state["dri"]["EZDK"]["mrmr"],
        )

    def _efs_cascade(self, state):
        b = state["billet"]["EFS"]
        return _long_line_cascade(
            rebar_qty_kt=60.0, wire_qty_kt=0.0,
            rebar_yield=state["finished_products"]["Rebar"]["EFS"]["rebar_yield"],
            wire_yield=1.0,  # not used (wire qty = 0)
            eaf_yield=b["yields"]["eaf"], ccp_yield=b["yields"]["ccp"],
            blending_pct=b["blending_pct"],
            mrmr=None,  # EFS has no own DRP
        )

    def _esr_cascade(self, state):
        b = state["billet"]["ESR"]
        return _long_line_cascade(
            rebar_qty_kt=70.0, wire_qty_kt=0.0,
            rebar_yield=state["finished_products"]["Rebar"]["ESR"]["rebar_yield"],
            wire_yield=1.0,
            eaf_yield=b["yields"]["eaf"], ccp_yield=b["yields"]["ccp"],
            blending_pct=b["blending_pct"],
            mrmr=None,
        )

    # EZDK column (verification §5.1)
    def test_ezdk_currency_tag(self, state):
        out = self._ezdk_cascade(state)
        assert out["_currency"] == "none" and out["_unit"] == "Ktons"

    def test_ezdk_rebar(self, state):
        _approx_2dp(self._ezdk_cascade(state)["rebar_kt"], 70.00, TOL_KT)

    def test_ezdk_wire_rod(self, state):
        _approx_2dp(self._ezdk_cascade(state)["wire_rod_kt"], 80.00, TOL_KT)

    def test_ezdk_billets(self, state):
        _approx_2dp(self._ezdk_cascade(state)["billets_kt"], 155.78, TOL_KT)

    def test_ezdk_molten_steel(self, state):
        _approx_2dp(self._ezdk_cascade(state)["molten_steel_kt"], 157.72, TOL_KT)

    def test_ezdk_solid_charge(self, state):
        _approx_2dp(self._ezdk_cascade(state)["solid_charge_kt"], 183.42, TOL_KT)

    def test_ezdk_dri(self, state):
        _approx_2dp(self._ezdk_cascade(state)["dri_kt"], 110.05, TOL_KT)

    def test_ezdk_imported_scrap(self, state):
        _approx_2dp(self._ezdk_cascade(state)["imported_scrap_kt"], 51.35, TOL_KT)

    def test_ezdk_local_scrap(self, state):
        _approx_2dp(self._ezdk_cascade(state)["local_scrap_kt"], 22.01, TOL_KT)

    def test_ezdk_iop(self, state):
        _approx_2dp(self._ezdk_cascade(state)["iop_kt"], 161.77, TOL_KT)

    # EFS column
    def test_efs_billets(self, state):
        _approx_2dp(self._efs_cascade(state)["billets_kt"], 61.80, TOL_KT)

    def test_efs_molten_steel(self, state):
        _approx_2dp(self._efs_cascade(state)["molten_steel_kt"], 63.03, TOL_KT)

    def test_efs_solid_charge(self, state):
        _approx_2dp(self._efs_cascade(state)["solid_charge_kt"], 74.31, TOL_KT)

    def test_efs_dri(self, state):
        _approx_2dp(self._efs_cascade(state)["dri_kt"], 52.02, TOL_KT)

    def test_efs_imported_scrap(self, state):
        _approx_2dp(self._efs_cascade(state)["imported_scrap_kt"], 6.76, TOL_KT)

    def test_efs_local_scrap(self, state):
        _approx_2dp(self._efs_cascade(state)["local_scrap_kt"], 15.53, TOL_KT)

    def test_efs_iop_is_none(self, state):
        # EFS has no own DRP — long-line IOP demand surfaces only via ERM aggregation.
        assert self._efs_cascade(state)["iop_kt"] is None

    # ESR column
    def test_esr_billets(self, state):
        _approx_2dp(self._esr_cascade(state)["billets_kt"], 72.30, TOL_KT)

    def test_esr_molten_steel(self, state):
        _approx_2dp(self._esr_cascade(state)["molten_steel_kt"], 73.40, TOL_KT)

    def test_esr_solid_charge(self, state):
        _approx_2dp(self._esr_cascade(state)["solid_charge_kt"], 84.03, TOL_KT)

    def test_esr_dri(self, state):
        _approx_2dp(self._esr_cascade(state)["dri_kt"], 16.81, TOL_KT)

    def test_esr_imported_scrap(self, state):
        _approx_2dp(self._esr_cascade(state)["imported_scrap_kt"], 53.78, TOL_KT)

    def test_esr_local_scrap(self, state):
        _approx_2dp(self._esr_cascade(state)["local_scrap_kt"], 13.44, TOL_KT)

    def test_esr_iop_is_none(self, state):
        assert self._esr_cascade(state)["iop_kt"] is None


# ---------------------------------------------------------------------------
# Stage F — Verification §5.2 Flat-line cascade (Rulebook §6.5)
# ---------------------------------------------------------------------------

class TestFlatLineCascade:
    """§5.2 cells per producer (EZDK + EFS only — ERM/ESR don't make HRC)."""

    def _ezdk_flat(self, state):
        h = state["finished_products"]["HRC"]["EZDK"]
        return _flat_line_cascade(
            hrc_qty_kt=45.0,
            eaf_yield=h["yields"]["eaf"],
            tsc_yield=h["yields"]["tsc"],
            hsm_yield=h["yields"]["hsm"],
            blending_pct=h["blending_pct"],
            mrmr=state["dri"]["EZDK"]["mrmr"],
        )

    def _efs_flat(self, state):
        h = state["finished_products"]["HRC"]["EFS"]
        return _flat_line_cascade(
            hrc_qty_kt=75.0,
            eaf_yield=h["yields"]["eaf"],
            tsc_yield=h["yields"]["tsc"],
            hsm_yield=h["yields"]["hsm"],
            blending_pct=h["blending_pct"],
            mrmr=None,  # EFS has no own DRP — IOP surfaces via ERM aggregation
        )

    # EZDK column (verification §5.2)
    def test_ezdk_currency_tag(self, state):
        out = self._ezdk_flat(state)
        assert out["_currency"] == "none" and out["_unit"] == "Ktons"

    def test_ezdk_hrc(self, state):
        _approx_2dp(self._ezdk_flat(state)["hrc_kt"], 45.00, TOL_KT)

    def test_ezdk_molten_steel(self, state):
        _approx_2dp(self._ezdk_flat(state)["molten_steel_kt"], 46.82, TOL_KT)

    def test_ezdk_solid_charge(self, state):
        _approx_2dp(self._ezdk_flat(state)["solid_charge_kt"], 54.61, TOL_KT)

    def test_ezdk_dri(self, state):
        _approx_2dp(self._ezdk_flat(state)["dri_kt"], 43.68, TOL_KT)

    def test_ezdk_imported_scrap(self, state):
        _approx_2dp(self._ezdk_flat(state)["imported_scrap_kt"], 1.11, TOL_KT)

    def test_ezdk_local_scrap(self, state):
        _approx_2dp(self._ezdk_flat(state)["local_scrap_kt"], 9.81, TOL_KT)

    def test_ezdk_iop(self, state):
        _approx_2dp(self._ezdk_flat(state)["iop_kt"], 64.22, TOL_KT)

    # EFS column
    def test_efs_hrc(self, state):
        _approx_2dp(self._efs_flat(state)["hrc_kt"], 75.00, TOL_KT)

    def test_efs_molten_steel(self, state):
        _approx_2dp(self._efs_flat(state)["molten_steel_kt"], 78.09, TOL_KT)

    def test_efs_solid_charge(self, state):
        _approx_2dp(self._efs_flat(state)["solid_charge_kt"], 92.07, TOL_KT)

    def test_efs_dri(self, state):
        _approx_2dp(self._efs_flat(state)["dri_kt"], 64.45, TOL_KT)

    def test_efs_imported_scrap(self, state):
        _approx_2dp(self._efs_flat(state)["imported_scrap_kt"], 8.29, TOL_KT)

    def test_efs_local_scrap(self, state):
        _approx_2dp(self._efs_flat(state)["local_scrap_kt"], 19.33, TOL_KT)

    def test_efs_iop_is_none(self, state):
        # EFS HRC DRI comes from ERM. EFS's own flat cascade returns None;
        # the 92.16 Kt IOP for ERM appears in _erm_dri_supply_aggregation.
        assert self._efs_flat(state)["iop_kt"] is None


# ---------------------------------------------------------------------------
# Stage F — Verification §5.1/§5.2/§5.3 ERM IOP aggregation
# ---------------------------------------------------------------------------

class TestERMSupplyAggregation:
    """Verification §5.1 footnote (ERM long-line IOP), §5.2 footnote (ERM
    flat-line IOP), §5.3 ERM total IOP. Tolerance is ±0.01 Kt for the
    individual long/flat cells; ±0.02 Kt is acceptable on the total per
    the session direction (rounding propagation), but full-precision math
    actually reconciles to ±0.01."""

    def _agg(self, state):
        # Build per-buyer cascade dicts (full precision, no intermediate rounding).
        long_line = {}
        flat_line = {}
        for c in ("EFS", "ESR"):
            b = state["billet"][c]
            long_line[c] = _long_line_cascade(
                rebar_qty_kt={"EFS": 60.0, "ESR": 70.0}[c],
                wire_qty_kt=0.0,
                rebar_yield=state["finished_products"]["Rebar"][c]["rebar_yield"],
                wire_yield=1.0,
                eaf_yield=b["yields"]["eaf"], ccp_yield=b["yields"]["ccp"],
                blending_pct=b["blending_pct"], mrmr=None,
            )
        h = state["finished_products"]["HRC"]["EFS"]
        flat_line["EFS"] = _flat_line_cascade(
            hrc_qty_kt=75.0,
            eaf_yield=h["yields"]["eaf"], tsc_yield=h["yields"]["tsc"],
            hsm_yield=h["yields"]["hsm"], blending_pct=h["blending_pct"], mrmr=None,
        )
        return _erm_dri_supply_aggregation(state, long_line, flat_line)

    def test_currency_tag(self, state):
        agg = self._agg(state)
        assert agg["_currency"] == "none" and agg["_unit"] == "Ktons"

    def test_erm_buyers_driven_by_supply_map(self, state):
        # Confirms drive-from-map, not hardcoded list. Current map: EFS, ESR → ERM.
        assert sorted(self._agg(state)["erm_buyers"]) == ["EFS", "ESR"]

    def test_long_iop(self, state):
        _approx_2dp(self._agg(state)["iop_long_kt"], 98.41, TOL_KT)

    def test_flat_iop(self, state):
        _approx_2dp(self._agg(state)["iop_flat_kt"], 92.16, TOL_KT)

    def test_total_iop(self, state):
        # Per session: ±0.02 Kt is acceptable; full-precision actually ≤ ±0.01.
        _approx_2dp(self._agg(state)["iop_total_kt"], 190.57, 0.02)

    def test_dri_supplied_sentinel_is_string_not_number(self, state):
        agg = self._agg(state)
        assert isinstance(agg["dri_supplied_sentinel"], str)
        assert "supplied" in agg["dri_supplied_sentinel"].lower()
        # And no numeric "ERM DRI" cell anywhere — ERM doesn't produce DRI for sale,
        # only for transfer; the aggregation reports IOP, not a DRI flow back to ERM.
        assert "dri_to_erm_kt" not in agg

    def test_map_driven_invariant(self, state):
        # Recompute totals from the supply map directly inside the test,
        # asserting the aggregator obeys the map.
        agg = self._agg(state)
        long_total = sum(agg["long_dri_per_buyer_kt"].values())
        flat_total = sum(agg["flat_dri_per_buyer_kt"].values())
        erm_mrmr = state["dri"]["ERM"]["mrmr"]
        assert abs(agg["iop_total_kt"] - (long_total + flat_total) * erm_mrmr) < 1e-9

    def test_ezdk_unaffected(self, state):
        # EZDK self-supplies; aggregation must not list EZDK as an ERM buyer
        # and must not contribute to ERM IOP.
        agg = self._agg(state)
        assert "EZDK" not in agg["erm_buyers"]
        assert "EZDK" not in agg["long_dri_per_buyer_kt"]
        assert "EZDK" not in agg["flat_dri_per_buyer_kt"]

    def test_buyer_in_supply_map_but_missing_cascade_raises_in_aggregation(self, state):
        # Construct a state with a phantom ERM buyer; the long-line dict
        # we feed in won't have the buyer; aggregator must raise.
        s = copy.deepcopy(state)
        s["entities"]["dri_supply_map"]["PHANTOM_CO"] = "ERM"
        long_line = {"EFS": _long_line_cascade(60.0, 0.0,
            rebar_yield=s["finished_products"]["Rebar"]["EFS"]["rebar_yield"],
            wire_yield=1.0,
            eaf_yield=s["billet"]["EFS"]["yields"]["eaf"],
            ccp_yield=s["billet"]["EFS"]["yields"]["ccp"],
            blending_pct=s["billet"]["EFS"]["blending_pct"], mrmr=None)}
        # Note: ESR and PHANTOM_CO both missing from long_line; first hit will raise.
        with pytest.raises(Exception) as excinfo:
            _erm_dri_supply_aggregation(s, long_line, {})
        assert "long-line cascade" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Stage F — Verification §5.3 monthly summary + §5.1/§5.2 round-trip
# ---------------------------------------------------------------------------

class TestProductionCascade_Assembly:
    """compute_production_cascade composes 3a/3b/3c outputs into a single
    dict. No new physics — just structural assembly + Total row sum."""

    def test_top_level_shape(self, state):
        out = compute_production_cascade(state)
        assert set(out.keys()) >= {"long_line", "flat_line",
                                   "erm_supply_aggregation",
                                   "monthly_summary"}
        assert out["_currency"] == "none"
        assert out["_unit"] == "Ktons"

    # §5.3 row totals
    def test_total_rebar(self, state):
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["Total"]["rebar_kt"], 200.00, 0.02)

    def test_total_wire_rod(self, state):
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["Total"]["wire_rod_kt"], 80.00, 0.02)

    def test_total_hrc(self, state):
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["Total"]["hrc_kt"], 120.00, 0.02)

    def test_total_billet(self, state):
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["Total"]["billet_kt"], 289.88, 0.02)

    def test_total_dri_excludes_erm_sentinel(self, state):
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["Total"]["dri_kt"], 287.01, 0.02)

    def test_total_iop_only_producers(self, state):
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["Total"]["iop_kt"], 416.56, 0.02)

    def test_total_scrap(self, state):
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["Total"]["scrap_kt"], 201.42, 0.02)

    # ERM DRI sentinel structurally
    def test_erm_dri_is_string_sentinel(self, state):
        erm = compute_production_cascade(state)["monthly_summary"]["ERM"]
        assert isinstance(erm["dri_kt"], str)
        assert "supplied" in erm["dri_kt"].lower()

    def test_erm_iop_is_aggregation_total(self, state):
        out = compute_production_cascade(state)
        _approx_2dp(out["monthly_summary"]["ERM"]["iop_kt"], 190.57, 0.02)

    def test_erm_long_line_iop_is_aggregation_long(self, state):
        out = compute_production_cascade(state)
        _approx_2dp(out["long_line"]["ERM"]["iop_kt"], 98.41, TOL_KT)

    # Per-company monthly cells
    def test_ezdk_monthly_dri(self, state):
        # 110.05 (long) + 43.68 (flat) = 153.73
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["EZDK"]["dri_kt"], 153.73, 0.02)

    def test_ezdk_monthly_iop(self, state):
        # 161.77 (long) + 64.22 (flat) = 225.99
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["EZDK"]["iop_kt"], 225.99, 0.02)

    def test_efs_monthly_dri(self, state):
        # 52.02 (long) + 64.45 (flat) = 116.47
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["EFS"]["dri_kt"], 116.47, 0.02)

    def test_efs_monthly_iop_is_none(self, state):
        # EFS has no DRP — IOP shows as None in §5.3 EFS column.
        assert compute_production_cascade(state)["monthly_summary"]["EFS"]["iop_kt"] is None

    def test_esr_monthly_iop_is_none(self, state):
        assert compute_production_cascade(state)["monthly_summary"]["ESR"]["iop_kt"] is None

    def test_esr_monthly_scrap(self, state):
        _approx_2dp(compute_production_cascade(state)["monthly_summary"]["ESR"]["scrap_kt"], 67.22, 0.02)

    # Round-trip from §5.1 / §5.2 — assembled dict must contain unaltered
    # sub-cascade values at predictable addresses.
    def test_roundtrip_long_line_ezdk_billets(self, state):
        out = compute_production_cascade(state)
        _approx_2dp(out["long_line"]["EZDK"]["billets_kt"], 155.78, TOL_KT)

    def test_roundtrip_long_line_efs_dri(self, state):
        _approx_2dp(compute_production_cascade(state)["long_line"]["EFS"]["dri_kt"], 52.02, TOL_KT)

    def test_roundtrip_long_line_esr_solid_charge(self, state):
        _approx_2dp(compute_production_cascade(state)["long_line"]["ESR"]["solid_charge_kt"], 84.03, TOL_KT)

    def test_roundtrip_flat_line_ezdk_iop(self, state):
        _approx_2dp(compute_production_cascade(state)["flat_line"]["EZDK"]["iop_kt"], 64.22, TOL_KT)

    def test_roundtrip_flat_line_efs_dri(self, state):
        _approx_2dp(compute_production_cascade(state)["flat_line"]["EFS"]["dri_kt"], 64.45, TOL_KT)

    def test_roundtrip_flat_line_efs_iop_is_none(self, state):
        assert compute_production_cascade(state)["flat_line"]["EFS"]["iop_kt"] is None


# ---------------------------------------------------------------------------
# Stage F — Verification §4.1, §4.2, §4.3 — Sales summary
# ---------------------------------------------------------------------------

class TestSales_MonthlyPlan:
    """Cell-for-cell against verification §4.1 (Ktons)."""

    def _qty(self, state, product, company):
        return compute_sales_summary(state)["monthly_plan_ktons"][product][company]

    # Rebar Local row
    def test_rebar_local_ezdk(self, state):
        assert self._qty(state, "Rebar", "EZDK")["local_qty_ktons"] == 70

    def test_rebar_local_efs(self, state):
        assert self._qty(state, "Rebar", "EFS")["local_qty_ktons"] == 60

    def test_rebar_local_erm(self, state):
        assert self._qty(state, "Rebar", "ERM")["local_qty_ktons"] == 0

    def test_rebar_local_esr(self, state):
        assert self._qty(state, "Rebar", "ESR")["local_qty_ktons"] == 70

    # Rebar Export row
    def test_rebar_export_all_zero(self, state):
        for c in ("EZDK", "EFS", "ERM", "ESR"):
            assert self._qty(state, "Rebar", c)["export_qty_ktons"] == 0

    # Wire Rod (EZDK only)
    def test_wire_rod_local_ezdk(self, state):
        assert self._qty(state, "Wire Rod", "EZDK")["local_qty_ktons"] == 40

    def test_wire_rod_export_ezdk(self, state):
        assert self._qty(state, "Wire Rod", "EZDK")["export_qty_ktons"] == 40

    # HRC (EZDK + EFS only)
    def test_hrc_local_ezdk(self, state):
        assert self._qty(state, "HRC", "EZDK")["local_qty_ktons"] == 45

    def test_hrc_local_efs(self, state):
        assert self._qty(state, "HRC", "EFS")["local_qty_ktons"] == 0

    def test_hrc_export_ezdk(self, state):
        assert self._qty(state, "HRC", "EZDK")["export_qty_ktons"] == 0

    def test_hrc_export_efs(self, state):
        assert self._qty(state, "HRC", "EFS")["export_qty_ktons"] == 75

    # Group totals
    def test_group_rebar(self, state):
        g = compute_sales_summary(state)["monthly_plan_ktons"]["Rebar"]["group"]
        assert g["local_ktons"] == 200 and g["export_ktons"] == 0 and g["total_ktons"] == 200

    def test_group_wire_rod(self, state):
        g = compute_sales_summary(state)["monthly_plan_ktons"]["Wire Rod"]["group"]
        assert g["local_ktons"] == 40 and g["export_ktons"] == 40 and g["total_ktons"] == 80

    def test_group_hrc(self, state):
        g = compute_sales_summary(state)["monthly_plan_ktons"]["HRC"]["group"]
        assert g["local_ktons"] == 45 and g["export_ktons"] == 75 and g["total_ktons"] == 120

    # Structural-non-existence: EFS Wire Rod, ERM Wire Rod, ESR Wire Rod
    # / ERM HRC, ESR HRC must not appear as keys.
    def test_efs_wire_rod_absent(self, state):
        assert "EFS" not in compute_sales_summary(state)["monthly_plan_ktons"]["Wire Rod"]

    def test_erm_wire_rod_absent(self, state):
        assert "ERM" not in compute_sales_summary(state)["monthly_plan_ktons"]["Wire Rod"]

    def test_esr_hrc_absent(self, state):
        assert "ESR" not in compute_sales_summary(state)["monthly_plan_ktons"]["HRC"]

    def test_currency_tag(self, state):
        out = compute_sales_summary(state)["monthly_plan_ktons"]
        assert out["_currency"] == "none" and out["_unit"] == "Ktons"


class TestSales_SellingPrices:
    """Cell-for-cell against verification §4.2."""

    # Local prices in LE/t
    def test_rebar_local_prices(self, state):
        p = compute_sales_summary(state)["local_prices_le_t"]["Rebar"]
        assert p["EZDK"] == 8910 and p["EFS"] == 8860 and p["ERM"] == 8860 and p["ESR"] == 8860

    def test_wire_rod_local_price_ezdk(self, state):
        assert compute_sales_summary(state)["local_prices_le_t"]["Wire Rod"]["EZDK"] == 8860

    def test_hrc_local_prices(self, state):
        p = compute_sales_summary(state)["local_prices_le_t"]["HRC"]
        assert p["EZDK"] == 8750 and p["EFS"] == 8750

    # Export prices in $/t
    def test_rebar_export_prices(self, state):
        p = compute_sales_summary(state)["export_prices_usd_t"]["Rebar"]
        assert p["EZDK"] == 500 and p["EFS"] == 500 and p["ERM"] == 500 and p["ESR"] == 500

    def test_wire_rod_export_price_ezdk(self, state):
        assert compute_sales_summary(state)["export_prices_usd_t"]["Wire Rod"]["EZDK"] == 520

    def test_hrc_export_price_ezdk(self, state):
        assert compute_sales_summary(state)["export_prices_usd_t"]["HRC"]["EZDK"] == 540

    def test_hrc_export_price_efs(self, state):
        assert compute_sales_summary(state)["export_prices_usd_t"]["HRC"]["EFS"] == 521

    def test_local_prices_currency_tag(self, state):
        out = compute_sales_summary(state)["local_prices_le_t"]
        assert out["_currency"] == "EGP" and out["_unit"] == "LE/t"

    def test_export_prices_currency_tag(self, state):
        out = compute_sales_summary(state)["export_prices_usd_t"]
        assert out["_currency"] == "USD" and out["_unit"] == "$/t"


class TestSales_ExportExpenses:
    """Cell-for-cell against verification §4.3 — passthrough rates."""

    def test_efs_hrc_rate(self, state):
        assert compute_sales_summary(state)["export_expense_rates_usd_t"]["HRC"]["EFS"] == 0.15

    def test_ezdk_wire_rod_rate(self, state):
        assert compute_sales_summary(state)["export_expense_rates_usd_t"]["Wire Rod"]["EZDK"] == 0.2

    def test_ezdk_hrc_rate(self, state):
        assert compute_sales_summary(state)["export_expense_rates_usd_t"]["HRC"]["EZDK"] == 0.8

    def test_others_zero(self, state):
        rates = compute_sales_summary(state)["export_expense_rates_usd_t"]
        # Rebar: all four companies = 0
        for c in ("EZDK", "EFS", "ERM", "ESR"):
            assert rates["Rebar"][c] == 0.0
        # HRC EFS = 0.15 (already tested), EZDK = 0.8 (already tested) — no other HRC entries

    def test_currency_tag(self, state):
        out = compute_sales_summary(state)["export_expense_rates_usd_t"]
        assert out["_currency"] == "USD" and out["_unit"] == "$/t"


# ---------------------------------------------------------------------------
# Stage F — Verification §4.4 — Market share
# ---------------------------------------------------------------------------

# Market share displays to 2 dp percent; ±0.01 pp tolerance.
TOL_PCT = 0.01


class TestMarketShare:

    def test_currency_tag(self, state):
        out = compute_market_share(state)
        assert out["_currency"] == "none" and out["_unit"] == "%"

    def test_rebar_group_local(self, state):
        assert compute_market_share(state)["Rebar"]["group_local_ktons"] == 200

    def test_rebar_total_market(self, state):
        assert compute_market_share(state)["Rebar"]["total_local_market_ktons"] == 440

    def test_rebar_market_share_pct(self, state):
        # 200/440 × 100 = 45.4545%
        _approx_2dp(compute_market_share(state)["Rebar"]["market_share_pct"], 45.45, TOL_PCT)

    def test_rebar_company_pct_of_group(self, state):
        cpg = compute_market_share(state)["Rebar"]["company_pct_of_group"]
        # 70/200=35, 60/200=30, 0/200=0, 70/200=35
        assert cpg["EZDK"] == 35.0 and cpg["EFS"] == 30.0
        assert cpg["ERM"] == 0.0 and cpg["ESR"] == 35.0

    def test_wire_rod_group_local(self, state):
        assert compute_market_share(state)["Wire Rod"]["group_local_ktons"] == 40

    def test_wire_rod_total_market(self, state):
        assert compute_market_share(state)["Wire Rod"]["total_local_market_ktons"] == 60

    def test_wire_rod_market_share_pct(self, state):
        # 40/60 × 100 = 66.6667
        _approx_2dp(compute_market_share(state)["Wire Rod"]["market_share_pct"], 66.67, TOL_PCT)

    def test_wire_rod_company_pct_of_group(self, state):
        cpg = compute_market_share(state)["Wire Rod"]["company_pct_of_group"]
        assert cpg == {"EZDK": 100.0}

    # HRC — Q6 ruling: market_share_pct is None when total_local_market is null
    def test_hrc_market_share_is_none(self, state):
        assert compute_market_share(state)["HRC"]["market_share_pct"] is None

    def test_hrc_total_market_is_none(self, state):
        assert compute_market_share(state)["HRC"]["total_local_market_ktons"] is None

    def test_hrc_group_local_still_computed(self, state):
        # Group local for HRC is computable (45 Ktons); only the share is None.
        assert compute_market_share(state)["HRC"]["group_local_ktons"] == 45

    def test_hrc_note_present(self, state):
        hrc = compute_market_share(state)["HRC"]
        assert "_note" in hrc
        assert "HRC" in hrc["_note"] and "not yet provided" in hrc["_note"]

    def test_hrc_does_not_raise(self, state):
        # Q6 ruling explicitly: HRC null market does NOT raise.
        compute_market_share(state)  # would raise if it were going to


class TestComputeAll:

    def test_runs_without_error(self, state):
        outputs = compute_all(state)
        assert isinstance(outputs, dict)
        assert "_integrity_checks" in outputs

    def test_includes_dri_views(self, state):
        outputs = compute_all(state)
        assert outputs["dri_detailed_EZDK"]["_currency"] == "EGP"
        assert outputs["dri_conversion_ERM"]["_currency"] == "USD"

    def test_includes_billet_views(self, state):
        outputs = compute_all(state)
        assert outputs["billet_conversion_EZDK"]["_currency"] == "USD"
        assert outputs["billet_market"]["_currency"] == "USD"
        assert outputs["billet_tradeoff_matrix"]["_currency"] == "USD"

    def test_includes_finished_views(self, state):
        outputs = compute_all(state)
        assert outputs["finished_sc1_Rebar_EZDK"]["_currency"] == "USD"
        assert outputs["finished_sc2_Rebar_ERM"]["_currency"] == "USD"
        assert outputs["hrc_summary_EFS"]["_currency"] == "USD"

    def test_no_finished_for_companies_outside_production_matrix(self, state):
        outputs = compute_all(state)
        # ERM does not produce HRC.
        assert "hrc_summary_ERM" not in outputs
        # ESR does not produce HRC.
        assert "hrc_summary_ESR" not in outputs
        # EFS does not produce Wire Rod.
        assert "finished_sc1_Wire Rod_EFS" not in outputs

    def test_integrity_results_all_pass(self, state):
        outputs = compute_all(state)
        for ok, detail in outputs["_integrity_checks"]:
            assert ok, detail
