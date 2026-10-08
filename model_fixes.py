"""
From the legacy workbook to the corrected model, one fix at a time.

Each fix pairs (a) a data correction, applied to the state, with (b) a rule switched on in
the engine.  ``to_corrected(legacy_state)`` applies them all and returns a clean
corrected-model state, with no typed-in results and no legacy-only fields.
``bridge(legacy_state)`` applies them one after another and measures what each one
moves, which is the "why did the number change" answer.

    python model_fixes.py [workbook.xlsx]

regenerates ``model_initial_state.json`` (the corrected baseline) and
``reports/fix_bridge.md`` from the workbook (default: the reference fixture).
"""

from __future__ import annotations

import copy
import json
import os
import sys

import cost_engine as ce

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE_WORKBOOK = os.path.join(HERE, "tests", "fixtures", "New_Corp_Model_v8_30-12-19.xlsx")


# --------------------------------------------------------------------------- #
# The fixes — each returns a list of human-readable notes on what it changed
# --------------------------------------------------------------------------- #

def fix_export_expenses(state, rules):
    """A1: the typed figures are monthly M$ totals ($20/t × export volume in the
    reference); store them as $/t so they scale with volume."""
    notes, per_t = [], {}
    legacy = state["pnl"].pop("export_expense_rate", {})
    for co, prods in state["sales"].items():
        per_t[co] = {}
        for prod, x in prods.items():
            musd = legacy.get(co, {}).get(prod, 0.0)
            if musd and x["export_kt"]:
                per_t[co][prod] = musd * 1000 / x["export_kt"]
                notes.append(f"{co} {prod}: {musd} M$/month on {x['export_kt']:g} kt "
                             f"→ {per_t[co][prod]:.2f} $/t")
            else:
                per_t[co][prod] = 0.0
                if musd:
                    notes.append(f"{co} {prod}: {musd} M$ typed with no export volume → dropped")
    state["pnl"]["export_expense_usd_t"] = per_t
    rules["export_expense_per_ton"] = True
    return notes


def fix_consistent_volumes(state, rules):
    """A2/A3/B6: rebar exports are produced and earn revenue; annual views are 12×."""
    rules["consistent_volumes"] = True
    ex = [f"{co} {p}" for co, ps in state["sales"].items() for p, x in ps.items()
          if x["export_kt"] and p == "Rebar"]
    return [f"rebar exports now produced and priced: {', '.join(ex) or 'none in this data'}"]


def fix_erm_dri_volume(state, rules):
    """A4: ERM's DRI volume includes the DRI it supplies to EFS's flat line."""
    rules["erm_dri_full_volume"] = True
    return ["ERM DRI volume = EFS long + EFS flat + ESR DRI"]


def fix_market_share(state, rules):
    """A5: HRC group sales = EZDK + EFS HRC local sales."""
    rules["market_share_hrc"] = True
    return ["HRC group sales computed; HRC share needs the total market size"
            if state["total_local_market_kt"].get("HRC") is None else "HRC share computed"]


def fix_esr_electricity(state, rules):
    """A6: ESR's 0.007 $/kWh is a misplaced decimal (every other line pays ~0.07)."""
    b = state["billet"]["companies"]
    esr, ref = b["ESR"]["electricity_usd_kwh"], b["EZDK"]["electricity_usd_kwh"]
    if ref and esr and esr < ref / 5:
        b["ESR"]["electricity_usd_kwh"] = esr * 10
        return [f"ESR electricity {esr} → {esr * 10:g} $/kWh"]
    return [f"ESR electricity {esr} $/kWh looks plausible — unchanged"]


def fix_blends(state, rules):
    """A7: blends must sum to 100%; imported scrap (the balancing material) takes the gap."""
    notes = []
    lines = [(f"{co} long", state["billet"]["companies"][co]["blend_pct"], f"{co} Rebar")
             for co in ce.BILLET_PRODUCERS]
    lines += [(f"{co} flat", state["flat"][co]["blend_pct"], f"{co} Flat") for co in ce.HRC_PRODUCERS]
    for name, bl, sheet in lines:
        extra = state["detail"][sheet]["stage1"]["blend_pct"]
        other = 100 * (extra["home_scrap"] + extra["pig_iron"])
        total = sum(bl.values()) + other
        if abs(total - 100) > 1e-9:
            old = bl["imported_scrap"]
            bl["imported_scrap"] = 100 - bl["dri"] - bl["local_scrap"] - other
            notes.append(f"{name}: imported scrap {old:g}% → {bl['imported_scrap']:g}% (blend was {total:g}%)")
    return notes or ["all blends already sum to 100%"]


def fix_dri_selling_price(state, rules):
    """B3: the DRI selling price is the model's own input, not a frozen external link."""
    notes = []
    for co, d in state["dri"].items():
        src = d.pop("selling_price_source", None)
        inp = d.pop("selling_price_input_le_t", None)
        if inp is not None:
            if inp != d["selling_price_le_t"]:
                notes.append(f"{co}: {d['selling_price_le_t']:g} (external link) → {inp:g} LE/t (input)")
            d["selling_price_le_t"] = inp
        elif src:
            notes.append(f"{co}: keeping {d['selling_price_le_t']:g} LE/t from {src}")
    return notes or ["selling prices were already inputs (same values)"]


def fix_own_line_inputs(state, rules):
    """B5: every line carries its own inputs — no silent links to another company."""
    notes = []
    b = state["billet"]["companies"]
    for co, x in b.items():
        for k in ("local_scrap_usd_t", "imported_scrap_usd_t"):
            if isinstance(x[k], dict):
                src = x[k]["same_as"]
                x[k] = b[src][k]
                notes.append(f"{co} {k} was linked to {src}; now its own input ({x[k]:g})")
    for co, f in state["flat"].items():
        m = f.pop("dri_margin_from_erm_usd_t", None)
        if m and co in b and abs(m - b[co]["dri_margin_from_erm_usd_t"]) > 1e-12:
            notes.append(f"{co} flat DRI margin {m} differed from long {b[co]['dri_margin_from_erm_usd_t']}; "
                         "one margin per buyer now")
    notes.append("flat lines now use their own electricity price ('Flat' sheet)")
    # ERM's rolling scrap was credited at the billet purchase price, so a change in an
    # intercompany price moved group profit.  Freeze today's value as ERM's own input.
    for sheet in ("ERM Rolling", "EZDK Wire"):
        p = state["detail"][sheet]["prices_le"]
        if p["byproduct_t"] == "billet_price":
            le = ce.compute_all(state, rules)["detail"][sheet]["price.byproduct"]
            p["byproduct_t"] = le
            notes.append(f"{sheet} scrap credit was linked to the billet price; now its own input "
                         f"({le:,.0f} LE/t) — review: EZDK Wire values rolling scrap at "
                         f"{state['detail']['EZDK Wire']['prices_le']['byproduct_t']:,.0f} LE/t")
    rules["own_line_inputs"] = True
    return notes


def fix_summaries(state, rules):
    """C: summary cost sheets are derived from the detailed build-up (they now agree)."""
    rules["summary_from_detail"] = True
    return ["billet / HRC / rebar summaries now equal the detail sheets"]


def fix_billet_sourcing(state, rules):
    """B1: no typed matrix cells; ERM buys from the cheapest source in the trade-off
    matrix, and an internal purchase raises the supplier's production."""
    notes = []
    for src, row in state["billet"].pop("tradeoff_overrides", {}).items():
        for buyer, v in row.items():
            notes.append(f"removed typed matrix cell {src}→{buyer} = {v}")
    state["billet"]["tradeoff_overrides"] = {}
    state["billet"].pop("landed_cost_factor", None)
    old = state["sourcing"]["ERM_rebar_billet"]
    state["sourcing"]["ERM_rebar_billet"] = "min"
    notes.append(f"ERM billet source {old} → min (cheapest offer in the trade-off matrix)")
    rules["billet_interco"] = True
    return notes


def fix_erm_dri_pnl(state, rules):
    """B2: ERM's DRI sales get a P&L column; ERM's fixed costs follow the distribution %;
    intercompany sales are eliminated on consolidation."""
    gain = state["pnl"].pop("intercompany_gain_dri_musd", {}).get("ERM", 0.0)
    rules["erm_dri_pnl"] = True
    return [f"removed typed DRI intercompany gain {gain} M$/month; ERM DRI column computed"]


def fix_break_even(state, rules):
    """B4: break-even = (fixed + depreciation) ÷ CM per ton; cash break-even added."""
    rules["break_even_on_cm"] = True
    return ["break-even uses CM per ton (after export expenses)"]


FIXES = [
    ("A1", "Export expenses: $/t × volume", fix_export_expenses),
    ("A2/A3/B6", "Exports produced, priced, ×12 consistently", fix_consistent_volumes),
    ("A4", "ERM DRI volume includes EFS flat", fix_erm_dri_volume),
    ("A5", "HRC market share", fix_market_share),
    ("A6", "ESR electricity price decimal", fix_esr_electricity),
    ("A7", "Blends sum to 100%", fix_blends),
    ("B3", "DRI selling price from input", fix_dri_selling_price),
    ("B5", "Own inputs per line", fix_own_line_inputs),
    ("C", "Summaries = detail", fix_summaries),
    ("B1", "ERM billet: cheapest source + supplier cascade", fix_billet_sourcing),
    ("B2", "ERM DRI P&L + eliminations", fix_erm_dri_pnl),
    ("B4", "Break-even on CM", fix_break_even),
]


def to_corrected(legacy_state: dict) -> tuple[dict, list]:
    """Apply every fix.  Returns (corrected state, [(fix id, title, notes)])."""
    state = copy.deepcopy(legacy_state)
    rules = dict(ce.LEGACY_RULES)
    log = []
    for fid, title, fn in FIXES:
        log.append((fid, title, fn(state, rules)))
    assert rules == ce.CORRECTED_RULES, "every rule must be switched on by some fix"
    state["rules_profile"] = "corrected"
    state.setdefault("meta", {})["derived_from"] = "legacy workbook via model_fixes.to_corrected"
    return state, log


# --------------------------------------------------------------------------- #
# Bridge: what each fix moves
# --------------------------------------------------------------------------- #

def _metrics(out: dict) -> dict:
    cols = out["pnl"]["usd_monthly"]["columns"]
    cons = out["consolidated"]["usd_monthly"]["consolidated"]
    m = {"Group EBT": cons["ebt"], "Group CM": cons["contribution_margin"],
         "Group revenue": cons["total_value"]}
    for co in ce.COMPANIES:
        m[f"{co} EBT"] = cols[f"{co}/Sub-Total"]["ebt"]
    m["ERM billet $/t"] = out["sourcing"]["price_usd_t"]
    m["ERM DRI fixed LE/t"] = out["dri"]["ERM"]["fixed_cost_le_t"]
    m["checks passed"] = sum(c["passed"] for c in out["integrity"])
    return m


def bridge(legacy_state: dict) -> list:
    state = copy.deepcopy(legacy_state)
    rules = dict(ce.LEGACY_RULES)
    rows = [("—", "Workbook as is (legacy)", [], _metrics(ce.compute_all(state, rules)))]
    for fid, title, fn in FIXES:
        notes = fn(state, rules)
        rows.append((fid, title, notes, _metrics(ce.compute_all(state, rules))))
    return rows


def render_bridge(rows: list) -> str:
    keys = list(rows[0][3])
    money = [k for k in keys if k.endswith("EBT") or k.startswith("Group")]
    head = "| Fix | What | " + " | ".join(money) + " |\n|---|---|" + "---:|" * len(money) + "\n"
    body = ""
    prev = None
    for fid, title, _, m in rows:
        cells = []
        for k in money:
            if prev is None:
                cells.append(f"{m[k]:.3f}")
            else:
                d = m[k] - prev[k]
                cells.append("·" if abs(d) < 5e-4 else f"{d:+.3f}")
        body += f"| {fid} | {title} | " + " | ".join(cells) + " |\n"
        prev = m
    last = rows[-1][3]
    body += "| **=** | **Corrected model** | " + " | ".join(f"**{last[k]:.3f}**" for k in money) + " |\n"
    notes = "\n".join(f"- **{fid} {title}:** " + "; ".join(n) for fid, title, n, _ in rows[1:] if n)
    other = "\n".join(f"| {k} | {rows[0][3][k]:.2f} | {last[k]:.2f} |" for k in keys if k not in money)
    return ("# Fix-by-fix bridge: workbook → corrected model\n\n"
            "Monthly, USD M. The first row shows the workbook's figures. Each later row shows the change "
            "from applying that one fix on top of the ones above it. Group figures are after "
            "intercompany eliminations. `·` = no change.\n\n" + head + body +
            "\n| Other measure | Workbook | Corrected |\n|---|---:|---:|\n" + other +
            "\n\n## What each fix changed in the data\n\n" + notes + "\n")


def main(argv):
    import excel_io
    path = argv[1] if len(argv) > 1 else REFERENCE_WORKBOOK
    legacy = excel_io.extract_state(path)
    corrected, _ = to_corrected(legacy)
    with open(os.path.join(HERE, "model_initial_state.json"), "w") as f:
        json.dump(corrected, f, indent=1)
    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    with open(os.path.join(HERE, "reports", "fix_bridge.md"), "w") as f:
        f.write(render_bridge(bridge(legacy)))
    print("wrote model_initial_state.json and reports/fix_bridge.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
