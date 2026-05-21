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
