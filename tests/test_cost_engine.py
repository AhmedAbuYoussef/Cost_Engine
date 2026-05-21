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
_USD_TOL_OVERRIDES = {
    ("dri_conversion", "EZDK", "other_conversion_usd_t"):    ABS_TOL_USD_WIDE,
    ("dri_conversion", "EZDK", "total_conversion_usd_t"):    ABS_TOL_USD_WIDE,
    ("dri_conversion", "EZDK", "total_variable_mfg_usd_t"):  ABS_TOL_USD_WIDE,
    ("dri_conversion", "ERM",  "other_conversion_usd_t"):    ABS_TOL_USD_WIDE,
    ("dri_conversion", "ERM",  "total_conversion_usd_t"):    ABS_TOL_USD_WIDE,
    ("dri_conversion", "ERM",  "total_variable_mfg_usd_t"):  ABS_TOL_USD_WIDE,
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
