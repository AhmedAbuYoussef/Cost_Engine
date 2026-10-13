"""
A simulated Claude for running and testing the router without an API key.

``SimulatedClaude`` exposes the same surface the router uses —
``client.messages.create(**request)`` and ``client.beta.messages.create(**request)`` — and
returns responses shaped like the API's (``content`` blocks, ``stop_reason``, ``usage``).

It is deliberately simple and deterministic: keyword rules map a question to one tool
call, and the answer is written only from that tool's result (tables rendered as
markdown).  It understands far less than Claude; it exists so the whole loop — request
building, tool execution, error handling, history — can be exercised end to end.
Every request it receives is kept in ``requests`` for inspection.
"""

from __future__ import annotations

import itertools
import json
import re
from types import SimpleNamespace

from ui_render import fmt

COMPANIES = ("EZDK", "EFS", "ERM", "ESR")
_ids = itertools.count(1)


def _block(**kw):
    return SimpleNamespace(**kw)


def _response(content, stop_reason):
    return SimpleNamespace(id=f"msg_sim_{next(_ids)}", type="message", role="assistant",
                           model="simulated", content=content, stop_reason=stop_reason,
                           stop_details=None,
                           usage=SimpleNamespace(input_tokens=0, output_tokens=0,
                                                 cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _g(block, key):
    return block.get(key) if isinstance(block, dict) else getattr(block, key, None)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(getattr(b, "text", None) or (b.get("text", "") if isinstance(b, dict) else "")
                    for b in content if (getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)) == "text")


# --------------------------------------------------------------------------- #
# Intent → tool call
# --------------------------------------------------------------------------- #

def _company(q):
    for c in COMPANIES:
        if re.search(rf"\b{c.lower()}\b", q):
            return c
    return None


def _product(q):
    if "wire" in q:
        return "Wire Rod"
    if "hrc" in q or "flat" in q or "coil" in q:
        return "HRC"
    if "rebar" in q:
        return "Rebar"
    return None


def _currency(q):
    """Only a currency the user named (otherwise the session's preference applies)."""
    if re.search(r"\b(egp|le|pounds?)\b", q):
        return {"currency": "EGP"}
    if re.search(r"\b(usd|dollars?)\b", q):
        return {"currency": "USD"}
    return {}


_CHART_TOOLS = {"get_cost_sheet", "get_pnl", "get_sales_report", "get_fixed_cost_report", "run_sensitivity"}


def plan(question: str):
    """(tool name, arguments) for a question, or None when the intent is unclear."""
    p = _plan(question)
    if p and p[0] in _CHART_TOOLS and re.search(r"\b(chart|graph|plot|visual)", question, re.I):
        p[1]["include_chart"] = True
    return p


def _plan(question: str):
    q = question.lower()
    co, prod, cur = _company(q), _product(q), _currency(q)
    if re.search(r"\bapply (?:the |this )?plan\b", q):
        return "apply_plan", {}
    if re.search(r"\b(optimi[sz]e|optimal|best mix)", q):
        args = {"objective": "company_cm", "company": co} if co and "group" not in q else {"objective": "group_cm"}
        m = re.search(r"hrc market (?:is |of |at )?([\d.]+)", q)
        if m:
            args["run_constraints"] = {"local_market_ceilings": {"HRC": float(m.group(1))}}
        return "find_optimal_mix", args
    m = re.search(r"\bset\s+([\w .]+?)\s+to\s+(-?[\d.]+)", question, re.I)
    if m:
        return "update_input", {"path": m.group(1).strip(), "value": float(m.group(2))}
    m = re.search(r"save (?:this |it )?as (?:a )?scenario(?:\s+(?:named|called))?(?:\s+['\"]?([^'\"]+)['\"]?)?",
                  question, re.I)
    if m:
        return "commit_state", {"action": "save_as_scenario", "name": (m.group(1) or "In-progress session").strip()}
    m = re.search(r"sensitivity of ([\w .]+?) on (ebt|cm|breakeven_qty|cm_per_ton)", q)
    if m:
        return "run_sensitivity", {"input_path": _restore_case(question, m.group(1)),
                                   "variation": {"type": "delta_pct", "values": [-10, -5, 0, 5, 10]},
                                   "output_metric": m.group(2), "company": co or "EZDK",
                                   **({"product": prod} if prod else {})}
    if re.search(r"\bdiscard\b", q):
        return "commit_state", {"action": "discard"}
    if re.search(r"\b(undo|revert|go back)\b", q):
        return "undo_last_change", {}
    if "scenario" in q and ("list" in q or "saved" in q or "which" in q):
        return "list_states", {"type": "scenarios"}
    if "compare" in q or "what changed" in q:
        return "compare_states", {"state_a_id": _baseline_id(q), "state_b_id": "working"}
    if "trade-off" in q or "tradeoff" in q or "sourcing" in q or "billet source" in q:
        return "get_tradeoff_matrix", {"buyer": co or "all"}
    if "market share" in q:
        args = {"company": "all", "product": prod or "all", "view": "market_share"}
        m = re.search(r"hrc market (?:is |of )?([\d.]+)", q)
        if m:
            args["hrc_total_local_market_kt"] = float(m.group(1))
        return "get_sales_report", args
    if "fixed cost" in q:
        return "get_fixed_cost_report", {"company": co or "all", **cur}
    if any(w in q for w in ("production", "capacity", "how much dri", "how much iop", "flow")):
        return "get_production_report", {"company": co or "all",
                                         "view": "flow_diagram" if "flow" in q else "summary"}
    if any(w in q for w in ("p&l", "pnl", "ebt", "profit", "contribution margin", "break-even", "breakeven")):
        if co and "consolidated" not in q and "group" not in q:
            return "get_pnl", {"scope": "standalone", "company": co, **cur}
        return "get_pnl", {"scope": "consolidated", **cur}
    if "cost" in q:
        stage = "dri" if "dri" in q else "billet" if "billet" in q else "finished_product" if prod else None
        if stage:
            args = {"stage": stage, "company": co or "all", **cur,
                    "view": "detailed" if "detail" in q else "conversion_summary"}
            if stage == "finished_product":
                args["product"] = prod
            return "get_cost_sheet", args
    if "sales" in q or "price" in q:
        return "get_sales_report", {"company": co or "all", "product": prod or "all",
                                    "view": "prices_only" if "price" in q else "full", **cur}
    return None


def _baseline_id(q):
    m = re.search(r"(\d{4}-\d{2})", q)
    return f"baseline_{m.group(1)}" if m else "baseline_2026-04"


def _restore_case(original: str, lowered: str) -> str:
    i = original.lower().find(lowered)
    return original[i:i + len(lowered)] if i >= 0 else lowered


# --------------------------------------------------------------------------- #
# Tool result → answer
# --------------------------------------------------------------------------- #

def _fmt(v, kind, unit):
    return fmt(v, kind, unit)


def render_table(t: dict) -> str:
    cols = t["columns"]
    out = [f"**{t['title']}**" + (f" ({t['currency']})" if t.get("currency") else ""), "",
           "| Item | Unit | " + " | ".join(cols) + " |", "|---|---|" + "---:|" * len(cols)]
    for r in t["rows"]:
        out.append(f"| {r['label']} | {r['unit']} | " +
                   " | ".join(_fmt(r["values"].get(c), r["kind"], r["unit"]) for c in cols) + " |")
    out += [""] + [f"*{f}*" for f in t.get("footnotes", [])] + [f"_{t['source']}_"]
    return "\n".join(out)


def answer(tool: str, result: dict) -> str:
    if result.get("status") == "error":
        return f"I couldn't do that: {result['error_message']}"
    if result.get("status") == "needs_input":
        return result["message"] + " What figure should I use?"
    if "table" in result:
        return render_table(result["table"])
    if "tables" in result:
        parts = [render_table(t) for t in result["tables"]]
        if result.get("flow_diagram"):
            parts.append("The production flow diagram is drawn below.")
        for w in result.get("warnings", []):
            parts.append(f"⚠ {w['detail']}")
        return "\n\n".join(parts)
    if tool == "update_input":
        lines = [f"Updated in your working session: `{c['path']}` {c['old']} → {c['new']}." for c in result["changes"]]
        for i in result.get("impact", [])[:5]:
            if i["delta"] is not None:
                lines.append(f"- {i['figure']}: {fmt(i['a'])} → {fmt(i['b'])} ({i['delta']:+,.2f})")
        if result.get("sourcing_change"):
            lines.append(f"⚠ {result['sourcing_change']['message']}")
        for w in result.get("warnings", []):
            lines.append(f"⚠ {w['detail']}")
        lines.append("Changes become permanent only if you promote them at end of session or refresh the baseline.")
        return "\n".join(lines) if result["changes"] else result.get("message", "Nothing changed.")
    if tool == "undo_last_change":
        lines = [f"Reverted `{r['path']}` to {r['restored']}." for r in result["reverted"]]
        for i in result.get("impact", [])[:3]:
            if i["delta"] is not None:
                lines.append(f"- {i['figure']}: {fmt(i['a'])} → {fmt(i['b'])} ({i['delta']:+,.2f})")
        lines.append(f"{result['remaining_changes']} earlier change(s) can still be undone.")
        return "\n".join(lines)
    if tool == "commit_state" and "scenario_id" not in result:
        return (f"Done. The working session now starts again from {result.get('base_baseline_id') or 'the baseline'}; "
                "this conversation is closed.")
    if tool == "commit_state":
        return f"Saved as '{result.get('name')}' (id: {result.get('scenario_id')}). Your working session is unchanged."
    if tool == "list_states":
        names = [f"{s['name']} ({s['id']})" for s in result["states"]]
        return "Saved scenarios: " + (", ".join(names) if names else "none.")
    if tool == "compare_states":
        lines = [f"Compared {result['a']['source']} with {result['b']['source']}: "
                 f"{result['summary']['inputs_changed']} inputs changed."]
        for d in result.get("inputs", [])[:10]:
            lines.append(f"- `{d['path']}`: {d['a']} → {d['b']}")
        if "group_ebt" in result:
            g = result["group_ebt"]
            lines.append(f"Group EBT: {fmt(g['a'])} → {fmt(g['b'])} M$ ({g['delta']:+,.2f}).")
        if result.get("sourcing_change"):
            lines.append(f"⚠ {result['sourcing_change']['message']}")
        return "\n".join(lines)
    if tool == "find_optimal_mix":
        cm = result["cm"]
        lines = ["**What was optimised**", ""] + [f"> {x}" for x in result["formulation"].splitlines()] + [
            "", f"**Contribution margin:** {fmt(cm['current'])} → {fmt(cm['optimal'])} M$ "
                f"({cm['delta']:+,.2f} M$ per month).",
            "Self-checks passed: engine cross-check, integrity and run constraints, ±5% perturbation.",
            "The plan, CM by company and the binding constraints (with shadow prices) are shown below.",
            "", "Do you want to apply this plan to your working state, save it as a scenario, or neither?"]
        return "\n".join(lines)
    if tool == "run_sensitivity":
        lines = [f"| {result['input_path']} | {result['output_metric']} ({result['unit']}) | status |", "|---:|---:|---|"]
        for p in result["points"]:
            out = "" if p["output"] is None else fmt(p["output"])
            lines.append(f"| {p['input']:,.2f} | {out} | {p['status']} |")
        if result["zero_crossings"]:
            lines.append("\nCrosses zero at " + ", ".join(f"{x:,.2f}" for x in result["zero_crossings"]) + ".")
        return "\n".join(lines)
    return "```json\n" + json.dumps(result, indent=1)[:3000] + "\n```"


CAPABILITIES = ("I can update inputs, show cost sheets, P&Ls, sales and market share, fixed costs, "
                "production requirements and the billet trade-off matrix, run sensitivities, find the "
                "optimal mix, compare states, and save, promote or discard your session. "
                "What would you like to do?")


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #

def _last_plan(messages):
    """The ``changes`` of the latest successful find_optimal_mix result in the conversation."""
    names = {}
    for m in messages:
        for b in (m["content"] if isinstance(m["content"], list) else []):
            if _g(b, "type") == "tool_use":
                names[_g(b, "id")] = _g(b, "name")
    for m in reversed(messages):
        for b in (m["content"] if isinstance(m["content"], list) else []):
            if _g(b, "type") == "tool_result" and names.get(_g(b, "tool_use_id")) == "find_optimal_mix":
                r = json.loads(_g(b, "content"))
                if r.get("status") == "ok":
                    return r["changes"]
    return None


class SimulatedClaude:
    def __init__(self):
        self.requests: list = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        last = request["messages"][-1]
        content = last["content"]
        results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] \
            if isinstance(content, list) else []
        if results:
            prev = request["messages"][-2]["content"]
            names = {_g(b, "id"): _g(b, "name") for b in prev if _g(b, "type") == "tool_use"}
            text = "\n\n".join(answer(names.get(r["tool_use_id"]), json.loads(r["content"])) for r in results)
            return _response([_block(type="text", text=text)], "end_turn")
        p = plan(_text([b for b in content if not str(_g(b, "text") or "").startswith("[")]))
        if p and p[0] == "apply_plan":
            changes = _last_plan(request["messages"])
            if changes is None:
                return _response([_block(type="text", text="There is no optimizer plan to apply yet.")], "end_turn")
            p = ("update_input", {"changes": changes})
        if p is None:
            return _response([_block(type="text", text=CAPABILITIES)], "end_turn")
        name, args = p
        if name not in {t["name"] for t in request["tools"]}:
            return _response([_block(type="text", text=f"That needs {name}, which isn't available to me here.")],
                             "end_turn")
        return _response([_block(type="text", text="Let me get that from the model."),
                          _block(type="tool_use", id=f"toolu_sim_{next(_ids)}", name=name, input=args)], "tool_use")
