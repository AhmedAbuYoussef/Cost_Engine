"""Step 6 — the web UI.  Done-criterion (Appendix C): demo-grade UX without needing a technical
explanation.  These tests cover what can be checked mechanically: numbers at display precision,
charts and comparisons drawn from tool results, the conversation shown as the user saw it, the
resume question on reopen, the currency toggle, the end of a session, and that the page serves."""

import json
import re
import socket

import gradio as gr
import pytest

import app as web
import state_manager as sm
import ui_render as ui
from llm_sim import SimulatedClaude
from tools import ToolBox


# ---- number formatting ----------------------------------------------------------------- #

@pytest.mark.parametrize("v, kind, unit, out", [
    (-14.0234, "money", "M$", "(14.02)"), (1234.5, "money", "M$", "1,234.50"), (-0.001, "money", "M$", "0.00"),
    (438.98, "per_t", "$/t", "438.98"), (-7112.4, "per_t", "LE/t", "(7,112)"), (104.63, "pct", "%", "105%"),
    (7.12, "pct", "%", "7.1%"), (261.57, "qty", "kt", "261.6"), (1.0411, "ratio", "", "1.0411"),
    (None, "money", "", ""), ("EZDK", "text", "", "EZDK"), (float("nan"), "money", "", "n/a"),
])
def test_fmt(v, kind, unit, out):
    assert ui.fmt(v, kind, unit) == out


def test_delta_direction():
    assert ui.delta_direction("Group EBT M$") == 1 and ui.delta_direction("EZDK CM M$") == 1
    assert ui.delta_direction("Billet EZDK cost $/t") == -1
    assert ui.delta_direction("Production EZDK dri kt") == 0 and ui.delta_direction("Capacity DRI EZDK %") == 0


# ---- charts and tables from real tool results --------------------------------------------- #

@pytest.fixture
def box(tmp_path):
    store = sm.StateStore(str(tmp_path / "ui.db"))
    yield ToolBox(store, template_dir=str(tmp_path))
    store.close()


def test_every_chart_spec_renders(box):
    calls = [("get_cost_sheet", {"stage": "dri", "company": "all"}),
             ("get_cost_sheet", {"stage": "billet", "company": "all"}),
             ("get_cost_sheet", {"stage": "finished_product", "product": "HRC", "company": "all"}),
             ("get_cost_sheet", {"stage": "finished_product", "product": "Rebar", "company": "all"}),
             ("get_pnl", {"scope": "consolidated"}), ("get_pnl", {"scope": "standalone", "company": "EZDK"}),
             ("get_sales_report", {"company": "all", "product": "all"}),
             ("get_fixed_cost_report", {"company": "all", "currency": "EGP"}),
             ("run_sensitivity", {"input_path": "dri.ERM.iop_landed_usd_t", "output_metric": "ebt", "company": "ERM",
                                  "variation": {"type": "delta_pct", "values": [-10, 0, 10]}})]
    for name, args in calls:
        r = box.call(name, {**args, "include_chart": True})
        assert r["status"] == "ok", (name, r)
        spec = r["table"]["chart"] if "table" in r else r["chart"]
        assert spec["unit"], name                              # every chart names its unit
        arts = ui.artifacts(name, r)
        assert [a["kind"] for a in arts] == ["chart"], name
        svg = arts[0]["html"]
        assert svg.count("<svg") == 1 and "<title>" in svg and "Source: working state" in svg
        assert html_is_balanced(svg)


def html_is_balanced(s):
    for tag in ("svg", "div", "g", "title", "text", "path", "style"):
        opened = len(re.findall(rf"<{tag}(?:\s[^>]*)?(?<!/)>", s))
        if opened != s.count(f"</{tag}>"):
            return False
    return True


def test_stacked_bar_totals_and_legend(box):
    t = box.call("get_cost_sheet", {"stage": "dri", "company": "all", "include_chart": True})["table"]
    svg = ui.chart_svg(t["chart"], t["source"])
    for i, co in enumerate(t["chart"]["categories"]):
        total = sum(s["values"][i] for s in t["chart"]["series"])
        assert f">{ui.fmt(total, 'per_t', '$/t')}</text>" in svg              # total label on top
    assert svg.count('class="viz-legend"') == 1                                   # ≥ 2 series → legend
    assert "--s1:#2a78d6" in svg and "--s1:#3987e5" in svg                        # light and dark steps


def test_negative_bars_and_single_series(box):
    t = box.call("get_pnl", {"scope": "consolidated", "include_chart": True})["table"]
    svg = ui.chart_svg(t["chart"], t["source"])
    ebt = t["chart"]["series"][0]["values"][-1]
    assert ebt < 0 and f">{ui.fmt(ebt, 'money', 'M$')}</text>" in svg and "(" in ui.fmt(ebt, "money")
    assert 'class="viz-legend"' not in svg                                        # one series: no legend


def test_line_chart_marks_zero_crossings():
    spec = {"type": "line", "title": "EBT vs price", "x": [1, 2, 3], "y": [-1, 0.5, 2], "markers": [1.67],
            "unit": "M$", "x_label": "price"}
    svg = ui.chart_svg(spec)
    assert "zero at 1.67" in svg and svg.count('r="4.5"') == 3
    assert "No computable points" in ui.chart_svg({**spec, "y": [None, None, None]})


def test_titles_and_labels_are_escaped():
    spec = {"type": "bar", "title": "<script>x</script>", "categories": ["A&B"], "unit": "M$", "kind": "money",
            "series": [{"name": "EBT", "values": [1.0]}]}
    svg = ui.chart_svg(spec)
    assert "<script>" not in svg and "&lt;script&gt;" in svg and "A&amp;B" in svg


def test_compare_html_colours_deltas(box):
    box.call("update_input", {"path": "sales.EZDK.Rebar.local_kt", "value": 120})
    r = box.call("compare_states", {"state_a_id": "baseline_2026-04", "state_b_id": "working"})
    h = ui.compare_html(r)
    row = lambda fig: re.search(rf"<tr><td>{re.escape(fig)}</td>.*?</tr>", h).group(0)
    assert 'class="up-good"' in row("Group EBT M$") and "▲" in row("Group EBT M$")
    assert "(14.02)" in row("Group EBT M$")                                     # accounting negatives
    assert 'class=""' in row("Production EZDK dri kt")                           # volumes are not judged
    assert "<code>sales.EZDK.Rebar.local_kt</code>" in h
    assert "better" in row("Group EBT M$")                                       # not colour alone
    assert ui.artifacts("compare_states", r)[0]["kind"] == "compare"


def test_tradeoff_heatmap_marks_the_cheapest_source(box):
    r = box.call("get_tradeoff_matrix", {"buyer": "all"})
    arts = ui.artifacts("get_tradeoff_matrix", r)
    assert [a["kind"] for a in arts] == ["heatmap"]
    h = arts[0]["html"]
    cheapest = next(x for x in r["table"]["rows"] if x["label"] == "Cheapest source")["values"]
    assert h.count('">✓ ') == len(cheapest)                                        # one cheapest per buyer
    assert "Source: working state" in h


def test_flow_diagram_is_drawn_from_the_tool_result(box):
    r = box.call("get_production_report", {"company": "all", "view": "flow_diagram"})
    arts = ui.artifacts("get_production_report", r)
    assert [a["kind"] for a in arts] == ["flow"]
    h = arts[0]["html"]
    shown = [n for n in r["flow_diagram"]["nodes"] if not n["id"].startswith("SCRAP")]
    for n in shown:
        assert f">{n['label']}</text>" in h.replace("→", "→")
    assert "incl. " in h and "scrap" in h                                          # scrap shown on the furnace
    assert h.count("<rect") == 2 * len(shown)


def test_errors_produce_no_artifacts(box):
    r = box.call("get_pnl", {"scope": "standalone", "company": "XYZ"})
    assert r["status"] == "error" and ui.artifacts("get_pnl", r) == []


# ---- the conversation as the user saw it --------------------------------------------------- #

def test_conversation_entries(box):
    from llm_router import Router
    router = Router(box, SimulatedClaude(), use_fallbacks=False)
    router.ask("Show the consolidated P&L with a chart")
    router.ask("Show the EZDK P&L for XYZ")                    # no tool needed: capabilities answer
    router.ask("set sales.NOPE.Rebar.local_kt to 5")            # a tool error
    e = ui.conversation(router.messages)
    assert [x["role"] for x in e] == ["user", "tool", "assistant", "user", "tool", "assistant",
                                      "user", "tool", "assistant"]
    assert not any(x["role"] == "user" and x["text"].startswith("[") for x in e)   # runtime header hidden
    assert e[1]["name"] == "get_pnl" and e[1]["status"] == "ok" and e[1]["input"]["include_chart"] is True
    assert [a["kind"] for a in e[2]["artifacts"]] == ["chart"]
    assert e[7]["status"] == "error" and e[7]["error_code"] and e[8]["artifacts"] == []


# ---- the app ------------------------------------------------------------------------------- #

def make_app(db):
    return web.App(sm.StateStore(db), SimulatedClaude(), simulated=True, use_fallbacks=False)


def contents(chat):
    out = []
    for m in chat:
        c = m.content
        out.append(c.value if isinstance(c, gr.HTML) else c)
    return out


def test_first_visit_and_a_question(tmp_path):
    a = make_app(str(tmp_path / "a.db"))
    chat, status, currency, scen = a.on_load()
    assert chat == [] and currency == "USD" and scen == []
    assert "Simulated assistant" in status and "same as the baseline" in status
    chat, status, currency, scen = a.ask("Show the DRI cost for all companies with a chart")
    roles = [m.role for m in chat]
    assert roles == ["user", "assistant", "assistant", "assistant"]
    assert chat[1].metadata["title"] == "🔧 Cost sheet"                            # tool, collapsible
    assert "DRI" in chat[2].content and "Source: working state" in chat[2].content
    assert isinstance(chat[3].content, gr.HTML) and "<svg" in chat[3].content.value


def test_reopen_offers_resume_with_buttons_and_restores_everything(tmp_path):
    db = str(tmp_path / "b.db")
    a = make_app(db)
    a.on_load()
    a.ask("set sales.EZDK.Rebar.local_kt to 120")
    a.on_currency("EGP")
    a.store.close()

    b = make_app(db)                                           # browser closed and reopened
    chat, status, currency, _ = b.on_load()
    assert currency == "EGP" and "1 unsaved change" in status and "sales.EZDK.Rebar.local_kt" in status
    assert chat[0].role == "user" and "set sales.EZDK.Rebar.local_kt to 120" == chat[0].content
    opener = chat[-1]
    assert opener.content.startswith("You have an in-progress session") and \
        [o["value"] for o in opener.options] == web.RESUME_OPTIONS
    chat, *_ = b.ask(web.RESUME_OPTIONS[1])                    # one click: save it as a scenario
    assert not any(getattr(m, "options", None) for m in chat)  # the question is answered
    assert b.scenarios()[0][0] == "In-progress session"
    b.store.close()


def test_session_end_keeps_the_last_turn_visible(tmp_path):
    a = make_app(str(tmp_path / "c.db"))
    a.on_load()
    a.ask("set sales.EZDK.Rebar.local_kt to 120")
    chat, status, currency, _ = a.ask("Discard it")
    assert "same as the baseline" in status and currency == "USD"
    assert chat[-1].metadata["title"] == "ℹ Session closed"
    assert any("set sales.EZDK.Rebar.local_kt to 120" == c for c in contents(chat))
    chat, *_ = a.ask("What is the consolidated EBT this month?")   # a fresh conversation below it
    assert sum(1 for m in chat if m.role == "user") == 3
    assert [h["status"] for h in a.session.history()] == ["active", "closed"]


def test_respond_reads_the_last_user_message_in_any_shape(tmp_path):
    a = make_app(str(tmp_path / "d.db"))
    a.on_load()
    box_value, chat = a.on_user_message("  Show the billet trade-off matrix ", [])
    assert box_value == "" and chat[-1].metadata["status"] == "pending"
    as_dicts = [{"role": m.role, "content": m.content} for m in chat]
    as_dicts[0]["content"] = [{"type": "text", "text": "Show the billet trade-off matrix"}]
    chat, *_ = a.respond(as_dicts)
    assert any(isinstance(m.content, gr.HTML) and "✓" in m.content.value for m in chat)
    assert a.on_user_message("   ", [])[1] == []


def test_a_failed_call_is_reported_and_nothing_is_lost(tmp_path):
    a = make_app(str(tmp_path / "e.db"))
    a.on_load()
    a.ask("set sales.EZDK.Rebar.local_kt to 120")

    def boom(**_):
        raise ConnectionError("network down")
    a.session.client.messages.create = boom
    a.session.router.client = a.session.client
    chat, status, *_ = a.ask("Show the consolidated P&L")
    assert "couldn't reach the assistant" in chat[-1].content and "network down" in chat[-1].content
    assert "1 unsaved change" in status and a.store.read("sales.EZDK.Rebar.local_kt") == 120


def test_page_builds_and_serves(tmp_path):
    a = make_app(str(tmp_path / "f.db"))
    demo = web.build(a)
    assert isinstance(demo, gr.Blocks)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    demo.queue().launch(server_name="127.0.0.1", server_port=port, prevent_thread_lock=True, quiet=True)
    try:
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        page = opener.open(f"http://127.0.0.1:{port}/", timeout=20).read().decode()
        assert web.TITLE in page
        cfg = json.loads(opener.open(f"http://127.0.0.1:{port}/config", timeout=20).read())
        assert any(c.get("type") == "chatbot" for c in cfg["components"])
    finally:
        demo.close()
