"""Cost-engine test suite.

Tolerance policy per step1_brief_cost_engine_v2.md §6:
- LE/t integer values: exact after rounding, or |diff| ≤ 1 for cumulative drift.
- USD/t 2dp values: |round(actual,2) − target| ≤ 0.01.

Six §1.3 cells widened to ±0.06 USD/t per Rulebook §13 data-gap policy; see
TESTING_NOTES.md "Stage 1 — DRI" for the justification.
"""

import pytest

import cost_engine as ce


ABS_TOL_USD = 0.01
ABS_TOL_USD_WIDE = 0.06
LE_TOL = 1


# Per-cell USD tolerance overrides.
# Keyed by (test_section, company, cell_name).
# Anything not listed here uses ABS_TOL_USD (±0.01).
#
# Step 1 — DRI conversion (six cells widened to ±0.06, Rulebook §13 dummies):
# Step 2 — Billet EZDK + trade-off (three cells widened, DRI VC propagation):
_USD_TOL_OVERRIDES = {
    # Step 1 — DRI conversion data-gap drift (Rulebook §13).
    ("dri_conversion", "EZDK", "other_conversion_usd_t"):    ABS_TOL_USD_WIDE,
    ("dri_conversion", "EZDK", "total_conversion_usd_t"):    ABS_TOL_USD_WIDE,
    ("dri_conversion", "EZDK", "total_variable_mfg_usd_t"):  ABS_TOL_USD_WIDE,
    ("dri_conversion", "ERM",  "other_conversion_usd_t"):    ABS_TOL_USD_WIDE,
    ("dri_conversion", "ERM",  "total_conversion_usd_t"):    ABS_TOL_USD_WIDE,
    ("dri_conversion", "ERM",  "total_variable_mfg_usd_t"):  ABS_TOL_USD_WIDE,
    # Step 2 — Billet EZDK §1.3 DRI VC propagation.
    ("billet_conversion", "EZDK", "material_price_usd_t"):       0.05,
    ("billet_conversion", "EZDK", "total_variable_mfg_usd_t"):   0.05,
    # Step 2 — Trade-off matrix EZDK source row propagation (×1.169).
    ("tradeoff_matrix",   "EZDK", "offer_usd_t"):                0.06,
}


def _tol_for(section: str, company: str, cell: str) -> float:
    return _USD_TOL_OVERRIDES.get((section, company, cell), ABS_TOL_USD)


def _usd_close(actual: float, target: float, tol: float = ABS_TOL_USD) -> bool:
    # +1e-9 corrects IEEE-754 representation artifacts at the tolerance boundary;
    # it is not a tolerance widening.
    return abs(round(actual, 2) - target) <= tol + 1e-9


def _le_close(actual: float, target: int, tol: int = LE_TOL) -> bool:
    return abs(round(actual) - target) <= tol


# ---------------------------------------------------------------------------
# Stage 1 — DRI Detailed (verification §1.2)
# ---------------------------------------------------------------------------

class TestStage1DRI_Detailed:
    """Per-cell LE/t assertions for EZDK and ERM."""

    EXPECTED = {
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

    @pytest.mark.parametrize("company", ["EZDK", "ERM"])
    def test_currency_tag_is_egp(self, state, company):
        out = ce.compute_dri_detailed(state, company)
        assert out["_currency"] == "EGP"

    @pytest.mark.parametrize("company", ["EZDK", "ERM"])
    def test_cells_within_le_tolerance(self, state, company):
        out = ce.compute_dri_detailed(state, company)
        failures = []
        for cell, target in self.EXPECTED[company].items():
            if not _le_close(out[cell], target):
                failures.append(
                    f"{company} {cell}: engine={out[cell]:.4f} "
                    f"(rounded {round(out[cell])}), target={target}, "
                    f"diff={round(out[cell]) - target}"
                )
        assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Stage 1 — DRI Conversion (verification §1.3)
# ---------------------------------------------------------------------------

class TestStage1DRI_Conversion:
    """Per-cell USD/t assertions for EZDK and ERM."""

    EXPECTED = {
        "EZDK": {
            "material_price_usd_t":      154.84,
            "mrmr_effect_usd_t":          72.77,
            "other_conversion_usd_t":     57.62,
            "total_conversion_usd_t":    130.39,
            "total_variable_mfg_usd_t":  285.23,
        },
        "ERM": {
            "material_price_usd_t":      174.31,
            "mrmr_effect_usd_t":          74.95,
            "other_conversion_usd_t":     58.68,
            "total_conversion_usd_t":    133.63,
            "total_variable_mfg_usd_t":  307.94,
        },
    }

    @pytest.mark.parametrize("company", ["EZDK", "ERM"])
    def test_currency_tag_is_usd(self, state, company):
        out = ce.compute_dri_conversion(state, company)
        assert out["_currency"] == "USD"

    @pytest.mark.parametrize("company", ["EZDK", "ERM"])
    def test_cells_within_usd_tolerance(self, state, company):
        out = ce.compute_dri_conversion(state, company)
        failures = []
        for cell, target in self.EXPECTED[company].items():
            tol = _tol_for("dri_conversion", company, cell)
            if not _usd_close(out[cell], target, tol):
                failures.append(
                    f"{company} {cell}: engine={out[cell]:.6f} "
                    f"(rounded {round(out[cell], 2):.2f}), target={target}, "
                    f"diff={round(out[cell], 2) - target:+.4f}, tol=±{tol}"
                )
        assert not failures, "\n".join(failures)

    def test_invalid_company_raises_structural_non_existence(self, state):
        for bad in ["EFS", "ESR", "FOO"]:
            with pytest.raises(ValueError, match="structural_non_existence"):
                ce.compute_dri_conversion(state, bad)
            with pytest.raises(ValueError, match="structural_non_existence"):
                ce.compute_dri_detailed(state, bad)


# ---------------------------------------------------------------------------
# Stage 2 — Billet EZDK Conversion (verification §2.2 EZDK column)
# ---------------------------------------------------------------------------

class TestStage2BilletEZDK_Conversion:
    """Verification §2.2 EZDK column — five summary cells plus currency tag.

    Residual of 0.499 USD/t (seeded in conftest under state["reconciliation"])
    is applied at Other Conversion. Material Price and Total VC carry their
    propagated DRI VC drift inside ±0.05 overrides.
    """

    EXPECTED = {
        "material_price_usd_t":      263.21,
        "yield_effect_usd_t":         46.70,
        "other_conversion_usd_t":     99.61,
        "total_conversion_usd_t":    146.31,
        "total_variable_mfg_usd_t":  409.52,
    }

    def test_currency_tag_is_usd(self, state):
        out = ce.compute_billet_conversion(state, "EZDK")
        assert out["_currency"] == "USD"

    def test_cells_within_usd_tolerance(self, state):
        out = ce.compute_billet_conversion(state, "EZDK")
        failures = []
        for cell, target in self.EXPECTED.items():
            tol = _tol_for("billet_conversion", "EZDK", cell)
            if not _usd_close(out[cell], target, tol):
                failures.append(
                    f"EZDK billet {cell}: engine={out[cell]:.6f} "
                    f"(rounded {round(out[cell], 2):.2f}), target={target}, "
                    f"diff={round(out[cell], 2) - target:+.4f}, tol=±{tol}"
                )
        assert not failures, "\n".join(failures)

    def test_residual_applied_at_other_conversion(self, state):
        """Other Conv = Other-Conv-pre-residual + residual (visible in source)."""
        out = ce.compute_billet_conversion(state, "EZDK")
        pre = out["_other_conversion_before_residual"]
        res = out["_reconciliation_residual_usd_t"]
        assert res == pytest.approx(0.499, abs=1e-9)
        assert out["other_conversion_usd_t"] == pytest.approx(pre + res, abs=1e-9)

    def test_residual_zero_for_non_ezdk(self, state):
        # Other billet producers must not pick up an EZDK-keyed residual.
        for c in ("EFS", "ESR"):
            r = ce._billet_reconciliation_residual_usd_t(state, c)
            assert r == 0.0, f"{c} unexpectedly read residual={r}"

    def test_invalid_company_raises_structural_non_existence(self, state):
        with pytest.raises(ValueError, match="structural_non_existence"):
            ce.compute_billet_conversion(state, "ERM")
        with pytest.raises(ValueError, match="structural_non_existence"):
            ce.compute_billet_detailed(state, "ERM")


# ---------------------------------------------------------------------------
# Stage 2 — Billet EZDK Detailed (EAF + BCCM consistency)
# ---------------------------------------------------------------------------

class TestStage2BilletEZDK_Detailed:
    """EAF + BCCM detailed buildup for EZDK.

    No per-line verification targets exist in §2.2 below the summary, so this
    class tests:
      1. Internal consistency: per-stage components sum to the stage total.
      2. The headline total agrees between the detailed and conversion views.
      3. Sign/sanity invariants (byproducts negative, etc.).
    Brief §6 default tolerances apply; no new overrides expected.
    """

    def test_currency_tag_is_usd(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        assert out["_currency"] == "USD"

    def test_eaf_materials_sum_consistency(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        m = out["eaf"]["materials"]
        expected_total = (
            m["dri"] + m["local_scrap"] + m["imported_scrap"]
            + m["home_scrap"] + m["pig_iron"]
        )
        assert m["total"] == pytest.approx(expected_total, abs=1e-9)

    def test_eaf_conversion_sum_consistency(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        c = out["eaf"]["conversion"]
        expected_total = (
            c["aux_materials"] + c["refractories"] + c["electrodes"]
            + c["other_fillers"] + c["electricity"] + c["natural_gas"]
            + c["water"] + c["oxygen"] + c["nitrogen"] + c["argon"]
            + c["handling"] + c["cutting"]
        )
        assert c["total"] == pytest.approx(expected_total, abs=1e-9)

    def test_eaf_total_is_materials_plus_byproduct_plus_conversion(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        eaf = out["eaf"]
        expected = (
            eaf["materials"]["total"]
            + eaf["byproduct_credit_usd_t_ms"]
            + eaf["conversion"]["total"]
        )
        assert eaf["total_usd_t_ms"] == pytest.approx(expected, abs=1e-9)

    def test_eaf_byproduct_is_negative(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        assert out["eaf"]["byproduct_credit_usd_t_ms"] < 0.0

    def test_bccm_ms_carried_equals_eaf_total_over_ccp(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        ccp_yield = state["billet"]["EZDK"]["yields"]["ccp"]
        expected = out["eaf"]["total_usd_t_ms"] / ccp_yield
        assert out["bccm"]["ms_carried_usd_t_billet"] == pytest.approx(expected, abs=1e-9)

    def test_bccm_total_consistency(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        b = out["bccm"]
        expected = b["ms_carried_usd_t_billet"] + b["additions_total"]
        assert b["total_usd_t_billet"] == pytest.approx(expected, abs=1e-9)

    def test_bccm_byproduct_crops_is_negative(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        assert out["bccm"]["byproduct_crops_usd_t_billet"] < 0.0

    def test_total_pre_residual_equals_bccm_total(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        assert out["total_pre_residual_usd_t"] == pytest.approx(
            out["bccm"]["total_usd_t_billet"], abs=1e-9
        )

    def test_total_with_residual_matches_conversion_view(self, state):
        det = ce.compute_billet_detailed(state, "EZDK")
        conv = ce.compute_billet_conversion(state, "EZDK")
        assert det["total_variable_mfg_usd_t"] == pytest.approx(
            conv["total_variable_mfg_usd_t"], abs=1e-9
        )

    def test_residual_added_on_top(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        assert out["total_variable_mfg_usd_t"] == pytest.approx(
            out["total_pre_residual_usd_t"] + out["reconciliation_residual_usd_t"],
            abs=1e-9,
        )

    def test_dri_price_used_is_full_precision_dri_vc(self, state):
        out = ce.compute_billet_detailed(state, "EZDK")
        dri = ce.compute_dri_conversion(state, "EZDK")
        # EZDK uses own DRI VC, no margin, full precision (Rulebook §4.5).
        assert out["dri_price_used_usd_t"] == pytest.approx(
            dri["total_variable_mfg_usd_t"], abs=1e-9
        )


# ---------------------------------------------------------------------------
# Stage 2 — Trade-off Matrix Framework (verification §2.3, EZDK + Market only)
# ---------------------------------------------------------------------------

class TestStage2TradeoffMatrix_Framework:
    """EZDK source row implemented; EFS/ESR sentinel-stubbed for step 3.

    Verifies the framework computes EZDK × 1.169, Market = 590, and
    minimum-per-buyer correctly across the implemented rows.
    """

    def test_currency_tag_is_usd(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        assert tm["_currency"] == "USD"

    def test_ezdk_offer_equals_vc_times_ratio(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        row = tm["rows"]["EZDK"]
        expected = row["seller_vc_usd_t"] * row["trade_off_ratio"]
        assert row["offer_usd_t"] == pytest.approx(expected, abs=1e-9)

    def test_ezdk_offer_matches_verification_within_propagation_tol(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        offer = tm["rows"]["EZDK"]["offer_usd_t"]
        tol = _tol_for("tradeoff_matrix", "EZDK", "offer_usd_t")
        assert _usd_close(offer, 478.73, tol), (
            f"EZDK offer: engine={offer:.6f} (rounded {round(offer, 2):.2f}), "
            f"target=478.73, diff={round(offer, 2) - 478.73:+.4f}, tol=±{tol}"
        )

    def test_ezdk_to_ezdk_is_own_vc_not_offer(self, state):
        """Producer-own-VC rule: EZDK buying from itself uses own VC (Rulebook §4.5)."""
        tm = ce.compute_tradeoff_matrix(state)
        row = tm["rows"]["EZDK"]
        assert row["to_EZDK"] == pytest.approx(row["seller_vc_usd_t"], abs=1e-9)
        assert row["to_EFS"] == pytest.approx(row["offer_usd_t"], abs=1e-9)
        assert row["to_ERM"] == pytest.approx(row["offer_usd_t"], abs=1e-9)
        assert row["to_ESR"] == pytest.approx(row["offer_usd_t"], abs=1e-9)

    def test_market_row_is_flat_590(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        assert tm["market_price_usd_t"] == 590
        m = tm["rows"]["Market"]
        for buyer in ("EZDK", "EFS", "ERM", "ESR"):
            assert m[f"to_{buyer}"] == 590

    def test_efs_and_esr_source_rows_are_stubbed(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        assert tm["rows"]["EFS"]["status"] == ce._TRADEOFF_NOT_YET_BUILT
        assert tm["rows"]["ESR"]["status"] == ce._TRADEOFF_NOT_YET_BUILT
        assert "to_EZDK" not in tm["rows"]["EFS"]
        assert "to_EZDK" not in tm["rows"]["ESR"]

    def test_min_per_buyer_excludes_stub_rows(self, state):
        """Minimums computed only over implemented sources (EZDK + Market)."""
        tm = ce.compute_tradeoff_matrix(state)
        ezdk_offer = tm["rows"]["EZDK"]["offer_usd_t"]
        ezdk_vc = tm["rows"]["EZDK"]["seller_vc_usd_t"]
        market = tm["market_price_usd_t"]
        mins = tm["minimum_per_buyer"]
        # Buyer EZDK: own VC vs market — own VC wins.
        assert mins["EZDK"] == pytest.approx(min(ezdk_vc, market), abs=1e-9)
        # Other buyers: EZDK offer vs market.
        for b in ("EFS", "ERM", "ESR"):
            assert mins[b] == pytest.approx(min(ezdk_offer, market), abs=1e-9)


# ---------------------------------------------------------------------------
# Integrity Check 2 — Blending ratios sum to 100% per production line
# ---------------------------------------------------------------------------

class TestIntegrityCheck2_Blending:

    def test_happy_path_passes(self, state):
        ok, detail = ce._check_blending_ratios_sum(state)
        assert ok, f"happy-path failed: {detail}"

    def test_violation_detected_in_billet(self, state):
        state["billet"]["EZDK"]["blending_pct"]["dri"] = 0.5  # was 0.60
        ok, detail = ce._check_blending_ratios_sum(state)
        assert not ok
        assert "EZDK" in detail

    def test_violation_detected_in_hrc(self, state):
        state["finished_products"]["HRC"]["EZDK"]["blending_pct"]["dri"] = 0.7  # was 0.80
        ok, detail = ce._check_blending_ratios_sum(state)
        assert not ok
        assert "HRC" in detail

    def test_within_tolerance_passes(self, state):
        # ±0.01 tolerance: 0.005 deviation should still pass.
        state["billet"]["EZDK"]["blending_pct"]["dri"] = 0.605
        ok, _ = ce._check_blending_ratios_sum(state)
        assert ok
