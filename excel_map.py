"""
Where every engine output lives in the workbook.

``excel_cells(outputs)`` yields ``("Sheet!Cell", value)`` for every output that has
a home cell.  Tests compare these against Excel's cached values (and against
LibreOffice recalculations of perturbed workbooks).

Regions intentionally *not* mapped (scratch / side calculations / blocks that read
an external workbook) are listed in ``UNMAPPED_REGIONS`` so the coverage report can
tell them apart from genuine gaps.
"""

from __future__ import annotations

COLS4 = {"EZDK": "E", "EFS": "F", "ERM": "G", "ESR": "H"}

# --- detail templates ------------------------------------------------------ #

INTEGRATED = {
    "finished_t": ["E10", "E156"], "s1.molten_steel_t": "E19", "s1.yield": "E20",
    "s1.solid_charge_t": "E21", "s1.blend.imported": "D24", "s1.blend.local": "D25",
    "s1.blend.dri": "D26", "s1.t.imported": "E24", "s1.t.local": "E25", "s1.t.dri": "E26",
    "s1.t.home": "E27", "s1.t.pig": "E28", "s1.byproduct_t": "E30",
    "s1.electricity_eaf_lf_kwh": "E37", "s1.price.imported": "E49", "s1.price.local": "E50",
    "s1.price.dri": "E51", "s1.electricity_usd_kwh": "E62",
    "s1.cost.material.imported": "E73", "s1.cost.material.local": "E74",
    "s1.cost.material.dri": "E75", "s1.cost.material.home": "E76", "s1.cost.material.pig": "E77",
    "s1.cost.byproduct": "E79", "s1.cost.aux_materials": "E81", "s1.cost.refractories": "E82",
    "s1.cost.electrodes": "E83", "s1.cost.other_fillers": "E84",
    "s1.cost.electricity_eaf_lf": "E86", "s1.cost.electricity_aux": "E87",
    "s1.cost.natural_gas": "E88", "s1.cost.water": "E89", "s1.cost.oxygen": "E90",
    "s1.cost.nitrogen": "E91", "s1.cost.argon": "E92", "s1.cost.handling": "E94",
    "s1.cost.cutting": "E95", "s1.cost.yield.imported": "E96", "s1.cost.yield.local": "E97",
    "s1.cost.yield.dri": "E98", "s1.conversion": "E99", "s1.ms_variable_cost": "E100",
    "s2.output_t": "E104", "s2.yield": "E105", "s2.molten_steel_t": "E106",
    "s2.byproduct_t": "E109", "s2.molten_steel_price": "E122",
    "s2.electricity_usd_kwh": ["E129", "E182"], "s2.cost.molten_steel": "E137",
    "s2.cost.byproduct": "E139", "s2.cost.aux_materials": "E141",
    "s2.cost.refractories": "E142", "s2.cost.electricity": "E144",
    "s2.cost.natural_gas": "E145", "s2.cost.water": "E146", "s2.cost.oxygen": "E147",
    "s2.cost.nitrogen": "E148", "s2.cost.argon": "E149", "s2.cost.yield": "E150",
    "s2.conversion": "E151", "s2.variable_cost": "E152",
    "s3.yield": "E157", "s3.feed.produced_t": "E158", "s3.feed.local_t": "E159",
    "s3.feed.imported_t": "E160", "s3.byproduct_t": "E163", "s3.feed_price": "E174",
    "s3.natural_gas_usd_nm3": "E183", "s3.water_usd_m3": "E184",
    "s3.cost.produced_feed": "E189", "s3.cost.local_feed": "E190",
    "s3.cost.imported_feed": "E191", "s3.cost.byproduct": "E193",
    "s3.cost.refractories": "E195", "s3.cost.electricity": "E197",
    "s3.cost.natural_gas": "E198", "s3.cost.water": "E199", "s3.cost.work_roll": "E201",
    "s3.cost.yield.produced": "E202", "s3.cost.yield.imported": "E203",
    "s3.conversion": "E204", "s3.variable_cost": "E205", "s3.variable_exp": "E206",
}
INTEGRATED_LONG = {
    "summary.yield.imported": "I238", "summary.yield.local": "I239", "summary.yield.dri": "I240",
    "summary.yield_effect": "J240", "summary.byproduct": "J244",
    "summary.conversion_ex_byproduct": "J269", "summary.other_conversion": "J270",
    "summary.total_value": "E269", "summary.vc_per_t": "E270",
}
INTEGRATED_FLAT = {
    "summary.yield.imported": "H231", "summary.yield.local": "H232", "summary.yield.dri": "H233",
    "summary.yield_effect": "J233", "summary.byproduct": "J237",
    "summary.conversion_ex_byproduct": "J268", "summary.other_conversion": "J269",
    "summary.total_value": "E268", "summary.vc_per_t": "E269",
}
ESR = {
    "finished_t": ["E10", "E104"], "s1.billets_t": ["E19", "E106"], "s1.eaf_yield": "E20",
    "s1.bccm_yield": "E21", "s1.yield": "E22", "s1.solid_charge_t": "E23",
    "s1.blend.imported": "D26", "s1.blend.local": "D27", "s1.blend.dri": "D28",
    "s1.t.imported": "E26", "s1.t.local": "E27", "s1.t.dri": "E28", "s1.t.home": "E29",
    "s1.t.pig": "E30", "s1.byproduct_t": "E32", "s1.electricity_kwh": "E39",
    "s1.price.imported": "E50", "s1.price.local": "E51", "s1.price.dri": "E52",
    "s1.p.byproduct_t": "E56", "s1.p.aux_materials_kg": "E58", "s1.p.refractories_kg": "E59",
    "s1.p.electrodes_kg": "E60", "s1.p.consumables_kg": "E61", "s1.electricity_usd_kwh": "E63",
    "s1.p.natural_gas_nm3": "E64", "s1.p.water_m3": "E65", "s1.p.oxygen_nm3": "E66",
    "s1.p.nitrogen_nm3": "E67", "s1.p.chemicals_unit": "E68",
    "s1.cost.material.imported": "E74", "s1.cost.material.local": "E75",
    "s1.cost.material.dri": "E76", "s1.cost.material.home": "E77", "s1.cost.material.pig": "E78",
    "s1.cost.byproduct": "E80", "s1.cost.aux_materials": "E82", "s1.cost.refractories": "E83",
    "s1.cost.electrodes": "E84", "s1.cost.consumables": "E85", "s1.cost.electricity": "E87",
    "s1.cost.natural_gas": "E88", "s1.cost.water": "E89", "s1.cost.oxygen": "E90",
    "s1.cost.nitrogen": "E91", "s1.cost.chemicals": "E92", "s1.cost.handling": "E94",
    "s1.cost.cutting": "E95", "s1.cost.yield.imported": "E96", "s1.cost.yield.local": "E97",
    "s1.cost.yield.dri": "E98", "s1.conversion": "E99", "s1.billet_variable_cost": "E100",
    "s3.yield": "E105", "s3.feed.local_t": "E107", "s3.feed.imported_t": "E108",
    "s3.byproduct_t": "E111", "s3.feed_price": "E125", "s3.electricity_usd_kwh": "E134",
    "s3.natural_gas_usd_nm3": "E135", "s3.water_usd_m3": "E136", "s3.labels_rings_usd": "E138",
    "s3.tying_usd_t": "E140", "s3.cost.produced_feed": "E143", "s3.cost.imported_feed": "E144",
    "s3.cost.byproduct": "E146", "s3.cost.crops": "E147", "s3.cost.refractories": "E149",
    "s3.cost.electricity": "E151", "s3.cost.natural_gas": "E152", "s3.cost.water": "E153",
    "s3.cost.labels_rings": "E155", "s3.cost.chemicals": "E156", "s3.cost.tying": "E157",
    "s3.cost.yield.produced": "E158", "s3.cost.yield.imported": "E159",
    "s3.conversion": "E160", "s3.variable_cost": "E161", "s3.variable_exp": "E162",
}
ROLLING = {
    "yield": "E19", "finished_t": "E20", "billets_t": "E21", "t.imported": "E24",
    "t.produced": "E25", "t.local": "E26", "byproduct_t": "E27", "ng_mmbtu_t": "E30",
    "price.imported_landed": "E41", "price.produced_billet": "E42", "price.byproduct": "E44",
    "price.electricity": "E45", "price.natural_gas_usd_mmbtu": "E46",
    "cost.imported": "E61", "cost.produced": "E62", "cost.local": "E63", "cost.byproduct": "E64",
    "raw_material_cost": "E66", "cost.electricity": "E68", "cost.natural_gas": "E69",
    "cost.recycled_water": "E70", "cost.tying": "E71", "cost.chemicals": "E72",
    "cost.labels_rings": "E73", "cost.spare_parts": "E74", "cost.external_services": "E75",
    "other_variable_cost": "E77", "conversion.imported": "E79", "conversion.produced": "E80",
    "conversion.local": "E81", "conversion.others": "E82", "conversion_exp": "E83",
    "variable_cost_le_t": "E86", "variable_exp_le": "E87",
}

DRI_COST = {
    "fx": "6", "mrmr": "15", "production_t": "16", "required_iop_t": "17",
    "consumption_ng_nm3": "21", "ng_mmbtu_t": "22", "iop_landed_usd_t": "33",
    "iop_landed_le_t": "34", "ng_price_le_nm3": "36", "ng_price_usd_mmbtu": "37",
    "fixed_le.other": "49",
    "cost_le_t.iop": "52", "cost_le_t.electricity": "53", "cost_le_t.natural_gas": "54",
    "cost_le_t.oxygen": "55", "cost_le_t.nitrogen": "56", "cost_le_t.water": "57",
    "cost_le_t.chemicals": "58", "cost_le_t.spare_parts": "59",
    "cost_le_t.external_services": "60", "cost_le_t.other": "61",
    "other_conversion_usd_t": "62", "conversion_rm_le_t": "63", "conversion_others_le_t": "64",
    "conversion_exp_le": "65", "variable_cost_le_t": "68", "variable_exp_le": "69",
    "fixed_le.labor": "71", "fixed_le.depreciation": "72", "fixed_le.other#": "73",
    "fixed_le_t.labor": "74", "fixed_le_t.depreciation": "75", "fixed_le_t.other": "76",
    "fixed_cost_le_t": "78", "fixed_exp_le": "79", "manufacturing_cost_le_t": ["81", "85"],
    "cogs_le": "82", "gross_margin_le_t": "87",
}

PNL_ROWS = {
    "local_qty": 7, "export_qty": 8, "total_qty": 9, "local_value": 11, "local_price": 12,
    "export_value": 13, "export_price": 14, "total_value": 15, "avg_price": 16,
    "variable_cogs": 18, "cost_per_t": 19, "export_expenses": 21, "contribution_margin": 23,
    "cm_per_t": 24, "cm_pct": 25, "intercompany_gain_dri": 28, "manufacturing_fixed": 31,
    "sga": 32, "net_finance": 33, "total_fixed": 34, "ebtd": 36, "ebtd_per_t": 37,
    "ebtd_pct": 38, "depreciation": 40, "fc_per_t": 41, "depreciation_per_t": 42, "ebt": 43,
    "ebt_per_t": 44, "ebt_pct": 45, "vc_plus_fc_per_t": 47, "break_even_qty": 48,
}

UNMAPPED_REGIONS = {
    "EZDK Rebar": "fixed/COGS/selling block rows 206–235 (superseded by Fixed Cost & P&L; "
                  "partly reads an external workbook); scratch columns G–K",
    "EFS Rebar": "same as EZDK Rebar",
    "EZDK Flat": "fixed/COGS block rows 208–226 (hardcoded, superseded by Fixed Cost & P&L)",
    "EFS Flat": "same as EZDK Flat",
    "ESR Rebar": "fixed block rows 164–180 and duplicate block rows 183–251; scratch F/G/H",
    "ERM Rolling": "fixed block rows 89–105 (LE, superseded by Fixed Cost & P&L); scratch F–J",
    "EZDK Wire": "same as ERM Rolling",
    "DRI Cost": "row 84/86 (external workbook link); scratch columns H–K",
    "Billet": "scratch K33/K34",
    "Market Share": "G14/G15 are #DIV/0! in Excel",
    "P&L LE Monthly": "scratch P49/P50",
    "P&L LE Annual": "scratch S15/S33",
    "(all)": "date stamps and page counters ('n / 12')",
}


def _emit(sheet, mapping, values):
    for key, cells in mapping.items():
        key = key.rstrip("#")
        if key not in values:
            continue
        for cell in (cells if isinstance(cells, list) else [cells]):
            yield f"{sheet}!{cell}", values[key]


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            out.update(_flatten(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def excel_cells(outputs: dict, state: dict):
    fx = state["fx_egp_per_usd"]
    det = outputs["detail"]
    for sheet in ("EZDK Rebar", "EFS Rebar"):
        yield from _emit(sheet, {**INTEGRATED, **INTEGRATED_LONG}, det[sheet])
    for sheet in ("EZDK Flat", "EFS Flat"):
        yield from _emit(sheet, {**INTEGRATED, **INTEGRATED_FLAT}, det[sheet])
    yield from _emit("ESR Rebar", ESR, det["ESR Rebar"])
    for sheet in ("ERM Rolling", "EZDK Wire"):
        yield from _emit(sheet, ROLLING, det[sheet])
    for sheet in ("EZDK Rebar", "EFS Rebar", "EZDK Flat", "EFS Flat", "ESR Rebar"):
        yield f"{sheet}!E5", fx
    for sheet in ("ERM Rolling", "EZDK Wire"):
        yield f"{sheet}!E6", fx

    # DRI Cost & DRI
    for co, col, dcol in (("EZDK", "E", "E"), ("ERM", "G", "F")):
        d = outputs["dri"][co]
        flat = _flatten(d)
        flat.update({"fx": fx, "consumption_ng_nm3": d["ng_mmbtu_t"] * 28,
                     "iop_landed_usd_t": d["summary_usd_t"]["material_price"],
                     "ng_price_usd_mmbtu": d["ng_price_le_nm3"] * 28 / fx,
                     "fixed_le.other": d["fixed_le"]["other"]})
        for key, rows in DRI_COST.items():
            key = key.rstrip("#")
            if key in flat:
                for r in (rows if isinstance(rows, list) else [rows]):
                    yield f"DRI Cost!{col}{r}", flat[key]
        sm = d["summary_usd_t"]
        yield f"DRI!{dcol}16", sm["material_price"]
        yield f"DRI!{dcol}18", sm["mrmr_effect"]
        yield f"DRI!{dcol}19", sm["other_conversion"]
        yield f"DRI!{dcol}20", sm["total_conversion"]
        yield f"DRI!{dcol}22", sm["total_variable_cost"]
    yield "DRI!E6", fx

    # Billet
    b = outputs["billet"]
    yield "Billet!D7", fx
    for co, col in (("EZDK", "E"), ("EFS", "F"), ("ESR", "G")):
        x = b[co]
        for row, key in ((8, "dri_price"), (9, "local_scrap_price"), (10, "imported_scrap_price"),
                         (19, "billet_yield_pct"), (24, "material_price"), (26, "yield_effect"),
                         (27, "other_conversion"), (28, "total_conversion"),
                         (30, "total_variable_cost")):
            yield f"Billet!{col}{row}", x[key]
    for src, row in (("EZDK", 39), ("EFS", 40), ("ESR", 41), ("Market", 42)):
        for buyer, col in COLS4.items():
            yield f"Billet!{col}{row}", b["tradeoff"]["rows"][src][buyer]
    for buyer, col in COLS4.items():
        yield f"Billet!{col}44", b["tradeoff"]["minimum"][buyer]
    yield "Billet!E52", b["market_price"]

    # Rebar / Wire / Flat summaries
    rows_sc = {"sc1": {12: "material_price", 14: "yield_effect", 15: "home_scrap_deduction",
                       16: "other_conversion", 17: "total_conversion", 19: "total_variable_cost"},
               "sc2": {25: "material_price", 27: "yield_effect", 28: "home_scrap_deduction",
                       29: "other_conversion", 30: "total_conversion", 32: "total_variable_cost"}}
    for sheet, data, cols in (("Rebar", outputs["rebar"], COLS4), ("Wire", outputs["wire"], {"EZDK": "E"})):
        for co, col in cols.items():
            for sc, rows in rows_sc.items():
                for r, key in rows.items():
                    yield f"{sheet}!{col}{r}", data[co][sc][key]
            yield f"{sheet}!{col}34", data[co]["difference"]
    yield "Flat!D7", fx
    for co, col in (("EZDK", "E"), ("EFS", "F")):
        x = outputs["flat"][co]
        for r, key in ((8, "dri_price"), (24, "material_price"), (26, "yield_effect"),
                       (27, "other_conversion"), (28, "total_conversion"), (30, "total_variable_cost")):
            yield f"Flat!{col}{r}", x[key]

    # Market Share
    ms = outputs["market_share"]
    yield "Market Share!D27", fx
    for prod, col in (("Rebar", "E"), ("Wire Rod", "F"), ("HRC", "G")):
        yield f"Market Share!{col}11", ms["group_local_kt"][prod]
        if prod != "HRC":
            yield f"Market Share!{col}12", ms["ezz_share_pct"][prod]
            yield f"Market Share!{col}13", ms["others_share_pct"][prod]
    for co, r in (("EZDK", 14), ("EFS", 15), ("ERM", 16), ("ESR", 17)):
        yield f"Market Share!E{r}", ms["company_pct_of_group"]["Rebar"][co]
    yield "Market Share!F14", ms["company_pct_of_group"]["Wire Rod"]["EZDK"]

    # Production Requirments
    pr = outputs["production"]
    S = "Production Requirments"
    long_rows = {"rebar": 7, "wire_rod": 8, "billet": 10, "molten_steel": 11, "solid_charge": 12,
                 "dri_pct": 13, "dri": 14, "imported_scrap_pct": 15, "imported_scrap": 16,
                 "local_scrap_pct": 17, "local_scrap": 18, "mrmr": 20, "iop": 21}
    flat_rows = {"hrc": 24, "molten_steel": 26, "solid_charge": 27, "dri_pct": 28, "dri": 29,
                 "imported_scrap_pct": 30, "imported_scrap": 31, "local_scrap_pct": 32,
                 "local_scrap": 33, "mrmr": 35, "iop": 36}
    sum_rows = {"rebar": 39, "wire_rod": 40, "hrc": 41, "billet": 42, "dri": 43, "iop": 44, "scrap": 45}
    for section, total, rows in (("long", "long_total", long_rows), ("flat", "flat_total", flat_rows),
                                 ("summary", "summary_total", sum_rows)):
        for co, col in COLS4.items():
            for key, r in rows.items():
                if key in pr[section].get(co, {}):
                    yield f"{S}!{col}{r}", pr[section][co][key]
        for key, r in rows.items():
            if key in pr[total]:
                yield f"{S}!I{r}", pr[total][key]

    # Fixed Cost
    fc = outputs["fixed_cost"]
    cols5 = {"EZDK": "D", "EFS": "E", "ERM": "F", "ESR": "G", "Total": "H"}
    for co, col in cols5.items():
        for r, key in ((6, "total_wo_dep"), (7, "manufacturing"), (8, "sga"), (9, "net_finance"),
                       (11, "depreciation"), (13, "total_with_dep")):
            yield f"Fixed Cost!{col}{r}", fc["usd_m"][co][key]
        for r, key in ((19, "total_wo_dep"), (20, "manufacturing"), (21, "sga"),
                       (22, "net_finance"), (24, "depreciation")):
            yield f"Fixed Cost!{col}{r}", fc["le_m"][co][key]
        if co != "Total":
            yield f"Fixed Cost!{col}34", fc["distribution_total_pct"][co]
    for prod, r0 in (("DRI", 38), ("Rebar", 46), ("Wire Rod", 54), ("HRC", 62)):
        a = fc["allocation_usd_m"][prod]
        for co, col in cols5.items():
            for i, line in enumerate(("manufacturing", "sga", "net_finance", "depreciation")):
                yield f"Fixed Cost!{col}{r0 + i}", a[co][line]
        yield f"Fixed Cost!H{r0 + 4}", a["Total"]["total"]

    # P&L
    from cost_engine import PNL_VARIANTS
    for variant, (sheet, in_le, _) in PNL_VARIANTS.items():
        cols = outputs["pnl"][variant]["columns"]
        if in_le:
            yield f"{sheet}!C4", fx
        for col, c in cols.items():
            for key, r in PNL_ROWS.items():
                if key in c and c[key] is not None:
                    yield f"{sheet}!{col}{r}", c[key]
