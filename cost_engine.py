"""cost_engine.py — Ezz Steel financial model engine.

Pure-function design per step1_brief §3. Reads dict-slices of state, returns
dict-slices of outputs. No globals, no class state, no I/O, no randomness.
Every output dict carries a "_currency" tag declaring its native currency.

Step 1 scope: Stage 1 — DRI cost (Rulebook §3) only.
"""

from __future__ import annotations


class IntegrityError(Exception):
    """Raised by compute_all() when an integrity check fails."""


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — DRI (Rulebook §3)
# ─────────────────────────────────────────────────────────────────────────────


def _dri_iop_cost_le(mrmr: float, iop_le_ton: float) -> float:
    return mrmr * iop_le_ton


def _dri_conversion_line_le(consumption: float, unit_price_le: float) -> float:
    return consumption * unit_price_le


def _dri_variable_cost_le(company_dri_state: dict) -> float:
    mrmr = company_dri_state["mrmr"]
    prices = company_dri_state["unit_prices"]
    cons = company_dri_state["consumptions_per_ton_dri"]

    iop = _dri_iop_cost_le(mrmr, prices["iop_landed_egp_ton"])
    items = (
        _dri_conversion_line_le(cons["electricity_kwh"],       prices["electricity_egp_kwh"])
        + _dri_conversion_line_le(cons["natural_gas_nm3"],     prices["natural_gas_egp_nm3"])
        + _dri_conversion_line_le(cons["oxygen_nm3"],          prices["oxygen_egp_nm3"])
        + _dri_conversion_line_le(cons["nitrogen_nm3"],        prices["nitrogen_egp_nm3"])
        + _dri_conversion_line_le(cons["water_nm3"],           prices["water_egp_nm3"])
        + _dri_conversion_line_le(cons["chemicals_t"],         prices["chemicals_le_ton"])
        + _dri_conversion_line_le(cons["spare_parts_t"],       prices["spare_parts_le_ton"])
        + _dri_conversion_line_le(cons["external_services_t"], prices["external_services_le_ton"])
        + _dri_conversion_line_le(cons["other_t"],             prices["other_le_ton"])
    )
    return iop + items


def _dri_fixed_cost_le(fixed_costs_le: dict, production_volume: float) -> float:
    return (
        fixed_costs_le["labor"]
        + fixed_costs_le["depreciation"]
        + fixed_costs_le["other_fixed"]
    ) / production_volume


def _dri_mrmr_effect_usd(mrmr: float, iop_usd_ton: float) -> float:
    return (mrmr - 1.0) * iop_usd_ton


def _dri_other_conversion_usd(variable_cost_le: float, iop_cost_le: float, fx: float) -> float:
    return (variable_cost_le - iop_cost_le) / fx


def compute_dri_detailed(state: dict, company: str) -> dict:
    """Verification §1.2 — DRI detailed (LE/t). Native EGP."""
    dri = state["dri"][company]
    prices = dri["unit_prices"]
    cons = dri["consumptions_per_ton_dri"]
    fixed = dri["fixed_costs_le"]
    mrmr = dri["mrmr"]
    volume = dri["production_volume_tons"]
    selling = dri["selling_price_le_ton"]

    iop_cost = _dri_iop_cost_le(mrmr, prices["iop_landed_egp_ton"])
    electricity = _dri_conversion_line_le(cons["electricity_kwh"],       prices["electricity_egp_kwh"])
    natural_gas = _dri_conversion_line_le(cons["natural_gas_nm3"],       prices["natural_gas_egp_nm3"])
    oxygen      = _dri_conversion_line_le(cons["oxygen_nm3"],            prices["oxygen_egp_nm3"])
    nitrogen    = _dri_conversion_line_le(cons["nitrogen_nm3"],          prices["nitrogen_egp_nm3"])
    water       = _dri_conversion_line_le(cons["water_nm3"],             prices["water_egp_nm3"])
    chemicals   = _dri_conversion_line_le(cons["chemicals_t"],           prices["chemicals_le_ton"])
    spare_parts = _dri_conversion_line_le(cons["spare_parts_t"],         prices["spare_parts_le_ton"])
    external    = _dri_conversion_line_le(cons["external_services_t"],   prices["external_services_le_ton"])
    other       = _dri_conversion_line_le(cons["other_t"],               prices["other_le_ton"])

    variable_cost = (
        iop_cost + electricity + natural_gas + oxygen + nitrogen + water
        + chemicals + spare_parts + external + other
    )
    labor       = fixed["labor"] / volume
    depreciation = fixed["depreciation"] / volume
    other_fixed = fixed["other_fixed"] / volume
    fixed_cost = labor + depreciation + other_fixed
    manufacturing_cost = variable_cost + fixed_cost
    gross_margin = selling - manufacturing_cost

    return {
        "iop_cost_le_t":            iop_cost,
        "electricity_le_t":         electricity,
        "natural_gas_le_t":         natural_gas,
        "oxygen_le_t":              oxygen,
        "nitrogen_le_t":            nitrogen,
        "water_le_t":               water,
        "chemicals_le_t":           chemicals,
        "spare_parts_le_t":         spare_parts,
        "external_services_le_t":   external,
        "other_le_t":               other,
        "variable_cost_le_t":       variable_cost,
        "labor_le_t":               labor,
        "depreciation_le_t":        depreciation,
        "other_fixed_le_t":         other_fixed,
        "fixed_cost_le_t":          fixed_cost,
        "manufacturing_cost_le_t":  manufacturing_cost,
        "dri_selling_price_le_t":   selling,
        "gross_margin_le_t":        gross_margin,
        "_currency":                "EGP",
    }


def compute_dri_conversion(state: dict, company: str) -> dict:
    """Verification §1.3 — DRI conversion view ($/t). Native USD."""
    dri = state["dri"][company]
    fx = state["global"]["fx_rate_egp_usd"]
    mrmr = dri["mrmr"]
    iop_usd = dri["unit_prices"]["iop_landed_usd_ton"]

    iop_cost_le = _dri_iop_cost_le(mrmr, dri["unit_prices"]["iop_landed_egp_ton"])
    variable_cost_le = _dri_variable_cost_le(dri)

    material_price = iop_usd
    mrmr_effect    = _dri_mrmr_effect_usd(mrmr, iop_usd)
    other_conv     = _dri_other_conversion_usd(variable_cost_le, iop_cost_le, fx)
    total_conv     = mrmr_effect + other_conv
    total_vc       = material_price + total_conv

    return {
        "material_price_usd_t":           material_price,
        "mrmr_effect_usd_t":              mrmr_effect,
        "other_conversion_cost_usd_t":    other_conv,
        "total_conversion_cost_usd_t":    total_conv,
        "total_variable_mfg_cost_usd_t":  total_vc,
        "_currency":                      "USD",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Integrity checks (stub — wired progressively in later build-order steps)
# ─────────────────────────────────────────────────────────────────────────────


def run_integrity_checks(state: dict, outputs: dict | None = None) -> list[tuple[bool, str]]:
    """Step 1 stub. The six checks land in steps 2, 5, 6, 7, 8 per brief §9."""
    return []
