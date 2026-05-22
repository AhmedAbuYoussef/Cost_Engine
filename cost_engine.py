"""
cost_engine.py — Ezz Steel Pricing Model deterministic calculation engine.

Pure-Python, dependency-free. State flows in as a dict, outputs flow out as a
dict. No globals, no class state, no I/O inside calculation functions, no LLM
calls. Same state in → same outputs out.

Full precision is held in float throughout; rounding is the caller's job per
Rulebook §2.3. Every output dict carries a `_currency` tag ("USD" or "EGP").

Stage 1 (DRI) implemented per Rulebook §3 and step1_brief_cost_engine_v2.md §4.1.
Subsequent stages added in build order §9.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Stage 1 — DRI (Rulebook §3)
# ---------------------------------------------------------------------------

_DRI_PRODUCERS = ("EZDK", "ERM")


def _require_dri_producer(company: str) -> None:
    if company not in _DRI_PRODUCERS:
        raise ValueError(
            f"structural_non_existence: DRI is produced only by "
            f"{_DRI_PRODUCERS}; requested '{company}'."
        )


def _dri_iop_cost_le(mrmr: float, iop_le_ton: float) -> float:
    return mrmr * iop_le_ton


def _dri_conversion_line_le(consumption: float, unit_price: float) -> float:
    return consumption * unit_price


def _dri_variable_cost_le(company_dri_state: dict) -> float:
    cons = company_dri_state["consumptions_per_ton_dri"]
    px = company_dri_state["unit_prices"]
    iop = _dri_iop_cost_le(company_dri_state["mrmr"], px["iop_landed_egp_ton"])
    items = (
        _dri_conversion_line_le(cons["electricity_kwh"],     px["electricity_egp_kwh"])
        + _dri_conversion_line_le(cons["natural_gas_nm3"],   px["natural_gas_egp_nm3"])
        + _dri_conversion_line_le(cons["oxygen_nm3"],        px["oxygen_egp_nm3"])
        + _dri_conversion_line_le(cons["nitrogen_nm3"],      px["nitrogen_egp_nm3"])
        + _dri_conversion_line_le(cons["water_nm3"],         px["water_egp_nm3"])
        + _dri_conversion_line_le(cons["chemicals_t"],       px["chemicals_le_ton"])
        + _dri_conversion_line_le(cons["spare_parts_t"],     px["spare_parts_le_ton"])
        + _dri_conversion_line_le(cons["external_services_t"], px["external_services_le_ton"])
        + _dri_conversion_line_le(cons["other_t"],           px["other_le_ton"])
    )
    return iop + items


def _dri_fixed_cost_le(fixed_costs_le: dict, production_volume_tons: float) -> dict:
    labor = fixed_costs_le["labor"] / production_volume_tons
    depreciation = fixed_costs_le["depreciation"] / production_volume_tons
    other_fixed = fixed_costs_le["other_fixed"] / production_volume_tons
    return {
        "labor_le_t": labor,
        "depreciation_le_t": depreciation,
        "other_fixed_le_t": other_fixed,
        "total_le_t": labor + depreciation + other_fixed,
    }


def _dri_mrmr_effect_usd(mrmr: float, iop_usd_ton: float) -> float:
    return (mrmr - 1.0) * iop_usd_ton


def _dri_other_conversion_usd(variable_cost_le: float, iop_cost_le: float, fx: float) -> float:
    # Σ conversion items (LE/t) ÷ FX, where Σ items = VC − IOP per Rulebook §3.1
    return (variable_cost_le - iop_cost_le) / fx


def compute_dri_detailed(state: dict, company: str) -> dict:
    """Verification §1.2 — full LE/t breakdown for a DRI producer."""
    _require_dri_producer(company)
    d = state["dri"][company]
    cons = d["consumptions_per_ton_dri"]
    px = d["unit_prices"]

    iop_le = _dri_iop_cost_le(d["mrmr"], px["iop_landed_egp_ton"])
    elec_le = _dri_conversion_line_le(cons["electricity_kwh"],     px["electricity_egp_kwh"])
    ng_le   = _dri_conversion_line_le(cons["natural_gas_nm3"],     px["natural_gas_egp_nm3"])
    ox_le   = _dri_conversion_line_le(cons["oxygen_nm3"],          px["oxygen_egp_nm3"])
    n2_le   = _dri_conversion_line_le(cons["nitrogen_nm3"],        px["nitrogen_egp_nm3"])
    h2o_le  = _dri_conversion_line_le(cons["water_nm3"],           px["water_egp_nm3"])
    chem_le = _dri_conversion_line_le(cons["chemicals_t"],         px["chemicals_le_ton"])
    sp_le   = _dri_conversion_line_le(cons["spare_parts_t"],       px["spare_parts_le_ton"])
    es_le   = _dri_conversion_line_le(cons["external_services_t"], px["external_services_le_ton"])
    other_le = _dri_conversion_line_le(cons["other_t"],            px["other_le_ton"])

    vc_le = iop_le + elec_le + ng_le + ox_le + n2_le + h2o_le + chem_le + sp_le + es_le + other_le
    fc = _dri_fixed_cost_le(d["fixed_costs_le"], d["production_volume_tons"])
    manuf_le = vc_le + fc["total_le_t"]
    selling_le = d["selling_price_le_ton"]
    gross_margin_le = selling_le - manuf_le

    return {
        "_currency": "EGP",
        "company": company,
        "iop_cost_le_t": iop_le,
        "electricity_le_t": elec_le,
        "natural_gas_le_t": ng_le,
        "oxygen_le_t": ox_le,
        "nitrogen_le_t": n2_le,
        "water_le_t": h2o_le,
        "chemicals_le_t": chem_le,
        "spare_parts_le_t": sp_le,
        "external_services_le_t": es_le,
        "other_le_t": other_le,
        "variable_cost_le_t": vc_le,
        "labor_le_t": fc["labor_le_t"],
        "depreciation_le_t": fc["depreciation_le_t"],
        "other_fixed_le_t": fc["other_fixed_le_t"],
        "fixed_cost_le_t": fc["total_le_t"],
        "manufacturing_cost_le_t": manuf_le,
        "dri_selling_price_le_t": selling_le,
        "gross_margin_le_t": gross_margin_le,
    }


def compute_dri_conversion(state: dict, company: str) -> dict:
    """Verification §1.3 — USD/t conversion-cost view for a DRI producer."""
    _require_dri_producer(company)
    d = state["dri"][company]
    fx = state["global"]["fx_rate_egp_usd"]

    iop_usd = d["unit_prices"]["iop_landed_usd_ton"]
    iop_le = _dri_iop_cost_le(d["mrmr"], d["unit_prices"]["iop_landed_egp_ton"])
    vc_le = _dri_variable_cost_le(d)

    material_usd = iop_usd
    mrmr_effect_usd = _dri_mrmr_effect_usd(d["mrmr"], iop_usd)
    other_conv_usd = _dri_other_conversion_usd(vc_le, iop_le, fx)
    total_conv_usd = mrmr_effect_usd + other_conv_usd
    total_vc_usd = material_usd + total_conv_usd

    return {
        "_currency": "USD",
        "company": company,
        "material_price_usd_t": material_usd,
        "mrmr_effect_usd_t": mrmr_effect_usd,
        "other_conversion_usd_t": other_conv_usd,
        "total_conversion_usd_t": total_conv_usd,
        "total_variable_mfg_usd_t": total_vc_usd,
    }


# ---------------------------------------------------------------------------
# Stage 2 — Billet (Rulebook §4)
# ---------------------------------------------------------------------------

_BILLET_PRODUCERS = ("EZDK", "EFS", "ESR")
_ALL_COMPANIES = ("EZDK", "EFS", "ERM", "ESR")


def _require_billet_producer(company: str) -> None:
    if company not in _BILLET_PRODUCERS:
        raise ValueError(
            f"structural_non_existence: Billet is produced only by "
            f"{_BILLET_PRODUCERS}; requested '{company}'."
        )


def _resolve_dri_price_for_buyer(state: dict, buyer: str) -> float:
    """DRI input price feeding the EAF for a billet producer (Rulebook §4.5)."""
    if buyer == "EZDK":
        # Own DRI VC, no margin.
        return compute_dri_conversion(state, "EZDK")["total_variable_mfg_usd_t"]
    if buyer == "EFS":
        # ERM DRI VC, no margin.
        return compute_dri_conversion(state, "ERM")["total_variable_mfg_usd_t"]
    if buyer == "ESR":
        # ERM DRI VC + intercompany margin.
        base = compute_dri_conversion(state, "ERM")["total_variable_mfg_usd_t"]
        margin = state["intercompany"]["dri_margin_usd_t"]["ERM_to_ESR"]
        return base + margin
    raise ValueError(
        f"structural_non_existence: DRI price resolution only defined for "
        f"{_BILLET_PRODUCERS}; requested '{buyer}'."
    )


def _eaf_material_cost_per_ton_ms(
    blending_pct: dict, unit_prices_usd: dict, eaf_yield: float, dri_price_usd: float
) -> dict:
    """Per-material (Blending % ÷ EAF Yield) × Unit Price, summed.

    Returns a dict with per-material breakdown plus 'total'.
    """
    dri = (blending_pct["dri"]            / eaf_yield) * dri_price_usd
    ls  = (blending_pct["local_scrap"]    / eaf_yield) * unit_prices_usd["local_scrap_t"]
    isc = (blending_pct["imported_scrap"] / eaf_yield) * unit_prices_usd["imported_scrap_t"]
    hs  = (blending_pct["home_scrap"]     / eaf_yield) * unit_prices_usd.get("home_scrap_t", 0.0)
    pi  = (blending_pct["pig_iron"]       / eaf_yield) * unit_prices_usd.get("pig_iron_t", 0.0)
    return {
        "dri": dri,
        "local_scrap": ls,
        "imported_scrap": isc,
        "home_scrap": hs,
        "pig_iron": pi,
        "total": dri + ls + isc + hs + pi,
    }


def _eaf_byproduct_credit_per_ton_ms(
    byproduct_pct_of_sc: float, byproduct_price_usd_t: float, eaf_yield: float
) -> float:
    """Byproduct tons per ton MS = (Solid Charge/MS) × bp_pct = bp_pct / EAF yield.

    Multiplied by price to yield $/t MS. byproduct_pct_of_sc is negative.
    """
    return (byproduct_pct_of_sc / eaf_yield) * byproduct_price_usd_t


def _eaf_conversion_cost_per_ton_ms(consumptions: dict, unit_prices_usd: dict) -> dict:
    """EAF conversion items in $/t MS.

    Unit conventions (locked decision):
      - aux_materials_kg price is $/kg DIRECT (no /1000)
      - refractories_kg, electrodes_kg, other_fillers_kg prices are $/MT (÷1000)
      - electricity_kwh, natural_gas_nm3, water_m3, oxygen_nm3, nitrogen_nm3,
        argon_nm3, handling_kg, cutting_kg prices are native unit, direct
    """
    aux  = consumptions["aux_materials_kg"]  * unit_prices_usd["aux_materials_kg"]
    refr = consumptions["refractories_kg"]   * unit_prices_usd["refractories_kg"]  / 1000.0
    elec = consumptions["electrodes_kg"]     * unit_prices_usd["electrodes_kg"]    / 1000.0
    fill = consumptions["other_fillers_kg"]  * unit_prices_usd["other_fillers_kg"] / 1000.0
    # Electricity: EAF + LF and Aux share a single $/kWh price.
    elec_kwh = consumptions["electricity_eaf_lf_kwh"] + consumptions["electricity_aux_kwh"]
    electricity = elec_kwh * unit_prices_usd["electricity_kwh"]
    ng   = consumptions["natural_gas_nm3"] * unit_prices_usd["natural_gas_nm3"]
    h2o  = consumptions["water_m3"]        * unit_prices_usd["water_m3"]
    ox   = consumptions["oxygen_nm3"]      * unit_prices_usd["oxygen_nm3"]
    n2   = consumptions["nitrogen_nm3"]    * unit_prices_usd["nitrogen_nm3"]
    ar   = consumptions["argon_nm3"]       * unit_prices_usd["argon_nm3"]
    hand = consumptions["handling_kg"]     * unit_prices_usd["handling_kg"]
    cut  = consumptions["cutting_kg"]      * unit_prices_usd["cutting_kg"]
    total = (aux + refr + elec + fill + electricity + ng + h2o + ox + n2 + ar
             + hand + cut)
    return {
        "aux_materials": aux,
        "refractories": refr,
        "electrodes": elec,
        "other_fillers": fill,
        "electricity": electricity,
        "natural_gas": ng,
        "water": h2o,
        "oxygen": ox,
        "nitrogen": n2,
        "argon": ar,
        "handling": hand,
        "cutting": cut,
        "total": total,
    }


def _eaf_variable_cost_per_ton_ms(
    state: dict, company: str, dri_price_usd: float
) -> dict:
    """Full EAF VC build-up per ton MS. Returns materials, byproduct, conversion, total."""
    b = state["billet"][company]
    eaf_yield = b["yields"]["eaf"]
    materials = _eaf_material_cost_per_ton_ms(
        b["blending_pct"], b["eaf_unit_prices_usd"], eaf_yield, dri_price_usd
    )
    byproduct = _eaf_byproduct_credit_per_ton_ms(
        b["eaf_consumptions_per_ton_ms"]["byproduct_pct_of_sc"],
        b["eaf_unit_prices_usd"]["byproduct_t"],
        eaf_yield,
    )
    conversion = _eaf_conversion_cost_per_ton_ms(
        b["eaf_consumptions_per_ton_ms"], b["eaf_unit_prices_usd"]
    )
    total = materials["total"] + byproduct + conversion["total"]
    return {
        "materials": materials,
        "byproduct_credit_usd_t_ms": byproduct,
        "conversion": conversion,
        "total_usd_t_ms": total,
    }


def _bccm_variable_cost_per_ton_billet(
    ms_vc_per_ton_ms: float, ccp_yield: float, bccm_consumptions: dict, bccm_prices: dict
) -> dict:
    """BCCM stage build-up per ton billet. MS carried + BCCM byproduct + BCCM conversion items.

    Byproduct (Crops) follows the EAF pattern: tons_per_billet = (MS/billet) × bp_pct.
    """
    ms_carried = ms_vc_per_ton_ms * (1.0 / ccp_yield)
    bp_crops = (bccm_consumptions["byproduct_crops_pct_of_ms"] / ccp_yield) \
        * bccm_prices["byproduct_crops_t"]
    aux   = bccm_consumptions["aux_materials_kg"] * bccm_prices["aux_materials_kg"] / 1000.0
    refr  = bccm_consumptions["refractories_kg"]  * bccm_prices["refractories_kg"]  / 1000.0
    elec  = bccm_consumptions["electricity_kwh"]  * bccm_prices["electricity_kwh"]
    ng    = bccm_consumptions["natural_gas_nm3"]  * bccm_prices["natural_gas_nm3"]
    h2o   = bccm_consumptions["water_m3"]         * bccm_prices["water_m3"]
    ox    = bccm_consumptions["oxygen_nm3"]       * bccm_prices["oxygen_nm3"]
    n2    = bccm_consumptions["nitrogen_nm3"]     * bccm_prices["nitrogen_nm3"]
    ar    = bccm_consumptions["argon_nm3"]        * bccm_prices["argon_nm3"]
    additions = bp_crops + aux + refr + elec + ng + h2o + ox + n2 + ar
    total = ms_carried + additions
    return {
        "ms_carried_usd_t_billet": ms_carried,
        "byproduct_crops_usd_t_billet": bp_crops,
        "aux_materials": aux,
        "refractories": refr,
        "electricity": elec,
        "natural_gas": ng,
        "water": h2o,
        "oxygen": ox,
        "nitrogen": n2,
        "argon": ar,
        "additions_total": additions,
        "total_usd_t_billet": total,
    }


def compute_billet_detailed(state: dict, company: str) -> dict:
    """EAF + BCCM detailed buildup. EZDK has real inputs in the JSON.

    EFS/ESR detailed inputs are dummies; this function will compute on them
    when they're populated in step 3, but the test suite asserts the summary
    only for EFS/ESR.
    """
    _require_billet_producer(company)
    b = state["billet"][company]
    if "eaf_consumptions_per_ton_ms" not in b:
        raise NotImplementedError(
            f"Detailed EAF/BCCM inputs not yet populated for {company} "
            f"(step 3 will seed EFS/ESR dummies)."
        )
    dri_price = _resolve_dri_price_for_buyer(state, company)
    eaf = _eaf_variable_cost_per_ton_ms(state, company, dri_price)
    bccm = _bccm_variable_cost_per_ton_billet(
        eaf["total_usd_t_ms"],
        b["yields"]["ccp"],
        b["bccm_consumptions_per_ton_billet"],
        b["bccm_unit_prices_usd"],
    )
    out = {
        "_currency": "USD",
        "company": company,
        "dri_price_used_usd_t": dri_price,
        "eaf": eaf,
        "bccm": bccm,
        "total_variable_mfg_usd_t": bccm["total_usd_t_billet"],
    }
    return out


def _billet_material_price_summary(blending_pct: dict, prices: dict) -> float:
    """Rulebook §4.4: (DRI% × DRI$) + (LS% × LS$) + (IS% × IS$)."""
    return (
        blending_pct["dri"]            * prices["dri"]
        + blending_pct["local_scrap"]    * prices["local_scrap"]
        + blending_pct["imported_scrap"] * prices["imported_scrap"]
    )


def _billet_yield_effect(material_price_usd: float, combined_yield: float) -> float:
    return material_price_usd * (1.0 / combined_yield - 1.0)


def compute_billet_conversion(state: dict, company: str) -> dict:
    """Verification §2.2 — billet conversion-cost view (USD/t)."""
    _require_billet_producer(company)
    b = state["billet"][company]
    dri_price = _resolve_dri_price_for_buyer(state, company)
    prices = {
        "dri": dri_price,
        "local_scrap": b["eaf_unit_prices_usd"]["local_scrap_t"],
        "imported_scrap": b["eaf_unit_prices_usd"]["imported_scrap_t"],
    }
    material = _billet_material_price_summary(b["blending_pct"], prices)
    combined_yield = b["yields"]["eaf"] * b["yields"]["ccp"]
    yield_effect = _billet_yield_effect(material, combined_yield)
    detailed = compute_billet_detailed(state, company)
    total_vc = detailed["total_variable_mfg_usd_t"]
    other_conversion = total_vc - material - yield_effect
    total_conversion = yield_effect + other_conversion
    return {
        "_currency": "USD",
        "company": company,
        "material_price_usd_t": material,
        "yield_effect_usd_t": yield_effect,
        "other_conversion_usd_t": other_conversion,
        "total_conversion_usd_t": total_conversion,
        "total_variable_mfg_usd_t": total_vc,
        "_combined_yield": combined_yield,
        "_dri_price_used": dri_price,
    }


def _intercompany_billet_price(seller_vc_usd_t: float, seller_tradeoff_ratio: float) -> float:
    """Rulebook §4.6: intercompany billet price = seller's VC × seller's trade-off ratio."""
    return seller_vc_usd_t * seller_tradeoff_ratio


def _market_billet_price(state: dict) -> float:
    """Rulebook §4.6: Base + Safe Guards + Other Costs from billet.market.components_usd_t."""
    c = state["billet"]["market"]["components_usd_t"]
    return c["base"] + c["safe_guards"] + c["other_costs"]


# Sentinel for trade-off matrix source rows not yet implemented.
_TRADEOFF_NOT_YET_BUILT = "not_yet_built"


def compute_tradeoff_matrix(state: dict) -> dict:
    """Rulebook §4.6 trade-off matrix — framework.

    Source rows: EZDK (implemented), EFS (sentinel — step 3), ESR (sentinel — step 3),
    Market (implemented). Buyer columns: EZDK, EFS, ERM, ESR.
    Minimum-per-buyer is computed across the *implemented* source rows only;
    sentinel rows are excluded from the minimum.
    """
    buyers = list(_ALL_COMPANIES)
    sources = ["EZDK", "EFS", "ESR", "Market"]

    rows: dict = {}

    # EZDK source row.
    ezdk_vc = compute_billet_conversion(state, "EZDK")["total_variable_mfg_usd_t"]
    ezdk_ratio = state["billet"]["EZDK"]["trade_off_ratio"]
    ezdk_offer = _intercompany_billet_price(ezdk_vc, ezdk_ratio)
    rows["EZDK"] = {
        "seller_vc_usd_t": ezdk_vc,
        "trade_off_ratio": ezdk_ratio,
        "offer_usd_t": ezdk_offer,
        # To EZDK itself, the buyer uses own VC, not the offer (Rulebook §4.5 producer rule).
        "to_EZDK": ezdk_vc,
        "to_EFS":  ezdk_offer,
        "to_ERM":  ezdk_offer,
        "to_ESR":  ezdk_offer,
    }

    # EFS source row — stub (step 3 will fill).
    rows["EFS"] = {
        "status": _TRADEOFF_NOT_YET_BUILT,
        "trade_off_ratio": state["billet"]["EFS"]["trade_off_ratio"],
    }

    # ESR source row — stub (step 3 will fill).
    rows["ESR"] = {
        "status": _TRADEOFF_NOT_YET_BUILT,
        "trade_off_ratio": state["billet"]["ESR"]["trade_off_ratio"],
    }

    # Market source row — flat price across buyers.
    market = _market_billet_price(state)
    rows["Market"] = {
        "price_usd_t": market,
        "to_EZDK": market,
        "to_EFS":  market,
        "to_ERM":  market,
        "to_ESR":  market,
    }

    # Minimum per buyer across the *implemented* source rows only.
    minima: dict = {}
    for buyer in buyers:
        candidates = []
        for src in sources:
            row = rows[src]
            if row.get("status") == _TRADEOFF_NOT_YET_BUILT:
                continue
            candidates.append(row[f"to_{buyer}"])
        minima[buyer] = min(candidates) if candidates else None

    return {
        "_currency": "USD",
        "sources": sources,
        "buyers": buyers,
        "rows": rows,
        "minimum_per_buyer": minima,
        "market_price_usd_t": market,
    }


# ---------------------------------------------------------------------------
# Integrity checks (wired incrementally — check 2 lands in step 2)
# ---------------------------------------------------------------------------

def _check_blending_ratios_sum(state: dict) -> tuple:
    """Check 2: blending ratios sum to 100% per company per production line.

    Tolerance ±0.01 per brief §4.7.
    """
    tol = 0.01
    failures = []
    for company, b in state.get("billet", {}).items():
        if company == "market":
            continue
        bp = b.get("blending_pct")
        if bp is None:
            continue
        total = sum(bp.values())
        if abs(total - 1.0) > tol:
            failures.append(
                f"{company} billet blending sums to {total:.4f} "
                f"(±{tol} tolerance violated)"
            )
    for product, by_company in state.get("finished_products", {}).get("HRC", {}).items():
        # HRC has its own blending_pct per company.
        if not isinstance(by_company, dict):
            continue
        bp = by_company.get("blending_pct")
        if bp is None:
            continue
        total = sum(bp.values())
        if abs(total - 1.0) > tol:
            failures.append(
                f"HRC {product} blending sums to {total:.4f} "
                f"(±{tol} tolerance violated)"
            )
    if failures:
        return (False, "; ".join(failures))
    return (True, "blending ratios sum to 1.00 within ±0.01")
