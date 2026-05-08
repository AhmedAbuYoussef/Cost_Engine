"""Pure-function calculation engine for the Ezz Steel pricing model.

Implements the formulas in EzzSteel_FinancialModel_Rulebook.md for Stages 1–3,
production cascade, fixed-cost allocation, and the standalone / consolidated
P&L. State flows in as a dict (shape of model_initial_state.json); outputs
flow out as dicts. Full float precision throughout — no rounding inside the
engine.

Currency-tag convention (integrity check 5): every output-producing function
returns a dict carrying ``_currency`` set to one of ``{"USD", "EGP",
"physical"}``. The runtime walker descends into USD/EGP subtrees and verifies
each numeric leaf; ``physical`` subtrees (production cascade) are skipped.
A nested tag overrides the parent tag for its subtree.
"""

from __future__ import annotations


class IntegrityError(Exception):
    """Raised when any of the six integrity checks fails."""


# ----------------------------------------------------------------------------
# Stage 1 — DRI (Rulebook §3)
# ----------------------------------------------------------------------------


def _dri_iop_cost_le(mrmr: float, iop_le_ton: float) -> float:
    return mrmr * iop_le_ton


def _dri_conversion_line_le(consumption: float, unit_price: float) -> float:
    return consumption * unit_price


def _dri_variable_cost_le(company_dri_state: dict) -> float:
    cons = company_dri_state["consumptions_per_ton_dri"]
    prices = company_dri_state["unit_prices"]
    iop = _dri_iop_cost_le(company_dri_state["mrmr"], prices["iop_landed_egp_ton"])
    conversion = (
        _dri_conversion_line_le(cons["electricity_kwh"], prices["electricity_egp_kwh"])
        + _dri_conversion_line_le(cons["natural_gas_nm3"], prices["natural_gas_egp_nm3"])
        + _dri_conversion_line_le(cons["oxygen_nm3"], prices["oxygen_egp_nm3"])
        + _dri_conversion_line_le(cons["nitrogen_nm3"], prices["nitrogen_egp_nm3"])
        + _dri_conversion_line_le(cons["water_nm3"], prices["water_egp_nm3"])
        + _dri_conversion_line_le(cons["chemicals_t"], prices["chemicals_le_ton"])
        + _dri_conversion_line_le(cons["spare_parts_t"], prices["spare_parts_le_ton"])
        + _dri_conversion_line_le(cons["external_services_t"], prices["external_services_le_ton"])
        + _dri_conversion_line_le(cons["other_t"], prices["other_le_ton"])
    )
    return iop + conversion


def _dri_fixed_cost_le(fixed_costs_le: dict, production_volume_tons: float) -> float:
    total = (
        fixed_costs_le["labor"]
        + fixed_costs_le["depreciation"]
        + fixed_costs_le["other_fixed"]
    )
    return total / production_volume_tons


def _dri_mrmr_effect_usd(mrmr: float, iop_usd_ton: float) -> float:
    return (mrmr - 1.0) * iop_usd_ton


def _dri_other_conversion_usd(variable_cost_le: float, iop_cost_le: float, fx: float) -> float:
    return (variable_cost_le - iop_cost_le) / fx


def compute_dri_detailed(state: dict, company: str) -> dict:
    """Verification §1.2 — DRI detailed cost sheet, EGP-native."""
    dri = state["dri"][company]
    cons = dri["consumptions_per_ton_dri"]
    prices = dri["unit_prices"]
    fixed = dri["fixed_costs_le"]
    volume = dri["production_volume_tons"]

    iop_cost = _dri_iop_cost_le(dri["mrmr"], prices["iop_landed_egp_ton"])
    electricity = _dri_conversion_line_le(cons["electricity_kwh"], prices["electricity_egp_kwh"])
    natural_gas = _dri_conversion_line_le(cons["natural_gas_nm3"], prices["natural_gas_egp_nm3"])
    oxygen = _dri_conversion_line_le(cons["oxygen_nm3"], prices["oxygen_egp_nm3"])
    nitrogen = _dri_conversion_line_le(cons["nitrogen_nm3"], prices["nitrogen_egp_nm3"])
    water = _dri_conversion_line_le(cons["water_nm3"], prices["water_egp_nm3"])
    chemicals = _dri_conversion_line_le(cons["chemicals_t"], prices["chemicals_le_ton"])
    spare_parts = _dri_conversion_line_le(cons["spare_parts_t"], prices["spare_parts_le_ton"])
    external_services = _dri_conversion_line_le(
        cons["external_services_t"], prices["external_services_le_ton"]
    )
    other = _dri_conversion_line_le(cons["other_t"], prices["other_le_ton"])

    variable_cost = _dri_variable_cost_le(dri)

    labor_per_ton = fixed["labor"] / volume
    depreciation_per_ton = fixed["depreciation"] / volume
    other_fixed_per_ton = fixed["other_fixed"] / volume
    fixed_cost = _dri_fixed_cost_le(fixed, volume)

    manuf_cost = variable_cost + fixed_cost
    selling_price = dri["selling_price_le_ton"]
    gross_margin = selling_price - manuf_cost

    return {
        "_currency": "EGP",
        "iop_cost": iop_cost,
        "electricity": electricity,
        "natural_gas": natural_gas,
        "oxygen": oxygen,
        "nitrogen": nitrogen,
        "water": water,
        "chemicals": chemicals,
        "spare_parts": spare_parts,
        "external_services": external_services,
        "other": other,
        "variable_cost": variable_cost,
        "labor": labor_per_ton,
        "depreciation": depreciation_per_ton,
        "other_fixed": other_fixed_per_ton,
        "fixed_cost": fixed_cost,
        "manuf_cost": manuf_cost,
        "selling_price": selling_price,
        "gross_margin": gross_margin,
    }


def compute_dri_conversion(state: dict, company: str) -> dict:
    """Verification §1.3 — DRI conversion-cost view, USD-native."""
    fx = state["global"]["fx_rate_egp_usd"]
    dri = state["dri"][company]
    prices = dri["unit_prices"]
    mrmr = dri["mrmr"]

    material_price = prices["iop_landed_usd_ton"]
    mrmr_effect = _dri_mrmr_effect_usd(mrmr, material_price)

    iop_cost_le = _dri_iop_cost_le(mrmr, prices["iop_landed_egp_ton"])
    variable_cost_le = _dri_variable_cost_le(dri)
    other_conversion = _dri_other_conversion_usd(variable_cost_le, iop_cost_le, fx)
    total_conversion = mrmr_effect + other_conversion
    total_variable_mfg = material_price + total_conversion

    return {
        "_currency": "USD",
        "material_price": material_price,
        "mrmr_effect": mrmr_effect,
        "other_conversion": other_conversion,
        "total_conversion": total_conversion,
        "total_variable_mfg": total_variable_mfg,
    }
