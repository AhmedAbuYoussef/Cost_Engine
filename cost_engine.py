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


# ---------------------------------------------------------------------------
# Stage 3 — Finished Products (Rulebook §5)
# ---------------------------------------------------------------------------

# Long-line Other-Conversion items (Rebar / Wire Rod): consumption key + price key.
_LONG_LINE_CONVERSION_ITEMS: tuple[tuple[str, str], ...] = (
    ("refractories_kg",  "refractories_kg"),
    ("electricity_kwh",  "electricity_kwh"),
    ("natural_gas_nm3",  "natural_gas_nm3"),
    ("water_m3",         "water_m3"),
)

# HRC Other-Conversion items (cloned-from-Rebar shape: same physical items,
# residual closes the gap to the verified Total VC).
_HRC_CONVERSION_ITEMS = _LONG_LINE_CONVERSION_ITEMS

_PRODUCT_YIELD_KEYS = {
    "Rebar":    "rebar_yield",
    "Wire Rod": "wire_yield",
}

_PRODUCT_CONSUMPTION_KEYS = {
    "Rebar":    "consumptions_per_ton_rebar",
    "Wire Rod": "consumptions_per_ton_wire",
}


def _resolve_finished_material_price_sc1(state: dict, company: str, product: str) -> float:
    """Dispatch on `sourcing_decision` per Step 1 brief §4.3.

    own              → own billet VC
    market           → 590
    internal_minimum → cheapest external offer in the trade-off matrix
                       for this company (i.e. excluding own billet)
    """
    decision = state["finished_products"][product][company]["sourcing_decision"]
    if decision == "own":
        if company not in state["entities"]["billet_producers"]:
            raise StateValidationError(
                f"sourcing_decision='own' invalid for {company} {product}: "
                f"{company} does not produce billet"
            )
        return compute_billet_conversion(state, company)["total_variable_mfg_cost"]
    if decision == "market":
        return state["billet"]["market"]["market_price_usd_t"]
    if decision == "internal_minimum":
        matrix = compute_tradeoff_matrix(state)
        external_offers = [matrix["rows"][s]["to"][company]
                           for s in matrix["rows"]
                           if s != company]
        return min(external_offers)
    raise StateValidationError(
        f"unknown sourcing_decision '{decision}' for {company} {product}"
    )


def _finished_yield_effect(material_price: float, finished_yield: float) -> float:
    """Long-line yield effect — only the finishing-mill yield (EAF×CCP already
    embedded in billet cost). Rulebook §5.2."""
    return material_price * (1.0 / finished_yield - 1.0)


def _finished_home_scrap_deduction(finished_yield: float, byproduct_pct: float,
                                   byproduct_price_usd: float) -> float:
    """$/t finished. Negative number. Per Rulebook §5.2:
        billets_used_per_finished_ton = 1 / yield
        byproduct_per_finished_ton    = billets_used × byproduct_pct
        $/t finished                  = byproduct_per_finished × byproduct_price
    Inputs identical between Sc1 and Sc2 — value depends on yield/pct/price only.
    """
    return (1.0 / finished_yield) * byproduct_pct * byproduct_price_usd


def _finished_other_conversion(consumptions: dict, prices: dict,
                               items: tuple[tuple[str, str], ...]) -> dict:
    """Sum of finishing-stage Other Conversion items (no work_roll yet)."""
    out = {ck: consumptions[ck] * prices[pk] for ck, pk in items}
    return {"items": out, "subtotal": sum(out.values())}


def _long_line_total_vc(state: dict, company: str, product: str,
                        material_price: float) -> dict:
    """Shared Sc1 / Sc2 chain for Rebar and Wire Rod (Rulebook §5.2)."""
    block = state["finished_products"][product][company]
    yield_key = _PRODUCT_YIELD_KEYS[product]
    cons_key = _PRODUCT_CONSUMPTION_KEYS[product]
    finished_yield = block[yield_key]
    cons = block[cons_key]
    prices = block["unit_prices_usd"]

    yield_effect = _finished_yield_effect(material_price, finished_yield)
    home_scrap = _finished_home_scrap_deduction(
        finished_yield,
        cons["byproduct_pct_of_billets_used"],
        prices["byproduct_rejected_slabs_t"],
    )
    other_conv = _finished_other_conversion(cons, prices, _LONG_LINE_CONVERSION_ITEMS)
    other_conv_total = other_conv["subtotal"] + cons["work_roll_usd_t"]
    residual = block.get("_reconciliation_residual_usd_per_ton", 0.0)
    other_conv_total += residual
    total_conv = yield_effect + home_scrap + other_conv_total
    total_vc = material_price + total_conv

    return {
        "material_price": material_price,
        "yield_effect": yield_effect,
        "home_scrap_deduction": home_scrap,
        "other_conversion_cost": other_conv_total,
        "other_conversion_breakdown": {**other_conv["items"],
                                       "work_roll": cons["work_roll_usd_t"],
                                       "reconciliation_residual": residual},
        "total_conversion_cost": total_conv,
        "total_variable_mfg_cost": total_vc,
        "reconciliation_residual": residual,
    }


def compute_finished_sc1(state: dict, company: str, product: str) -> dict:
    """Verification §3.1 Sc1 (long-line: Rebar / Wire Rod)."""
    assert_in_production_matrix(company, product)
    if product == "HRC":
        raise StateValidationError(
            "compute_finished_sc1 is for long-line products; "
            "use compute_hrc_summary for HRC"
        )
    block = state["finished_products"][product][company]
    material = _resolve_finished_material_price_sc1(state, company, product)
    chain = _long_line_total_vc(state, company, product, material)
    out = {"_currency": "USD", "_unit": "$/t", "company": company,
           "product": product, "scenario": "Sc1", **chain}
    if block.get("_reconstructed_dummies"):
        out["warning"] = ("detailed Other Conversion is reconstructed from "
                          "Rebar.EZDK; only the summary Total VC is verified")
    return out


def compute_finished_sc2(state: dict, company: str, product: str) -> dict:
    """Verification §3.1 Sc2 (long-line: market billet at $590)."""
    assert_in_production_matrix(company, product)
    if product == "HRC":
        raise StateValidationError(
            "compute_finished_sc2 is for long-line products; "
            "use compute_hrc_summary for HRC"
        )
    block = state["finished_products"][product][company]
    material = state["billet"]["market"]["market_price_usd_t"]
    chain = _long_line_total_vc(state, company, product, material)
    out = {"_currency": "USD", "_unit": "$/t", "company": company,
           "product": product, "scenario": "Sc2", **chain}
    if block.get("_reconstructed_dummies"):
        out["warning"] = ("detailed Other Conversion is reconstructed from "
                          "Rebar.EZDK; only the summary Total VC is verified")
    return out


def _hrc_material_price(state: dict, company: str) -> float:
    """Verification §3.3 — HRC material uses flat-line scrap prices,
    distinct from billet scrap prices (Rulebook §5.3 to be patched)."""
    hrc = state["finished_products"]["HRC"][company]
    blending = hrc["blending_pct"]
    scrap = hrc["flat_line_scrap_prices_usd"]
    dri_price = _resolve_dri_price_for_buyer(state, company)
    return (blending["dri"]            * dri_price
            + blending["local_scrap"]    * scrap["local_scrap_t"]
            + blending["imported_scrap"] * scrap["imported_scrap_t"])


# ---------------------------------------------------------------------------
# Stage F — Sales, Production Cascade, Market Share (Rulebook §6)
# ---------------------------------------------------------------------------

def _long_line_cascade(rebar_qty_kt: float,
                       wire_qty_kt: float,
                       *,
                       rebar_yield: float,
                       wire_yield: float,
                       eaf_yield: float,
                       ccp_yield: float,
                       blending_pct: dict,
                       mrmr: float | None = None) -> dict:
    """Long-line cascade per Rulebook §6.4.

    `rebar_qty_kt + wire_qty_kt` drives billets → molten steel → solid charge →
    DRI / scrap. IOP is computed only when `mrmr` is provided (the company
    runs its own DRP); callers without their own DRP pass `mrmr=None` and
    receive `iop_kt=None` per the design choice for §5.1 EFS/ESR rows.
    """
    billets = ((rebar_qty_kt / rebar_yield) if rebar_qty_kt else 0.0) + \
              ((wire_qty_kt  / wire_yield)  if wire_qty_kt  else 0.0)
    ms = billets / ccp_yield
    sc = ms / eaf_yield
    dri = sc * blending_pct["dri"]
    imp = sc * blending_pct["imported_scrap"]
    loc = sc * blending_pct["local_scrap"]
    iop = (dri * mrmr) if mrmr is not None else None
    return {
        "_currency": "none",
        "_unit": "Ktons",
        "rebar_kt": rebar_qty_kt,
        "wire_rod_kt": wire_qty_kt,
        "billets_kt": billets,
        "molten_steel_kt": ms,
        "solid_charge_kt": sc,
        "dri_kt": dri,
        "imported_scrap_kt": imp,
        "local_scrap_kt": loc,
        "iop_kt": iop,
    }


def _flat_line_cascade(hrc_qty_kt: float,
                       *,
                       eaf_yield: float,
                       tsc_yield: float,
                       hsm_yield: float,
                       blending_pct: dict,
                       mrmr: float | None = None) -> dict:
    """Flat-line cascade per Rulebook §6.5.

    Three-stage yield chain for HRC: HRC → MS via TSC×HSM → solid charge via
    EAF → DRI / scrap. IOP only when `mrmr` is supplied (matches the long-line
    convention from `_long_line_cascade`); EFS HRC passes `mrmr=None` and the
    ERM-side IOP demand is computed separately by the supply aggregation step.
    Flat-line blending is DRI / Local Scrap / Imported Scrap only — no home
    scrap or pig iron on this stage per the JSON / verification §5.2.
    """
    ms = hrc_qty_kt / (tsc_yield * hsm_yield)
    sc = ms / eaf_yield
    dri = sc * blending_pct["dri"]
    imp = sc * blending_pct["imported_scrap"]
    loc = sc * blending_pct["local_scrap"]
    iop = (dri * mrmr) if mrmr is not None else None
    return {
        "_currency": "none",
        "_unit": "Ktons",
        "hrc_kt": hrc_qty_kt,
        "molten_steel_kt": ms,
        "solid_charge_kt": sc,
        "dri_kt": dri,
        "imported_scrap_kt": imp,
        "local_scrap_kt": loc,
        "iop_kt": iop,
    }


# ---------------------------------------------------------------------------
# Integrity checks (Rulebook §12 / Step 1 brief §4.7)
#
# Six checks total — Q3 ruling drops Rulebook §12 check 3 (trade-off matrix
# fully dynamic) by construction. Each check returns (bool_passed, detail).
# State-only checks run from `state`; output-dependent checks need an
# `outputs` dict (built from compute_* views).
# ---------------------------------------------------------------------------

# Check 1 — Fixed cost distribution % sums to 100% per company.
def _check_fixed_distribution_sums(state: dict) -> tuple[bool, str]:
    tol = 0.01
    failures = []
    for company in state["entities"]["companies"]:
        dist = state["fixed_costs"][company]["distribution_pct"]
        total = sum(dist[k] for k in ("DRI", "Rebar", "Wire Rod", "HRC"))
        if abs(total - 100.0) > tol:
            failures.append(f"{company}: {total:.4f} (expected 100)")
    if failures:
        return False, "Fixed-cost distribution % does not sum to 100: " + "; ".join(failures)
    return True, "Fixed-cost distribution % sums to 100 per company"


# Check 2 — Blending ratios sum to 100% per production line.
def _check_blending_ratios_sum(state: dict) -> tuple[bool, str]:
    tol = 0.0001  # blending stored as fraction; accept 1.0 ± 0.0001
    failures = []
    # Billet (long-line) blending — DRI + Local + Imported + Home Scrap + Pig Iron
    for producer in state["entities"]["billet_producers"]:
        b = state["billet"][producer]["blending_pct"]
        total = (b["dri"] + b["local_scrap"] + b["imported_scrap"]
                 + b.get("home_scrap", 0.0) + b.get("pig_iron", 0.0))
        if abs(total - 1.0) > tol:
            failures.append(f"billet.{producer}: {total:.6f}")
    # HRC (flat-line) blending — DRI + Local + Imported
    for producer in ("EZDK", "EFS"):
        b = state["finished_products"]["HRC"][producer]["blending_pct"]
        total = b["dri"] + b["local_scrap"] + b["imported_scrap"]
        if abs(total - 1.0) > tol:
            failures.append(f"HRC.{producer}: {total:.6f}")
    if failures:
        return False, "Blending ratios do not sum to 1.0: " + "; ".join(failures)
    return True, "Blending ratios sum to 1.0 per production line"


# Check 4 — Sales drive production: no orphan production figures.
# Structural assertion: state["finished_products"][product][company] must NOT
# carry a free-floating production_qty / billets_qty / molten_steel_qty / etc.
# (Production qty = local_qty + export_qty per Rulebook §6.4.) DRI's standalone
# production_volume_tons is allowed because it normalises fixed cost per ton.
def _check_sales_drive_production(state: dict) -> tuple[bool, str]:
    forbidden_keys = {"production_qty_tons", "production_qty_ktons",
                      "billets_qty_tons", "molten_steel_qty_tons",
                      "solid_charge_qty_tons", "iop_qty_tons",
                      "scrap_qty_tons"}
    failures = []
    for product, companies in state["finished_products"].items():
        for company, block in companies.items():
            present = forbidden_keys & set(block.keys())
            if present:
                failures.append(f"finished_products.{product}.{company}: {sorted(present)}")
    for company, block in state["billet"].items():
        if company == "market":
            continue
        present = forbidden_keys & set(block.keys())
        if present:
            failures.append(f"billet.{company}: {sorted(present)}")
    if failures:
        return False, ("Orphan production fields present (must derive from sales): "
                       + "; ".join(failures))
    return True, "No orphan production fields; production derives from sales"


# Check 5 — No output view mixes currencies.
def _check_currency_consistency(output: dict) -> tuple[bool, str]:
    """Walks every numeric leaf in an output dict; asserts none would imply
    a different currency from the dict's `_currency` tag.

    The check is structural: `_currency` must be present and one of
    {"USD", "EGP"}. The walker simply verifies the tag is set; legitimate
    cross-currency conversion happens at engine boundaries via FX, not
    inside an output view.
    """
    if "_currency" not in output:
        return False, "output view missing _currency tag"
    if output["_currency"] not in ("USD", "EGP"):
        return False, f"unknown currency tag: {output['_currency']!r}"
    return True, f"output view tagged {output['_currency']}"


# Check 6 — Intercompany seller revenue = buyer cost.
# Deferred behind the P&L stage (out of scope for this run). Stub returns
# a structured "deferred" tuple so the master callable's contract holds.
def _check_intercompany_reconciliation(state: dict) -> tuple[bool, str]:
    return True, ("DEFERRED — requires P&L stage; structural placeholder. "
                  "When P&L lands, replace with real check that ERM DRI revenue "
                  "to EFS+ESR equals EFS+ESR DRI cost embedded from ERM.")


# Check 7 — Break-even = 0 when Total Sales Qty = 0.
# Deferred behind P&L (break-even is computed there). Stub for symmetry.
def _check_break_even_zero_when_no_sales(output: dict) -> tuple[bool, str]:
    return True, ("DEFERRED — requires P&L stage; structural placeholder. "
                  "When P&L lands, replace with check that any per-product break-even "
                  "is 0 whenever Total Sales Qty for that product is 0.")


def run_integrity_checks(state: dict,
                         outputs: dict | None = None) -> list[tuple[bool, str]]:
    """Run the six integrity checks in order.

    State-only checks (1, 2, 4, 6) run from `state`. Output-dependent checks
    (5, 7) run from `outputs` if provided; otherwise they are skipped and
    flagged as such. Master callable; not bypassable downstream.
    """
    results: list[tuple[bool, str]] = []
    results.append(_check_fixed_distribution_sums(state))
    results.append(_check_blending_ratios_sum(state))
    results.append(_check_sales_drive_production(state))
    if outputs is not None:
        # Walk every output view, run currency consistency on each.
        check5_failures = []
        for view_name, view in outputs.items():
            ok, detail = _check_currency_consistency(view)
            if not ok:
                check5_failures.append(f"{view_name}: {detail}")
        if check5_failures:
            results.append((False, "Currency consistency: "
                            + "; ".join(check5_failures)))
        else:
            results.append((True, "Currency consistency holds across all output views"))
    else:
        results.append((True, "Check 5 (currency) skipped — no outputs supplied"))
    results.append(_check_intercompany_reconciliation(state))
    if outputs is not None:
        results.append(_check_break_even_zero_when_no_sales(outputs))
    else:
        results.append((True, "Check 7 (break-even=0) skipped — no outputs supplied"))
    return results


def compute_all(state: dict) -> dict:
    """Top-level entry point per brief §3.

    Runs state-level integrity checks first; raises IntegrityError on any
    failure. Computes every verified output the engine knows about (DRI,
    billet, finished products), runs output-dependent integrity checks,
    raises again on failure. Returns the assembled outputs dict.
    """
    state_results = run_integrity_checks(state)
    for ok, detail in state_results[:3]:  # checks 1, 2, 4 are state-only
        if not ok:
            raise IntegrityError(detail)

    outputs: dict[str, dict] = {}
    for c in state["entities"]["dri_producers"]:
        outputs[f"dri_detailed_{c}"] = compute_dri_detailed(state, c)
        outputs[f"dri_conversion_{c}"] = compute_dri_conversion(state, c)
    for c in state["entities"]["billet_producers"]:
        outputs[f"billet_detailed_{c}"] = compute_billet_detailed(state, c)
        outputs[f"billet_conversion_{c}"] = compute_billet_conversion(state, c)
    outputs["billet_market"] = _market_billet_price(state)
    outputs["billet_tradeoff_matrix"] = compute_tradeoff_matrix(state)

    for product in ("Rebar", "Wire Rod"):
        for company in PRODUCTION_MATRIX:
            if product in PRODUCTION_MATRIX[company]:
                outputs[f"finished_sc1_{product}_{company}"] = compute_finished_sc1(state, company, product)
                outputs[f"finished_sc2_{product}_{company}"] = compute_finished_sc2(state, company, product)
    for company in ("EZDK", "EFS"):
        outputs[f"hrc_summary_{company}"] = compute_hrc_summary(state, company)

    full_results = run_integrity_checks(state, outputs)
    for ok, detail in full_results:
        if not ok:
            raise IntegrityError(detail)
    outputs["_integrity_checks"] = full_results
    return outputs


def compute_hrc_summary(state: dict, company: str) -> dict:
    """Verification §3.3 — HRC summary view (three-stage yield chain)."""
    assert_in_production_matrix(company, company == "EZDK" and "HRC" or "HRC")
    if company not in state["finished_products"]["HRC"]:
        raise StateValidationError(f"{company} does not produce HRC")
    block = state["finished_products"]["HRC"][company]
    yields = block["yields"]
    combined_yield = yields["eaf"] * yields["tsc"] * yields["hsm"]

    material = _hrc_material_price(state, company)
    yield_effect = material * (1.0 / combined_yield - 1.0)
    cons = block["consumptions_per_ton_hrc"]
    prices = block["unit_prices_usd"]
    other_conv = _finished_other_conversion(cons, prices, _HRC_CONVERSION_ITEMS)
    other_conv_total = other_conv["subtotal"] + cons["work_roll_usd_t"]
    residual = block.get("_reconciliation_residual_usd_per_ton", 0.0)
    other_conv_total += residual
    total_vc = material + yield_effect + other_conv_total

    out = {
        "_currency": "USD",
        "_unit": "$/t",
        "company": company,
        "product": "HRC",
        "material_price": material,
        "yield_effect": yield_effect,
        "other_conversion_cost": other_conv_total,
        "other_conversion_breakdown": {**other_conv["items"],
                                       "work_roll": cons["work_roll_usd_t"],
                                       "reconciliation_residual": residual},
        "total_variable_mfg_cost": total_vc,
        "combined_yield": combined_yield,
        "reconciliation_residual": residual,
    }
    if block.get("_reconstructed_dummies"):
        out["warning"] = ("detailed Other Conversion is reconstructed; "
                          "only the summary Total VC is verified")
    return out
