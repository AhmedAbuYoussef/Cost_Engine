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
    # Step 3 — Billet EFS ERM-DRI-VC propagation (no residual, pure propagation).
    ("billet_conversion", "EFS", "material_price_usd_t"):        0.05,
    ("billet_conversion", "EFS", "total_variable_mfg_usd_t"):    0.06,
    # Step 3 — Trade-off matrix EFS source row propagation (×1.016).
    ("tradeoff_matrix",   "EFS", "offer_usd_t"):                 0.07,
    # ESR uses default ±0.01 everywhere (its propagation is small enough).
    # Step 4 — finished Sc1 material price inherits own-billet-VC drift
    # (same magnitudes as the billet_conversion total_variable_mfg overrides).
    ("finished_sc1", "EZDK", "material_price_usd_t"): 0.05,
    ("finished_sc1", "EFS",  "material_price_usd_t"): 0.06,
    # Step 4 — ERM/ESR rebar yield effects: 4dp display-rounded JSON yields
    # (engine 12.53 vs sheet 12.55; 19.38 vs 19.36). Derived bound ±0.03;
    # see TESTING_NOTES.md "Step 4". Tightens to ±0.01 when Excel
    # formula-bar yields land.
    ("finished_sc1", "ERM", "yield_effect_usd_t"): 0.03,
    ("finished_sc1", "ESR", "yield_effect_usd_t"): 0.03,
    ("finished_sc2", "ERM", "yield_effect_usd_t"): 0.03,
    ("finished_sc2", "ESR", "yield_effect_usd_t"): 0.03,
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

class TestStage2BilletEFS_Summary:
    """Verification §2.2 EFS column — five summary cells via summary_fitted mode.

    No reconciliation residual (the seeded summary_other_conversion IS the fit).
    Drift on Material Price and Total VC is pure ERM-DRI-VC propagation,
    handled by per-cell ±0.05/±0.06 overrides.
    """

    EXPECTED = {
        "material_price_usd_t":      299.98,
        "yield_effect_usd_t":         60.72,
        "other_conversion_usd_t":    107.26,
        "total_conversion_usd_t":    167.98,
        "total_variable_mfg_usd_t":  467.96,
    }

    def test_currency_tag_is_usd(self, state):
        out = ce.compute_billet_conversion(state, "EFS")
        assert out["_currency"] == "USD"

    def test_billet_mode_is_summary_fitted(self, state):
        out = ce.compute_billet_conversion(state, "EFS")
        assert out["billet_mode"] == ce._BILLET_MODE_SUMMARY_FITTED

    def test_no_residual_applied(self, state):
        out = ce.compute_billet_conversion(state, "EFS")
        assert out["_reconciliation_residual_usd_t"] == 0.0

    def test_dri_price_uses_erm_vc_no_margin(self, state):
        out = ce.compute_billet_conversion(state, "EFS")
        erm_dri = ce.compute_dri_conversion(state, "ERM")["total_variable_mfg_usd_t"]
        # ERM_to_EFS margin is 0.00 per state["intercompany"].
        assert out["_dri_price_used"] == pytest.approx(erm_dri, abs=1e-9)

    def test_cells_within_usd_tolerance(self, state):
        out = ce.compute_billet_conversion(state, "EFS")
        failures = []
        for cell, target in self.EXPECTED.items():
            tol = _tol_for("billet_conversion", "EFS", cell)
            if not _usd_close(out[cell], target, tol):
                failures.append(
                    f"EFS billet {cell}: engine={out[cell]:.6f} "
                    f"(rounded {round(out[cell], 2):.2f}), target={target}, "
                    f"diff={round(out[cell], 2) - target:+.4f}, tol=±{tol}"
                )
        assert not failures, "\n".join(failures)


class TestStage2BilletESR_Summary:
    """Verification §2.2 ESR column — same structure as EFS, all cells at ±0.01.

    ESR's blend weights (DRI 20%, scraps 80%) make the ERM-DRI-VC propagation
    drift small enough to land everywhere within ±0.01.
    """

    EXPECTED = {
        "material_price_usd_t":      303.15,
        "yield_effect_usd_t":         49.19,
        "other_conversion_usd_t":     97.97,
        "total_conversion_usd_t":    147.16,
        "total_variable_mfg_usd_t":  450.31,
    }

    def test_currency_tag_is_usd(self, state):
        out = ce.compute_billet_conversion(state, "ESR")
        assert out["_currency"] == "USD"

    def test_billet_mode_is_summary_fitted(self, state):
        out = ce.compute_billet_conversion(state, "ESR")
        assert out["billet_mode"] == ce._BILLET_MODE_SUMMARY_FITTED

    def test_no_residual_applied(self, state):
        out = ce.compute_billet_conversion(state, "ESR")
        assert out["_reconciliation_residual_usd_t"] == 0.0

    def test_dri_price_uses_erm_vc_plus_margin(self, state):
        out = ce.compute_billet_conversion(state, "ESR")
        erm_dri = ce.compute_dri_conversion(state, "ERM")["total_variable_mfg_usd_t"]
        margin = state["intercompany"]["dri_margin_usd_t"]["ERM_to_ESR"]
        # Rulebook §4.5: ESR uses ERM DRI VC + margin (no hardcode of 7.54).
        assert out["_dri_price_used"] == pytest.approx(erm_dri + margin, abs=1e-9)

    def test_cells_within_usd_tolerance(self, state):
        out = ce.compute_billet_conversion(state, "ESR")
        failures = []
        for cell, target in self.EXPECTED.items():
            tol = _tol_for("billet_conversion", "ESR", cell)
            if not _usd_close(out[cell], target, tol):
                failures.append(
                    f"ESR billet {cell}: engine={out[cell]:.6f} "
                    f"(rounded {round(out[cell], 2):.2f}), target={target}, "
                    f"diff={round(out[cell], 2) - target:+.4f}, tol=±{tol}"
                )
        assert not failures, "\n".join(failures)


class TestSc2Dispatch_BilletMode:
    """Verify state-driven billet_mode dispatch across companies."""

    def test_ezdk_uses_detailed_with_residual(self, state):
        out = ce.compute_billet_conversion(state, "EZDK")
        assert out["billet_mode"] == ce._BILLET_MODE_DETAILED_WITH_RESIDUAL
        assert out["_reconciliation_residual_usd_t"] == pytest.approx(0.499, abs=1e-9)

    def test_efs_uses_summary_fitted(self, state):
        out = ce.compute_billet_conversion(state, "EFS")
        assert out["billet_mode"] == ce._BILLET_MODE_SUMMARY_FITTED
        assert out["_reconciliation_residual_usd_t"] == 0.0

    def test_esr_uses_summary_fitted(self, state):
        out = ce.compute_billet_conversion(state, "ESR")
        assert out["billet_mode"] == ce._BILLET_MODE_SUMMARY_FITTED
        assert out["_reconciliation_residual_usd_t"] == 0.0

    def test_company_missing_billet_inputs_raises(self, state):
        # Strip both EAF consumptions and summary seed → mode lookup should fail.
        del state["billet"]["EFS"]["summary_other_conversion_usd_per_ton"]
        with pytest.raises(ValueError, match="structural_non_existence"):
            ce.compute_billet_conversion(state, "EFS")


class TestStage2TradeoffMatrix_Full:
    """Verification §2.3 — full 4×4 matrix with minimums.

    Source rows: EZDK, EFS, ESR, Market.
    Buyer columns: EZDK, EFS, ERM, ESR. ERM is buyer-only per Rulebook §1.4.

    Tolerance per cell follows from the underlying source: source-row offer
    cells use the source company's override; minimum cells inherit from
    whichever source contributes them.
    """

    def test_currency_tag_is_usd(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        assert tm["_currency"] == "USD"

    def test_market_row_is_flat_590(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        assert tm["market_price_usd_t"] == 590
        m = tm["rows"]["Market"]
        for buyer in ("EZDK", "EFS", "ERM", "ESR"):
            assert m[f"to_{buyer}"] == 590

    def test_producer_own_vc_at_diagonal(self, state):
        """Source==buyer: own VC, not the ratio'd offer (Rulebook §4.5)."""
        tm = ce.compute_tradeoff_matrix(state)
        for src in ("EZDK", "EFS", "ESR"):
            row = tm["rows"][src]
            assert row[f"to_{src}"] == pytest.approx(row["seller_vc_usd_t"], abs=1e-9)

    def test_offcell_intercompany_uses_offer(self, state):
        """Source!=buyer: seller_vc × seller_tradeoff_ratio."""
        tm = ce.compute_tradeoff_matrix(state)
        for src in ("EZDK", "EFS", "ESR"):
            row = tm["rows"][src]
            expected_offer = row["seller_vc_usd_t"] * row["trade_off_ratio"]
            assert row["offer_usd_t"] == pytest.approx(expected_offer, abs=1e-9)
            for buyer in ("EZDK", "EFS", "ERM", "ESR"):
                if buyer == src:
                    continue
                assert row[f"to_{buyer}"] == pytest.approx(row["offer_usd_t"], abs=1e-9)

    def test_erm_never_a_source_row(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        assert "ERM" not in tm["rows"], "ERM must not appear as a source (Rulebook §1.4)"
        assert "ERM" not in tm["sources"]
        assert "ERM" in tm["buyers"]

    def test_source_row_offers_match_verification(self, state):
        """Verification §2.3 source row 'Price ($/t)' column."""
        tm = ce.compute_tradeoff_matrix(state)
        # (source, verification offer, tolerance)
        expected = [
            ("EZDK", 478.73, _tol_for("tradeoff_matrix", "EZDK", "offer_usd_t")),
            ("EFS",  475.45, _tol_for("tradeoff_matrix", "EFS",  "offer_usd_t")),
            ("ESR",  457.97, _tol_for("tradeoff_matrix", "ESR",  "offer_usd_t")),
        ]
        failures = []
        for src, target, tol in expected:
            offer = tm["rows"][src]["offer_usd_t"]
            if not _usd_close(offer, target, tol):
                failures.append(
                    f"{src} offer: engine={offer:.6f} (rounded {round(offer, 2):.2f}), "
                    f"target={target}, diff={round(offer, 2) - target:+.4f}, tol=±{tol}"
                )
        assert not failures, "\n".join(failures)

    def test_minimum_per_buyer_matches_verification(self, state):
        """Verification §2.3 'Minimum' row.

        Minimums inherit tolerance from the source cell that contributes them.
        - To EZDK: from EZDK own VC → ±0.05 (EZDK Total VC override).
        - To EFS, To ERM: from ESR offer → ±0.01 (no ESR override).
        - To ESR: from ESR own VC → ±0.01 (no ESR override).
        """
        tm = ce.compute_tradeoff_matrix(state)
        expected = [
            ("EZDK", 409.52, _tol_for("billet_conversion", "EZDK", "total_variable_mfg_usd_t")),
            ("EFS",  457.97, ABS_TOL_USD),
            ("ERM",  457.97, ABS_TOL_USD),
            ("ESR",  450.31, ABS_TOL_USD),
        ]
        failures = []
        mins = tm["minimum_per_buyer"]
        for buyer, target, tol in expected:
            eng = mins[buyer]
            if not _usd_close(eng, target, tol):
                failures.append(
                    f"min to {buyer}: engine={eng:.6f} (rounded {round(eng, 2):.2f}), "
                    f"target={target}, diff={round(eng, 2) - target:+.4f}, tol=±{tol}"
                )
        assert not failures, "\n".join(failures)

    def test_minimum_source_attribution(self, state):
        """Verify which source contributes the minimum for each buyer."""
        tm = ce.compute_tradeoff_matrix(state)
        srcs = tm["minimum_per_buyer_source"]
        assert srcs["EZDK"] == "EZDK"  # own VC
        assert srcs["EFS"]  == "ESR"   # ESR external (450.31 × 1.017)
        assert srcs["ERM"]  == "ESR"   # ESR external; ERM has no own VC
        assert srcs["ESR"]  == "ESR"   # own VC


class TestStage2MarketBilletBuildup:
    """Verification §2.4 — Market price components."""

    def test_components_match(self, state):
        m = state["billet"]["market"]
        c = m["components_usd_t"]
        assert c["base"] == 428
        assert c["safe_guards"] == 74
        assert c["other_costs"] == 88

    def test_components_sum_to_market_price(self, state):
        m = state["billet"]["market"]
        c = m["components_usd_t"]
        total = c["base"] + c["safe_guards"] + c["other_costs"]
        assert total == 590
        assert m["market_price_usd_t"] == total

    def test_engine_helper_returns_590(self, state):
        assert ce._market_billet_price(state) == 590

    def test_market_appears_in_tradeoff_at_590(self, state):
        tm = ce.compute_tradeoff_matrix(state)
        assert tm["market_price_usd_t"] == 590


# ---------------------------------------------------------------------------
# Stage 3 — Finished Products (verification §3) — step 4 Excel-independent
# subset. Pending assertions (wired next sub-step on Excel-confirmed values):
#   - EZDK Rebar Other Conversion / Total Conversion / Total VC (Sc1 and Sc2)
#   - EZDK Rebar Sc2 Home Scrap + cascaded cells (group a)
#   - EFS/ERM/ESR Rebar Home Scrap rows and all totals
#   - HRC Material Price / Yield Effect / Other Conversion / Total VC
#     (groups b and item-6; plus the §3.3 Combined Yield cell discrepancy —
#     see TESTING_NOTES.md "Step 4")
# ---------------------------------------------------------------------------

class TestFinishedProducerGuard:
    """Structural production matrix: Rebar×4, Wire Rod×EZDK, HRC×{EZDK, EFS}."""

    LEGAL = {
        "Rebar": ("EZDK", "EFS", "ERM", "ESR"),
        "Wire Rod": ("EZDK",),
        "HRC": ("EZDK", "EFS"),
    }

    def test_legal_combinations_pass(self):
        for product, companies in self.LEGAL.items():
            for co in companies:
                ce._require_finished_producer(product, co)  # must not raise

    def test_wire_rod_non_ezdk_raises(self):
        for co in ("EFS", "ERM", "ESR"):
            with pytest.raises(ValueError, match="structural_non_existence"):
                ce._require_finished_producer("Wire Rod", co)

    def test_hrc_non_producers_raise(self):
        for co in ("ERM", "ESR"):
            with pytest.raises(ValueError, match="structural_non_existence"):
                ce._require_finished_producer("HRC", co)

    def test_unknown_product_raises(self):
        with pytest.raises(ValueError, match="structural_non_existence"):
            ce._require_finished_producer("Plates", "EZDK")

    def test_sc1_on_hrc_redirects_to_hrc_summary(self, state):
        with pytest.raises(ValueError, match="compute_hrc_summary"):
            ce.compute_finished_sc1(state, "EZDK", "HRC")


class TestSc1SourcingDispatch:
    """Brief §4.3 Q1/Q2: own / market / internal_minimum + illegal cases."""

    def test_producers_own_equals_own_billet_vc(self, state):
        for co in ("EZDK", "EFS", "ESR"):
            mat = ce._finished_material_price_sc1(state, co, "Rebar")
            own = ce.compute_billet_conversion(state, co)["total_variable_mfg_usd_t"]
            assert mat == own  # full precision, no pre-rounding

    def test_erm_market_default_is_590(self, state):
        assert ce._finished_material_price_sc1(state, "ERM", "Rebar") == 590

    def test_erm_internal_minimum_is_cheapest_external(self, state):
        state["finished_products"]["Rebar"]["ERM"]["sourcing_decision"] = "internal_minimum"
        mat = ce._finished_material_price_sc1(state, "ERM", "Rebar")
        assert _usd_close(mat, 457.97)  # ESR offer, verification §3.1 footnote
        esr_offer = ce.compute_tradeoff_matrix(state)["rows"]["ESR"]["to_ERM"]
        assert mat == esr_offer

    def test_producer_internal_minimum_excludes_own_vc(self, state):
        # EZDK's own VC (409.56) is the global minimum but is NOT an external
        # offer; cheapest external for EZDK is the ESR offer.
        state["finished_products"]["Rebar"]["EZDK"]["sourcing_decision"] = "internal_minimum"
        mat = ce._finished_material_price_sc1(state, "EZDK", "Rebar")
        assert _usd_close(mat, 457.97)

    def test_erm_own_raises(self, state):
        state["finished_products"]["Rebar"]["ERM"]["sourcing_decision"] = "own"
        with pytest.raises(ValueError, match="non-billet-producer"):
            ce._finished_material_price_sc1(state, "ERM", "Rebar")

    def test_unknown_decision_raises(self, state):
        state["finished_products"]["Rebar"]["EZDK"]["sourcing_decision"] = "cheapest"
        with pytest.raises(ValueError, match="illegal sourcing_decision"):
            ce._finished_material_price_sc1(state, "EZDK", "Rebar")

    def test_missing_decision_raises(self, state):
        del state["finished_products"]["Rebar"]["EZDK"]["sourcing_decision"]
        with pytest.raises(ValueError, match="illegal sourcing_decision"):
            ce._finished_material_price_sc1(state, "EZDK", "Rebar")


class TestStage3Rebar_Sc1:
    """Verification §3.1 Sc1 — Excel-independent rows only."""

    MATERIAL = {"EZDK": 409.52, "EFS": 467.96, "ERM": 590.00, "ESR": 450.31}
    YIELD_EFFECT = {"EZDK": 23.19, "EFS": 14.03, "ERM": 12.55, "ESR": 14.78}

    def test_material_price_row(self, state):
        for co, target in self.MATERIAL.items():
            out = ce.compute_finished_sc1(state, co, "Rebar")
            tol = _tol_for("finished_sc1", co, "material_price_usd_t")
            assert _usd_close(out["material_price_usd_t"], target, tol), (
                f"{co} Sc1 material {out['material_price_usd_t']:.4f} "
                f"vs {target} (±{tol})"
            )

    def test_yield_effect_row(self, state):
        for co, target in self.YIELD_EFFECT.items():
            out = ce.compute_finished_sc1(state, co, "Rebar")
            tol = _tol_for("finished_sc1", co, "yield_effect_usd_t")
            assert _usd_close(out["yield_effect_usd_t"], target, tol), (
                f"{co} Sc1 yield effect {out['yield_effect_usd_t']:.4f} "
                f"vs {target} (±{tol})"
            )

    def test_ezdk_home_scrap_deduction(self, state):
        # Engine: (−0.043 × 318.94) / 0.9464 = −14.4911 → −14.49 vs sheet
        # (14.48), inside the standard ±0.01-after-rounding tolerance.
        out = ce.compute_finished_sc1(state, "EZDK", "Rebar")
        assert _usd_close(out["home_scrap_deduction_usd_t"], -14.48)

    def test_currency_tags(self, state):
        for co in ("EZDK", "EFS", "ERM", "ESR"):
            assert ce.compute_finished_sc1(state, co, "Rebar")["_currency"] == "USD"


class TestStage3Rebar_Sc2:
    """Verification §3.1 Sc2 — Excel-independent rows only.

    EZDK Home Scrap and its cascaded cells (Total Conversion, Total VC,
    Difference) are PENDING-EXCEL-CONFIRMATION (group a) — not asserted.
    """

    YIELD_EFFECT = {"EZDK": 33.42, "EFS": 17.68, "ERM": 12.55, "ESR": 19.36}

    def test_material_price_row_is_market_590(self, state):
        for co in ("EZDK", "EFS", "ERM", "ESR"):
            out = ce.compute_finished_sc2(state, co, "Rebar")
            assert out["material_price_usd_t"] == 590

    def test_yield_effect_row(self, state):
        for co, target in self.YIELD_EFFECT.items():
            out = ce.compute_finished_sc2(state, co, "Rebar")
            tol = _tol_for("finished_sc2", co, "yield_effect_usd_t")
            assert _usd_close(out["yield_effect_usd_t"], target, tol), (
                f"{co} Sc2 yield effect {out['yield_effect_usd_t']:.4f} "
                f"vs {target} (±{tol})"
            )

    def test_erm_sc1_equals_sc2_invariant(self, state):
        # ERM defaults to market sourcing, so Sc1 and Sc2 are the same view.
        sc1 = ce.compute_finished_sc1(state, "ERM", "Rebar")
        sc2 = ce.compute_finished_sc2(state, "ERM", "Rebar")
        for cell in (
            "material_price_usd_t",
            "yield_effect_usd_t",
            "home_scrap_deduction_usd_t",
            "other_conversion_usd_t",
            "total_conversion_usd_t",
            "total_variable_mfg_usd_t",
        ):
            assert sc1[cell] == sc2[cell], cell

    def test_currency_tags(self, state):
        for co in ("EZDK", "EFS", "ERM", "ESR"):
            assert ce.compute_finished_sc2(state, co, "Rebar")["_currency"] == "USD"


class TestStage3WireRod_Structural:
    """Verification §3.2 gives no numeric targets; structural assertions only
    (item-4 ruling: data-gap note, no other-conversion component)."""

    def test_sc1_material_is_own_billet_vc(self, state):
        out = ce.compute_finished_sc1(state, "EZDK", "Wire Rod")
        own = ce.compute_billet_conversion(state, "EZDK")["total_variable_mfg_usd_t"]
        assert out["material_price_usd_t"] == own

    def test_yield_effect_derivation(self, state):
        out = ce.compute_finished_sc1(state, "EZDK", "Wire Rod")
        expected = out["material_price_usd_t"] * (1.0 / 0.9778 - 1.0)
        assert out["yield_effect_usd_t"] == pytest.approx(expected, abs=1e-9)

    def test_data_gap_mode_and_pending_components(self, state):
        out = ce.compute_finished_sc1(state, "EZDK", "Wire Rod")
        assert out["finished_mode"] == ce._FINISHED_MODE_DATA_GAP
        assert out["other_conversion_usd_t"] is None
        assert out["home_scrap_deduction_usd_t"] is None
        assert out["total_variable_mfg_usd_t"] is None
        assert any("data gap" in n for n in out["_notes"])

    def test_currency_tag(self, state):
        assert ce.compute_finished_sc1(state, "EZDK", "Wire Rod")["_currency"] == "USD"


class TestStage3HRC_Skeleton:
    """Verification §3.3 — step-4 skeleton.

    The sheet's Combined Yield cells (82.37 / 81.43) are NOT asserted: they
    disagree with the full-precision product of the displayed stage yields
    (82.4100 / 81.4611) AND with the sheet's own Yield Effect row, which
    reproduces only from the full-precision product. PENDING-EXCEL — see
    TESTING_NOTES.md "Step 4". The identity assertion below pins the engine
    formula; the sheet-cell assertion is wired once Excel adjudicates.
    """

    def test_combined_yield_identity(self, state):
        for co in ("EZDK", "EFS"):
            y = state["finished_products"]["HRC"][co]["yields"]
            out = ce.compute_hrc_summary(state, co)
            assert out["combined_yield"] == pytest.approx(
                y["eaf"] * y["tsc"] * y["hsm"], abs=1e-12
            )

    def test_blending_echo(self, state):
        out = ce.compute_hrc_summary(state, "EZDK")
        assert out["blending_pct"] == {
            "dri": 0.80, "local_scrap": 0.1796, "imported_scrap": 0.0204,
        }
        out = ce.compute_hrc_summary(state, "EFS")
        assert out["blending_pct"] == {
            "dri": 0.70, "local_scrap": 0.21, "imported_scrap": 0.09,
        }

    def test_pending_components_are_none_with_notes(self, state):
        for co in ("EZDK", "EFS"):
            out = ce.compute_hrc_summary(state, co)
            assert out["material_price_usd_t"] is None
            assert out["yield_effect_usd_t"] is None
            assert out["total_variable_mfg_usd_t"] is None
            # The §3.3 scalar seed is present (plumbing only, not asserted
            # against the sheet until the item-6 sub-step).
            assert out["other_conversion_usd_t"] is not None
            assert any("pending" in n for n in out["_notes"])

    def test_currency_tags(self, state):
        for co in ("EZDK", "EFS"):
            assert ce.compute_hrc_summary(state, co)["_currency"] == "USD"


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
