"""
Ezz Steel cost engine.

The engine runs one model under one of two rule sets:

* ``CORRECTED_RULES`` (default) — the model with every workbook mistake fixed and
  no hardcoded results (see MODEL_FIXES.md for each fix and its effect);
* ``LEGACY_RULES`` — an exact replica of the "New Corp Model" workbook, quirks
  included.  The tests prove it reproduces the workbook cell for cell, and the
  fix-by-fix bridge (model_fixes.py) starts from it.

Which rule set applies comes from ``state["rules_profile"]`` ("corrected" or
"legacy"), or from the ``rules`` argument of ``compute_all``.  Each rule is a
named switch, so any single fix can be turned on or off.

Design rules (step1_brief_cost_engine_v2.md): pure functions, no I/O,
deterministic, full float precision (rounding is the display layer's job).
A division by zero, which Excel shows as #DIV/0!, is returned as ``None``.
"""

from __future__ import annotations

COMPANIES = ("EZDK", "EFS", "ERM", "ESR")
BILLET_PRODUCERS = ("EZDK", "EFS", "ESR")
HRC_PRODUCERS = ("EZDK", "EFS")
PRODUCTS = ("Rebar", "Wire Rod", "HRC")

# Each rule switches one correction on.  Names refer to MODEL_FIXES.md.
RULES = {
    "export_expense_per_ton": "A1  export expenses are $/t × export volume, not a lump sum",
    "consistent_volumes": "A2/A3/B6  every export is produced, priced and ×12 in annual views",
    "erm_dri_full_volume": "A4  ERM DRI volume includes the DRI it supplies to EFS's flat line",
    "market_share_hrc": "A5  HRC group sales = EZDK + EFS HRC local sales",
    "billet_interco": "B1  ERM's internal billet purchase raises the supplier's production "
                      "and is booked as an intercompany sale",
    "erm_dri_pnl": "B2  ERM's DRI sales get their own P&L column; fixed costs follow the "
                   "distribution %; intercompany sales are eliminated on consolidation",
    "break_even_on_cm": "B4  break-even = (fixed + depreciation) ÷ contribution margin per ton",
    "own_line_inputs": "B5  each line uses its own electricity price and one DRI margin per buyer",
    "summary_from_detail": "C   summary cost sheets equal the detailed build-up",
}
CORRECTED_RULES = {name: True for name in RULES}
LEGACY_RULES = {name: False for name in RULES}


class IntegrityError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _div(a, b):
    """a / b, or None where Excel would show #DIV/0!."""
    if a is None or b is None or b == 0:
        return None
    return a / b


def _usd(v, fx):
    """Input amount → USD.  {'le': x} is converted at FX; plain numbers are USD."""
    if isinstance(v, dict):
        return v["le"] / fx if "le" in v else v["usd"]
    return v


def _le(v, fx):
    """Input amount → LE.  {'usd': x} is converted at FX; plain numbers are LE."""
    if isinstance(v, dict):
        return v["usd"] * fx if "usd" in v else v["le"]
    return v


def _pct(v):
    return v / 100.0


# Outputs of the detail templates that scale with volume (tons and money totals);
# everything else they return is a per-ton rate that does not depend on volume.
_VOLUME_KEYS = {
    "finished_t", "billets_t", "byproduct_t", "conversion_exp", "variable_exp_le",
    "s1.molten_steel_t", "s1.solid_charge_t", "s1.byproduct_t", "s1.billets_t",
    "s2.output_t", "s2.molten_steel_t", "s2.byproduct_t",
    "s3.feed.produced_t", "s3.feed.local_t", "s3.feed.imported_t", "s3.byproduct_t",
    "s3.variable_exp", "summary.total_value",
}


def _volume_safe(run, finished_t: float) -> dict:
    """Evaluate a detail template at ``finished_t``.  At zero volume Excel shows
    #DIV/0! for every per-ton cost; the engine instead returns the per-ton rates
    (volume-independent) and extrapolates the volume figures linearly to zero:
    V(0) = 2·V(1) − V(2), exact because they are linear in the finished quantity."""
    if finished_t != 0:
        return run(finished_t)
    a, b = run(1.0), run(2.0)
    for k in a:
        if k in _VOLUME_KEYS or k.startswith(("s1.t.", "t.")):
            a[k] = 2 * a[k] - b[k]
    a["finished_t"] = 0.0
    return a


# --------------------------------------------------------------------------- #
# Stage 1 — DRI ('DRI Cost' and 'DRI' sheets)
# --------------------------------------------------------------------------- #

_DRI_LINES = ("electricity", "natural_gas", "oxygen", "nitrogen", "water",
              "chemicals", "spare_parts", "external_services", "other")


def _dri_annual_capacity(state: dict, company: str) -> float:
    """'DRI Cost'!E10 (annual).  The corrected state keeps one source of truth: the
    monthly ceiling in ``capacity_ceilings``."""
    d = state["dri"][company]
    if "capacity_t" in d:
        return d["capacity_t"]
    return state["capacity_ceilings"]["dri"][company] * 12


def compute_dri_variable(state: dict, company: str) -> dict:
    """DRI variable cost — no volume needed.  'DRI Cost' rows 15–68, 'DRI' sheet."""
    d, fx = state["dri"][company], state["fx_egp_per_usd"]
    c, p = d["consumption"], d["prices_le"]
    iop_le = d["iop_landed_usd_t"] * fx
    ng_le_nm3 = d["ng_price_usd_mmbtu"] * fx / 28
    lines = {
        "electricity": c["electricity_kwh"] * p["electricity_kwh"],
        "natural_gas": c["natural_gas_nm3"] * ng_le_nm3,
        "oxygen": c["oxygen_nm3"] * p["oxygen_nm3"],
        "nitrogen": c["nitrogen_nm3"] * p["nitrogen_nm3"],
        "water": c["water_nm3"] * p["water_nm3"],
        "chemicals": c["chemicals_t"] * p["chemicals_t"],
        "spare_parts": c["spare_parts_t"] * p["spare_parts_t"],
        "external_services": c["external_services_t"] * p["external_services_t"],
        "other": c["other_t"] * p["other_t"],
    }
    others_le = sum(lines.values())
    iop_cost_le = iop_le * d["mrmr"]
    material = d["iop_landed_usd_t"]
    mrmr_effect = (d["mrmr"] - 1) * material
    other_conv = others_le / fx
    return {
        "_currency": "LE",
        "mrmr": d["mrmr"],
        "ng_mmbtu_t": c["natural_gas_nm3"] / 28,
        "iop_landed_le_t": iop_le,
        "ng_price_le_nm3": ng_le_nm3,
        "cost_le_t": {"iop": iop_cost_le, **lines},
        "other_conversion_usd_t": other_conv,
        "conversion_rm_le_t": (d["mrmr"] - 1) * iop_le,
        "conversion_others_le_t": others_le,
        "conversion_exp_le": _dri_annual_capacity(state, company) * ((d["mrmr"] - 1) * iop_le + others_le),
        "variable_cost_le_t": iop_cost_le + others_le,
        # 'DRI' sheet — conversion-cost view in USD
        "summary_usd_t": {
            "_currency": "USD",
            "material_price": material,
            "mrmr_effect": mrmr_effect,
            "other_conversion": other_conv,
            "total_conversion": mrmr_effect + other_conv,
            "total_variable_cost": mrmr_effect + other_conv + material,
        },
    }


def compute_dri_full(state: dict, company: str, variable: dict, production_t: float) -> dict:
    """Adds the volume-dependent part of 'DRI Cost' (rows 16–17, 69–87)."""
    d = state["dri"][company]
    f = d["fixed_le"]
    other_fixed = f["other_fixed"]
    if isinstance(other_fixed, dict):  # =<total> - <dep> - labor, as written in the workbook
        other_fixed = other_fixed["total_le"] - other_fixed["less_depreciation_le"] - f["labor"]
    fixed = {"labor": f["labor"], "depreciation": f["depreciation"], "other": other_fixed}
    fixed_t = {k: _div(v, production_t) for k, v in fixed.items()}
    fixed_per_t = None if None in fixed_t.values() else sum(fixed_t.values())
    vc = variable["variable_cost_le_t"]
    manuf = None if fixed_per_t is None else fixed_per_t + vc
    return {
        **variable,
        "production_t": production_t,
        "required_iop_t": production_t * d["mrmr"],
        "variable_exp_le": vc * production_t,
        "fixed_le": fixed,
        "fixed_le_t": fixed_t,
        "fixed_cost_le_t": fixed_per_t,
        "fixed_exp_le": None if fixed_per_t is None else fixed_per_t * production_t,
        "manufacturing_cost_le_t": manuf,
        "cogs_le": None if manuf is None else manuf * production_t,
        "selling_price_le_t": d["selling_price_le_t"],
        "gross_margin_le_t": None if manuf is None else d["selling_price_le_t"] - manuf,
    }


# --------------------------------------------------------------------------- #
# Integrated detail template — 'EZDK Rebar', 'EFS Rebar', 'EZDK Flat', 'EFS Flat'
# EAF (stage 1) → CCP/TSC (stage 2) → rolling mill / HSM (stage 3)
# --------------------------------------------------------------------------- #

def compute_integrated_detail(p: dict, link: dict) -> dict:
    """
    ``p``    – the sheet's own inputs (state['detail'][sheet]).
    ``link`` – values the sheet pulls from other sheets:
        layout ('long' | 'flat'), finished_t, extra_feed_t, eaf_yield, s2_yield,
        s3_yield (fractions), blend {imported, local, dri} (fractions),
        price {imported, local, dri} ($/t), electricity_usd_kwh, eaf_lf_kwh.
    """
    s1, s2, s3 = p["stage1"], p["stage2"], p["stage3"]
    c1, p1 = s1["consumption"], s1["prices_usd"]
    c2, p2 = s2["consumption"], s2["prices_usd"]
    c3, p3 = s3["consumption"], s3["prices_usd"]
    o: dict = {"_currency": "USD"}

    # stage 3 quantities first — they drive everything upstream
    fin = link["finished_t"]
    sh = s3["feed_share"]
    feed_prod = fin / link["s3_yield"] * sh["produced"]
    feed_local = fin / link["s3_yield"] * sh["local"]
    feed_imp = fin / link["s3_yield"] * sh["imported"]
    s2_out = feed_prod + link["extra_feed_t"]          # E104 (billets incl. wire-rod billets)
    ms = s2_out / link["s2_yield"]                     # E106 = E19
    sc = ms / link["eaf_yield"]                        # E21

    # ---- stage 1: EAF ----
    blend = {"imported": link["blend"]["imported"], "local": link["blend"]["local"],
             "dri": link["blend"]["dri"], "home": s1["blend_pct"]["home_scrap"],
             "pig": s1["blend_pct"]["pig_iron"]}
    price = {"imported": link["price"]["imported"], "local": link["price"]["local"],
             "dri": link["price"]["dri"], "home": p1["home_scrap_t"], "pig": p1["pig_iron_t"]}
    tons = {k: blend[k] * sc for k in blend}
    byp_t = s1["byproduct_pct_of_solid_charge"] * sc
    elec = link["electricity_usd_kwh"]
    o.update({
        "finished_t": fin, "s1.molten_steel_t": ms, "s1.yield": link["eaf_yield"],
        "s1.solid_charge_t": sc, "s1.byproduct_t": byp_t,
        "s1.electricity_eaf_lf_kwh": link["eaf_lf_kwh"], "s1.electricity_usd_kwh": elec,
    })
    for k in blend:
        o[f"s1.blend.{k}"] = blend[k]
        o[f"s1.price.{k}"] = price[k]
        o[f"s1.t.{k}"] = tons[k]
    cost1 = {f"material.{k}": tons[k] * price[k] / ms for k in blend}
    cost1["byproduct"] = byp_t * p1["byproduct_t"] / ms
    conv1 = {
        "aux_materials": p1["aux_materials_kg"] * c1["aux_materials_kg"] / 1000,
        "refractories": p1["refractories_kg"] * c1["refractories_kg"] / 1000,
        "electrodes": p1["electrodes_kg"] * c1["electrodes_kg"] / 1000,
        "other_fillers": p1["other_fillers_kg"] * c1["other_fillers_kg"] / 1000,
        "electricity_eaf_lf": elec * link["eaf_lf_kwh"],
        "electricity_aux": elec * c1["electricity_aux_kwh"],
        "natural_gas": p1["natural_gas_nm3"] * c1["natural_gas_nm3"],
        "water": p1["water_m3"] * c1["water_m3"],
        "oxygen": p1["oxygen_nm3"] * c1["oxygen_nm3"],
        "nitrogen": p1["nitrogen_nm3"] * c1["nitrogen_nm3"],
        "argon": p1["argon_nm3"] * c1["argon_nm3"],
        "handling": p1["handling_t"] * c1["handling_kg"],
        "cutting": p1["cutting_t"] * c1["cutting_kg"],
    }
    yld1 = {k: ((1 / link["eaf_yield"]) - 1) * blend[k] * price[k]
            for k in ("imported", "local", "dri")}
    for k, v in {**cost1, **conv1}.items():
        o[f"s1.cost.{k}"] = v
    for k, v in yld1.items():
        o[f"s1.cost.yield.{k}"] = v
    o["s1.conversion"] = cost1["byproduct"] + sum(conv1.values()) + sum(yld1.values())
    ms_vc = sum(cost1.values()) + sum(conv1.values())
    o["s1.ms_variable_cost"] = ms_vc

    # ---- stage 2: CCP (long) / TSC (flat) ----
    crops_t = s2["byproduct_pct_of_molten_steel"] * ms
    cost2 = {
        "molten_steel": ms_vc * ms / s2_out,
        "byproduct": crops_t * p2["byproduct_t"] / s2_out,
        "aux_materials": p2["aux_materials_kg"] * c2["aux_materials_kg"] / 1000,
        "refractories": p2["refractories_kg"] * c2["refractories_kg"] / 1000,
        "electricity": elec * c2["electricity_kwh"],
        "natural_gas": p2["natural_gas_nm3"] * c2["natural_gas_nm3"],
        "water": p2["water_m3"] * c2["water_m3"],
        "oxygen": p2["oxygen_nm3"] * c2["oxygen_nm3"],
        "nitrogen": p2["nitrogen_nm3"] * c2["nitrogen_nm3"],
        "argon": p2["argon_nm3"] * c2["argon_nm3"],
    }
    yld2 = ((1 / link["s2_yield"]) - 1) * ms_vc
    s2_vc = sum(cost2.values())
    o.update({"s2.output_t": s2_out, "s2.yield": link["s2_yield"], "s2.molten_steel_t": ms,
              "s2.byproduct_t": crops_t, "s2.molten_steel_price": ms_vc,
              "s2.electricity_usd_kwh": elec, "s2.cost.yield": yld2,
              "s2.conversion": sum(v for k, v in cost2.items() if k != "molten_steel") + yld2,
              "s2.variable_cost": s2_vc})
    for k, v in cost2.items():
        o[f"s2.cost.{k}"] = v

    # ---- stage 3: rolling mill (long) / HSM (flat) ----
    rej_t = s3["byproduct_pct_of_feed"] * feed_prod
    cost3_mat = {
        "produced_feed": s2_vc * feed_prod / fin,
        "local_feed": p3["local_feed_t"] * feed_local / fin,
        "imported_feed": feed_imp * p3["imported_feed_t"] / fin,
    }
    cost3 = {
        "byproduct": rej_t * p3["byproduct_t"] / fin,
        "refractories": p3["refractories_kg"] * c3["refractories_kg"] / 1000,
        "electricity": elec * c3["electricity_kwh"],
        "natural_gas": p2["natural_gas_nm3"] * c3["natural_gas_nm3"],
        "water": p2["water_m3"] * c3["water_m3"],
        "work_roll": p3["work_roll_unit"] * c3["work_roll_units"],
    }
    yld3 = {"produced": ((1 / link["s3_yield"]) - 1) * sh["produced"] * s2_vc,
            "imported": ((1 / link["s3_yield"]) - 1) * sh["imported"] * p3["imported_feed_t"]}
    vc = sum(cost3_mat.values()) + sum(cost3.values())
    o.update({"s3.yield": link["s3_yield"], "s3.feed.produced_t": feed_prod,
              "s3.feed.local_t": feed_local, "s3.feed.imported_t": feed_imp,
              "s3.byproduct_t": rej_t, "s3.feed_price": s2_vc,
              "s3.natural_gas_usd_nm3": p2["natural_gas_nm3"], "s3.water_usd_m3": p2["water_m3"],
              "s3.cost.yield.produced": yld3["produced"], "s3.cost.yield.imported": yld3["imported"],
              "s3.conversion": sum(cost3.values()) + sum(yld3.values()),
              "s3.variable_cost": vc, "s3.variable_exp": vc * fin})
    for k, v in {**cost3_mat, **cost3}.items():
        o[f"s3.cost.{k}"] = v

    # ---- summary analysis block (feeds the 'Billet' / 'Flat' summary sheets) ----
    ey, s2y, s3y = link["eaf_yield"], link["s2_yield"], link["s3_yield"]
    mat_val = {k: cost1[f"material.{k}"] * ms for k in blend}
    conv_s1_val = {k: conv1[k] * ms for k in conv1}
    conv_s2_val = {k: cost2[k] * s2_out
                   for k in ("aux_materials", "refractories", "electricity", "natural_gas",
                             "water", "oxygen")}       # nitrogen & argon of stage 2 are not in the block
    byp_val = [cost1["byproduct"] * ms, cost2["byproduct"] * s2_out]
    if link["layout"] == "long":
        conv_val = sum(conv_s1_val.values()) + sum(conv_s2_val.values())
        o["summary.total_value"] = sum(mat_val.values()) + sum(byp_val) + conv_val
        o["summary.vc_per_t"] = o["summary.total_value"] / s2_out
        for k in ("imported", "local", "dri"):
            o[f"summary.yield.{k}"] = (1 / (ey * s2y) - 1) * price[k] * blend[k]
        o["summary.yield_effect"] = sum(o[f"summary.yield.{k}"] for k in ("imported", "local", "dri"))
        o["summary.byproduct"] = sum(byp_val) / s2_out
        o["summary.conversion_ex_byproduct"] = conv_val / s2_out
        o["summary.other_conversion"] = o["summary.conversion_ex_byproduct"] + o["summary.byproduct"]
    else:
        conv_s3_val = {k: cost3[k] * fin for k in ("refractories", "electricity", "natural_gas",
                                                   "water", "work_roll")}
        byp_val.append(cost3["byproduct"] * fin)
        conv_val = sum(conv_s1_val.values()) + sum(conv_s2_val.values()) + sum(conv_s3_val.values())
        o["summary.total_value"] = sum(mat_val.values()) + sum(byp_val) + conv_val
        o["summary.vc_per_t"] = o["summary.total_value"] / fin
        for k in ("imported", "local", "dri"):
            o[f"summary.yield.{k}"] = (1 / (ey * s2y * s3y) - 1) * price[k] * blend[k]
        o["summary.yield_effect"] = sum(o[f"summary.yield.{k}"] for k in ("imported", "local", "dri"))
        o["summary.byproduct"] = sum(byp_val) / fin
        o["summary.conversion_ex_byproduct"] = conv_val / fin
        o["summary.other_conversion"] = o["summary.conversion_ex_byproduct"] + o["summary.byproduct"]
    return o


# --------------------------------------------------------------------------- #
# ESR detail template — 'ESR Rebar' (EAF+BCCM as one stage, then rolling)
# --------------------------------------------------------------------------- #

def compute_esr_stage1(p: dict, link: dict, fx: float) -> dict:
    """Billet build-up.  link: finished_t, s3_yield, eaf_yield, bccm_yield, blend, price,
    electricity_usd_kwh, eaf_lf_kwh, and optionally extra_feed_t (billets sold to others)."""
    s1, s3 = p["stage1"], p["stage3"]
    c1, p1 = s1["consumption"], s1["prices_usd"]
    u = lambda v: _usd(v, fx)
    fin = link["finished_t"]
    sh = s3["feed_share"]
    feed_prod = fin / link["s3_yield"] * sh["produced"] + link.get("extra_feed_t", 0.0)
    y = link["eaf_yield"] * link["bccm_yield"]
    sc = feed_prod / y
    blend = {"imported": link["blend"]["imported"], "local": link["blend"]["local"],
             "dri": link["blend"]["dri"], "home": s1["blend_pct"]["home_scrap"],
             "pig": s1["blend_pct"]["pig_iron"]}
    price = {"imported": link["price"]["imported"], "local": link["price"]["local"],
             "dri": link["price"]["dri"], "home": p1["home_scrap_t"], "pig": p1["pig_iron_t"]}
    tons = {k: blend[k] * sc for k in blend}
    byp_t = s1["byproduct_pct_of_solid_charge"] * sc
    elec_kwh = link["eaf_lf_kwh"] + s1["electricity_extra_kwh"]
    elec = link["electricity_usd_kwh"]
    o: dict = {"_currency": "USD", "finished_t": fin, "s1.billets_t": feed_prod,
               "s1.eaf_yield": link["eaf_yield"], "s1.bccm_yield": link["bccm_yield"],
               "s1.yield": y, "s1.solid_charge_t": sc, "s1.byproduct_t": byp_t,
               "s1.electricity_kwh": elec_kwh, "s1.electricity_usd_kwh": elec}
    for k in blend:
        o[f"s1.blend.{k}"] = blend[k]
        o[f"s1.price.{k}"] = price[k]
        o[f"s1.t.{k}"] = tons[k]
    prices = {k: u(p1[k]) for k in ("byproduct_t", "aux_materials_kg", "refractories_kg",
                                    "electrodes_kg", "consumables_kg", "natural_gas_nm3",
                                    "water_m3", "oxygen_nm3", "nitrogen_nm3", "chemicals_unit",
                                    "handling_unit", "cutting_unit")}
    for k, v in prices.items():
        o[f"s1.p.{k}"] = v
    cost = {f"material.{k}": tons[k] * price[k] / feed_prod for k in blend}
    cost["byproduct"] = byp_t * prices["byproduct_t"] / feed_prod
    conv = {
        "aux_materials": prices["aux_materials_kg"] * c1["aux_materials_kg"] / 1000,
        "refractories": prices["refractories_kg"] * c1["refractories_kg"] / 1000,
        "electrodes": prices["electrodes_kg"] * c1["electrodes_kg"] / 1000,
        "consumables": prices["consumables_kg"] * c1["consumables_kg"] / 1000,
        "electricity": elec * elec_kwh,
        "natural_gas": prices["natural_gas_nm3"] * c1["natural_gas_nm3"],
        "water": prices["water_m3"] * c1["water_m3"],
        "oxygen": prices["oxygen_nm3"] * c1["oxygen_nm3"],
        "nitrogen": prices["nitrogen_nm3"] * c1["nitrogen_nm3"],
        "chemicals": prices["chemicals_unit"] * c1["chemicals_units"],
        "handling": prices["handling_unit"] * c1["handling_units"],
        "cutting": prices["cutting_unit"] * c1["cutting_units"],
    }
    yld = {k: ((1 / y) - 1) * blend[k] * price[k] for k in ("imported", "local", "dri")}
    for k, v in {**cost, **conv}.items():
        o[f"s1.cost.{k}"] = v
    for k, v in yld.items():
        o[f"s1.cost.yield.{k}"] = v
    o["s1.conversion"] = cost["byproduct"] + sum(conv.values()) + sum(yld.values())
    o["s1.billet_variable_cost"] = sum(cost.values()) + sum(conv.values())
    # 'Billet'!G27 = SUM('ESR Rebar'!E80:E95): byproduct + conversion lines
    o["summary.other_conversion"] = cost["byproduct"] + sum(conv.values())
    return o


def compute_esr_stage3(p: dict, link: dict, fx: float, s1: dict, billet_price: float) -> dict:
    """Rolling.  ``billet_price`` is 'Rebar'!H12 (= the Billet summary VC)."""
    s1p, s3 = p["stage1"], p["stage3"]
    c3, p3 = s3["consumption"], s3["prices_usd"]
    fin, yld = link["finished_t"], link["s3_yield"]
    sh = s3["feed_share"]
    feed = {k: fin / yld * sh[k] for k in ("produced", "local", "imported")}
    rej_t = s3["byproduct_pct_of_feed"] * sum(feed.values())
    elec = link["electricity_usd_kwh"]
    ng = _usd(s1p["prices_usd"]["natural_gas_nm3"], fx)
    water = _usd(s1p["prices_usd"]["water_m3"], fx)
    labels, tying = _usd(p3["labels_rings_unit"], fx), _usd(p3["tying_t"], fx)
    chem = _usd(p3["chemicals_unit"], fx)
    cost_mat = {"produced_feed": billet_price * feed["produced"] / fin,
                "imported_feed": feed["imported"] * p3["imported_feed_t"] / fin}
    cost = {
        "byproduct": rej_t * p3["byproduct_t"] / fin,
        "crops": s3["crops_t"] * p3["crops_t"] / fin,
        "refractories": p3["refractories_kg"] * c3["refractories_kg"] / 1000,
        "electricity": elec * c3["electricity_kwh"],
        "natural_gas": ng * c3["natural_gas_nm3"],
        "water": water * c3["water_m3"],
        "labels_rings": labels * c3["labels_rings_units"],
        "chemicals": chem * c3["chemicals_units"],
        "tying": tying * c3["tying_kg"] / 1000,
    }
    yl = {"produced": ((1 / yld) - 1) * sh["produced"] * billet_price,
          "imported": ((1 / yld) - 1) * sh["imported"] * p3["imported_feed_t"]}
    vc = sum(cost_mat.values()) + sum(cost.values())
    o = dict(s1)
    o.update({"s3.yield": yld, "s3.feed.produced_t": feed["produced"],
              "s3.feed.local_t": feed["local"], "s3.feed.imported_t": feed["imported"],
              "s3.byproduct_t": rej_t, "s3.feed_price": billet_price,
              "s3.electricity_usd_kwh": elec, "s3.natural_gas_usd_nm3": ng,
              "s3.water_usd_m3": water, "s3.labels_rings_usd": labels, "s3.tying_usd_t": tying,
              "s3.cost.yield.produced": yl["produced"], "s3.cost.yield.imported": yl["imported"],
              "s3.conversion": sum(cost.values()) + sum(yl.values()),
              "s3.variable_cost": vc, "s3.variable_exp": vc * fin})
    for k, v in {**cost_mat, **cost}.items():
        o[f"s3.cost.{k}"] = v
    # 'Rebar'!H16 = SUM('ESR Rebar'!E149:E157)
    o["summary.rolling_other_conversion"] = sum(
        cost[k] for k in ("refractories", "electricity", "natural_gas", "water",
                          "labels_rings", "chemicals", "tying"))
    return o


# --------------------------------------------------------------------------- #
# Rolling-only template — 'ERM Rolling', 'EZDK Wire' (built in LE)
# --------------------------------------------------------------------------- #

def compute_rolling_detail(p: dict, link: dict, fx: float) -> dict:
    """link: finished_t, yield (fraction), billet_price_usd_t."""
    c, pr = p["consumption"], p["prices_le"]
    fin, yld = link["finished_t"], link["yield"]
    billets = fin / yld
    sh = p["feed_share"]
    t = {k: sh[k] * billets for k in ("imported", "produced", "local")}
    byp_t = p["byproduct_pct_of_feed"] * sum(t.values())
    imp_landed = fx * pr["imported_billet_usd_t"] + pr["imported_extra_le_t"]
    billet_le = link["billet_price_usd_t"] * fx
    local_le = pr["local_billet_t"]
    byp_price = billet_le if pr["byproduct_t"] == "billet_price" else pr["byproduct_t"]
    le = {k: _le(pr[k], fx) for k in ("electricity_kwh", "natural_gas_nm3", "recycled_water_nm3",
                                      "tying_kg", "chemicals_kg", "labels_rings_kg",
                                      "spare_parts_kg", "external_services_kg")}
    raw = {"imported": t["imported"] * imp_landed / fin,
           "produced": t["produced"] * billet_le / fin,
           "local": t["local"] * local_le / fin,
           "byproduct": byp_t * byp_price / fin}
    other = {
        "electricity": c["electricity_kwh"] * le["electricity_kwh"],
        "natural_gas": c["natural_gas_nm3"] * le["natural_gas_nm3"],
        "recycled_water": c["recycled_water_nm3"] * le["recycled_water_nm3"],
        "tying": c["tying_kg"] * le["tying_kg"],
        "chemicals": c["chemicals_kg"] * le["chemicals_kg"],
        "labels_rings": c["labels_rings_kg"] * le["labels_rings_kg"],
        "spare_parts": c["spare_parts_kg"] * le["spare_parts_kg"],
        "external_services": c["external_services_kg"] * le["external_services_kg"],
    }
    other_vc = sum(other.values())
    raw_total = sum(raw.values())
    conv = {"imported": ((1 / yld) - 1) * imp_landed, "produced": ((1 / yld) - 1) * billet_le,
            "local": ((1 / yld) - 1) * local_le, "others": raw["byproduct"] + other_vc}
    vc = other_vc + raw_total
    o = {"_currency": "LE", "yield": yld, "finished_t": fin, "billets_t": billets,
         "ng_mmbtu_t": c["natural_gas_nm3"] / 28, "byproduct_t": byp_t,
         "price.imported_landed": imp_landed, "price.produced_billet": billet_le,
         "price.byproduct": byp_price, "price.electricity": le["electricity_kwh"],
         "price.natural_gas_usd_mmbtu": le["natural_gas_nm3"] * 28 / fx,
         "raw_material_cost": raw_total, "other_variable_cost": other_vc,
         "conversion_exp": sum(conv.values()) * fin,
         "variable_cost_le_t": vc, "variable_exp_le": vc * fin,
         # USD views used by the 'Rebar'/'Wire' summaries and the USD P&L
         "summary.home_scrap_usd_t": raw["byproduct"] / fx,
         "summary.other_conversion_usd_t": other_vc / fx,
         "variable_cost_usd_t": vc / fx}
    for k, v in t.items():
        o[f"t.{k}"] = v
    for k, v in raw.items():
        o[f"cost.{k}"] = v
    for k, v in other.items():
        o[f"cost.{k}"] = v
    for k, v in conv.items():
        o[f"conversion.{k}"] = v
    return o


# --------------------------------------------------------------------------- #
# 'Billet' summary sheet and trade-off matrix
# --------------------------------------------------------------------------- #

CHARGE = ("imported", "local", "dri", "home", "pig")


def _billet_inputs(state: dict, company: str) -> dict:
    b = state["billet"]["companies"][company]
    out = dict(b)
    for k in ("local_scrap_usd_t", "imported_scrap_usd_t"):
        if isinstance(b[k], dict):
            out[k] = state["billet"]["companies"][b[k]["same_as"]][k]
    return out


def _dri_margin(state: dict, buyer: str, line: str, rules: dict) -> float:
    """ERM → buyer DRI margin ($/t).  The legacy workbook keeps a second copy of the
    EFS margin on the 'Flat' sheet; corrected, one margin per buyer serves both lines."""
    if line == "flat" and not rules["own_line_inputs"] and "dri_margin_from_erm_usd_t" in state["flat"][buyer]:
        return state["flat"][buyer]["dri_margin_from_erm_usd_t"]
    return state["billet"]["companies"][buyer]["dri_margin_from_erm_usd_t"]


def _summary_from_detail(d: dict, vc: float, combined_yield: float) -> dict:
    """Rulebook §4.4: Material = Σ blend × price; Yield Effect = Material × (1/yield − 1);
    Other Conversion = Total VC − Material − Yield Effect, with VC from the detail sheet."""
    mat = sum(d[f"s1.blend.{k}"] * d[f"s1.price.{k}"] for k in CHARGE)
    yld = mat * (1 / combined_yield - 1)
    return {"material_price": mat, "yield_effect": yld, "other_conversion": vc - mat - yld,
            "total_conversion": vc - mat, "total_variable_cost": vc}


def compute_billet_summary(state: dict, dri_vc: dict, rules: dict, detail: dict) -> dict:
    """'Billet' rows 8–30 + trade-off matrix (rows 35–52).  ``detail`` maps each producer
    to its billet build-up (EZDK/EFS Rebar sheet, ESR stage 1)."""
    out: dict = {"_currency": "USD"}
    for co in BILLET_PRODUCERS:
        b = _billet_inputs(state, co)
        d = detail[co]
        dri_price = dri_vc["EZDK"] if co == "EZDK" else dri_vc["ERM"] + b["dri_margin_from_erm_usd_t"]
        row = {"dri_price": dri_price, "local_scrap_price": b["local_scrap_usd_t"],
               "imported_scrap_price": b["imported_scrap_usd_t"],
               "billet_yield_pct": b["ccp_yield_pct"] * b["eaf_yield_pct"] / 100}
        if rules["summary_from_detail"]:
            if co == "ESR":
                row.update(_summary_from_detail(d, d["s1.billet_variable_cost"], d["s1.yield"]))
            else:
                row.update(_summary_from_detail(d, d["s2.variable_cost"], d["s1.yield"] * d["s2.yield"]))
        else:
            bl = b["blend_pct"]
            mat = (dri_price * _pct(bl["dri"]) + b["local_scrap_usd_t"] * _pct(bl["local_scrap"])
                   + b["imported_scrap_usd_t"] * _pct(bl["imported_scrap"]))
            k = 1 / (_pct(b["eaf_yield_pct"]) * _pct(b["ccp_yield_pct"])) - 1
            yld = (k * dri_price * _pct(bl["dri"]) + k * b["local_scrap_usd_t"] * _pct(bl["local_scrap"])
                   + k * b["imported_scrap_usd_t"] * _pct(bl["imported_scrap"]))
            oc = d["summary.other_conversion"]
            row.update({"material_price": mat, "yield_effect": yld, "other_conversion": oc,
                        "total_conversion": yld + oc, "total_variable_cost": yld + oc + mat})
        out[co] = row
    m = state["billet"]["market_usd_t"]
    market = m["base"] + m["safe_guards"] + m["other_costs"]
    out["market_price"] = market
    out["tradeoff"] = compute_tradeoff_matrix(state, {co: out[co]["total_variable_cost"]
                                                      for co in BILLET_PRODUCERS}, market)
    return out


def compute_tradeoff_matrix(state: dict, vc: dict, market: float) -> dict:
    """Seller VC × seller trade-off ratio; the seller's own column is its plain VC.
    Constant cells typed into the workbook matrix arrive as overrides (the corrected
    baseline has none; integrity check ``no_hardcoded_results`` reports any)."""
    b = state["billet"]["companies"]
    rows = {}
    for src in BILLET_PRODUCERS:
        rows[src] = {buyer: vc[src] if buyer == src else vc[src] * b[src]["tradeoff_ratio"]
                     for buyer in COMPANIES}
        rows[src].update(state["billet"].get("tradeoff_overrides", {}).get(src, {}))
    rows["Market"] = {buyer: market for buyer in COMPANIES}
    minimum = {buyer: min(rows[r][buyer] for r in rows) for buyer in COMPANIES}
    cheapest = {buyer: min(rows, key=lambda r: rows[r][buyer]) for buyer in COMPANIES}
    return {"_currency": "USD", "rows": rows, "minimum": minimum, "cheapest_source": cheapest}


def resolve_billet_source(source: str, billet: dict) -> tuple:
    """ERM's billet source → (price $/t, supplying company or None for market).
    'market' | 'min' (cheapest row of the trade-off matrix) | 'offer:<CO>' (that
    company's intercompany price) | 'vc:<CO>' (that company's VC, i.e. at cost)."""
    if source == "market":
        return billet["market_price"], None
    if source == "min":
        src = billet["tradeoff"]["cheapest_source"]["ERM"]
        return billet["tradeoff"]["minimum"]["ERM"], (None if src == "Market" else src)
    kind, co = source.split(":")
    if kind == "vc":
        return billet[co]["total_variable_cost"], co
    if kind == "offer":
        return billet["tradeoff"]["rows"][co]["ERM"], co
    raise ValueError(f"unknown billet source {source!r}")


# --------------------------------------------------------------------------- #
# 'Rebar', 'Wire', 'Flat' summary sheets
# --------------------------------------------------------------------------- #

def _finished_summary(material_sc1, market, yield_pct, home_scrap, other_conv):
    def sc(mat):
        y = mat * ((1 / _pct(yield_pct)) - 1)
        conv = other_conv + home_scrap + y
        return {"material_price": mat, "yield_effect": y, "home_scrap_deduction": home_scrap,
                "other_conversion": other_conv, "total_conversion": conv,
                "total_variable_cost": conv + mat}
    s1, s2 = sc(material_sc1), sc(market)
    return {"sc1": s1, "sc2": s2, "difference": s1["total_variable_cost"] - s2["total_variable_cost"]}


def compute_flat_summary(state: dict, dri_vc: dict, rules: dict, detail: dict) -> dict:
    out: dict = {"_currency": "USD"}
    for co in HRC_PRODUCERS:
        f = state["flat"][co]
        d = detail[co]
        dri_price = dri_vc["EZDK"] if co == "EZDK" else dri_vc["ERM"] + _dri_margin(state, co, "flat", rules)
        if rules["summary_from_detail"]:
            row = _summary_from_detail(d, d["s3.variable_cost"],
                                       d["s1.yield"] * d["s2.yield"] * d["s3.yield"])
        else:
            bl = f["blend_pct"]
            mat = (dri_price * _pct(bl["dri"]) + f["local_scrap_usd_t"] * _pct(bl["local_scrap"])
                   + f["imported_scrap_usd_t"] * _pct(bl["imported_scrap"]))
            k = 1 / (_pct(f["eaf_yield_pct"]) * _pct(f["tsc_yield_pct"]) * _pct(f["hsm_yield_pct"])) - 1
            yld = (k * dri_price * _pct(bl["dri"]) + k * f["local_scrap_usd_t"] * _pct(bl["local_scrap"])
                   + k * f["imported_scrap_usd_t"] * _pct(bl["imported_scrap"]))
            oc = d["summary.other_conversion"]
            row = {"material_price": mat, "yield_effect": yld, "other_conversion": oc,
                   "total_conversion": yld + oc, "total_variable_cost": yld + oc + mat}
        out[co] = {"dri_price": dri_price, **row}
    return out


# --------------------------------------------------------------------------- #
# 'Market Share', 'Production Requirments', 'Fixed Cost'
# --------------------------------------------------------------------------- #

def _pct_of(a, b):
    v = _div(a, b)
    return None if v is None else v * 100


def compute_market_share(state: dict, rules: dict) -> dict:
    s, mkt = state["sales"], state["total_local_market_kt"]
    rebar = {co: s[co]["Rebar"]["local_kt"] for co in COMPANIES}
    hrc = {co: s[co]["HRC"]["local_kt"] for co in HRC_PRODUCERS}
    grp = {"Rebar": sum(rebar.values()), "Wire Rod": s["EZDK"]["Wire Rod"]["local_kt"]}
    if rules["market_share_hrc"]:
        grp["HRC"] = sum(hrc.values())
    else:  # 'Market Share'!G11 = SUM(G22:G23): sums the market-size cells
        grp["HRC"] = mkt["HRC"] or 0.0
    share = {p: _pct_of(grp[p], mkt[p]) for p in ("Rebar", "Wire Rod")}
    if rules["market_share_hrc"]:
        share["HRC"] = _pct_of(grp["HRC"], mkt["HRC"])
    return {
        "_currency": "none",
        "group_local_kt": grp,
        "ezz_share_pct": share,
        "others_share_pct": {p: None if v is None else 100 - v for p, v in share.items()},
        "company_pct_of_group": {
            "Rebar": {co: _pct_of(rebar[co], grp["Rebar"]) for co in COMPANIES},
            "Wire Rod": {"EZDK": _pct_of(grp["Wire Rod"], grp["Wire Rod"])},
            "HRC": {co: _pct_of(hrc[co], grp["HRC"]) for co in HRC_PRODUCERS},
        },
    }


def compute_production(state: dict, det: dict, rules: dict, erm_supplier) -> dict:
    """'Production Requirments' — sales-driven cascade, in Ktons."""
    k = 1000.0
    ez, efs, esr = det["EZDK Rebar"], det["EFS Rebar"], det["ESR Rebar"]
    erm, wire = det["ERM Rolling"], det["EZDK Wire"]
    ezf, efsf = det["EZDK Flat"], det["EFS Flat"]
    mrmr_ez, mrmr_erm = state["dri"]["EZDK"]["mrmr"], state["dri"]["ERM"]["mrmr"]
    long = {
        "EZDK": {"rebar": ez["finished_t"] / k, "wire_rod": wire["finished_t"] / k,
                 "billet": ez["s2.output_t"] / k, "molten_steel": ez["s1.molten_steel_t"] / k,
                 "solid_charge": ez["s1.solid_charge_t"] / k, "dri_pct": ez["s1.blend.dri"],
                 "dri": ez["s1.t.dri"] / k, "imported_scrap_pct": ez["s1.blend.imported"],
                 "imported_scrap": ez["s1.t.imported"] / k, "local_scrap_pct": ez["s1.blend.local"],
                 "local_scrap": ez["s1.t.local"] / k, "mrmr": mrmr_ez},
        "EFS": {"rebar": efs["finished_t"] / k, "billet": efs["s2.output_t"] / k,
                "molten_steel": efs["s2.molten_steel_t"] / k,
                "solid_charge": efs["s1.solid_charge_t"] / k, "dri_pct": efs["s1.blend.dri"],
                "dri": efs["s1.t.dri"] / k, "imported_scrap_pct": efs["s1.blend.imported"],
                "imported_scrap": efs["s1.t.imported"] / k, "local_scrap_pct": efs["s1.blend.local"],
                "local_scrap": efs["s1.t.local"] / k},
        "ERM": {"rebar": erm["finished_t"] / k, "billet": erm["billets_t"] / k, "mrmr": mrmr_erm},
        "ESR": {"rebar": esr["finished_t"] / k, "billet": esr["s1.billets_t"] / k,
                "molten_steel": esr["s1.billets_t"] / k / esr["s1.bccm_yield"],
                "solid_charge": esr["s1.solid_charge_t"] / k, "dri_pct": esr["s1.blend.dri"],
                "dri": esr["s1.t.dri"] / k, "imported_scrap_pct": esr["s1.blend.imported"],
                "imported_scrap": esr["s1.t.imported"] / k, "local_scrap_pct": esr["s1.blend.local"],
                "local_scrap": esr["s1.t.local"] / k},
    }
    long["EZDK"]["iop"] = long["EZDK"]["dri"] * mrmr_ez
    long["ERM"]["iop"] = (long["EFS"]["dri"] + long["ESR"]["dri"]) * mrmr_erm
    flat = {}
    for co, d in (("EZDK", ezf), ("EFS", efsf)):
        flat[co] = {"hrc": d["finished_t"] / k, "molten_steel": d["s1.molten_steel_t"] / k,
                    "solid_charge": d["s1.solid_charge_t"] / k, "dri_pct": d["s1.blend.dri"],
                    "dri": d["s1.t.dri"] / k, "imported_scrap_pct": d["s1.blend.imported"],
                    "imported_scrap": d["s1.t.imported"] / k, "local_scrap_pct": d["s1.blend.local"],
                    "local_scrap": d["s1.t.local"] / k}
    flat["EZDK"]["mrmr"] = mrmr_ez
    flat["EZDK"]["iop"] = flat["EZDK"]["dri"] * mrmr_ez
    flat["ERM"] = {"mrmr": mrmr_erm, "iop": flat["EFS"]["dri"] * mrmr_erm}

    # ERM buys its billets; corrected, they are not counted as group production again
    # (an internal purchase is already inside the supplier's billet figure).
    produced_only = rules["billet_interco"]
    long["ERM"]["billet_source"] = erm_supplier or "market"

    def tot(section, key):
        return sum(v.get(key, 0.0) for c, v in section.items()
                   if not (produced_only and key == "billet" and c == "ERM"))

    long_tot = {key: tot(long, key) for key in ("rebar", "wire_rod", "billet", "molten_steel",
                                                "solid_charge", "dri", "imported_scrap",
                                                "local_scrap", "iop")}
    flat_tot = {key: tot(flat, key) for key in ("hrc", "molten_steel", "solid_charge", "dri",
                                                "imported_scrap", "local_scrap", "iop")}
    summary = {
        "EZDK": {"rebar": long["EZDK"]["rebar"], "wire_rod": long["EZDK"]["wire_rod"],
                 "hrc": flat["EZDK"]["hrc"], "billet": long["EZDK"]["billet"],
                 "dri": flat["EZDK"]["dri"] + long["EZDK"]["dri"],
                 "iop": long["EZDK"]["iop"] + flat["EZDK"]["iop"]},
        "EFS": {"rebar": long["EFS"]["rebar"], "hrc": flat["EFS"]["hrc"],
                "billet": long["EFS"]["billet"], "dri": flat["EFS"]["dri"] + long["EFS"]["dri"]},
        "ERM": {"rebar": long["ERM"]["rebar"], "billet": long["ERM"]["billet"],
                "iop": long["ERM"]["iop"] + flat["ERM"]["iop"]},
        "ESR": {"rebar": long["ESR"]["rebar"], "billet": long["ESR"]["billet"],
                "dri": long["ESR"]["dri"]},
    }
    for co in ("EZDK", "EFS", "ESR"):
        summary[co]["scrap"] = (long[co]["imported_scrap"] + long[co]["local_scrap"]
                                + flat.get(co, {}).get("imported_scrap", 0.0)
                                + flat.get(co, {}).get("local_scrap", 0.0))
    sum_tot = {key: tot(summary, key) for key in ("rebar", "wire_rod", "hrc", "billet",
                                                  "dri", "iop", "scrap")}
    return {"_currency": "none", "long": long, "long_total": long_tot, "flat": flat,
            "flat_total": flat_tot, "summary": summary, "summary_total": sum_tot}


_FIXED_LINES = (("manufacturing", "manufacturing_musd"), ("sga", "sga_musd"),
                ("net_finance", "net_finance_musd"), ("depreciation", "depreciation_musd"))


def compute_fixed_allocation(state: dict) -> dict:
    fc, fx = state["fixed_cost"], state["fx_egp_per_usd"]
    usd, le = {}, {}
    for co in COMPANIES:
        f = fc[co]
        w = f["manufacturing_musd"] + f["sga_musd"] + f["net_finance_musd"]
        usd[co] = {"total_wo_dep": w, "manufacturing": f["manufacturing_musd"],
                   "sga": f["sga_musd"], "net_finance": f["net_finance_musd"],
                   "depreciation": f["depreciation_musd"],
                   "total_with_dep": f["depreciation_musd"] + w}
        le[co] = {k: usd[co][k] * fx for k in ("total_wo_dep", "manufacturing", "sga",
                                               "net_finance", "depreciation")}
    usd["Total"] = {k: sum(usd[co][k] for co in COMPANIES) for k in usd["EZDK"]}
    le["Total"] = {k: sum(le[co][k] for co in COMPANIES) for k in le["EZDK"]}
    dist_total = {co: sum(fc[co]["distribution_pct"].values()) for co in COMPANIES}
    alloc = {}
    for prod in ("DRI", "Rebar", "Wire Rod", "HRC"):
        alloc[prod] = {}
        for co in COMPANIES:
            pct = fc[co]["distribution_pct"][prod]
            alloc[prod][co] = {line: _pct(pct) * fc[co][key] for line, key in _FIXED_LINES}
        alloc[prod]["Total"] = {line: sum(alloc[prod][co][line] for co in COMPANIES)
                                for line, _ in _FIXED_LINES}
        alloc[prod]["Total"]["total"] = sum(alloc[prod]["Total"][line] for line, _ in _FIXED_LINES)
    return {"_currency": "USD", "usd_m": usd, "le_m": le, "distribution_total_pct": dist_total,
            "allocation_usd_m": alloc}


# --------------------------------------------------------------------------- #
# P&L — 'P&L $ Monthly', 'P&L LE Monthly', 'P&L $ Annual', 'P&L LE Annual'
# --------------------------------------------------------------------------- #

PNL_VARIANTS = {
    "usd_monthly": ("P&L $ Monthly", False, False),
    "le_monthly": ("P&L LE Monthly", True, False),
    "usd_annual": ("P&L $ Annual", False, True),
    "le_annual": ("P&L LE Annual", True, True),
}

# workbook column letter → P&L column key
PNL_COLUMN_LETTERS = {
    "E": "EZDK/Rebar", "F": "EZDK/Wire Rod", "G": "EZDK/HRC", "H": "EZDK/Sub-Total",
    "J": "EFS/Rebar", "K": "EFS/HRC", "L": "EFS/Sub-Total", "N": "ERM/Rebar",
    "P": "ESR/Rebar", "R": "Total",
}

_PRODUCT_LINES = (("EZDK", "Rebar"), ("EZDK", "Wire Rod"), ("EZDK", "HRC"), ("EFS", "Rebar"),
                  ("EFS", "HRC"), ("ERM", "Rebar"), ("ESR", "Rebar"))


def _variable_cost_per_t(det: dict, co: str, prod: str, in_le: bool, fx: float) -> float:
    if (co, prod) in (("EZDK", "Wire Rod"), ("ERM", "Rebar")):
        d = det["EZDK Wire" if prod == "Wire Rod" else "ERM Rolling"]
        return d["variable_cost_le_t"] if in_le else d["variable_cost_usd_t"]
    sheet = {("EZDK", "Rebar"): "EZDK Rebar", ("EZDK", "HRC"): "EZDK Flat",
             ("EFS", "Rebar"): "EFS Rebar", ("EFS", "HRC"): "EFS Flat",
             ("ESR", "Rebar"): "ESR Rebar"}[(co, prod)]
    return det[sheet]["s3.variable_cost"] * (fx if in_le else 1.0)


def compute_pnl(state: dict, det: dict, fixed: dict, variant: str, rules: dict, interco: dict) -> dict:
    sheet, in_le, annual = PNL_VARIANTS[variant]
    fx = state["fx_egp_per_usd"]
    cur = fx if in_le else 1.0
    mult = 12.0 if annual else 1.0
    s = state["sales"]
    cv = rules["consistent_volumes"]
    alloc = fixed["allocation_usd_m"]
    cols: dict = {}
    for co, prod in _PRODUCT_LINES:
        sl = s[co][prod]
        local_q = sl["local_kt"] * mult
        if cv:
            export_q = sl["export_kt"] * mult
        elif co in ("ERM", "ESR"):
            export_q = 0.0
        elif (co, prod) == ("EFS", "Rebar") or ((co, prod) == ("EZDK", "Rebar") and variant == "le_annual"):
            export_q = sl["export_kt"]           # the workbook forgets ×12 here
        else:
            export_q = sl["export_kt"] * mult
        qty = local_q + export_q
        local_price = sl["local_price_le_t"] if in_le else sl["local_price_le_t"] / fx
        local_val = local_price * (qty if (co == "ESR" and not cv) else local_q) / 1000
        if not cv and (co, prod) in (("EFS", "Rebar"), ("ERM", "Rebar"), ("ESR", "Rebar")):
            export_price, export_val = 0.0, 0.0  # hardcoded 0 in the workbook
        else:
            export_price = sl["export_price_usd_t"] * cur
            export_val = export_price * export_q / 1000
        vc = _variable_cost_per_t(det, co, prod, in_le, fx)
        if rules["export_expense_per_ton"]:
            exp = export_q * state["pnl"]["export_expense_usd_t"][co][prod] * cur / 1000
        else:                                     # the workbook subtracts the typed figure as M$
            exp = state["pnl"].get("export_expense_rate", {}).get(co, {}).get(prod, 0.0) * cur * mult
        gain = None
        if co == "ERM" and not rules["erm_dri_pnl"]:
            gain = state["pnl"].get("intercompany_gain_dri_musd", {}).get("ERM", 0.0) * cur * mult
            fl = {line: fixed["usd_m"]["ERM"][line] for line, _ in _FIXED_LINES}
        else:
            fl = dict(alloc[prod][co])
            if co == "ESR" and not rules["erm_dri_pnl"]:
                fl["depreciation"] = fixed["usd_m"]["ESR"]["depreciation"]
        fl = {k: v * cur * mult for k, v in fl.items()}
        c = _pnl_column(local_q, export_q, local_val, local_price, export_val, export_price,
                        qty * vc / 1000, vc, exp, gain, fl, rules)
        c.update(company=co, product=prod, intercompany=False)
        cols[f"{co}/{prod}"] = c

    for key, x in interco.items():               # intercompany sales (corrected model)
        fl = {k: v * cur * mult for k, v in x["fixed_usd_m"].items()}
        q = x["qty_kt"] * mult
        rev = x["revenue_usd_m"] * cur * mult
        cogs = x["cogs_usd_m"] * cur * mult
        c = _pnl_column(q, 0.0, rev, _div(rev * 1000, q), 0.0, 0.0, cogs,
                        _div(cogs * 1000, q), 0.0, None, fl, rules)
        c.update(company=x["seller"], product=x["product"], intercompany=True,
                 buyers=x["buyers"])
        cols[key] = c

    for co in COMPANIES:
        members = [c for c in cols.values() if c["company"] == co and "product" in c]
        if members:
            cols[f"{co}/Sub-Total"] = _pnl_subtotal(members, rules)
            cols[f"{co}/Sub-Total"].update(company=co)
    if not cv:   # 'P&L $ Monthly'!L14 is a hardcoded 0 and L21 = K21
        cols["EFS/Sub-Total"]["export_price"] = 0.0
        cols["EFS/Sub-Total"]["export_expenses"] = cols["EFS/HRC"]["export_expenses"]
    cols["Total"] = _pnl_subtotal([cols[f"{co}/Sub-Total"] for co in COMPANIES
                                   if f"{co}/Sub-Total" in cols], rules)
    cols["Total"]["intercompany_gain_dri"] = cols["ERM/Rebar"]["intercompany_gain_dri"]
    for c in cols.values():                      # row 42 ('P&L $ Annual' only in the workbook)
        c["depreciation_per_t"] = _div(c["depreciation"] * 1000, c["total_qty"])
    return {"_currency": "LE" if in_le else "USD", "sheet": sheet, "columns": cols}


def _pnl_column(lq, eq, lv, lp, ev, ep, cogs, vc, exp, gain, fl, rules):
    qty = lq + eq
    total = lv + ev
    cm = total - cogs - exp
    fixed_tot = fl["manufacturing"] + fl["sga"] + fl["net_finance"]
    ebtd = cm + (gain or 0.0) - fixed_tot
    c = {"local_qty": lq, "export_qty": eq, "total_qty": qty, "local_value": lv, "local_price": lp,
         "export_value": ev, "export_price": ep, "total_value": total,
         "avg_price": _div(total * 1000, qty), "variable_cogs": cogs, "cost_per_t": vc,
         "export_expenses": exp, "contribution_margin": cm, "intercompany_gain_dri": gain,
         "manufacturing_fixed": fl["manufacturing"], "sga": fl["sga"],
         "net_finance": fl["net_finance"], "total_fixed": fixed_tot, "ebtd": ebtd,
         "depreciation": fl["depreciation"], "ebt": ebtd - fl["depreciation"]}
    return _pnl_ratios(c, rules)


def _per_t(v, q):
    return _div(v * 1000, q) if v is not None else None


def _pct_of_price(per_t, price):
    return _div(per_t, price) and per_t / price * 100


def _pnl_ratios(c, rules):
    q = c["total_qty"]
    c["cm_per_t"] = _per_t(c["contribution_margin"], q)
    c["cm_pct"] = _pct_of_price(c["cm_per_t"], c["avg_price"])
    c["ebtd_per_t"] = _per_t(c["ebtd"], q)
    c["ebtd_pct"] = _pct_of_price(c["ebtd_per_t"], c["avg_price"])
    c["fc_per_t"] = _per_t(c["depreciation"] + c["total_fixed"], q)
    c["ebt_per_t"] = _per_t(c["ebt"], q)
    c["ebt_pct"] = _pct_of_price(c["ebt_per_t"], c["avg_price"])
    c["vc_plus_fc_per_t"] = None if c["fc_per_t"] is None or c["cost_per_t"] is None \
        else c["cost_per_t"] + c["fc_per_t"]
    fixed_all = c["total_fixed"] + c["depreciation"]
    if q == 0:            # rulebook check 7 (Excel shows #DIV/0!)
        c["break_even_qty"] = 0.0
        c["cash_break_even_qty"] = 0.0
    elif rules["break_even_on_cm"]:
        # quantity at which CM covers the fixed costs; none if each ton loses money
        cm_t = c["cm_per_t"]
        c["break_even_qty"] = _div(fixed_all * 1000, cm_t) if cm_t and cm_t > 0 else None
        c["cash_break_even_qty"] = _div(c["total_fixed"] * 1000, cm_t) if cm_t and cm_t > 0 else None
    else:                 # workbook: (fixed + dep) ÷ (average price − VC per ton)
        margin = None if c["avg_price"] is None or c["cost_per_t"] is None \
            else c["avg_price"] - c["cost_per_t"]
        c["break_even_qty"] = _div(fixed_all * 1000, margin)
        c["cash_break_even_qty"] = None
    return c


_ADDITIVE = ("local_qty", "export_qty", "total_qty", "local_value", "export_value", "total_value",
             "variable_cogs", "export_expenses", "contribution_margin", "manufacturing_fixed",
             "sga", "net_finance", "total_fixed", "ebtd", "depreciation", "ebt")


def _pnl_subtotal(parts, rules):
    c = {k: sum(p[k] for p in parts) for k in _ADDITIVE}
    c["intercompany_gain_dri"] = None
    c["local_price"] = _per_t(c["local_value"], c["local_qty"])
    c["export_price"] = _per_t(c["export_value"], c["export_qty"])
    c["avg_price"] = _per_t(c["total_value"], c["total_qty"])
    c["cost_per_t"] = _per_t(c["variable_cogs"], c["total_qty"])
    return _pnl_ratios(c, rules)


def compute_consolidated(pnl: dict, rules: dict) -> dict:
    """Group P&L: each company's sub-total, an explicit eliminations column, and the
    consolidated figures (rulebook §8.4–8.6).  Buyers' COGS carry intercompany
    purchases at transfer price, so eliminating the intercompany revenue from both
    revenue and COGS leaves the contribution margin unchanged."""
    cols = pnl["columns"]
    companies = {co: cols[f"{co}/Sub-Total"] for co in COMPANIES if f"{co}/Sub-Total" in cols}
    interco = [c for c in cols.values() if c.get("intercompany")]
    elim_rev = sum(c["total_value"] for c in interco)
    elim_qty = sum(c["total_qty"] for c in interco)
    lines = ("total_value", "variable_cogs", "export_expenses", "contribution_margin",
             "manufacturing_fixed", "sga", "net_finance", "total_fixed", "ebtd",
             "depreciation", "ebt")
    elims = {k: 0.0 for k in lines}
    elims["total_value"] = -elim_rev
    elims["variable_cogs"] = -elim_rev
    total = {k: sum(c[k] for c in companies.values()) for k in lines}
    cons = {k: total[k] + elims[k] for k in lines}
    ext_qty = sum(c["total_qty"] for c in companies.values()) - elim_qty
    local_qty = sum(c["local_qty"] for c in cols.values()
                    if "product" in c and not c.get("intercompany"))
    local_val = sum(c["local_value"] for c in cols.values()
                    if "product" in c and not c.get("intercompany"))
    cons.update({
        "external_sales_qty": ext_qty,
        "local_qty": local_qty,
        "local_value": local_val,
        "avg_local_price": _per_t(local_val, local_qty),    # rulebook §8.5
        "cm_pct": _pct_of_price(cons["contribution_margin"], cons["total_value"]),
        "ebt_pct": _pct_of_price(cons["ebt"], cons["total_value"]),
    })
    return {"_currency": pnl["_currency"],
            "companies": {co: {k: c[k] for k in lines} for co, c in companies.items()},
            "eliminations": elims, "consolidated": cons,
            "intercompany_sales": {k: {"seller": c["company"], "product": c["product"],
                                       "qty": c["total_qty"], "revenue": c["total_value"]}
                                   for k, c in cols.items() if c.get("intercompany")}}


# --------------------------------------------------------------------------- #
# Integrity checks (rulebook §12, brief §4.7)
# --------------------------------------------------------------------------- #

def _close(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def _check_fixed_distribution_sums(state):
    bad = {co: sum(state["fixed_cost"][co]["distribution_pct"].values()) for co in COMPANIES}
    bad = {co: v for co, v in bad.items() if abs(v - 100) > 0.01}
    return (not bad, "fixed-cost distribution sums to 100% for every company" if not bad
            else f"fixed-cost distribution does not sum to 100%: {bad}")


def _check_blending_ratios_sum(state):
    """DRI + local + imported scrap (summary sheets) + home scrap + pig iron (detail
    sheets, stored as fractions) must make 100% of the charge on every line."""
    bad = {}
    lines = [(f"{co} long", state["billet"]["companies"][co]["blend_pct"], f"{co} Rebar")
             for co in BILLET_PRODUCERS]
    lines += [(f"{co} flat", state["flat"][co]["blend_pct"], f"{co} Flat") for co in HRC_PRODUCERS]
    for name, bl, sheet in lines:
        extra = state["detail"][sheet]["stage1"]["blend_pct"]
        t = sum(bl.values()) + 100 * (extra["home_scrap"] + extra["pig_iron"])
        if abs(t - 100) > 0.01:
            bad[name] = round(t, 4)
    return (not bad, "blending ratios sum to 100% on every line" if not bad
            else f"blending ratios do not sum to 100%: {bad}")


def _check_no_hardcoded_results(state, rules):
    found = []
    for src, row in state["billet"].get("tradeoff_overrides", {}).items():
        found += [f"trade-off matrix {src}→{buyer} typed as {v}" for buyer, v in row.items()]
    gain = state["pnl"].get("intercompany_gain_dri_musd", {}).get("ERM", 0.0)
    if gain and not rules["erm_dri_pnl"]:
        found.append(f"ERM DRI intercompany gain typed as {gain} M$")
    return (not found, "no typed-in results" if not found else "typed-in results: " + "; ".join(found))


def _check_currency_consistency(outputs):
    bad = [k for k, v in outputs.items()
           if isinstance(v, dict) and v.get("_currency") not in ("USD", "LE", "none")
           and not all(isinstance(x, dict) and x.get("_currency") in ("USD", "LE", "none")
                       for x in v.values())]
    return (not bad, "every output view declares its currency" if not bad
            else f"views without a currency tag: {bad}")


def _check_break_even_zero_when_no_sales(outputs):
    bad = [f"{v}:{c}" for v, p in outputs["pnl"].items() for c, col in p["columns"].items()
           if col["total_qty"] == 0 and col["break_even_qty"] != 0]
    return (not bad, "break-even is 0 wherever sales are 0" if not bad else f"break-even ≠ 0: {bad}")


def _check_intercompany_reconciliation(outputs, fx):
    """Seller's intercompany revenue = cost the buyers carry for the same goods."""
    det, cols = outputs["detail"], outputs["pnl"]["usd_monthly"]["columns"]
    msgs, ok = [], True
    if "ERM/DRI" in cols:
        bought = sum(det[sh]["s1.t.dri"] * det[sh]["s1.price.dri"]
                     for sh in ("EFS Rebar", "EFS Flat", "ESR Rebar")) / 1e6
        sold = cols["ERM/DRI"]["total_value"]
        ok &= _close(bought, sold)
        msgs.append(f"DRI: ERM sold {sold:.4f} M$, EFS+ESR bought {bought:.4f} M$")
    for key, c in cols.items():
        if c.get("intercompany") and c["product"] == "Billet":
            erm = det["ERM Rolling"]
            bought = erm["t.produced"] * erm["price.produced_billet"] / fx / 1e6
            ok &= _close(bought, c["total_value"])
            msgs.append(f"billet: {c['company']} sold {c['total_value']:.4f} M$, ERM bought {bought:.4f} M$")
    return ok, "; ".join(msgs) or "no intercompany sales"


def _check_summary_matches_detail(outputs):
    det, bad = outputs["detail"], []
    pairs = [("billet EZDK", outputs["billet"]["EZDK"]["total_variable_cost"], det["EZDK Rebar"]["s2.variable_cost"]),
             ("billet EFS", outputs["billet"]["EFS"]["total_variable_cost"], det["EFS Rebar"]["s2.variable_cost"]),
             ("billet ESR", outputs["billet"]["ESR"]["total_variable_cost"], det["ESR Rebar"]["s1.billet_variable_cost"]),
             ("HRC EZDK", outputs["flat"]["EZDK"]["total_variable_cost"], det["EZDK Flat"]["s3.variable_cost"]),
             ("HRC EFS", outputs["flat"]["EFS"]["total_variable_cost"], det["EFS Flat"]["s3.variable_cost"]),
             ("rebar EZDK", outputs["rebar"]["EZDK"]["sc1"]["total_variable_cost"], det["EZDK Rebar"]["s3.variable_cost"]),
             ("rebar EFS", outputs["rebar"]["EFS"]["sc1"]["total_variable_cost"], det["EFS Rebar"]["s3.variable_cost"]),
             ("rebar ESR", outputs["rebar"]["ESR"]["sc1"]["total_variable_cost"], det["ESR Rebar"]["s3.variable_cost"]),
             ("rebar ERM", outputs["rebar"]["ERM"]["sc1"]["total_variable_cost"], det["ERM Rolling"]["variable_cost_usd_t"]),
             ("wire EZDK", outputs["wire"]["EZDK"]["sc1"]["total_variable_cost"], det["EZDK Wire"]["variable_cost_usd_t"])]
    bad = [f"{n}: summary {a:.4f} vs detail {b:.4f}" for n, a, b in pairs if not _close(a, b)]
    return (not bad, "summary cost sheets equal the detailed build-up" if not bad
            else "summary ≠ detail: " + "; ".join(bad))


# A failed "error" check means the numbers cannot be trusted; a failed "warning" check
# (capacity) means the plan is physically stretched — reported, never blocking.
CHECK_SEVERITY = {"capacity_within_limits": "warning"}


def compute_capacity(state: dict, outputs: dict) -> dict:
    """Utilisation against the monthly ceilings (system prompt, Appendix A).  Billet has no
    ceiling: billet capacity is taken to follow downstream demand."""
    caps = state.get("capacity_ceilings")
    if not caps:
        return {"_currency": "none", "items": {}}
    det = outputs["detail"]
    sheet = {("EZDK", "Rebar"): "EZDK Rebar", ("EZDK", "Wire Rod"): "EZDK Wire",
             ("EZDK", "HRC"): "EZDK Flat", ("EFS", "Rebar"): "EFS Rebar", ("EFS", "HRC"): "EFS Flat",
             ("ERM", "Rebar"): "ERM Rolling", ("ESR", "Rebar"): "ESR Rebar"}
    items = {}
    for co, cap in caps.get("dri", {}).items():
        items[f"DRI {co}"] = (outputs["dri"][co]["production_t"], cap)
    for co, prods in caps.get("finished", {}).items():
        for prod, cap in prods.items():
            items[f"{prod} {co}"] = (det[sheet[(co, prod)]]["finished_t"], cap)
    return {"_currency": "none", "items": {
        k: {"required_t": req, "ceiling_t": cap, "utilisation_pct": _pct_of(req, cap),
            "over_by_t": max(0.0, req - cap)} for k, (req, cap) in items.items()}}


def _check_capacity(capacity: dict):
    over = {k: v for k, v in capacity["items"].items() if v["over_by_t"] > 1e-6}
    return (not over, "every stage within its monthly capacity" if not over else
            "over capacity: " + "; ".join(f"{k} needs {v['required_t']:,.0f} t vs {v['ceiling_t']:,.0f} t "
                                          f"({v['utilisation_pct']:.1f}%)" for k, v in over.items()))


def run_integrity_checks(state: dict, outputs: dict | None = None, rules: dict | None = None) -> list:
    """Returns [(name, passed, detail)].  Checks 3 and 4 hold by construction: the matrix
    is computed on demand and every quantity is derived from sales.  Severity of each
    check: CHECK_SEVERITY (default "error")."""
    rules = rules or CORRECTED_RULES
    res = [("fixed_distribution_100", *_check_fixed_distribution_sums(state)),
           ("blending_100", *_check_blending_ratios_sum(state)),
           ("no_hardcoded_results", *_check_no_hardcoded_results(state, rules))]
    if outputs is not None:
        res.append(("currency_tagged", *_check_currency_consistency(outputs)))
        res.append(("break_even_zero", *_check_break_even_zero_when_no_sales(outputs)))
        if rules["erm_dri_pnl"] or rules["billet_interco"]:
            res.append(("intercompany_reconciles",
                        *_check_intercompany_reconciliation(outputs, state["fx_egp_per_usd"])))
        if rules["summary_from_detail"]:
            res.append(("summary_matches_detail", *_check_summary_matches_detail(outputs)))
        if outputs.get("capacity", {}).get("items"):
            res.append(("capacity_within_limits", *_check_capacity(outputs["capacity"])))
    return res


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def rules_for(state: dict) -> dict:
    return LEGACY_RULES if state.get("rules_profile") == "legacy" else CORRECTED_RULES


def compute_all(state: dict, rules: dict | None = None, strict: bool = False) -> dict:
    """Every view of the model.  ``rules`` defaults to the state's ``rules_profile``
    (corrected unless the state says "legacy").  ``strict`` raises IntegrityError on the
    first failed check."""
    rules = {**(rules_for(state) if rules is None else rules)}
    missing = set(RULES) - set(rules)
    if missing:
        raise ValueError(f"rules missing: {sorted(missing)}")
    fx = state["fx_egp_per_usd"]
    s = state["sales"]
    D = state["detail"]
    cv = rules["consistent_volumes"]

    def sold_t(co, prod, with_export=True):
        x = s[co][prod]
        return (x["local_kt"] + (x["export_kt"] if with_export else 0.0)) * 1000

    # Stage 1 — DRI variable cost
    dri_var = {co: compute_dri_variable(state, co) for co in ("EZDK", "ERM")}
    dri_vc = {co: dri_var[co]["summary_usd_t"]["total_variable_cost"] for co in dri_var}

    # Stage 2 — billet producers' detail sheets
    bil = {co: _billet_inputs(state, co) for co in BILLET_PRODUCERS}
    dri_price = {"EZDK": dri_vc["EZDK"],
                 "EFS": dri_vc["ERM"] + _dri_margin(state, "EFS", "long", rules),
                 "ESR": dri_vc["ERM"] + _dri_margin(state, "ESR", "long", rules)}
    fy = state["finishing_yield_pct"]
    wire_t = sold_t("EZDK", "Wire Rod")
    wire_billets = wire_t / _pct(fy["Wire Rod"]["EZDK"])

    def long_link(co, finished_t, extra):
        b = bil[co]
        return {"layout": "long", "finished_t": finished_t, "extra_feed_t": extra,
                "eaf_yield": _pct(b["eaf_yield_pct"]), "s2_yield": _pct(b["ccp_yield_pct"]),
                "s3_yield": _pct(fy["Rebar"][co]),
                "blend": {"imported": _pct(b["blend_pct"]["imported_scrap"]),
                          "local": _pct(b["blend_pct"]["local_scrap"]),
                          "dri": _pct(b["blend_pct"]["dri"])},
                "price": {"imported": b["imported_scrap_usd_t"], "local": b["local_scrap_usd_t"],
                          "dri": dri_price[co]},
                "electricity_usd_kwh": b["electricity_usd_kwh"],
                "eaf_lf_kwh": b["eaf_lf_electricity_kwh_t_ms"]}

    def flat_link(co):
        f = state["flat"][co]
        dp = dri_vc["EZDK"] if co == "EZDK" else dri_vc["ERM"] + _dri_margin(state, co, "flat", rules)
        return {"layout": "flat", "finished_t": sold_t(co, "HRC"),
                "extra_feed_t": 0.0, "eaf_yield": _pct(f["eaf_yield_pct"]),
                "s2_yield": _pct(f["tsc_yield_pct"]), "s3_yield": _pct(f["hsm_yield_pct"]),
                "blend": {"imported": _pct(f["blend_pct"]["imported_scrap"]),
                          "local": _pct(f["blend_pct"]["local_scrap"]),
                          "dri": _pct(f["blend_pct"]["dri"])},
                "price": {"imported": f["imported_scrap_usd_t"], "local": f["local_scrap_usd_t"],
                          "dri": dp},
                # legacy: both flat sheets read EZDK's billet electricity price ('Billet'!E11)
                "electricity_usd_kwh": (f["electricity_usd_kwh"] if rules["own_line_inputs"]
                                        else bil["EZDK"]["electricity_usd_kwh"]),
                "eaf_lf_kwh": f["eaf_lf_electricity_kwh_t_ms"]}

    def integrated(sheet, link):
        return _volume_safe(lambda t: compute_integrated_detail(D[sheet], {**link, "finished_t": t}),
                            link["finished_t"])

    b = bil["ESR"]
    esr_link = {"finished_t": sold_t("ESR", "Rebar", cv), "s3_yield": _pct(fy["Rebar"]["ESR"]),
                "eaf_yield": _pct(b["eaf_yield_pct"]), "bccm_yield": _pct(b["ccp_yield_pct"]),
                "blend": {"imported": _pct(b["blend_pct"]["imported_scrap"]),
                          "local": _pct(b["blend_pct"]["local_scrap"]),
                          "dri": _pct(b["blend_pct"]["dri"])},
                "price": {"imported": b["imported_scrap_usd_t"], "local": b["local_scrap_usd_t"],
                          "dri": dri_price["ESR"]},
                "electricity_usd_kwh": b["electricity_usd_kwh"],
                "eaf_lf_kwh": b["eaf_lf_electricity_kwh_t_ms"], "extra_feed_t": 0.0}

    def esr_stage1(link):
        return _volume_safe(lambda t: compute_esr_stage1(D["ESR Rebar"], {**link, "finished_t": t}, fx),
                            link["finished_t"])

    long_extra = {"EZDK": wire_billets, "EFS": 0.0}
    det = {
        "EZDK Rebar": integrated("EZDK Rebar", long_link("EZDK", sold_t("EZDK", "Rebar", cv), wire_billets)),
        "EFS Rebar": integrated("EFS Rebar", long_link("EFS", sold_t("EFS", "Rebar", cv), 0.0)),
        "EZDK Flat": integrated("EZDK Flat", flat_link("EZDK")),
        "EFS Flat": integrated("EFS Flat", flat_link("EFS")),
    }
    esr1 = esr_stage1(esr_link)

    billet = compute_billet_summary(state, dri_vc, rules, {
        "EZDK": det["EZDK Rebar"], "EFS": det["EFS Rebar"], "ESR": esr1})

    # ERM's billet source.  Per-ton costs do not depend on volume, so the supplier's
    # sheet is re-run with the extra billets only to update its tonnages.
    erm_price, erm_supplier = resolve_billet_source(state["sourcing"]["ERM_rebar_billet"], billet)

    def rolling(sheet, finished_t, yield_pct, billet_price):
        return _volume_safe(lambda t: compute_rolling_detail(
            D[sheet], {"finished_t": t, "yield": _pct(yield_pct), "billet_price_usd_t": billet_price},
            fx), finished_t)

    det["ERM Rolling"] = rolling("ERM Rolling", sold_t("ERM", "Rebar", cv), fy["Rebar"]["ERM"], erm_price)
    erm_billets_t = det["ERM Rolling"]["t.produced"]
    if rules["billet_interco"] and erm_supplier and erm_billets_t:
        if erm_supplier == "ESR":
            esr_link["extra_feed_t"] = erm_billets_t
            esr1 = esr_stage1(esr_link)
        else:
            sheet = f"{erm_supplier} Rebar"
            det[sheet] = integrated(sheet, long_link(erm_supplier, det[sheet]["finished_t"],
                                                     long_extra[erm_supplier] + erm_billets_t))
    det["ESR Rebar"] = _volume_safe(
        lambda t: compute_esr_stage3(D["ESR Rebar"], {**esr_link, "finished_t": t}, fx,
                                     esr_stage1({**esr_link, "finished_t": t}),
                                     billet["ESR"]["total_variable_cost"]), esr_link["finished_t"])
    det["EZDK Wire"] = rolling("EZDK Wire", wire_t, fy["Wire Rod"]["EZDK"],
                               billet["EZDK"]["total_variable_cost"])

    # Stage 3 summaries
    market = billet["market_price"]
    rebar = {"_currency": "USD"}
    full = rules["summary_from_detail"]
    s3_other = ("refractories", "electricity", "natural_gas", "water", "work_roll")
    rebar_inputs = {
        "EZDK": (billet["EZDK"]["total_variable_cost"], det["EZDK Rebar"]["s3.cost.byproduct"],
                 sum(det["EZDK Rebar"][f"s3.cost.{k}"] for k in s3_other)),
        "EFS": (billet["EFS"]["total_variable_cost"], det["EFS Rebar"]["s3.cost.byproduct"],
                sum(det["EFS Rebar"][f"s3.cost.{k}"] for k in (s3_other if full else s3_other[:4]))),
        "ERM": (erm_price, det["ERM Rolling"]["summary.home_scrap_usd_t"],
                det["ERM Rolling"]["summary.other_conversion_usd_t"]),
        "ESR": (billet["ESR"]["total_variable_cost"], det["ESR Rebar"]["s3.cost.byproduct"],
                det["ESR Rebar"]["summary.rolling_other_conversion"]),
    }
    for co, (mat, home, other) in rebar_inputs.items():
        rebar[co] = _finished_summary(mat, market, fy["Rebar"][co], home, other)
    wire = {"_currency": "USD", "EZDK": _finished_summary(
        billet["EZDK"]["total_variable_cost"], market, fy["Wire Rod"]["EZDK"],
        det["EZDK Wire"]["summary.home_scrap_usd_t"], det["EZDK Wire"]["summary.other_conversion_usd_t"])}
    flat = compute_flat_summary(state, dri_vc, rules, {"EZDK": det["EZDK Flat"], "EFS": det["EFS Flat"]})

    # Stage 1 — volume-dependent DRI ('DRI Cost'!E16 / G16)
    erm_dri_t = det["EFS Rebar"]["s1.t.dri"] + det["ESR Rebar"]["s1.t.dri"]
    if rules["erm_dri_full_volume"]:
        erm_dri_t += det["EFS Flat"]["s1.t.dri"]
    dri_volume = {"EZDK": det["EZDK Rebar"]["s1.t.dri"] + det["EZDK Flat"]["s1.t.dri"], "ERM": erm_dri_t}
    dri = {co: compute_dri_full(state, co, dri_var[co], dri_volume[co]) for co in dri_var}

    fixed = compute_fixed_allocation(state)

    # Intercompany sales booked in the corrected P&L (USD, monthly, per Ktons)
    interco = {}
    if rules["erm_dri_pnl"]:
        buyers = {"EFS": det["EFS Rebar"]["s1.t.dri"] * det["EFS Rebar"]["s1.price.dri"]
                  + det["EFS Flat"]["s1.t.dri"] * det["EFS Flat"]["s1.price.dri"],
                  "ESR": det["ESR Rebar"]["s1.t.dri"] * det["ESR Rebar"]["s1.price.dri"]}
        qty_t = det["EFS Rebar"]["s1.t.dri"] + det["EFS Flat"]["s1.t.dri"] + det["ESR Rebar"]["s1.t.dri"]
        interco["ERM/DRI"] = {"seller": "ERM", "product": "DRI", "buyers": ["EFS", "ESR"],
                              "qty_kt": qty_t / 1000, "revenue_usd_m": sum(buyers.values()) / 1e6,
                              "cogs_usd_m": qty_t * dri_vc["ERM"] / 1e6,
                              "fixed_usd_m": fixed["allocation_usd_m"]["DRI"]["ERM"]}
    if rules["billet_interco"] and erm_supplier and erm_billets_t:
        sup_vc = billet[erm_supplier]["total_variable_cost"]
        interco[f"{erm_supplier}/Billet"] = {
            "seller": erm_supplier, "product": "Billet", "buyers": ["ERM"],
            "qty_kt": erm_billets_t / 1000, "revenue_usd_m": erm_billets_t * erm_price / 1e6,
            "cogs_usd_m": erm_billets_t * sup_vc / 1e6,
            "fixed_usd_m": {line: 0.0 for line, _ in _FIXED_LINES}}

    pnl = {v: compute_pnl(state, det, fixed, v, rules, interco) for v in PNL_VARIANTS}
    outputs = {
        "dri": dri, "billet": billet, "detail": det, "rebar": rebar, "wire": wire, "flat": flat,
        "market_share": compute_market_share(state, rules),
        "production": compute_production(state, det, rules, erm_supplier),
        "fixed_cost": fixed,
        "pnl": pnl,
        "consolidated": {v: compute_consolidated(p, rules) for v, p in pnl.items()},
        "sourcing": {"_currency": "USD", "ERM_rebar_billet": state["sourcing"]["ERM_rebar_billet"],
                     "price_usd_t": erm_price, "supplier": erm_supplier or "market",
                     "billets_t": erm_billets_t},
        "rules": dict(rules),
    }
    outputs["dri"]["_currency"] = "LE"
    outputs["detail"]["_currency"] = "none"
    outputs["capacity"] = compute_capacity(state, outputs)
    checks = run_integrity_checks(state, {k: v for k, v in outputs.items() if k != "rules"}, rules)
    outputs["integrity"] = [{"check": n, "passed": ok, "detail": d,
                             "severity": CHECK_SEVERITY.get(n, "error")} for n, ok, d in checks]
    if strict:
        failed = failed_errors(outputs)
        if failed:
            raise IntegrityError(failed[0]["detail"])
    return outputs


def failed_errors(outputs: dict) -> list:
    """Failed checks of severity "error" — the ones that block commits and strict runs."""
    return [c for c in outputs["integrity"] if not c["passed"] and c["severity"] == "error"]


def key_figures(outputs: dict) -> dict:
    """A flat digest of the figures people decide on — used for the impact of an
    amendment and for comparing states.  Keys name the figure and its unit."""
    k: dict = {}
    cons = outputs["consolidated"]["usd_monthly"]["consolidated"]
    for line, label in (("total_value", "revenue"), ("contribution_margin", "CM"), ("ebtd", "EBTD"),
                        ("ebt", "EBT")):
        k[f"Group {label} M$"] = cons[line]
    cols = outputs["pnl"]["usd_monthly"]["columns"]
    for key, c in cols.items():
        if key == "Total":
            continue
        if key.endswith("/Sub-Total"):
            co = key.split("/")[0]
            k[f"{co} revenue M$"] = c["total_value"]
            k[f"{co} CM M$"] = c["contribution_margin"]
            k[f"{co} EBT M$"] = c["ebt"]
        else:
            k[f"{key} qty kt"] = c["total_qty"]
            k[f"{key} VC $/t"] = c["cost_per_t"]
            k[f"{key} CM $/t"] = c["cm_per_t"]
            k[f"{key} EBT M$"] = c["ebt"]
    for co in ("EZDK", "ERM"):
        k[f"DRI {co} VC $/t"] = outputs["dri"][co]["summary_usd_t"]["total_variable_cost"]
    for co in BILLET_PRODUCERS:
        k[f"Billet {co} VC $/t"] = outputs["billet"][co]["total_variable_cost"]
    for co in HRC_PRODUCERS:
        k[f"HRC {co} VC $/t"] = outputs["flat"][co]["total_variable_cost"]
    k["ERM billet price $/t"] = outputs["sourcing"]["price_usd_t"]
    for name, v in outputs.get("capacity", {}).get("items", {}).items():
        k[f"Capacity {name} %"] = v["utilisation_pct"]
    return k
