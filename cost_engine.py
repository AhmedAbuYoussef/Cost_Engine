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


# ---------------------------------------------------------------------------
# Stage 2 — Billet (Rulebook §4)
# ---------------------------------------------------------------------------

# EAF conversion items: (consumption key, unit-price key)
_EAF_CONVERSION_ITEMS: tuple[tuple[str, str], ...] = (
    ("aux_materials_kg",       "aux_materials_kg"),
    ("refractories_kg",        "refractories_kg"),
    ("electrodes_kg",          "electrodes_kg"),
    ("other_fillers_kg",       "other_fillers_kg"),
    ("electricity_eaf_lf_kwh", "electricity_kwh"),
    ("electricity_aux_kwh",    "electricity_kwh"),
    ("natural_gas_nm3",        "natural_gas_nm3"),
    ("water_m3",               "water_m3"),
    ("oxygen_nm3",             "oxygen_nm3"),
    ("nitrogen_nm3",           "nitrogen_nm3"),
    ("argon_nm3",              "argon_nm3"),
    ("handling_kg",            "handling_kg"),
    ("cutting_kg",             "cutting_kg"),
)

# BCCM items beyond the carried MS cost and the byproduct credit.
_BCCM_CONVERSION_ITEMS: tuple[tuple[str, str], ...] = (
    ("aux_materials_kg", "aux_materials_kg"),
    ("refractories_kg",  "refractories_kg"),
    ("electricity_kwh",  "electricity_kwh"),
    ("natural_gas_nm3",  "natural_gas_nm3"),
    ("water_m3",         "water_m3"),
    ("oxygen_nm3",       "oxygen_nm3"),
    ("nitrogen_nm3",     "nitrogen_nm3"),
    ("argon_nm3",        "argon_nm3"),
)


def _resolve_dri_price_for_buyer(state: dict, buyer: str) -> float:
    """DRI transfer price into a billet producer's EAF (Rulebook §4.5)."""
    if buyer == "EZDK":
        return compute_dri_conversion(state, "EZDK")["total_variable_mfg_cost"]
    if buyer == "EFS":
        return compute_dri_conversion(state, "ERM")["total_variable_mfg_cost"]
    if buyer == "ESR":
        erm_vc = compute_dri_conversion(state, "ERM")["total_variable_mfg_cost"]
        margin = state["intercompany"]["dri_margin_usd_t"]["ERM_to_ESR"]
        return erm_vc + margin
    raise StateValidationError(f"DRI price resolution unknown for buyer '{buyer}'")


def _eaf_material_cost_per_ton_ms(blending_pct: dict, scrap_prices: dict,
                                  eaf_yield: float, dri_price_usd: float) -> dict:
    """Material cost per ton of MS, broken out per material plus subtotal.

    Per Rulebook §4.2: each material's $/t MS = (Blending % ÷ EAF Yield) × Unit Price.
    """
    contributions = {
        "DRI":            (blending_pct["dri"]            / eaf_yield) * dri_price_usd,
        "Local Scrap":    (blending_pct["local_scrap"]    / eaf_yield) * scrap_prices["local_scrap_t"],
        "Imported Scrap": (blending_pct["imported_scrap"] / eaf_yield) * scrap_prices["imported_scrap_t"],
        "Home Scrap":     (blending_pct.get("home_scrap", 0.0) / eaf_yield) * scrap_prices.get("home_scrap_t", 0.0),
        "Pig Iron":       (blending_pct.get("pig_iron",  0.0) / eaf_yield) * scrap_prices.get("pig_iron_t", 0.0),
    }
    return {"items": contributions, "total": sum(contributions.values())}


def _eaf_byproduct_credit(byproduct_pct_of_sc: float, byproduct_price_usd: float,
                          eaf_yield: float) -> float:
    """Byproduct credit per ton MS (Rulebook §4.2). Negative number."""
    return (byproduct_pct_of_sc / eaf_yield) * byproduct_price_usd


def _eaf_conversion_cost_per_ton_ms(consumptions: dict, prices: dict) -> dict:
    """Sum of EAF conversion items per ton MS (excluding materials + byproduct)."""
    items = {ck: consumptions[ck] * prices[pk] for ck, pk in _EAF_CONVERSION_ITEMS}
    return {"items": items, "total": sum(items.values())}


def _eaf_variable_cost_per_ton_ms(billet_block: dict, dri_price_usd: float) -> dict:
    eaf_yield = billet_block["yields"]["eaf"]
    blending = billet_block["blending_pct"]
    cons = billet_block["eaf_consumptions_per_ton_ms"]
    prices = billet_block["eaf_unit_prices_usd"]

    materials = _eaf_material_cost_per_ton_ms(blending, prices, eaf_yield, dri_price_usd)
    byproduct = _eaf_byproduct_credit(cons["byproduct_pct_of_sc"], prices["byproduct_t"], eaf_yield)
    conversion = _eaf_conversion_cost_per_ton_ms(cons, prices)
    return {
        "materials": materials,
        "byproduct_credit": byproduct,
        "conversion": conversion,
        "total": materials["total"] + byproduct + conversion["total"],
    }


def _bccm_variable_cost_per_ton_billet(ms_vc_per_ton_ms: float, billet_block: dict) -> dict:
    ccp_yield = billet_block["yields"]["ccp"]
    cons = billet_block["bccm_consumptions_per_ton_billet"]
    prices = billet_block["bccm_unit_prices_usd"]

    ms_carried = ms_vc_per_ton_ms / ccp_yield
    byproduct_crops = (cons["byproduct_crops_pct_of_ms"] / ccp_yield) * prices["byproduct_crops_t"]
    items = {ck: cons[ck] * prices[pk] for ck, pk in _BCCM_CONVERSION_ITEMS}
    items_total = sum(items.values())
    return {
        "ms_carried": ms_carried,
        "byproduct_crops": byproduct_crops,
        "items": items,
        "items_total": items_total,
        "total": ms_carried + byproduct_crops + items_total,
    }


def compute_billet_detailed(state: dict, company: str) -> dict:
    """Verification §2 detailed view: full EAF + BCCM build-up.

    For EFS and ESR the underlying consumptions are reconstructed dummies
    (Rulebook §13 known data gap). The output dict surfaces this via a
    `warning` field so the caller does not present it as audited detail.
    """
    if company not in state["entities"]["billet_producers"]:
        raise StateValidationError(f"{company} does not produce billet")
    block = state["billet"][company]

    dri_price = _resolve_dri_price_for_buyer(state, company)
    eaf = _eaf_variable_cost_per_ton_ms(block, dri_price)
    bccm = _bccm_variable_cost_per_ton_billet(eaf["total"], block)
    residual = block.get("_reconciliation_residual_usd_per_ton", 0.0)
    total = bccm["total"] + residual

    out = {
        "_currency": "USD",
        "_unit": "$/t",
        "company": company,
        "dri_price_used": dri_price,
        "eaf": eaf,
        "bccm": bccm,
        "reconciliation_residual": residual,
        "total_variable_mfg_cost": total,
    }
    if block.get("_reconstructed_dummies"):
        out["warning"] = ("detailed breakdown is reconstructed; only the "
                          "summary total is verified")
    return out


def _billet_material_price_summary(blending_pct: dict, dri_price_usd: float,
                                   local_scrap_price: float,
                                   imported_scrap_price: float) -> float:
    """Rulebook §4.4 summary view — weighted average over blending fractions
    of DRI / Local Scrap / Imported Scrap, NOT divided by EAF yield."""
    return (blending_pct["dri"]            * dri_price_usd
            + blending_pct["local_scrap"]    * local_scrap_price
            + blending_pct["imported_scrap"] * imported_scrap_price)


def _billet_yield_effect(material_price: float, combined_yield: float) -> float:
    return material_price * (1.0 / combined_yield - 1.0)


def compute_billet_conversion(state: dict, company: str) -> dict:
    """Verification §2.2 — billet conversion-cost view (USD/t)."""
    if company not in state["entities"]["billet_producers"]:
        raise StateValidationError(f"{company} does not produce billet")
    block = state["billet"][company]
    eaf_yield = block["yields"]["eaf"]
    ccp_yield = block["yields"]["ccp"]
    blending = block["blending_pct"]
    prices = block["eaf_unit_prices_usd"]

    dri_price = _resolve_dri_price_for_buyer(state, company)
    material = _billet_material_price_summary(blending, dri_price,
                                              prices["local_scrap_t"],
                                              prices["imported_scrap_t"])
    combined_yield = eaf_yield * ccp_yield
    yield_effect = _billet_yield_effect(material, combined_yield)
    total_vc = compute_billet_detailed(state, company)["total_variable_mfg_cost"]
    other_conversion = total_vc - material - yield_effect
    total_conversion = yield_effect + other_conversion

    out = {
        "_currency": "USD",
        "_unit": "$/t",
        "company": company,
        "material_price": material,
        "yield_effect": yield_effect,
        "other_conversion_cost": other_conversion,
        "total_conversion_cost": total_conversion,
        "total_variable_mfg_cost": total_vc,
    }
    if block.get("_reconstructed_dummies"):
        out["warning"] = ("Other Conversion includes a reconciliation "
                          "residual; underlying consumption decimals are "
                          "reconstructed dummies (Rulebook §13)")
    return out


def _intercompany_billet_price(seller_vc: float, seller_tradeoff_ratio: float) -> float:
    """Rulebook §4.6: cross-sell intercompany billet price."""
    return seller_vc * seller_tradeoff_ratio


def _market_billet_price(state: dict) -> dict:
    market = state["billet"]["market"]
    components = market["components_usd_t"]
    base = components["base"]
    safe = components["safe_guards"]
    other = components["other_costs"]
    total = market["market_price_usd_t"]
    if abs((base + safe + other) - total) > 1e-6:
        raise IntegrityError(
            f"Market billet build-up does not reconcile: "
            f"{base} + {safe} + {other} = {base + safe + other} ≠ {total}"
        )
    return {
        "_currency": "USD",
        "_unit": "$/t",
        "base": base,
        "safe_guards": safe,
        "other_costs": other,
        "market_price": total,
    }


def compute_tradeoff_matrix(state: dict) -> dict:
    """Verification §2.3 — fully dynamic intercompany billet matrix.

    Rows: producers (EZDK, EFS, ESR) and Market.
    Cols: all four companies as buyers (EZDK, EFS, ERM, ESR).
    Diagonal entries (producer buying own billet) use the producer's own VC.
    Off-diagonal: own VC × seller tradeoff ratio. Market: 590 across.
    """
    buyers = list(state["entities"]["companies"])
    sellers = list(state["entities"]["billet_producers"])

    own_vc = {s: compute_billet_conversion(state, s)["total_variable_mfg_cost"]
              for s in sellers}
    ratios = {s: state["billet"][s]["trade_off_ratio"] for s in sellers}
    market_price = state["billet"]["market"]["market_price_usd_t"]

    rows: dict[str, dict] = {}
    for s in sellers:
        offer = _intercompany_billet_price(own_vc[s], ratios[s])
        rows[s] = {
            "price_external_usd_t": offer,
            "to": {b: (own_vc[s] if b == s else offer) for b in buyers},
        }
    rows["Market"] = {
        "price_external_usd_t": market_price,
        "to": {b: market_price for b in buyers},
    }

    minima = {b: min(rows[s]["to"][b] for s in rows) for b in buyers}
    return {
        "_currency": "USD",
        "_unit": "$/t",
        "buyers": buyers,
        "sources": list(rows.keys()),
        "rows": rows,
        "minima": minima,
        "own_vc": own_vc,
    }
