"""Pure-Python cost engine for the Ezz Steel financial model.

Implements Rulebook §3 (DRI), §4 (Billet), §5 (Finished Products), and the
six runtime integrity checks of Rulebook §12 / Step 1 brief §4.7. No I/O,
no globals, no hidden state — every calculation is a pure function of the
state dict passed in. Rounding is the caller's job (presentation layer);
the engine carries full float precision throughout.

The engine is strict on field access: missing fields raise KeyError or
StateValidationError. Sourcing-decision defaults are injected by
`state_manager.load_state`, not here.
"""

from __future__ import annotations

from typing import Any

from state_manager import (
    PRODUCTION_MATRIX,
    StateValidationError,
    assert_in_production_matrix,
)


class IntegrityError(Exception):
    """Raised when a runtime integrity check fails."""


# ---------------------------------------------------------------------------
# Stage 1 — DRI (Rulebook §3)
# ---------------------------------------------------------------------------

# Items that appear in the verification §1.2 detailed view, in display order.
# Maps display label -> (consumption key, unit-price key in EGP).
_DRI_CONVERSION_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("Electricity",       "electricity_kwh",      "electricity_egp_kwh"),
    ("Natural Gas",       "natural_gas_nm3",      "natural_gas_egp_nm3"),
    ("Oxygen",            "oxygen_nm3",           "oxygen_egp_nm3"),
    ("Nitrogen",          "nitrogen_nm3",         "nitrogen_egp_nm3"),
    ("Water",             "water_nm3",            "water_egp_nm3"),
    ("Chemicals",         "chemicals_t",          "chemicals_le_ton"),
    ("Spare Parts",       "spare_parts_t",        "spare_parts_le_ton"),
    ("External Services", "external_services_t",  "external_services_le_ton"),
    ("Other",             "other_t",              "other_le_ton"),
)


def _dri_iop_cost_le(mrmr: float, iop_le_ton: float) -> float:
    return mrmr * iop_le_ton


def _dri_conversion_line_le(consumption: float, unit_price_egp: float) -> float:
    return consumption * unit_price_egp


def _dri_variable_cost_le(company_dri: dict) -> float:
    iop = _dri_iop_cost_le(company_dri["mrmr"],
                           company_dri["unit_prices"]["iop_landed_egp_ton"])
    cons = company_dri["consumptions_per_ton_dri"]
    prices = company_dri["unit_prices"]
    conv = sum(_dri_conversion_line_le(cons[ck], prices[pk])
               for _, ck, pk in _DRI_CONVERSION_ITEMS)
    return iop + conv


def _dri_fixed_cost_le(fixed_costs_le: dict, production_volume_tons: float) -> dict:
    labor = fixed_costs_le["labor"] / production_volume_tons
    dep = fixed_costs_le["depreciation"] / production_volume_tons
    other = fixed_costs_le["other_fixed"] / production_volume_tons
    return {"labor_le_t": labor, "depreciation_le_t": dep, "other_fixed_le_t": other,
            "total_le_t": labor + dep + other}


def _dri_mrmr_effect_usd(mrmr: float, iop_usd_ton: float) -> float:
    return (mrmr - 1.0) * iop_usd_ton


def _dri_other_conversion_usd(variable_cost_le: float, iop_cost_le: float, fx: float) -> float:
    return (variable_cost_le - iop_cost_le) / fx


def compute_dri_detailed(state: dict, company: str) -> dict:
    """Verification §1.2 — detailed DRI cost in LE/t (native EGP view)."""
    if company not in state["entities"]["dri_producers"]:
        raise StateValidationError(f"{company} does not produce DRI")
    block = state["dri"][company]
    cons = block["consumptions_per_ton_dri"]
    prices = block["unit_prices"]

    iop_cost = _dri_iop_cost_le(block["mrmr"], prices["iop_landed_egp_ton"])
    items = {label: _dri_conversion_line_le(cons[ck], prices[pk])
             for label, ck, pk in _DRI_CONVERSION_ITEMS}
    variable_cost = iop_cost + sum(items.values())

    fixed = _dri_fixed_cost_le(block["fixed_costs_le"], block["production_volume_tons"])
    manuf_cost = variable_cost + fixed["total_le_t"]
    selling_price = block["selling_price_le_ton"]

    return {
        "_currency": "EGP",
        "_unit": "LE/t",
        "company": company,
        "iop_cost": iop_cost,
        "items": items,
        "variable_cost": variable_cost,
        "labor": fixed["labor_le_t"],
        "depreciation": fixed["depreciation_le_t"],
        "other_fixed": fixed["other_fixed_le_t"],
        "fixed_cost": fixed["total_le_t"],
        "manufacturing_cost": manuf_cost,
        "selling_price": selling_price,
        "gross_margin": selling_price - manuf_cost,
    }


def compute_dri_conversion(state: dict, company: str) -> dict:
    """Verification §1.3 — DRI conversion-cost view in $/t (USD-only)."""
    if company not in state["entities"]["dri_producers"]:
        raise StateValidationError(f"{company} does not produce DRI")
    block = state["dri"][company]
    fx = state["global"]["fx_rate_egp_usd"]
    iop_usd = block["unit_prices"]["iop_landed_usd_ton"]
    iop_le = block["unit_prices"]["iop_landed_egp_ton"]

    var_cost_le = _dri_variable_cost_le(block)
    iop_cost_le = _dri_iop_cost_le(block["mrmr"], iop_le)

    material = iop_usd
    mrmr_effect = _dri_mrmr_effect_usd(block["mrmr"], iop_usd)
    other_conversion = _dri_other_conversion_usd(var_cost_le, iop_cost_le, fx)
    total_conversion = mrmr_effect + other_conversion
    total_vc = material + total_conversion

    return {
        "_currency": "USD",
        "_unit": "$/t",
        "company": company,
        "material_price": material,
        "mrmr_effect": mrmr_effect,
        "other_conversion_cost": other_conversion,
        "total_conversion_cost": total_conversion,
        "total_variable_mfg_cost": total_vc,
    }
