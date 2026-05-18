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


class StructuralNonExistence(ValueError):
    """Raised when a function is called on a company × stage combination that
    does not physically exist (e.g., ERM has no own billet production). Maps
    to ``error_code: structural_non_existence`` in the orchestrator response
    shape (system prompt §5).
    """


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


# ----------------------------------------------------------------------------
# Stage 2 — Billet (Rulebook §4) — EAF + BCCM helpers, USD-native
# ----------------------------------------------------------------------------


def _resolve_dri_price_for_buyer(state: dict, buyer: str) -> float:
    """Per Rulebook §4.5: which DRI VC ($/t) flows into the buyer's EAF.

    EZDK consumes own DRI at own VC.
    EFS  consumes ERM DRI at ERM VC (no margin).
    ESR  consumes ERM DRI at ERM VC + intercompany margin.
    """
    if buyer == "EZDK":
        return compute_dri_conversion(state, "EZDK")["total_variable_mfg"]
    if buyer == "EFS":
        return compute_dri_conversion(state, "ERM")["total_variable_mfg"]
    if buyer == "ESR":
        erm_vc = compute_dri_conversion(state, "ERM")["total_variable_mfg"]
        margin = state["intercompany"]["dri_margin_usd_t"]["ERM_to_ESR"]
        return erm_vc + margin
    raise ValueError(f"Unknown billet buyer: {buyer}")


def _eaf_material_cost_per_ton_ms(
    blending_pct: dict,
    unit_prices_usd: dict,
    eaf_yield: float,
    dri_price_usd: float,
) -> float:
    """Σ over DRI / LS / IS / HS / PI of (blend% / EAF yield) × price."""
    dri = blending_pct.get("dri", 0.0)
    ls = blending_pct.get("local_scrap", 0.0)
    isc = blending_pct.get("imported_scrap", 0.0)
    hs = blending_pct.get("home_scrap", 0.0)
    pi = blending_pct.get("pig_iron", 0.0)

    home_scrap_price = unit_prices_usd.get("home_scrap_t", 0.0)
    pig_iron_price = unit_prices_usd.get("pig_iron_t", 0.0)

    inv_yield = 1.0 / eaf_yield
    return (
        inv_yield * dri * dri_price_usd
        + inv_yield * ls * unit_prices_usd["local_scrap_t"]
        + inv_yield * isc * unit_prices_usd["imported_scrap_t"]
        + inv_yield * hs * home_scrap_price
        + inv_yield * pi * pig_iron_price
    )


def _eaf_byproduct_credit_per_ton_ms(
    byproduct_pct_of_sc: float,
    byproduct_price_usd: float,
    eaf_yield: float,
) -> float:
    """(1/EAF yield) × byproduct% × price. byproduct% is negative in JSON."""
    return (1.0 / eaf_yield) * byproduct_pct_of_sc * byproduct_price_usd


def _eaf_conversion_cost_per_ton_ms(consumptions: dict, unit_prices_usd: dict) -> float:
    """Σ consumption × unit price across all EAF conversion items.

    Skips ``byproduct_pct_of_sc`` (handled via the byproduct credit helper).
    Both electricity consumption keys (``electricity_eaf_lf_kwh`` and
    ``electricity_aux_kwh``) multiply by the single ``electricity_kwh`` price.
    """
    aux_mats = consumptions.get("aux_materials_kg", 0.0) * unit_prices_usd.get("aux_materials_kg", 0.0)
    refractories = consumptions.get("refractories_kg", 0.0) * unit_prices_usd.get("refractories_kg", 0.0)
    electrodes = consumptions.get("electrodes_kg", 0.0) * unit_prices_usd.get("electrodes_kg", 0.0)
    other_fillers = consumptions.get("other_fillers_kg", 0.0) * unit_prices_usd.get("other_fillers_kg", 0.0)

    elec_price = unit_prices_usd.get("electricity_kwh", 0.0)
    elec_eaf_lf = consumptions.get("electricity_eaf_lf_kwh", 0.0) * elec_price
    elec_aux = consumptions.get("electricity_aux_kwh", 0.0) * elec_price

    natural_gas = consumptions.get("natural_gas_nm3", 0.0) * unit_prices_usd.get("natural_gas_nm3", 0.0)
    water = consumptions.get("water_m3", 0.0) * unit_prices_usd.get("water_m3", 0.0)
    oxygen = consumptions.get("oxygen_nm3", 0.0) * unit_prices_usd.get("oxygen_nm3", 0.0)
    nitrogen = consumptions.get("nitrogen_nm3", 0.0) * unit_prices_usd.get("nitrogen_nm3", 0.0)
    argon = consumptions.get("argon_nm3", 0.0) * unit_prices_usd.get("argon_nm3", 0.0)
    handling = consumptions.get("handling_kg", 0.0) * unit_prices_usd.get("handling_kg", 0.0)
    cutting = consumptions.get("cutting_kg", 0.0) * unit_prices_usd.get("cutting_kg", 0.0)

    return (
        aux_mats
        + refractories
        + electrodes
        + other_fillers
        + elec_eaf_lf
        + elec_aux
        + natural_gas
        + water
        + oxygen
        + nitrogen
        + argon
        + handling
        + cutting
    )


def _eaf_variable_cost_per_ton_ms(material: float, byproduct: float, conversion: float) -> float:
    return material + byproduct + conversion


def _bccm_variable_cost_per_ton_billet(
    ms_vc_per_ton: float,
    ccp_yield: float,
    bccm_consumptions: dict,
    bccm_unit_prices_usd: dict,
) -> float:
    """Carry MS VC through CCP yield; add BCCM byproduct (crops) + conversion items."""
    ms_carried = ms_vc_per_ton * (1.0 / ccp_yield)

    crops_pct = bccm_consumptions.get("byproduct_crops_pct_of_ms", 0.0)
    crops_price = bccm_unit_prices_usd.get("byproduct_crops_t", 0.0)
    crops = crops_pct * crops_price

    aux_mats = bccm_consumptions.get("aux_materials_kg", 0.0) * bccm_unit_prices_usd.get("aux_materials_kg", 0.0)
    refractories = bccm_consumptions.get("refractories_kg", 0.0) * bccm_unit_prices_usd.get("refractories_kg", 0.0)
    electricity = bccm_consumptions.get("electricity_kwh", 0.0) * bccm_unit_prices_usd.get("electricity_kwh", 0.0)
    natural_gas = bccm_consumptions.get("natural_gas_nm3", 0.0) * bccm_unit_prices_usd.get("natural_gas_nm3", 0.0)
    water = bccm_consumptions.get("water_m3", 0.0) * bccm_unit_prices_usd.get("water_m3", 0.0)
    oxygen = bccm_consumptions.get("oxygen_nm3", 0.0) * bccm_unit_prices_usd.get("oxygen_nm3", 0.0)
    nitrogen = bccm_consumptions.get("nitrogen_nm3", 0.0) * bccm_unit_prices_usd.get("nitrogen_nm3", 0.0)
    argon = bccm_consumptions.get("argon_nm3", 0.0) * bccm_unit_prices_usd.get("argon_nm3", 0.0)

    return (
        ms_carried
        + crops
        + aux_mats
        + refractories
        + electricity
        + natural_gas
        + water
        + oxygen
        + nitrogen
        + argon
    )


def _billet_material_price_summary(
    blending_pct: dict,
    dri_price: float,
    local_scrap_price: float,
    imported_scrap_price: float,
) -> float:
    """Rulebook §4.4: weighted average of input prices. No yield divide."""
    return (
        blending_pct.get("dri", 0.0) * dri_price
        + blending_pct.get("local_scrap", 0.0) * local_scrap_price
        + blending_pct.get("imported_scrap", 0.0) * imported_scrap_price
    )


def _billet_yield_effect(material_price: float, eaf_yield: float, ccp_yield: float) -> float:
    """Material × (1 / (EAF × CCP) − 1)."""
    combined = eaf_yield * ccp_yield
    return material_price * ((1.0 / combined) - 1.0)


def _intercompany_billet_price(seller_vc: float, seller_tradeoff_ratio: float) -> float:
    """Rulebook §4.6: seller VC × seller trade-off ratio. (Used in step 3.)"""
    return seller_vc * seller_tradeoff_ratio


def compute_billet_detailed(state: dict, company: str) -> dict:
    """Verification §2.x — billet detailed cost sheet, USD-native.

    EAF stage + BCCM stage. For EZDK the underlying consumptions are real
    Excel data; EFS / ESR detailed blocks will be tagged reconstructed in
    Step 3.

    Output dict exposes three distinct totals:
      * ``total_variable_mfg_computed`` — engine's honest sum from JSON inputs.
      * ``_reconciliation_residual_usd_per_ton`` — frozen per-baseline offset
        loaded from ``state["reconciliation"]["billet"][company]``; 0 when
        absent.
      * ``total_variable_mfg`` — computed + residual; the value downstream
        readers (trade-off matrix, Stage 3 Sc1) MUST use to match the
        verification cascade. See the residual-application comment below.
    """
    producers = state.get("entities", {}).get(
        "billet_producers", ["EZDK", "EFS", "ESR"]
    )
    if company not in producers:
        raise StructuralNonExistence(
            f"compute_billet_detailed not callable for {company}: not a "
            f"billet producer (producers: {producers})."
        )
    b = state["billet"][company]
    eaf_prices = b["eaf_unit_prices_usd"]
    eaf_cons = b["eaf_consumptions_per_ton_ms"]
    eaf_yield = b["yields"]["eaf"]
    ccp_yield = b["yields"]["ccp"]

    dri_price = _resolve_dri_price_for_buyer(state, company)

    material = _eaf_material_cost_per_ton_ms(
        b["blending_pct"], eaf_prices, eaf_yield, dri_price
    )
    byproduct = _eaf_byproduct_credit_per_ton_ms(
        eaf_cons["byproduct_pct_of_sc"], eaf_prices["byproduct_t"], eaf_yield
    )
    conversion = _eaf_conversion_cost_per_ton_ms(eaf_cons, eaf_prices)
    ms_vc = _eaf_variable_cost_per_ton_ms(material, byproduct, conversion)

    billet_vc_computed = _bccm_variable_cost_per_ton_billet(
        ms_vc,
        ccp_yield,
        b["bccm_consumptions_per_ton_billet"],
        b["bccm_unit_prices_usd"],
    )

    # Residual application site.
    #
    # Residual is a frozen per-baseline offset, not a function of operational
    # inputs. Sensitivity sweeps on consumption or price inputs vary
    # total_variable_mfg_computed; residual is added back as a constant.
    # Optimizer shadow prices on consumption/price knobs reflect
    # total_variable_mfg_computed gradients only. Residual is NOT an optimizer
    # knob and NOT a sensitivity dimension. (Binding contract for Steps 8 / 10.)
    reconciliation = (
        state.get("reconciliation", {}).get("billet", {}).get(company, {})
    )
    residual = reconciliation.get("residual_usd_per_ton", 0.0)
    note = reconciliation.get("note")

    total_variable_mfg = billet_vc_computed + residual

    out: dict = {
        "_currency": "USD",
        "eaf": {
            "material_cost_per_ton_ms": material,
            "byproduct_credit_per_ton_ms": byproduct,
            "conversion_cost_per_ton_ms": conversion,
            "ms_variable_cost_per_ton_ms": ms_vc,
        },
        "bccm": {
            "billet_variable_cost_per_ton_billet": billet_vc_computed,
        },
        "total_variable_mfg_computed": billet_vc_computed,
        "_reconciliation_residual_usd_per_ton": residual,
        "total_variable_mfg": total_variable_mfg,
    }
    if note:
        out["_reconciliation_note"] = note
    if b.get("_reconstructed_dummies"):
        out["_reconstructed_dummies"] = True
    return out


def compute_billet_conversion(state: dict, company: str) -> dict:
    """Verification §2.2 — billet summary conversion view, USD-native.

    ``total_variable_mfg`` and ``other_conversion`` are derived from the
    residual-included total so the summary cells match verification §2.2
    directly. ``total_variable_mfg_computed`` is preserved on the dict for
    inspection; downstream readers (trade-off matrix, Stage 3 Sc1) MUST
    consume ``total_variable_mfg`` to match the verification cascade — see
    reconciliation block in state.
    """
    producers = state.get("entities", {}).get(
        "billet_producers", ["EZDK", "EFS", "ESR"]
    )
    if company not in producers:
        raise StructuralNonExistence(
            f"compute_billet_conversion not callable for {company}: not a "
            f"billet producer (producers: {producers})."
        )
    b = state["billet"][company]
    blending = b["blending_pct"]
    eaf_yield = b["yields"]["eaf"]
    ccp_yield = b["yields"]["ccp"]
    eaf_prices = b["eaf_unit_prices_usd"]

    dri_price = _resolve_dri_price_for_buyer(state, company)

    material_price = _billet_material_price_summary(
        blending,
        dri_price,
        eaf_prices["local_scrap_t"],
        eaf_prices["imported_scrap_t"],
    )
    yield_effect = _billet_yield_effect(material_price, eaf_yield, ccp_yield)

    detailed = compute_billet_detailed(state, company)
    billet_vc_computed = detailed["total_variable_mfg_computed"]
    residual = detailed["_reconciliation_residual_usd_per_ton"]
    total_variable_mfg = detailed["total_variable_mfg"]
    note = detailed.get("_reconciliation_note")

    other_conversion = total_variable_mfg - material_price - yield_effect
    total_conversion = yield_effect + other_conversion

    out: dict = {
        "_currency": "USD",
        "material_price": material_price,
        "yield_effect": yield_effect,
        "other_conversion": other_conversion,
        "total_conversion": total_conversion,
        "total_variable_mfg_computed": billet_vc_computed,
        "_reconciliation_residual_usd_per_ton": residual,
        "total_variable_mfg": total_variable_mfg,
    }
    if note:
        out["_reconciliation_note"] = note
    if b.get("_reconstructed_dummies"):
        out["_reconstructed_dummies"] = True
    return out


def _market_billet_price(state: dict) -> float:
    """Rulebook §4.6 / Verification §2.4 — Base + Safe Guards + Other Costs."""
    components = state["billet"]["market"]["components_usd_t"]
    return (
        components["base"]
        + components["safe_guards"]
        + components["other_costs"]
    )


def compute_tradeoff_matrix(state: dict) -> dict:
    """Verification §2.3 — fully dynamic billet trade-off matrix, USD-native.

    Source rows: producers (EZDK, EFS, ESR) plus Market. ERM never appears
    as a source (it has no own production).
    Buyer columns: EZDK, EFS, ERM, ESR.

    Cell rule:
      * Producer source row, off-diagonal cell: intercompany price =
        seller's ``total_variable_mfg`` (residual-included) × seller's
        ``trade_off_ratio``.
      * Producer source row, diagonal cell (buyer == seller): seller's
        own ``total_variable_mfg`` (no markup to self).
      * Market source row: ``_market_billet_price(state)`` for every
        buyer.

    Per-buyer minimum: MIN across all source rows.

    Reads ``total_variable_mfg`` (residual-included) from
    ``compute_billet_conversion``, NOT ``total_variable_mfg_computed``.
    This is what makes EZDK source intercompany price land at 478.73
    (= 409.52 × 1.169) rather than 478.16 (= 409.04 × 1.169).

    This is a view function — it is never called during default P&L
    generation and is not persisted.
    """
    buyers = ["EZDK", "EFS", "ERM", "ESR"]
    producers = ["EZDK", "EFS", "ESR"]

    sources: dict = {}
    for producer in producers:
        bc = compute_billet_conversion(state, producer)
        own_vc = bc["total_variable_mfg"]  # residual-included; matches §2.3
        ratio = state["billet"][producer]["trade_off_ratio"]
        intercompany_price = _intercompany_billet_price(own_vc, ratio)
        row = {"price": intercompany_price}
        for buyer in buyers:
            row["to_" + buyer] = own_vc if buyer == producer else intercompany_price
        sources[producer] = row

    market_price = _market_billet_price(state)
    market_row: dict = {"price": market_price}
    for buyer in buyers:
        market_row["to_" + buyer] = market_price
    sources["Market"] = market_row

    minimum = {
        buyer: min(sources[s]["to_" + buyer] for s in sources) for buyer in buyers
    }

    return {
        "_currency": "USD",
        "sources": sources,
        "minimum": minimum,
    }


# ----------------------------------------------------------------------------
# Integrity check 2 — blending ratios per company per line sum to 1.0
# ----------------------------------------------------------------------------


def _blending_sum(blending: dict) -> float:
    return (
        blending.get("dri", 0.0)
        + blending.get("local_scrap", 0.0)
        + blending.get("imported_scrap", 0.0)
        + blending.get("home_scrap", 0.0)
        + blending.get("pig_iron", 0.0)
    )


def _check_blending_ratios_sum(state: dict) -> tuple[bool, str]:
    """Per Rulebook §12 check 2: DRI + LS + IS + HS + PI ≈ 1.0 (±0.01).

    Walks every company × production line that carries a ``blending_pct``
    block: billet (EZDK / EFS / ESR) and HRC flat (EZDK / EFS).
    """
    tol = 0.01
    failures: list[str] = []

    for company, payload in state.get("billet", {}).items():
        if not isinstance(payload, dict):
            continue
        blending = payload.get("blending_pct")
        if blending is None:
            continue
        total = _blending_sum(blending)
        if abs(total - 1.0) > tol:
            failures.append(f"billet[{company}] sum={total:.4f}")

    for company, payload in state.get("finished_products", {}).get("HRC", {}).items():
        if not isinstance(payload, dict):
            continue
        blending = payload.get("blending_pct")
        if blending is None:
            continue
        total = _blending_sum(blending)
        if abs(total - 1.0) > tol:
            failures.append(f"finished_products.HRC[{company}] sum={total:.4f}")

    if failures:
        return (False, "Blending ratios do not sum to 1.0 (±0.01): " + "; ".join(failures))
    return (True, "All blending ratios sum to 1.0 (±0.01).")
