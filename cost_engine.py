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


def _billet_reconciliation_residual_usd_t(state: dict, company: str) -> float:
    """Structural Excel-to-engine reconciliation residual at the Other Conversion line.

    Closes a per-company gap that cannot be eliminated without modifying the
    JSON's reconstructed-dummy class of inputs. Currently populated for EZDK
    only (step 2 adjudication). Other companies default to 0.0; their own
    residuals (if needed) will be adjudicated and added in step 3.

    Source: state["reconciliation"]["billet_<COMPANY>_excel_to_engine_usd_t"].
    The reconciliation block is seeded in tests/conftest.py per-fixture, not
    written into model_initial_state.json (step_manager.py / SQLite persistence
    is the eventual home — see brief §11 forward log).
    """
    if company != "EZDK":
        return 0.0
    rec = state.get("reconciliation", {})
    return float(rec.get("billet_EZDK_excel_to_engine_usd_t", 0.0))


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

    The reconciliation residual (currently EZDK-only) is added on top of the
    engineering buildup. `total_pre_residual_usd_t` exposes the pure buildup;
    `total_variable_mfg_usd_t` is the residual-included headline.
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
    total_pre_residual = bccm["total_usd_t_billet"]
    residual = _billet_reconciliation_residual_usd_t(state, company)
    total_with_residual = total_pre_residual + residual
    return {
        "_currency": "USD",
        "company": company,
        "dri_price_used_usd_t": dri_price,
        "eaf": eaf,
        "bccm": bccm,
        "total_pre_residual_usd_t": total_pre_residual,
        "reconciliation_residual_usd_t": residual,
        "total_variable_mfg_usd_t": total_with_residual,
    }


def _billet_material_price_summary(blending_pct: dict, prices: dict) -> float:
    """Rulebook §4.4: (DRI% × DRI$) + (LS% × LS$) + (IS% × IS$)."""
    return (
        blending_pct["dri"]            * prices["dri"]
        + blending_pct["local_scrap"]    * prices["local_scrap"]
        + blending_pct["imported_scrap"] * prices["imported_scrap"]
    )


def _billet_yield_effect(material_price_usd: float, combined_yield: float) -> float:
    return material_price_usd * (1.0 / combined_yield - 1.0)


_BILLET_MODE_DETAILED_WITH_RESIDUAL = "detailed_with_residual"
_BILLET_MODE_SUMMARY_FITTED = "summary_fitted"


def _billet_mode_for_company(state: dict, company: str) -> str:
    """Dispatch the billet computation path based on available state.

    - "detailed_with_residual": company has full EAF+BCCM consumptions
      (EZDK). Engineering buildup + reconciliation residual at Other Conv.
    - "summary_fitted": company has only yields, blending, and a seeded
      `summary_other_conversion_usd_per_ton` value (EFS, ESR pilot dummies).
      Direct §4.4 summary path; no residual.

    When real Excel data later replaces the EFS/ESR seeds with detailed
    consumptions, this function will pick up the detailed path automatically.
    """
    b = state["billet"][company]
    if "eaf_consumptions_per_ton_ms" in b:
        return _BILLET_MODE_DETAILED_WITH_RESIDUAL
    if "summary_other_conversion_usd_per_ton" in b:
        return _BILLET_MODE_SUMMARY_FITTED
    raise ValueError(
        f"structural_non_existence: no billet inputs available for {company} "
        f"(neither detailed EAF/BCCM consumptions nor a summary "
        f"other_conversion seed)."
    )


def compute_billet_conversion(state: dict, company: str) -> dict:
    """Verification §2.2 — billet conversion-cost view (USD/t).

    Dispatch on `_billet_mode_for_company`:

    - DETAILED_WITH_RESIDUAL (EZDK): full EAF+BCCM buildup via
      `compute_billet_detailed`, then the reconciliation residual is added
      to Other Conversion. Total Conversion = Yield Effect + Other Conv
      (residual included); Total Variable Mfg = Material + Total Conv.

    - SUMMARY_FITTED (EFS, ESR pilot dummies): direct §4.4 summary. Other
      Conversion is read from state as a seeded scalar; no residual is
      applied (the seed is itself the fit to the verification target).
      Total Conversion = Yield Effect + Other Conv; Total VC = Material +
      Total Conv.

    The residual fields are present in the returned dict for both modes,
    set to 0.0 in summary mode for caller transparency.
    """
    _require_billet_producer(company)
    b = state["billet"][company]
    mode = _billet_mode_for_company(state, company)

    dri_price = _resolve_dri_price_for_buyer(state, company)
    prices = {
        "dri": dri_price,
        "local_scrap": b["eaf_unit_prices_usd"]["local_scrap_t"],
        "imported_scrap": b["eaf_unit_prices_usd"]["imported_scrap_t"],
    }
    material = _billet_material_price_summary(b["blending_pct"], prices)
    combined_yield = b["yields"]["eaf"] * b["yields"]["ccp"]
    yield_effect = _billet_yield_effect(material, combined_yield)

    if mode == _BILLET_MODE_DETAILED_WITH_RESIDUAL:
        detailed = compute_billet_detailed(state, company)
        total_pre_residual = detailed["total_pre_residual_usd_t"]
        residual = detailed["reconciliation_residual_usd_t"]
        _other_conversion_before_residual = total_pre_residual - material - yield_effect
        _other_conversion_with_residual = _other_conversion_before_residual + residual
    else:  # SUMMARY_FITTED
        _other_conversion_before_residual = b["summary_other_conversion_usd_per_ton"]
        residual = 0.0
        _other_conversion_with_residual = _other_conversion_before_residual + residual

    total_conversion = yield_effect + _other_conversion_with_residual
    total_vc = material + total_conversion

    return {
        "_currency": "USD",
        "company": company,
        "billet_mode": mode,
        "material_price_usd_t": material,
        "yield_effect_usd_t": yield_effect,
        "other_conversion_usd_t": _other_conversion_with_residual,
        "total_conversion_usd_t": total_conversion,
        "total_variable_mfg_usd_t": total_vc,
        "_other_conversion_before_residual": _other_conversion_before_residual,
        "_reconciliation_residual_usd_t": residual,
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


def _producer_source_row(state: dict, source: str, buyers: tuple) -> dict:
    """Build one producer source row: own VC, ratio, offer, per-buyer prices.

    For source==buyer (producer to itself), the row shows own VC, not the
    ratio'd offer (Rulebook §4.5 producer-own-VC rule).
    """
    vc = compute_billet_conversion(state, source)["total_variable_mfg_usd_t"]
    ratio = state["billet"][source]["trade_off_ratio"]
    offer = _intercompany_billet_price(vc, ratio)
    row = {
        "seller_vc_usd_t": vc,
        "trade_off_ratio": ratio,
        "offer_usd_t": offer,
    }
    for buyer in buyers:
        if buyer == source:
            row[f"to_{buyer}"] = vc
        else:
            row[f"to_{buyer}"] = offer
    return row


def compute_tradeoff_matrix(state: dict) -> dict:
    """Rulebook §4.6 trade-off matrix.

    Source rows: EZDK, EFS, ESR (producers), and Market (flat 590).
    Buyer columns: EZDK, EFS, ERM, ESR. ERM is buyer-only — never a source,
    per Rulebook §1.4.

    Source==buyer cells use the producer-own-VC rule. Source!=buyer cells use
    seller_vc × seller_tradeoff_ratio. Market is flat across buyers.

    `minimum_per_buyer` is MIN across the column, including own-VC cells when
    present. For ERM (no own VC), the minimum is over all source rows'
    intercompany offers + market.
    """
    buyers = _ALL_COMPANIES
    producer_sources = ("EZDK", "EFS", "ESR")
    sources = list(producer_sources) + ["Market"]

    rows: dict = {}
    for src in producer_sources:
        rows[src] = _producer_source_row(state, src, buyers)

    market = _market_billet_price(state)
    market_row = {"price_usd_t": market}
    for buyer in buyers:
        market_row[f"to_{buyer}"] = market
    rows["Market"] = market_row

    minima: dict = {}
    minima_source: dict = {}
    for buyer in buyers:
        column = {src: rows[src][f"to_{buyer}"] for src in sources}
        winning_src = min(column, key=column.get)
        minima[buyer] = column[winning_src]
        minima_source[buyer] = winning_src

    return {
        "_currency": "USD",
        "sources": sources,
        "buyers": list(buyers),
        "rows": rows,
        "minimum_per_buyer": minima,
        "minimum_per_buyer_source": minima_source,
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
