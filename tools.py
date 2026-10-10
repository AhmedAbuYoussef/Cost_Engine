"""
Step 3 — the assistant's 14 tools (system prompt §3), callable directly from Python.

    from tools import ToolBox
    box = ToolBox(store)                  # store = state_manager.StateStore(...)
    box.call("get_pnl", {"scope": "consolidated"})

* Every tool takes structured arguments and returns a dict: ``{"status": "ok", ...}`` or
  the system prompt's error object ``{"status": "error", "error_code", ...}``.
* ``TOOL_SPECS`` holds each tool's description and JSON-schema arguments.  ``call``
  validates arguments against it, and Step 4 hands the same specs to Claude.
* The caller's mode is fixed when the ToolBox is made: ``"user"`` (direct user) or
  ``"orchestrator"`` (Fantomaas: no baseline commits, no refresh).
* Reports never calculate here: every number comes from ``cost_engine``.  A report
  refuses to serve a state that fails an error-level integrity check, and refuses a
  company/product combination that does not exist (structural_non_existence).
* Tables are data: ``{"title", "source", "currency", "columns", "rows": [{"label",
  "unit", "kind", "values": {column: number}}], "footnotes", "chart"?}``.  Numbers are
  full precision; ``kind`` (qty, money, per_t, pct, ratio, consumption, price) tells the
  display layer how to round.
"""

from __future__ import annotations

import copy
import datetime as dt
import math
import os

import cost_engine as ce
import refresh_template
import state_schema as schema
from state_schema import COMPANIES, PRODUCTION_MATRIX, PRODUCTS, ModelError

CURRENCIES = ("USD", "EGP")


# --------------------------------------------------------------------------- #
# Tool specs (single source of truth for validation and for the LLM layer)
# --------------------------------------------------------------------------- #

_STATE_ID = {"type": "string", "description": "'working' (default), a baseline id such as "
             "'baseline_2026-04', or a scenario id."}
_COMPANY_ALL = {"type": "string", "enum": [*COMPANIES, "all"]}
_CURRENCY = {"type": "string", "enum": list(CURRENCIES), "default": "USD"}
_CHART = {"type": "boolean", "default": False}


def _spec(name, description, properties, required=(), available=True, user_only=False):
    return {"name": name, "description": description, "available": available, "user_only": user_only,
            "input_schema": {"type": "object", "properties": properties, "required": list(required),
                             "additionalProperties": False}}


TOOL_SPECS = {s["name"]: s for s in [
    _spec("update_input",
          "Change one model input in the working session (never a baseline or scenario). "
          "Returns old and new values, the impact on key figures, and the reports affected. "
          "Several changes that must go together (e.g. a blend and its balancing scrap share) "
          "can be sent as 'changes'.",
          {"path": {"type": "string", "description": "dotted path, e.g. sales.EZDK.Rebar.local_kt"},
           "value": {"description": "new value (number, text or {'le': x} / {'usd': x})"},
           "scope": {"type": "string", "enum": ["single", "all_companies", "all_products"], "default": "single"},
           "changes": {"type": "array", "items": {"type": "object"},
                       "description": "alternative to path/value: [{path, value, scope?}, ...] applied together"},
           "note": {"type": "string"}}),
    _spec("read_state", "Read a slice of any stored state ('*' for all of it).",
          {"path": {"type": "string", "default": "*"}, "state_id": _STATE_ID}),
    _spec("list_states", "List baselines and/or scenarios with their metadata.",
          {"type": {"type": "string", "enum": ["baselines", "scenarios", "all"], "default": "all"},
           "filter_by": {"type": "object", "description": "date_from, date_to (YYYY-MM-DD), changed_inputs "
                         "(path prefixes), requested_outputs, tags, month_label"}}),
    _spec("get_cost_sheet", "Cost sheet at a production stage: detailed build-up, conversion summary "
          "(material + MRMR/yield effect + other conversion) or inputs side by side.",
          {"stage": {"type": "string", "enum": ["dri", "billet", "finished_product"]},
           "company": _COMPANY_ALL, "product": {"type": "string", "enum": list(PRODUCTS)},
           "view": {"type": "string", "enum": ["detailed", "conversion_summary", "inputs_side_by_side"],
                    "default": "conversion_summary"},
           "currency": _CURRENCY, "include_chart": _CHART, "state_id": _STATE_ID},
          required=["stage", "company"]),
    _spec("get_pnl", "P&L for the month (or year): revenue → CM → EBTD → EBT with break-even, per product "
          "and sub-total for one company, or all companies + eliminations + consolidated.",
          {"scope": {"type": "string", "enum": ["standalone", "consolidated"]},
           "company": {"type": "string", "enum": list(COMPANIES)},
           "period": {"type": "string", "enum": ["monthly", "annual"], "default": "monthly"},
           "currency": _CURRENCY, "include_chart": _CHART, "state_id": _STATE_ID},
          required=["scope"]),
    _spec("get_sales_report", "Sales volumes, sales mix, selling prices and market share.",
          {"company": _COMPANY_ALL, "product": {"type": "string", "enum": [*PRODUCTS, "all"]},
           "view": {"type": "string", "enum": ["full", "sales_mix", "prices_only", "market_share"],
                    "default": "full"},
           "hrc_total_local_market_kt": {"type": "number", "description": "HRC local market size for this "
                                         "run only (never stored); required for HRC market share"},
           "currency": _CURRENCY, "include_chart": _CHART, "state_id": _STATE_ID},
          required=["company", "product"]),
    _spec("get_fixed_cost_report", "Fixed costs (manufacturing, SG&A, net finance, depreciation): "
          "amounts, per ton, or the distribution across products.",
          {"company": _COMPANY_ALL,
           "view": {"type": "string", "enum": ["full_amount", "per_unit", "allocation_only"],
                    "default": "full_amount"},
           "currency": _CURRENCY, "include_chart": _CHART, "state_id": _STATE_ID},
          required=["company"]),
    _spec("get_production_report", "Production requirements derived from sales: the backward cascade, "
          "a summary with capacity use, a flow diagram, or the full plan.",
          {"company": _COMPANY_ALL,
           "view": {"type": "string", "enum": ["cascade", "summary", "flow_diagram", "full_plan"],
                    "default": "summary"},
           "line_filter": {"type": "string", "enum": ["long_line", "flat_line", "both"], "default": "both"},
           "state_id": _STATE_ID},
          required=["company"]),
    _spec("get_tradeoff_matrix", "Billet sourcing options: every source × every buyer, cheapest per buyer.",
          {"buyer": _COMPANY_ALL, "state_id": _STATE_ID}),
    _spec("run_sensitivity", "Vary one input over a range and track one output for one company "
          "(optionally one product). Stored states are not changed.",
          {"input_path": {"type": "string"},
           "variation": {"type": "object", "description": "{type: range, from, to, steps} | "
                         "{type: delta_pct, values: [...]} | {type: delta_abs, values: [...]}"},
           "output_metric": {"type": "string", "enum": ["ebt", "cm", "cm_per_ton", "breakeven_qty",
                                                        "variable_cost_per_ton", "manuf_cost_per_ton"]},
           "company": {"type": "string", "enum": list(COMPANIES)},
           "product": {"type": "string", "enum": list(PRODUCTS)},
           "include_chart": _CHART, "state_id": _STATE_ID},
          required=["input_path", "variation", "output_metric", "company"]),
    _spec("compare_states", "Side-by-side comparison of two stored states: inputs, outputs or both.",
          {"state_a_id": {"type": "string"}, "state_b_id": {"type": "string"},
           "comparison_type": {"type": "string", "enum": ["inputs", "outputs", "both"], "default": "both"},
           "output_focus": {"type": "string", "enum": ["pnl", "cost_sheet", "sales", "production", "fixed_cost"]},
           "threshold_pct": {"type": "number", "default": 0}},
          required=["state_a_id", "state_b_id"]),
    _spec("find_optimal_mix", "Search the operational plan that maximises contribution margin "
          "(available from build step 8, after its four verification cases pass).",
          {"objective": {"type": "string", "enum": ["group_cm", "company_cm"]},
           "company": {"type": "string", "enum": list(COMPANIES)},
           "free_variables": {"type": "array", "items": {"type": "string"}},
           "run_constraints": {"type": "object"}, "state_id": _STATE_ID},
          required=["objective"], available=False),
    _spec("manage_baseline_refresh", "Monthly baseline refresh: generate the seven-sheet XLSX template, "
          "or commit a filled template / CSV / full state as a month's baseline. Direct user only.",
          {"action": {"type": "string", "enum": ["generate_template", "commit"]},
           "source_baseline_id": {"type": "string"},
           "pre_fill_this_month": {"type": "boolean", "default": False},
           "output_dir": {"type": "string"},
           "source": {"type": "string", "enum": ["xlsx", "csv", "payload"]},
           "file_path": {"type": "string"}, "payload": {"type": "object"},
           "month_label": {"type": "string"}, "overwrite_if_exists": {"type": "boolean", "default": False}},
          required=["action"], user_only=True),
    _spec("commit_state", "Close or checkpoint the working session: promote it to a month's baseline "
          "(direct user only), save it as a named scenario, or discard it.",
          {"action": {"type": "string", "enum": ["promote_to_baseline", "save_as_scenario", "discard"]},
           "month_label": {"type": "string"}, "overwrite_if_exists": {"type": "boolean", "default": False},
           "name": {"type": "string"}, "description": {"type": "string"},
           "tags": {"type": "array", "items": {"type": "string"}}},
          required=["action"]),
]}

_TYPES = {"string": str, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def validate_args(name: str, args: dict) -> dict:
    """Required / unknown / enum / type checks; returns args with defaults filled in."""
    spec = TOOL_SPECS[name]["input_schema"]
    args = dict(args or {})
    unknown = set(args) - set(spec["properties"])
    if unknown:
        raise ModelError("schema_validation_error", f"{name}: unknown argument(s) {sorted(unknown)}",
                         field=sorted(unknown)[0], expected=sorted(spec["properties"]))
    for req in spec["required"]:
        if args.get(req) in (None, ""):
            raise ModelError("missing_required_arg", f"{name} needs '{req}'", field=req)
    for k, p in spec["properties"].items():
        if k not in args or args[k] is None:
            if "default" in p:
                args[k] = p["default"]
            continue
        t = p.get("type")
        v = args[k]
        if t and (not isinstance(v, _TYPES[t]) or (t == "number" and isinstance(v, bool))):
            raise ModelError("schema_validation_error", f"{name}.{k}: expected {t}", field=k, expected=t)
        if "enum" in p and v not in p["enum"]:
            raise ModelError("schema_validation_error", f"{name}.{k}: {v!r} is not one of {p['enum']}",
                             field=k, expected=p["enum"])
    return args


# --------------------------------------------------------------------------- #
# Table helpers
# --------------------------------------------------------------------------- #

def _row(label, values, unit="", kind="money", **extra):
    r = {"label": label, "unit": unit, "kind": kind, "values": values}
    r.update(extra)
    return r


def _table(title, columns, rows, *, source, currency=None, footnotes=(), **extra):
    t = {"title": title, "source": source, "currency": currency, "columns": list(columns),
         "rows": rows, "footnotes": [f for f in footnotes if f]}
    t.update(extra)
    return t


def _units(currency):
    usd = currency == "USD"
    return {"money": "M$" if usd else "M LE", "per_t": "$/t" if usd else "LE/t",
            "price": "$" if usd else "LE"}


def _stacked_chart(title, categories, series, total_label=True):
    """Chart data for the display layer (rulebook §9.2) — never a rendered image."""
    return {"type": "stacked_bar", "title": title, "categories": list(categories),
            "series": [{"name": n, "values": list(v)} for n, v in series], "total_labels": total_label}


def _producers(stage_or_product, company):
    who = [c for c in COMPANIES if c in PRODUCTION_MATRIX[stage_or_product]]
    if company == "all":
        excluded = [c for c in COMPANIES if c not in who]
        note = (f"{' and '.join(excluded)} {'does' if len(excluded) == 1 else 'do'} not produce "
                f"{schema.STAGE_LABEL[stage_or_product]}." if excluded else None)
        return who, note
    if company not in who:
        raise schema.missing_path_error({"DRI": f"dri.{company}", "Billet": f"billet.companies.{company}",
                                         "HRC": f"flat.{company}"}.get(stage_or_product,
                                                                       f"sales.{company}.{stage_or_product}"))
    return [company], None


_PNL_ROWS = (
    ("local_qty", "Local sales", "qty"), ("export_qty", "Export sales", "qty"),
    ("total_qty", "Total sales", "qty"), ("local_value", "Local revenue", "money"),
    ("local_price", "Local price", "per_t"), ("export_value", "Export revenue", "money"),
    ("export_price", "Export price", "per_t"), ("total_value", "Total revenue", "money"),
    ("avg_price", "Average price", "per_t"), ("variable_cogs", "Variable COGS", "money"),
    ("cost_per_t", "Variable cost per ton", "per_t"), ("export_expenses", "Export expenses", "money"),
    ("contribution_margin", "Contribution margin", "money"), ("cm_per_t", "CM per ton", "per_t"),
    ("cm_pct", "CM %", "pct"), ("intercompany_gain_dri", "Intercompany gain — DRI (legacy)", "money"),
    ("manufacturing_fixed", "Manufacturing fixed cost", "money"), ("sga", "SG&A", "money"),
    ("net_finance", "Net finance cost", "money"), ("total_fixed", "Total fixed expenses", "money"),
    ("ebtd", "EBTD", "money"), ("ebtd_per_t", "EBTD per ton", "per_t"), ("ebtd_pct", "EBTD %", "pct"),
    ("depreciation", "Depreciation", "money"), ("fc_per_t", "Fixed cost per ton (with dep.)", "per_t"),
    ("ebt", "EBT", "money"), ("ebt_per_t", "EBT per ton", "per_t"), ("ebt_pct", "EBT %", "pct"),
    ("vc_plus_fc_per_t", "VC + FC per ton", "per_t"), ("break_even_qty", "Break-even quantity", "qty"),
    ("cash_break_even_qty", "Cash break-even quantity (before dep.)", "qty"),
)

_STAGE_NAMES = {"long": {"s1": "EAF", "s2": "CCP", "s3": "Rolling mill"},
                "flat": {"s1": "EAF", "s2": "TSC", "s3": "HSM"},
                "esr": {"s1": "EAF + BCCM", "s3": "Rolling mill"}}


def _line_label(key: str, stages: dict) -> str:
    st, _, rest = key.partition(".")
    rest = rest.replace("cost.", "")
    if rest.startswith("material."):
        rest = rest.split(".", 1)[1].replace("dri", "DRI") + " (charge)"
    elif rest.startswith("yield."):
        rest = rest.split(".", 1)[1].replace("dri", "DRI") + " yield effect"
    rest = rest.replace("_", " ")
    return f"{stages.get(st, st)} · {rest}"


# --------------------------------------------------------------------------- #
# ToolBox
# --------------------------------------------------------------------------- #

class ToolBox:
    """The 14 tools bound to one StateStore and one caller mode."""

    def __init__(self, store, *, mode: str = "user", template_dir: str = "refresh_templates"):
        if mode not in ("user", "orchestrator"):
            raise ValueError("mode must be 'user' or 'orchestrator'")
        self.store, self.mode, self.template_dir = store, mode, template_dir

    # ---------------------------------------------------------------- dispatch

    def call(self, name: str, args: dict | None = None) -> dict:
        """Run a tool by name; errors come back as the structured error object."""
        try:
            if name not in TOOL_SPECS:
                raise ModelError("invalid_path", f"no tool named {name!r}", field="tool",
                                 expected=sorted(TOOL_SPECS))
            spec = TOOL_SPECS[name]
            if spec["user_only"] and self.mode != "user":
                raise ModelError("permission_denied", f"{name} is available to the direct user only")
            return getattr(self, name)(**validate_args(name, args))
        except ModelError as e:
            return e.to_dict()

    def visible_tools(self) -> list:
        """Tools the assistant may see now (D.3: the optimizer stays hidden until it ships;
        refresh is not offered to the orchestrator)."""
        return [s for s in TOOL_SPECS.values()
                if s["available"] and not (s["user_only"] and self.mode != "user")]

    # ---------------------------------------------------------------- shared

    def _source(self, state_id: str) -> str:
        if state_id == "working":
            return "Source: working state"
        meta = next((m for m in self.store.list_states("all") if m["id"] == state_id), None)
        if meta is None:
            self.store.get_state(state_id)          # raises the right not-found error
        if meta["type"] == "baseline":
            return f"Source: Baseline {meta['month_label']}"
        return f"Source: Scenario '{meta['name']}' ({state_id})"

    def _load(self, state_id: str):
        """(state, outputs, source label) — refusing states that fail an error-level check."""
        state = self.store.get_state(state_id)
        out = ce.compute_all(state)
        failed = ce.failed_errors(out)
        if failed:
            raise ModelError("integrity_check_failed",
                             "; ".join(f"{c['check']}: {c['detail']}" for c in failed),
                             field=failed[0]["check"])
        return state, out, self._source(state_id)

    @staticmethod
    def _warnings(out):
        return [c for c in out["integrity"] if not c["passed"] and c["severity"] == "warning"]

    # ================================================================ Input & state

    def update_input(self, path=None, value=None, scope="single", changes=None, note=None):
        if changes is None:
            if path is None:
                raise ModelError("missing_required_arg", "update_input needs 'path' and 'value' "
                                 "(or 'changes')", field="path")
            changes = [{"path": path, "value": value, "scope": scope}]
        elif path is not None:
            raise ModelError("schema_validation_error", "give either path/value or changes, not both",
                             field="changes")
        before = self.store.get_state("working")
        res = self.store.update_inputs(changes, actor=self.mode, note=note)
        if res["changes"]:
            ob, oa = ce.compute_all(before), self.store.compute("working")
            res["affected_reports"] = _affected_reports(ob, oa)
            note_ = _sourcing_change(ob, oa)
            if note_:
                res["sourcing_change"] = note_
            res["message"] = ("Updated in your working session — changes become permanent only if you "
                              "promote them at end of session or refresh the baseline.")
        return res

    def read_state(self, path="*", state_id="working"):
        return {"status": "ok", "state_id": state_id, "path": path,
                "value": self.store.read(path, state_id), "source": self._source(state_id)}

    def list_states(self, type="all", filter_by=None):
        return {"status": "ok", "states": self.store.list_states(type, filter_by)}

    # ================================================================ Reports

    def get_cost_sheet(self, stage, company, product=None, view="conversion_summary", currency="USD",
                       include_chart=False, state_id="working"):
        state, out, src = self._load(state_id)
        fx = state["fx_egp_per_usd"]
        if stage == "dri":
            return self._dri_sheet(state, out, src, company, view, currency, include_chart, fx)
        if stage == "billet":
            return self._billet_sheet(state, out, src, company, view, currency, include_chart, fx)
        if not product:
            raise ModelError("missing_required_arg", "finished_product needs 'product'", field="product")
        return self._finished_sheet(state, out, src, company, product, view, currency, include_chart, fx)

    def _dri_sheet(self, state, out, src, company, view, currency, chart, fx):
        cos, note = _producers("DRI", company)
        u = _units(currency)
        to = (1 / fx) if currency == "USD" else 1.0          # DRI detail is built in LE
        rows = []
        if view == "conversion_summary":
            k = fx if currency == "EGP" else 1.0
            for key, label in (("material_price", "Material price (IOP landed)"),
                               ("mrmr_effect", "MRMR effect"), ("other_conversion", "Other conversion cost"),
                               ("total_conversion", "Total conversion cost"),
                               ("total_variable_cost", "Total variable manufacturing cost")):
                rows.append(_row(label, {c: out["dri"][c]["summary_usd_t"][key] * k for c in cos},
                                 u["per_t"], "per_t"))
            t = _table("DRI — conversion cost", cos, rows, source=src, currency=currency, footnotes=[note])
            if chart:
                s = lambda key: [out["dri"][c]["summary_usd_t"][key] * k for c in cos]
                t["chart"] = _stacked_chart("DRI cost per ton", cos, [("Material", s("material_price")),
                                            ("MRMR effect", s("mrmr_effect")),
                                            ("Other conversion", s("other_conversion"))])
            return {"status": "ok", "table": t}
        if view == "inputs_side_by_side":
            keys = list(state["dri"][cos[0]]["consumption"])
            rows.append(_row("MRMR", {c: state["dri"][c]["mrmr"] for c in cos}, "t IOP/t DRI", "ratio"))
            rows.append(_row("IOP landed", {c: state["dri"][c]["iop_landed_usd_t"] * (fx if currency == "EGP" else 1)
                                            for c in cos}, u["per_t"], "price"))
            rows.append(_row("Natural gas price", {c: state["dri"][c]["ng_price_usd_mmbtu"] *
                                                   (fx if currency == "EGP" else 1) for c in cos},
                             f"{u['price']}/MMBTU", "price"))
            for key in keys:
                rows.append(_row(f"Consumption · {key.replace('_', ' ')}",
                                 {c: state["dri"][c]["consumption"][key] for c in cos}, "per t DRI", "consumption"))
            for key in state["dri"][cos[0]]["prices_le"]:
                rows.append(_row(f"Unit price · {key.replace('_', ' ')}",
                                 {c: state["dri"][c]["prices_le"][key] * to for c in cos},
                                 u["price"], "price"))
            for key in ("labor", "depreciation", "other_fixed"):
                rows.append(_row(f"Fixed · {key.replace('_', ' ')}",
                                 {c: state["dri"][c]["fixed_le"][key] * to / 1e6 for c in cos}, u["money"], "money"))
            return {"status": "ok", "table": _table("DRI — inputs", cos, rows, source=src, currency=currency,
                                                    footnotes=[note])}
        # detailed: consumption × price = cost, per line, then fixed and margin
        cols = [f"{c} {x}" for c in cos for x in ("consumption", "unit price", "cost/t")]
        lines = (("electricity", "electricity_kwh", "electricity_kwh"), ("natural_gas", "natural_gas_nm3", None),
                 ("oxygen", "oxygen_nm3", "oxygen_nm3"), ("nitrogen", "nitrogen_nm3", "nitrogen_nm3"),
                 ("water", "water_nm3", "water_nm3"), ("chemicals", "chemicals_t", "chemicals_t"),
                 ("spare_parts", "spare_parts_t", "spare_parts_t"),
                 ("external_services", "external_services_t", "external_services_t"), ("other", "other_t", "other_t"))
        v = {}
        for c in cos:
            o, d = out["dri"][c], state["dri"][c]
            v[c] = {"IOP": (d["mrmr"], o["iop_landed_le_t"], o["cost_le_t"]["iop"])}
            for line, ck, pk in lines:
                price = o["ng_price_le_nm3"] if pk is None else d["prices_le"][pk]
                v[c][line] = (d["consumption"][ck], price, o["cost_le_t"][line])
        for line in ["IOP", *[x[0] for x in lines]]:
            vals = {}
            for c in cos:
                q, p, cost = v[c][line]
                vals.update({f"{c} consumption": q, f"{c} unit price": p * to, f"{c} cost/t": cost * to})
            rows.append(_row(line.replace("_", " ").capitalize() if line != "IOP" else "IOP (MRMR × landed)",
                             vals, u["per_t"], "per_t"))
        tot = lambda key: {f"{c} cost/t": (out["dri"][c][key] * to if out["dri"][c][key] is not None else None)
                           for c in cos}
        rows.append(_row("Variable cost", tot("variable_cost_le_t"), u["per_t"], "per_t"))
        for key, label in (("labor", "Labor"), ("depreciation", "Depreciation"), ("other", "Other fixed")):
            rows.append(_row(label, {f"{c} cost/t": (out["dri"][c]["fixed_le_t"][key] or 0) * to for c in cos},
                             u["per_t"], "per_t"))
        rows.append(_row("Fixed cost", tot("fixed_cost_le_t"), u["per_t"], "per_t"))
        rows.append(_row("Manufacturing cost", tot("manufacturing_cost_le_t"), u["per_t"], "per_t"))
        rows.append(_row("DRI selling price", tot("selling_price_le_t"), u["per_t"], "per_t"))
        rows.append(_row("Gross margin", tot("gross_margin_le_t"), u["per_t"], "per_t"))
        rows.append(_row("Production", {f"{c} cost/t": out["dri"][c]["production_t"] / 1000 for c in cos},
                         "kt", "qty"))
        return {"status": "ok", "table": _table("DRI — detailed cost sheet", cols, rows, source=src,
                                                currency=currency, footnotes=[note])}

    def _billet_sheet(self, state, out, src, company, view, currency, chart, fx):
        cos, note = _producers("Billet", company)
        u = _units(currency)
        k = fx if currency == "EGP" else 1.0
        if view == "conversion_summary":
            rows = [_row(label, {c: out["billet"][c][key] * k for c in cos}, u["per_t"], "per_t")
                    for key, label in (("material_price", "Material price"), ("yield_effect", "Yield effect"),
                                       ("other_conversion", "Other conversion cost"),
                                       ("total_conversion", "Total conversion cost"),
                                       ("total_variable_cost", "Total variable manufacturing cost"))]
            rows += [_row("DRI price", {c: out["billet"][c]["dri_price"] * k for c in cos}, u["per_t"], "price"),
                     _row("Billet yield from solid charge", {c: out["billet"][c]["billet_yield_pct"] for c in cos},
                          "%", "pct")]
            t = _table("Billet — conversion cost", cos, rows, source=src, currency=currency,
                       footnotes=[note, "ERM has no furnace; it buys billets (see the trade-off matrix)."])
            if chart:
                s = lambda key: [out["billet"][c][key] * k for c in cos]
                t["chart"] = _stacked_chart("Billet cost per ton", cos, [("Material", s("material_price")),
                                            ("Yield effect", s("yield_effect")),
                                            ("Other conversion", s("other_conversion"))])
            return {"status": "ok", "table": t}
        if view == "inputs_side_by_side":
            rows = []
            for key, label, unit, kind in (("eaf_yield_pct", "EAF yield", "%", "pct"),
                                           ("ccp_yield_pct", "CCP yield", "%", "pct"),
                                           ("tradeoff_ratio", "Trade-off ratio", "×", "ratio"),
                                           ("eaf_lf_electricity_kwh_t_ms", "EAF & LF electricity", "kWh/t MS",
                                            "consumption")):
                rows.append(_row(label, {c: state["billet"]["companies"][c][key] for c in cos}, unit, kind))
            for key in ("dri", "local_scrap", "imported_scrap"):
                rows.append(_row(f"Blend · {key.replace('_', ' ')}",
                                 {c: state["billet"]["companies"][c]["blend_pct"][key] for c in cos}, "%", "pct"))
            for key, label in (("local_scrap_usd_t", "Local scrap price"), ("imported_scrap_usd_t", "Imported scrap price"),
                               ("electricity_usd_kwh", "Electricity price")):
                rows.append(_row(label, {c: state["billet"]["companies"][c][key] * k for c in cos},
                                 u["price"], "price"))
            rows += _detail_input_rows(state, {c: ("EZDK Rebar" if c == "EZDK" else f"{c} Rebar") for c in cos},
                                       ("stage1", "stage2"), fx, currency)
            return {"status": "ok", "table": _table("Billet — inputs", cos, rows, source=src, currency=currency,
                                                    footnotes=[note])}
        # detailed: every cost line, stage by stage
        sheets = {c: out["detail"][f"{c} Rebar"] for c in cos}
        keys = []
        for c in cos:
            d = sheets[c]
            for key in d:
                if (key.startswith(("s1.cost.", "s2.cost.")) or key in
                        ("s1.conversion", "s1.ms_variable_cost", "s1.billet_variable_cost", "s2.conversion",
                         "s2.variable_cost")) and key not in keys:
                    keys.append(key)
        rows = []
        for key in keys:
            stages = _STAGE_NAMES["long"]
            label = _line_label(key, stages if not any(c == "ESR" for c in cos) or key.startswith("s2")
                                else {**stages, "s1": "EAF (+ BCCM at ESR)"})
            rows.append(_row(label, {c: (sheets[c][key] * k if key in sheets[c] else None) for c in cos},
                             u["per_t"] + (" MS" if key.startswith("s1") and key != "s1.billet_variable_cost" else ""),
                             "per_t"))
        rows.append(_row("Billet variable cost", {c: (sheets[c].get("s2.variable_cost") or
                                                      sheets[c].get("s1.billet_variable_cost")) * k for c in cos},
                         u["per_t"], "per_t"))
        return {"status": "ok", "table": _table("Billet — detailed cost sheet", cos, rows, source=src,
                                                currency=currency, footnotes=[
                                                    note, "EZDK and EFS cost the EAF per ton of molten steel and add "
                                                    "the caster (CCP); ESR's sheet costs EAF and caster together "
                                                    "per ton of billet."])}

    def _finished_sheet(self, state, out, src, company, product, view, currency, chart, fx):
        cos, note = _producers(product, company)
        u = _units(currency)
        k = fx if currency == "EGP" else 1.0
        if view == "conversion_summary":
            if product == "HRC":
                rows = [_row(label, {c: out["flat"][c][key] * k for c in cos}, u["per_t"], "per_t")
                        for key, label in (("material_price", "Material price"), ("yield_effect", "Yield effect"),
                                           ("other_conversion", "Other conversion cost"),
                                           ("total_conversion", "Total conversion cost"),
                                           ("total_variable_cost", "Total variable manufacturing cost"))]
                t = _table("HRC — conversion cost", cos, rows, source=src, currency=currency, footnotes=[note])
                if chart:
                    s = lambda key: [out["flat"][c][key] * k for c in cos]
                    t["chart"] = _stacked_chart("HRC cost per ton", cos, [("Material", s("material_price")),
                                                ("Yield effect", s("yield_effect")),
                                                ("Other conversion", s("other_conversion"))])
                return {"status": "ok", "table": t}
            data = out["rebar"] if product == "Rebar" else out["wire"]
            rows = []
            for sc, label in (("sc1", "Sc1 — in-house billet"), ("sc2", "Sc2 — market billet")):
                for key, line in (("material_price", "Material price"), ("yield_effect", "Yield effect"),
                                  ("home_scrap_deduction", "Home scrap deduction"),
                                  ("other_conversion", "Other conversion cost"),
                                  ("total_conversion", "Total conversion cost"),
                                  ("total_variable_cost", "Total variable manufacturing cost")):
                    rows.append(_row(f"{label} · {line}", {c: data[c][sc][key] * k for c in cos},
                                     u["per_t"], "per_t", scenario=sc))
            rows.append(_row("Difference (Sc1 − Sc2)", {c: data[c]["difference"] * k for c in cos},
                             u["per_t"], "per_t"))
            foot = [note]
            if "ERM" in cos:
                srcs = out["sourcing"]
                foot.append(f"ERM's Sc1 billet is {srcs['ERM_rebar_billet']} → {srcs['supplier']} at "
                            f"{srcs['price_usd_t'] * k:,.2f} {u['per_t']}.")
            t = _table(f"{product} — conversion cost (Sc1 vs Sc2)", cos, rows, source=src, currency=currency,
                       footnotes=foot)
            if chart:
                s = lambda key: [data[c]["sc1"][key] * k for c in cos]
                t["chart"] = _stacked_chart(f"{product} cost per ton (Sc1)", cos,
                                            [("Material", s("material_price")), ("Yield effect", s("yield_effect")),
                                             ("Home scrap", s("home_scrap_deduction")),
                                             ("Other conversion", s("other_conversion"))])
            return {"status": "ok", "table": t}
        sheets = {c: _finished_sheet_name(c, product) for c in cos}
        if view == "inputs_side_by_side":
            rows = [_row(f"{product} yield", {c: state["finishing_yield_pct"].get(product, {}).get(c) for c in cos}, "%", "pct")] \
                if product != "HRC" else \
                [_row(label, {c: state["flat"][c][key] for c in cos}, "%", "pct")
                 for key, label in (("eaf_yield_pct", "EAF yield"), ("tsc_yield_pct", "TSC yield"),
                                    ("hsm_yield_pct", "HSM yield"))]
            stages = ("stage1", "stage2", "stage3") if product == "HRC" else ("stage3",)
            rows += _detail_input_rows(state, sheets, stages, fx, currency)
            return {"status": "ok", "table": _table(f"{product} — inputs", cos, rows, source=src,
                                                    currency=currency, footnotes=[note])}
        # detailed
        rows, keys = [], []
        prefixes = ("s1.cost.", "s2.cost.", "s3.cost.") if product == "HRC" else ("s3.cost.",)
        totals = ("s1.ms_variable_cost", "s2.variable_cost", "s3.conversion", "s3.variable_cost") \
            if product == "HRC" else ("s3.conversion", "s3.variable_cost")
        rolling = {c for c in cos if sheets[c] in ("ERM Rolling", "EZDK Wire")}
        for c in cos:
            d = out["detail"][sheets[c]]
            if c in rolling:
                for key in d:
                    if (key.startswith(("cost.", "conversion.")) or key in ("raw_material_cost",
                                                                           "other_variable_cost")) and key not in keys:
                        keys.append(key)
            else:
                for key in d:
                    if (key.startswith(prefixes) or key in totals) and key not in keys:
                        keys.append(key)
        stages = _STAGE_NAMES["flat" if product == "HRC" else "long"]
        for key in keys:
            vals = {}
            for c in cos:
                d = out["detail"][sheets[c]]
                if key not in d:
                    vals[c] = None
                elif c in rolling:          # built in LE
                    vals[c] = d[key] / fx * k
                else:
                    vals[c] = d[key] * k
            label = (f"Rolling · {key.replace('cost.', '').replace('conversion.', 'conversion ').replace('_', ' ')}"
                     if not key.startswith("s") else _line_label(key, stages))
            rows.append(_row(label, vals, u["per_t"], "per_t"))
        rows.append(_row(f"{product} variable cost", {
            c: (out["detail"][sheets[c]]["variable_cost_usd_t"] if c in rolling
                else out["detail"][sheets[c]]["s3.variable_cost"]) * k for c in cos}, u["per_t"], "per_t"))
        foot = [note]
        if rolling:
            foot.append(f"{', '.join(sorted(rolling))}: rolling-only sheet (bought or transferred billets), "
                        f"built in LE and shown here converted at FX {fx:g}.")
        return {"status": "ok", "table": _table(f"{product} — detailed cost sheet", cos, rows, source=src,
                                                currency=currency, footnotes=foot)}

    def get_pnl(self, scope, company=None, period="monthly", currency="USD", include_chart=False,
                state_id="working"):
        state, out, src = self._load(state_id)
        variant = f"{'usd' if currency == 'USD' else 'le'}_{period}"
        u = _units(currency)
        cols = out["pnl"][variant]["columns"]
        span = "month" if period == "monthly" else "year"
        if scope == "standalone":
            if not company:
                raise ModelError("missing_required_arg", "a standalone P&L needs 'company'", field="company")
            keys = [k for k, c in cols.items() if c.get("company") == company and k != "Total"]
            keys = [k for k in keys if not k.endswith("Sub-Total")] + [f"{company}/Sub-Total"]
            names = {k: k.split("/", 1)[1] + (" (intercompany)" if cols[k].get("intercompany") else "")
                     for k in keys}
            rows = []
            for key, label, kind in _PNL_ROWS:
                vals = {names[k]: cols[k].get(key) for k in keys}
                if all(v is None for v in vals.values()) and key in ("intercompany_gain_dri", "cash_break_even_qty"):
                    continue
                unit = {"qty": "kt", "money": u["money"], "per_t": u["per_t"], "pct": "%"}[kind]
                rows.append(_row(label, vals, unit, kind, key=key))
            foot = []
            for k in keys:
                c = cols[k]
                if c.get("intercompany"):
                    foot.append(f"{names[k]}: sold to {', '.join(c['buyers'])}; eliminated in the consolidated P&L.")
            foot.append("Break-even = (fixed costs + depreciation) ÷ contribution margin per ton; blank when "
                        "each ton loses money, 0 when nothing is sold.")
            t = _table(f"{company} — P&L per {span}", [names[k] for k in keys], rows, source=src,
                       currency=currency, footnotes=foot)
            if include_chart:
                prod = [k for k in keys if not k.endswith("Sub-Total")]
                t["chart"] = {"type": "bar", "title": f"{company} EBT by product ({u['money']})",
                              "categories": [names[k] for k in prod],
                              "series": [{"name": "EBT", "values": [cols[k]["ebt"] for k in prod]}]}
            return {"status": "ok", "table": t}
        con = out["consolidated"][variant]
        columns = [*con["companies"], "Eliminations", "Consolidated"]
        lines = (("total_value", "Revenue"), ("variable_cogs", "Variable COGS"), ("export_expenses", "Export expenses"),
                 ("contribution_margin", "Contribution margin"), ("manufacturing_fixed", "Manufacturing fixed cost"),
                 ("sga", "SG&A"), ("net_finance", "Net finance cost"), ("total_fixed", "Total fixed expenses"),
                 ("ebtd", "EBTD"), ("depreciation", "Depreciation"), ("ebt", "EBT"))
        rows = []
        for key, label in lines:
            vals = {co: con["companies"][co][key] for co in con["companies"]}
            vals["Eliminations"] = con["eliminations"][key]
            vals["Consolidated"] = con["consolidated"][key]
            rows.append(_row(label, vals, u["money"], "money", key=key))
            if key in ("contribution_margin", "ebt"):
                rev = {c: (con["companies"][c]["total_value"] if c in con["companies"] else
                           con["consolidated"]["total_value"]) for c in columns if c != "Eliminations"}
                pct = {c: _div_pct(vals[c], rev[c]) for c in rev}
                rows.append(_row(f"{label} %", pct, "%", "pct", key=f"{key}_pct"))
        c = con["consolidated"]
        rows.append(_row("External sales quantity", {"Consolidated": c["external_sales_qty"]}, "kt", "qty"))
        rows.append(_row("Average local price (revenue ÷ volume)", {"Consolidated": c["avg_local_price"]},
                         u["per_t"], "per_t"))
        foot = [f"Eliminated: {s['product']} sold by {s['seller']} — {s['revenue']:,.3f} {u['money']} "
                f"({s['qty']:,.1f} kt), removed from revenue and from the buyers' COGS."
                for s in con["intercompany_sales"].values()]
        t = _table(f"Consolidated P&L per {span}", columns, rows, source=src, currency=currency, footnotes=foot)
        if include_chart:
            t["chart"] = {"type": "bar", "title": f"EBT by company ({u['money']})", "categories": columns,
                          "series": [{"name": "EBT", "values": [r for r in
                                      [next(x for x in rows if x.get("key") == "ebt")["values"][c] for c in columns]]}]}
        return {"status": "ok", "table": t}

    def get_sales_report(self, company, product, view="full", hrc_total_local_market_kt=None,
                         currency="USD", include_chart=False, state_id="working"):
        state, out, src = self._load(state_id)
        fx = state["fx_egp_per_usd"]
        u = _units(currency)
        k = fx if currency == "EGP" else 1.0
        products = list(PRODUCTS) if product == "all" else [product]
        combos, excluded = [], []
        for p in products:
            if company == "all":
                combos += [(c, p) for c in COMPANIES if c in PRODUCTION_MATRIX[p]]
            elif company in PRODUCTION_MATRIX[p]:
                combos.append((company, p))
            elif product != "all":
                raise schema.missing_path_error(f"sales.{company}.{p}")
            else:
                excluded.append(p)
        foot = [f"{company} does not produce {', '.join(excluded)}."] if excluded else []
        cols = out["pnl"]["usd_monthly"]["columns"]
        if view == "market_share":
            ms = out["market_share"]
            rows, columns = [], products
            mkt = dict(state["total_local_market_kt"])
            if "HRC" in products:
                if hrc_total_local_market_kt is None:
                    return {"status": "needs_input", "field": "hrc_total_local_market_kt",
                            "message": "HRC market share needs the total local HRC market for this month (Ktons). "
                                       "It is asked at each run and never stored."}
                mkt["HRC"] = hrc_total_local_market_kt
            group = ms["group_local_kt"]
            rows.append(_row("Group local sales", {p: group[p] for p in products}, "kt", "qty"))
            rows.append(_row("Total local market", {p: mkt[p] for p in products}, "kt", "qty"))
            rows.append(_row("Ezz Steel market share", {p: _div_pct(group[p], mkt[p]) for p in products}, "%", "pct"))
            for c in COMPANIES:
                if company not in ("all", c):
                    continue
                rows.append(_row(f"{c} share of group local sales",
                                 {p: (_div_pct(state["sales"][c][p]["local_kt"], group[p])
                                      if c in PRODUCTION_MATRIX[p] else None) for p in products}, "%", "pct"))
            return {"status": "ok", "table": _table("Market share", columns, rows, source=src, footnotes=foot)}
        columns = [f"{c} {p}" for c, p in combos]
        rows = []
        sl = {f"{c} {p}": state["sales"][c][p] for c, p in combos}
        if view in ("full", "sales_mix"):
            rows += [_row("Local sales", {x: s["local_kt"] for x, s in sl.items()}, "kt", "qty"),
                     _row("Export sales", {x: s["export_kt"] for x, s in sl.items()}, "kt", "qty"),
                     _row("Total sales", {x: s["local_kt"] + s["export_kt"] for x, s in sl.items()}, "kt", "qty")]
        if view == "sales_mix":
            rows.append(_row("Local %", {x: _div_pct(s["local_kt"], s["local_kt"] + s["export_kt"]) for x, s in sl.items()},
                             "%", "pct"))
            rows.append(_row("Export %", {x: _div_pct(s["export_kt"], s["local_kt"] + s["export_kt"]) for x, s in sl.items()},
                             "%", "pct"))
            tot = {c: sum(state["sales"][c][p]["local_kt"] + state["sales"][c][p]["export_kt"]
                          for p in state["sales"][c]) for c in COMPANIES}
            rows.append(_row("Share of company volume", {f"{c} {p}": _div_pct(
                state["sales"][c][p]["local_kt"] + state["sales"][c][p]["export_kt"], tot[c]) for c, p in combos},
                "%", "pct"))
        if view in ("full", "prices_only"):
            rows += [_row("Local price", {x: s["local_price_le_t"] / fx * k for x, s in sl.items()}, u["per_t"], "price"),
                     _row("Export price", {x: s["export_price_usd_t"] * k for x, s in sl.items()}, u["per_t"], "price")]
        if view == "full":
            rows += [_row("Local revenue", {f"{c} {p}": cols[f"{c}/{p}"]["local_value"] * k for c, p in combos},
                          u["money"], "money"),
                     _row("Export revenue", {f"{c} {p}": cols[f"{c}/{p}"]["export_value"] * k for c, p in combos},
                          u["money"], "money"),
                     _row("Export expense rate", {f"{c} {p}": state["pnl"]["export_expense_usd_t"][c][p] * k
                                                  for c, p in combos}, u["per_t"], "price")]
        t = _table(f"Sales — {view.replace('_', ' ')}", columns, rows, source=src, currency=currency, footnotes=foot)
        if include_chart:
            t["chart"] = _stacked_chart("Sales volume (kt)", columns, [
                ("Local", [s["local_kt"] for s in sl.values()]), ("Export", [s["export_kt"] for s in sl.values()])])
        return {"status": "ok", "table": t}

    def get_fixed_cost_report(self, company, view="full_amount", currency="USD", include_chart=False,
                              state_id="working"):
        state, out, src = self._load(state_id)
        fx = state["fx_egp_per_usd"]
        u = _units(currency)
        k = fx if currency == "EGP" else 1.0
        cos = list(COMPANIES) if company == "all" else [company]
        fc = out["fixed_cost"]
        lines = (("manufacturing", "Manufacturing fixed cost"), ("sga", "SG&A"),
                 ("net_finance", "Net finance cost"), ("depreciation", "Depreciation"))
        if view == "full_amount":
            rows = [_row(label, {c: fc["usd_m"][c][key] * k for c in cos}, u["money"], "money") for key, label in lines]
            rows.append(_row("Total with depreciation", {c: fc["usd_m"][c]["total_with_dep"] * k for c in cos},
                             u["money"], "money"))
            for p in ("DRI", "Rebar", "Wire Rod", "HRC"):
                rows.append(_row(f"Distribution · {p}", {c: state["fixed_cost"][c]["distribution_pct"][p] for c in cos},
                                 "%", "pct"))
            t = _table("Fixed costs per month", cos, rows, source=src, currency=currency)
            if include_chart:
                t["chart"] = _stacked_chart("Fixed costs", cos, [(label, [fc["usd_m"][c][key] * k for c in cos])
                                                                 for key, label in lines])
            return {"status": "ok", "table": t}
        if view == "allocation_only":
            cols = [f"{c} {p}" for c in cos for p in ("DRI", "Rebar", "Wire Rod", "HRC")
                    if state["fixed_cost"][c]["distribution_pct"][p]]
            rows = [_row("Distribution", {x: state["fixed_cost"][x.split(' ', 1)[0]]["distribution_pct"][x.split(' ', 1)[1]]
                                          for x in cols}, "%", "pct")]
            for key, label in lines:
                rows.append(_row(label, {x: fc["allocation_usd_m"][x.split(' ', 1)[1]][x.split(' ', 1)[0]][key] * k
                                         for x in cols}, u["money"], "money"))
            return {"status": "ok", "table": _table("Fixed-cost allocation", cols, rows, source=src, currency=currency)}
        pcols = out["pnl"]["usd_monthly"]["columns"]
        keys = [x for x, c in pcols.items() if c.get("company") in cos and "product" in c and not c.get("intercompany")]
        keys += [x for x, c in pcols.items() if c.get("company") in cos and c.get("product") == "DRI"]
        rows = []
        for key, label in (("manufacturing_fixed", "Manufacturing fixed"), ("sga", "SG&A"),
                           ("net_finance", "Net finance"), ("depreciation", "Depreciation")):
            rows.append(_row(f"{label} per ton", {x: _div_per_t(pcols[x][key], pcols[x]["total_qty"]) * k
                                                  if _div_per_t(pcols[x][key], pcols[x]["total_qty"]) is not None else None
                                                  for x in keys}, u["per_t"], "per_t"))
        rows.append(_row("Fixed cost per ton (with dep.)", {x: (pcols[x]["fc_per_t"] * k if pcols[x]["fc_per_t"] is not None
                                                                else None) for x in keys}, u["per_t"], "per_t"))
        rows.append(_row("Volume", {x: pcols[x]["total_qty"] for x in keys}, "kt", "qty"))
        return {"status": "ok", "table": _table("Fixed cost per ton", keys, rows, source=src, currency=currency,
                                                footnotes=["Per ton of sales (= production) of each product."])}

    def get_production_report(self, company, view="summary", line_filter="both", state_id="working"):
        state, out, src = self._load(state_id)
        pr = out["production"]
        cos = list(COMPANIES) if company == "all" else [company]
        tables = []
        if view in ("cascade", "full_plan"):
            if line_filter in ("long_line", "both"):
                tables.append(_cascade_table("Long line (rebar & wire rod)", pr["long"], pr["long_total"], cos,
                              (("rebar", "Rebar"), ("wire_rod", "Wire rod"), ("billet", "Billets"),
                               ("molten_steel", "Molten steel"), ("solid_charge", "Solid charge"),
                               ("dri", "DRI"), ("imported_scrap", "Imported scrap"), ("local_scrap", "Local scrap"),
                               ("iop", "IOP")), src, company == "all", out))
            if line_filter in ("flat_line", "both"):
                tables.append(_cascade_table("Flat line (HRC)", pr["flat"], pr["flat_total"],
                              [c for c in cos if c in pr["flat"]],
                              (("hrc", "HRC"), ("molten_steel", "Molten steel"), ("solid_charge", "Solid charge"),
                               ("dri", "DRI"), ("imported_scrap", "Imported scrap"), ("local_scrap", "Local scrap"),
                               ("iop", "IOP")), src, company == "all", out))
        if view in ("summary", "full_plan"):
            tables.append(_cascade_table("Monthly production summary", pr["summary"], pr["summary_total"], cos,
                          (("rebar", "Rebar"), ("wire_rod", "Wire rod"), ("hrc", "HRC"), ("billet", "Billets"),
                           ("dri", "DRI"), ("iop", "IOP"), ("scrap", "Scrap (local + imported)")), src,
                          company == "all", out))
            cap = out["capacity"]["items"]
            rows = [_row(name, {"Required": v["required_t"] / 1000, "Ceiling": v["ceiling_t"] / 1000,
                                "Utilisation %": v["utilisation_pct"]}, "kt", "qty", over=v["over_by_t"] > 0)
                    for name, v in cap.items() if company == "all" or name.endswith(company)]
            tables.append(_table("Capacity use", ["Required", "Ceiling", "Utilisation %"], rows, source=src,
                                 footnotes=["Billet has no ceiling: billet capacity follows downstream demand."]))
        res = {"status": "ok", "tables": tables, "warnings": self._warnings(out)}
        if view in ("flow_diagram", "full_plan"):
            res["flow_diagram"] = _flow_diagram(out, cos)
        if view == "full_plan":
            s = out["sourcing"]
            res["sourcing"] = {"ERM billets": f"{s['billets_t'] / 1000:,.1f} kt from {s['supplier']} at "
                                              f"{s['price_usd_t']:,.2f} $/t ({s['ERM_rebar_billet']})"}
        return res

    def get_tradeoff_matrix(self, buyer="all", state_id="working"):
        state, out, src = self._load(state_id)
        t = out["billet"]["tradeoff"]
        buyers = list(COMPANIES) if buyer == "all" else [buyer]
        sources = ["EZDK", "EFS", "ESR", "Market"]
        rows = [_row(f"{s}" + (f" (×{state['billet']['companies'][s]['tradeoff_ratio']:.4f})" if s != "Market" else ""),
                     {b: t["rows"][s][b] for b in buyers}, "$/t", "price", source=s,
                     cheapest_for=[b for b in buyers if t["cheapest_source"][b] == s])
                for s in sources]
        rows.append(_row("Minimum", {b: t["minimum"][b] for b in buyers}, "$/t", "price"))
        rows.append(_row("Cheapest source", {b: t["cheapest_source"][b] for b in buyers}, "", "text"))
        srcs = out["sourcing"]
        foot = ["Intercompany price = seller's billet VC × seller's trade-off ratio; a producer's own column is "
                "its VC. Producers use their own billet (furnaces cannot be idled economically).",
                f"ERM currently sources {srcs['ERM_rebar_billet']} → {srcs['supplier']} at {srcs['price_usd_t']:,.2f} $/t; "
                "an internal source raises that supplier's production (capacity is checked)."]
        return {"status": "ok", "table": _table("Billet trade-off matrix", buyers, rows, source=src, currency="USD",
                                                footnotes=foot, highlight="minimum per buyer")}

    # ================================================================ Analysis

    def run_sensitivity(self, input_path, variation, output_metric, company, product=None,
                        include_chart=False, state_id="working"):
        state, base_out, src = self._load(state_id)
        if not schema.exists(state, input_path):
            raise schema.missing_path_error(input_path)
        base_leaf = schema.get(state, input_path)
        amount = base_leaf[next(iter(base_leaf))] if isinstance(base_leaf, dict) and len(base_leaf) == 1 else base_leaf
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise ModelError("schema_validation_error", f"{input_path} is not a numeric input", field="input_path")
        col = f"{company}/{product}" if product else f"{company}/Sub-Total"
        if product and company not in PRODUCTION_MATRIX[product]:
            raise schema.missing_path_error(f"sales.{company}.{product}")
        points = _variation_points(variation, amount)
        metric = {"ebt": ("ebt", "M$"), "cm": ("contribution_margin", "M$"), "cm_per_ton": ("cm_per_t", "$/t"),
                  "breakeven_qty": ("break_even_qty", "kt"), "variable_cost_per_ton": ("cost_per_t", "$/t"),
                  "manuf_cost_per_ton": ("vc_plus_fc_per_t", "$/t")}[output_metric]
        rows = []
        for x in points:
            trial = copy.deepcopy(state)
            schema.set_value(trial, input_path, {next(iter(base_leaf)): x} if isinstance(base_leaf, dict) else x)
            point = {"input": x, "output": None, "status": "ok"}
            try:
                schema.validate(trial)
            except ModelError as e:
                point.update(status="invalid_input", detail=e.message)
                rows.append(point)
                continue
            o = ce.compute_all(trial)
            failed = ce.failed_errors(o)
            if failed:
                point.update(status="integrity_failed", detail="; ".join(c["check"] for c in failed))
            point["output"] = o["pnl"]["usd_monthly"]["columns"][col][metric[0]]
            rows.append(point)
        crossings = []
        for a, b in zip(rows, rows[1:]):
            ya, yb = a["output"], b["output"]
            if ya is not None and yb is not None and (ya < 0 <= yb or yb < 0 <= ya) and ya != yb:
                crossings.append(a["input"] + (0 - ya) * (b["input"] - a["input"]) / (yb - ya))
        res = {"status": "ok", "input_path": input_path, "base_value": amount,
               "output_metric": output_metric, "unit": metric[1], "column": col, "points": rows,
               "zero_crossings": crossings, "source": src}
        if include_chart:
            res["chart"] = {"type": "line", "title": f"{output_metric} of {col} vs {input_path}",
                            "x": [p["input"] for p in rows], "y": [p["output"] for p in rows],
                            "markers": crossings}
        return res

    def compare_states(self, state_a_id, state_b_id, comparison_type="both", output_focus=None,
                       threshold_pct=0):
        d = self.store.diff(state_a_id, state_b_id, threshold_pct=threshold_pct,
                            include_outputs=comparison_type != "inputs")
        res = {"status": "ok", "a": {"id": state_a_id, "source": self._source(state_a_id)},
               "b": {"id": state_b_id, "source": self._source(state_b_id)}}
        if comparison_type in ("inputs", "both"):
            res["inputs"] = d["inputs"]
        if comparison_type in ("outputs", "both"):
            outs = d["outputs"]
            if output_focus:
                pat = _FOCUS[output_focus]
                outs = [o for o in outs if pat(o["figure"])]
            res["outputs"] = outs
            res["group_ebt"] = d["group_ebt"]
        res["summary"] = {"inputs_changed": len(d["inputs"]), "outputs_changed": len(res.get("outputs", []))}
        if comparison_type != "inputs":
            note_ = _sourcing_change(self.store.compute(state_a_id), self.store.compute(state_b_id))
            if note_:
                res["sourcing_change"] = note_
        return res

    def find_optimal_mix(self, **_):
        raise ModelError("tool_unavailable",
                         "the optimizer is not available yet: it ships at build step 8, and only after its four "
                         "verification cases pass (system prompt, Appendix D.2–D.3)")

    # ================================================================ Lifecycle

    def manage_baseline_refresh(self, action, source_baseline_id=None, pre_fill_this_month=False,
                                output_dir=None, source=None, file_path=None, payload=None,
                                month_label=None, overwrite_if_exists=False):
        if action == "generate_template":
            bases = self.store.list_states("baselines")
            if source_baseline_id is None:
                if bases:
                    source_baseline_id = sorted(bases, key=lambda b: b["month_label"])[-1]["id"]
                    base = self.store.get_state(source_baseline_id)
                else:                                   # first-ever use
                    base, source_baseline_id = schema.load_template(), None
            else:
                base = self.store.get_state(source_baseline_id)
            folder = output_dir or self.template_dir
            os.makedirs(folder, exist_ok=True)
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
            path = os.path.join(folder, f"refresh_template_from_{base['month_label']}_{stamp}.xlsx")
            refresh_template.generate(base, path, pre_fill_this_month=pre_fill_this_month,
                                      source_label=self._source(source_baseline_id) if source_baseline_id
                                      else "initial state")
            return {"status": "ok", "file_path": path, "source_baseline_id": source_baseline_id,
                    "sheets": list(refresh_template.SHEETS)}
        # commit
        if source is None:
            raise ModelError("missing_required_arg", "commit needs 'source' (xlsx | csv | payload)", field="source")
        base_id = source_baseline_id or sorted(self.store.list_states("baselines"),
                                               key=lambda b: b["month_label"])[-1]["id"]
        changes, meta = None, {}
        if source in ("xlsx", "csv"):
            if not file_path:
                raise ModelError("missing_required_arg", f"a {source} commit needs 'file_path'", field="file_path")
            if not os.path.exists(file_path):
                raise ModelError("missing_required_arg", f"no file at {file_path!r}", field="file_path")
            base = self.store.get_state(base_id)
            parsed = (refresh_template.parse_xlsx if source == "xlsx" else refresh_template.parse_csv)(file_path, base)
            payload, changes = parsed["payload"], parsed["changes"]
            month_label = month_label or parsed["month_label"]
            meta = {"author": parsed["author"], "notes": parsed["notes"]}
        elif payload is None:
            raise ModelError("missing_required_arg", "a payload commit needs 'payload' (a complete state)",
                             field="payload")
        res = self.store.refresh_baseline(payload, month_label, actor=self.mode,
                                          overwrite_if_exists=overwrite_if_exists)
        if changes is not None:
            res["entered_this_month"] = changes
            res["carried_forward_from"] = base_id
        res.update({k: v for k, v in meta.items() if v})
        return res

    def commit_state(self, action, month_label=None, overwrite_if_exists=False, name=None,
                     description=None, tags=None):
        return self.store.commit_state(action, actor=self.mode, month_label=month_label,
                                       overwrite_if_exists=overwrite_if_exists, name=name,
                                       description=description, tags=tags)


# --------------------------------------------------------------------------- #
# Helpers used by several tools
# --------------------------------------------------------------------------- #

def _div_pct(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b * 100


def _div_per_t(musd, kt):
    if musd is None or not kt:
        return None
    return musd * 1000 / kt


def _finished_sheet_name(company, product):
    return {("EZDK", "Rebar"): "EZDK Rebar", ("EFS", "Rebar"): "EFS Rebar", ("ESR", "Rebar"): "ESR Rebar",
            ("ERM", "Rebar"): "ERM Rolling", ("EZDK", "Wire Rod"): "EZDK Wire", ("EZDK", "HRC"): "EZDK Flat",
            ("EFS", "HRC"): "EFS Flat"}[(company, product)]


def _detail_input_rows(state, sheets: dict, stages, fx, currency):
    """Consumptions and unit prices of the detail sheets, one row per input, side by side."""
    rows, seen = [], {}
    k = fx if currency == "EGP" else 1.0
    for c, sheet in sheets.items():
        d = state["detail"][sheet]
        parts = [(st, d[st]) for st in stages if st in d] or [("rolling", d)]
        for st, block in parts:
            for path, v in schema.leaves(block).items():
                label = f"{st} · {path.replace('_', ' ')}"
                seen.setdefault(label, {})[c] = v
    for label, vals in seen.items():
        out = {}
        for c, v in vals.items():
            if isinstance(v, dict) and len(v) == 1:
                unit_k, x = next(iter(v.items()))
                out[c] = x / fx * k if unit_k == "le" else x * k
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                money = "price" in label or "prices" in label
                rolling = label.startswith("rolling")
                out[c] = (v / fx * k if rolling else v * k) if money else v
            else:
                out[c] = v
        kind = "price" if "price" in label else "consumption"
        rows.append(_row(label, out, "", kind))
    return rows


def _cascade_table(title, section, totals, cos, items, src, with_total, out):
    cols = [c for c in cos if c in section]
    rows = []
    for key, label in items:
        vals = {c: section[c].get(key) for c in cols if key in section[c]}
        if not vals:
            continue
        if with_total and key in totals:
            vals["Total"] = totals[key]
        kind = "pct" if key.endswith("_pct") else "ratio" if key == "mrmr" else "qty"
        rows.append(_row(label, vals, "kt", kind))
    foot = []
    if "ERM" in cols and "billet" in section.get("ERM", {}):
        s = out["sourcing"]
        foot.append(f"ERM buys its billets ({s['supplier']}); "
                    + ("they are produced inside the supplier's figures and not counted twice in the total."
                       if s["supplier"] != "market" else "market billets are not group production."))
    if "ERM" in cols and "iop" in section.get("ERM", {}):
        foot.append("ERM's DRI plant supplies EFS and ESR; its IOP = (EFS DRI + ESR DRI) × ERM MRMR.")
    return _table(title, cols + (["Total"] if with_total else []), rows, source=src, footnotes=foot)


def _flow_diagram(out, cos):
    """Nodes and edges (kt) from IOP to finished products, plus Mermaid text for display."""
    pr, nodes, edges = out["production"], [], []
    add = lambda nid, label, kt: nodes.append({"id": nid, "label": label, "kt": kt})
    edge = lambda a, b, kt: edges.append({"from": a, "to": b, "kt": kt})
    for plant, customers in (("EZDK", ("EZDK",)), ("ERM", ("EFS", "ESR"))):
        if not set(customers + (plant,)) & set(cos):
            continue
        dri_t = out["dri"][plant]["production_t"] / 1000
        add(f"IOP_{plant}", f"IOP → {plant} DRP", dri_t * out["dri"][plant]["mrmr"])
        add(f"DRI_{plant}", f"{plant} DRI", dri_t)
        edge(f"IOP_{plant}", f"DRI_{plant}", dri_t * out["dri"][plant]["mrmr"])
    lines = (("long", "EAF (long)", ("EZDK", "EFS", "ESR")), ("flat", "EAF (flat)", ("EZDK", "EFS")))
    for line, label, who in lines:
        for c in who:
            if c not in cos or c not in pr[line] or "solid_charge" not in pr[line][c]:
                continue
            x = pr[line][c]
            plant = "EZDK" if c == "EZDK" else "ERM"
            eaf = f"EAF_{line}_{c}"
            add(eaf, f"{c} {label}", x["solid_charge"])
            edge(f"DRI_{plant}", eaf, x["dri"])
            add(f"SCRAP_{line}_{c}", f"{c} scrap", x["imported_scrap"] + x["local_scrap"])
            edge(f"SCRAP_{line}_{c}", eaf, x["imported_scrap"] + x["local_scrap"])
            cast = f"CAST_{line}_{c}"
            add(cast, f"{c} {'billets' if line == 'long' else 'slabs'}",
                x.get("billet", x["molten_steel"]) if line == "long" else x["molten_steel"])
            edge(eaf, cast, x["molten_steel"])
            for prod, key in ((("Rebar", "rebar"), ("Wire rod", "wire_rod")) if line == "long" else (("HRC", "hrc"),)):
                if x.get(key):
                    pid = f"FIN_{c}_{key}"
                    add(pid, f"{c} {prod}", x[key])
                    edge(cast, pid, x[key])
    if "ERM" in cos:
        s = out["sourcing"]
        add("FIN_ERM_rebar", "ERM Rebar", pr["long"]["ERM"]["rebar"])
        src = f"CAST_long_{s['supplier']}" if s["supplier"] != "market" else "MARKET"
        if s["supplier"] == "market" or src not in {n["id"] for n in nodes}:
            add(src, "Market billets" if s["supplier"] == "market" else f"{s['supplier']} billets",
                pr["long"]["ERM"]["billet"])
        edge(src, "FIN_ERM_rebar", pr["long"]["ERM"]["billet"])
    seen, uniq = set(), []
    for n in nodes:
        if n["id"] not in seen:
            seen.add(n["id"])
            uniq.append(n)
    mermaid = ["flowchart LR"] + [f'  {n["id"]}["{n["label"]}<br/>{n["kt"]:,.1f} kt"]' for n in uniq] + \
              [f'  {e["from"]} -- "{e["kt"]:,.1f} kt" --> {e["to"]}' for e in edges]
    return {"nodes": uniq, "edges": edges, "mermaid": "\n".join(mermaid)}


def _variation_points(variation: dict, base: float) -> list:
    t = variation.get("type")
    try:
        if t == "range":
            a, b, n = float(variation["from"]), float(variation["to"]), int(variation["steps"])
            if n < 2:
                raise ValueError
            return [a + (b - a) * i / (n - 1) for i in range(n)]
        if t == "delta_pct":
            return [base * (1 + float(v) / 100) for v in variation["values"]]
        if t == "delta_abs":
            return [base + float(v) for v in variation["values"]]
    except (KeyError, TypeError, ValueError):
        pass
    raise ModelError("schema_validation_error", "variation must be {type: range, from, to, steps≥2} | "
                     "{type: delta_pct, values} | {type: delta_abs, values}", field="variation")


_FOCUS = {
    "pnl": lambda f: f.startswith("Group") or "EBT" in f or " CM " in f or f.endswith(("CM M$", "revenue M$")),
    "cost_sheet": lambda f: "VC $/t" in f or "price $/t" in f,
    "sales": lambda f: "qty kt" in f or "revenue" in f,
    "production": lambda f: f.startswith(("Production", "Capacity")),
    "fixed_cost": lambda f: f.startswith("Fixed"),
}

# engine view → reports that show it (for update_input's "affected_reports")
_VIEW_REPORTS = {"dri": ["get_cost_sheet(dri)"], "billet": ["get_cost_sheet(billet)", "get_tradeoff_matrix"],
                 "rebar": ["get_cost_sheet(finished_product, Rebar)"], "wire": ["get_cost_sheet(finished_product, Wire Rod)"],
                 "flat": ["get_cost_sheet(finished_product, HRC)"], "pnl": ["get_pnl"],
                 "consolidated": ["get_pnl(consolidated)"], "market_share": ["get_sales_report(market_share)"],
                 "production": ["get_production_report"], "capacity": ["get_production_report(summary)"],
                 "fixed_cost": ["get_fixed_cost_report"]}


def _sourcing_change(before: dict, after: dict):
    """ERM's billet supplier differs between two states — worth saying out loud, because the
    billet volume (and the DRI, scrap and IOP behind it) moves from one company to another."""
    a, b = before["sourcing"], after["sourcing"]
    if a["supplier"] == b["supplier"]:
        return None
    return {"from": a["supplier"], "to": b["supplier"], "price_before": a["price_usd_t"],
            "price_after": b["price_usd_t"], "billets_kt": b["billets_t"] / 1000,
            "message": f"ERM's cheapest billet source changed from {a['supplier']} to {b['supplier']} "
                       f"({a['price_usd_t']:,.2f} → {b['price_usd_t']:,.2f} $/t); "
                       f"{b['billets_t'] / 1000:,.1f} kt of billet production moves with it."}


def _affected_reports(before: dict, after: dict) -> list:
    def same(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
        if isinstance(a, float) and isinstance(b, float):
            return a == b or (math.isnan(a) and math.isnan(b))
        return a == b
    out = []
    for view, reports in _VIEW_REPORTS.items():
        if not same(before.get(view), after.get(view)):
            out += reports
    return out
