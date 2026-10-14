"""Step 7 — the Fantomaas entry point.  Done-criterion (Appendix C): structured JSON in, structured
JSON out, permission_denied returned correctly on refused operations (model B)."""

import copy
import io
import json
import sys
from types import SimpleNamespace as NS

import pytest
from anthropic.types.beta import BetaTextBlock, BetaToolUseBlock
from fastapi.testclient import TestClient

import orchestrator_api as oa
import state_manager as sm
from llm_sim import SimulatedClaude

ENVELOPE_KEYS = {"status", "tool_called", "result", "error", "integrity_checks", "warnings"}


@pytest.fixture
def store(tmp_path):
    s = sm.StateStore(str(tmp_path / "o.db"))
    yield s
    s.close()


@pytest.fixture
def api(store, tmp_path):
    return oa.OrchestratorAPI(store, SimulatedClaude(), template_dir=str(tmp_path / "t"), use_fallbacks=False)


def baselines(store):
    return sorted(b["id"] for b in store.list_states("baselines"))


# ---- permission model B ----------------------------------------------------------------------- #

@pytest.mark.parametrize("tool, args", [
    ("commit_state", {"action": "promote_to_baseline", "month_label": "2026-05"}),
    ("commit_state", {"action": "promote_to_baseline", "month_label": "2026-04", "overwrite_if_exists": True}),
    ("manage_baseline_refresh", {"action": "commit", "source": "payload", "payload": {}, "month_label": "2026-05"}),
    ("manage_baseline_refresh", {"action": "generate_template"}),
    ("manage_baseline_refresh", {}),
])
def test_baseline_commits_are_refused(api, store, tool, args):
    api.call_tool("update_input", {"path": "sales.EZDK.Rebar.local_kt", "value": 120})
    before = (baselines(store), store.get_state("baseline_2026-04"))
    r = api.handle({"tool": tool, "args": args})
    assert set(r) == ENVELOPE_KEYS
    assert r["status"] == "error" and r["error"]["error_code"] == "permission_denied"
    assert r["tool_called"] == tool and r["result"] is None and r["integrity_checks"] == "not_run"
    assert "Rule 2" in r["error"]["error_message"]
    assert (baselines(store), store.get_state("baseline_2026-04")) == before         # nothing written
    assert store.read("sales.EZDK.Rebar.local_kt") == 120                             # working state intact


def test_the_inner_layers_refuse_too(api, store):
    """Defence in depth: bypassing the API's own check still meets the ToolBox and the StateStore."""
    r = api.box.call("commit_state", {"action": "promote_to_baseline", "month_label": "2026-05"})
    assert r["error_code"] == "permission_denied"
    assert api.box.call("manage_baseline_refresh", {"action": "generate_template"})["error_code"] == "permission_denied"
    with pytest.raises(sm.ModelError) as e:
        store.commit_state("promote_to_baseline", actor="orchestrator", month_label="2026-05")
    assert e.value.code == "permission_denied"
    assert baselines(store) == ["baseline_2026-04"]


def test_allowed_operations(api, store):
    r = api.handle({"tool": "update_input", "args": {"path": "sales.EZDK.Rebar.local_kt", "value": 120}})
    assert r["status"] == "ok" and r["integrity_checks"] == "passed" and r["error"] is None
    assert r["result"]["changes"] == [{"path": "sales.EZDK.Rebar.local_kt", "old": 100.0, "new": 120}]
    assert any(w["check"] == "capacity_within_limits" for w in r["warnings"])         # capacity: warn, not stop
    r = api.handle({"tool": "commit_state", "args": {"action": "save_as_scenario", "name": "fantomaas push"}})
    assert r["status"] == "ok" and r["result"]["scenario_id"]
    sid = r["result"]["scenario_id"]
    r = api.handle({"tool": "compare_states", "args": {"state_a_id": "baseline_2026-04", "state_b_id": sid}})
    assert r["status"] == "ok" and r["result"]["group_ebt"]["delta"] > 0
    r = api.handle({"tool": "undo_last_change", "args": {}})
    assert r["status"] == "ok" and store.read("sales.EZDK.Rebar.local_kt") == 100
    api.handle({"tool": "update_input", "args": {"path": "sales.EZDK.Rebar.local_kt", "value": 90}})
    r = api.handle({"tool": "commit_state", "args": {"action": "discard"}})
    assert r["status"] == "ok" and store.session_summary()["status"] != "in_progress"
    assert baselines(store) == ["baseline_2026-04"]


def test_every_read_and_analysis_tool_answers(api):
    calls = [("read_state", {"path": "sales.EZDK.Rebar"}), ("list_states", {"type": "all"}),
             ("get_cost_sheet", {"stage": "dri", "company": "all"}), ("get_pnl", {"scope": "consolidated"}),
             ("get_sales_report", {"company": "all", "product": "all"}),
             ("get_fixed_cost_report", {"company": "all"}),
             ("get_production_report", {"company": "all", "view": "flow_diagram"}),
             ("get_tradeoff_matrix", {"buyer": "all"}),
             ("run_sensitivity", {"input_path": "dri.ERM.iop_landed_usd_t", "output_metric": "ebt",
                                  "company": "ERM", "variation": {"type": "delta_pct", "values": [-5, 0, 5]}}),
             ("compare_states", {"state_a_id": "baseline_2026-04", "state_b_id": "working"})]
    names = {t["name"] for t in api.describe()["tools"]}
    for tool, args in calls:
        assert tool in names
        r = api.call_tool(tool, args)
        assert r["status"] == "ok", (tool, r["error"])
        json.dumps(r, allow_nan=False)                                                 # strict JSON


def test_describe_lists_what_is_refused(api):
    d = api.describe()
    names = {t["name"] for t in d["tools"]}
    assert "manage_baseline_refresh" not in names and "find_optimal_mix" in names
    assert {"tool": "commit_state", "action": "promote_to_baseline"} in d["refused"]
    assert all({"name", "description", "input_schema"} <= set(t) for t in d["tools"])


# ---- envelope ----------------------------------------------------------------------------------- #

def test_envelope_statuses(api):
    r = api.call_tool("get_sales_report", {"company": "all", "product": "HRC", "view": "market_share"})
    assert r["status"] == "needs_input" and r["result"]["field"] == "hrc_total_local_market_kt"
    r = api.call_tool("get_pnl", {"scope": "standalone", "company": "XYZ"})
    assert r["status"] == "error" and r["error"]["error_code"] and r["integrity_checks"] == "not_run"
    r = api.call_tool("update_input", {"path": "billet.companies.EZDK.blend_pct.dri", "value": 90})
    assert r["error"]["error_code"] == "integrity_check_failed" and r["integrity_checks"] == "failed: blending_100"
    r = api.call_tool("update_input", {"path": "dri.EZDK.iop_landed_usd_t", "value": 140})
    assert [w["check"] for w in r["warnings"]][-1] == "sourcing_change"                # ERM changes supplier


def test_request_validation(api):
    bad = [("not json", None), ([], None), ({}, "request"), ({"tool": "get_pnl", "instruction": "x"}, "request"),
           ({"tool": "get_pnl", "args": {"scope": "consolidated"}, "mode": "user"}, "mode"),
           ({"tool": "get_pnl", "args": {"scope": "consolidated"}, "actor": "user"}, "actor"),
           ({"tool": 5}, "tool"), ({"tool": "get_pnl", "args": [1]}, "args"),
           ({"calls": []}, "calls"), ({"instruction": "  "}, "instruction")]
    for req, field in bad:
        r = api.handle(req)
        assert r["status"] == "error" and r["error"]["error_code"] == "schema_validation_error", req
        if field:
            assert r["error"].get("field") == field, req
    r = api.handle('{"tool": "no_such_tool", "request_id": "x1"}')
    assert r["error"]["error_code"] == "invalid_path" and r["request_id"] == "x1"


def test_non_finite_numbers_become_null():
    env = oa.envelope("t", {"status": "ok", "x": float("nan"), "y": [float("inf"), 1.0]})
    assert env["result"] == {"x": None, "y": [None, 1.0]}


# ---- batches -------------------------------------------------------------------------------------- #

def test_batch_runs_in_order_and_stops_at_the_first_refusal(api, store):
    r = api.handle({"request_id": 9, "calls": [
        {"tool": "update_input", "args": {"path": "sales.EZDK.Rebar.local_kt", "value": 120}},
        {"tool": "commit_state", "args": {"action": "promote_to_baseline", "month_label": "2026-05"}},
        {"tool": "update_input", "args": {"path": "sales.EZDK.Rebar.local_kt", "value": 130}}]})
    assert r["status"] == "error" and r["completed"] == 1 and r["requested"] == 3 and r["request_id"] == 9
    assert [x["status"] for x in r["results"]] == ["ok", "error"]
    assert r["results"][1]["error"]["error_code"] == "permission_denied"
    assert store.read("sales.EZDK.Rebar.local_kt") == 120 and baselines(store) == ["baseline_2026-04"]
    r = api.handle({"calls": [{"tool": "get_pnl", "args": {"scope": "consolidated"}},
                              {"tool": "get_tradeoff_matrix", "args": {"buyer": "ERM"}}]})
    assert r["status"] == "ok" and r["completed"] == 2
    assert api.handle({"calls": [{"tool": "get_pnl", "extra": 1}]})["results"][0]["error"]["field"] == "calls[0]"


# ---- instructions (through Claude) ----------------------------------------------------------- #

def resp(content, stop="end_turn"):
    return NS(content=content, stop_reason=stop, stop_details=None,
              usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class Scripted:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.messages = NS(create=self._create)
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **req):
        self.requests.append(copy.deepcopy(req))
        return self.responses.pop(0)


def test_instruction_runs_in_orchestrator_mode(api, store):
    r = api.handle({"instruction": "set sales.EZDK.Rebar.local_kt to 120", "request_id": "r1"})
    assert r["status"] == "ok" and r["tool_called"] == "update_input" and r["request_id"] == "r1"
    assert r["tool_calls"] == [{"tool": "update_input", "args": {"path": "sales.EZDK.Rebar.local_kt", "value": 120.0},
                                "status": "ok", "error_code": None}]
    assert store.read("sales.EZDK.Rebar.local_kt") == 120
    req = api._session.client.requests[-1]
    assert "Caller mode for this conversation: orchestrator" in req["system"][0]["text"]
    assert "manage_baseline_refresh" not in {t["name"] for t in req["tools"]}
    assert store.session_summary()["change_log"][-1]["actor"] == "orchestrator"


def test_instruction_figures_come_from_the_tools_not_the_text(store, tmp_path):
    client = Scripted([
        resp([BetaToolUseBlock(type="tool_use", id="t1", name="get_pnl", input={"scope": "consolidated"})], "tool_use"),
        resp([BetaTextBlock(type="text", text='{"status": "ok", "result": {"group_ebt": 999}}')]),
    ])
    api = oa.OrchestratorAPI(store, client, use_fallbacks=False)
    r = api.handle({"instruction": "Group EBT?"})
    assert r["status"] == "ok" and r["tool_called"] == "get_pnl"
    assert "rows" in r["result"]["table"] and "group_ebt" not in r["result"]           # Rule 1: not Claude's figure


def test_instruction_to_promote_is_refused_by_the_tools(store):
    client = Scripted([
        resp([BetaToolUseBlock(type="tool_use", id="t1", name="commit_state",
                               input={"action": "promote_to_baseline", "month_label": "2026-05"})], "tool_use"),
        resp([BetaTextBlock(type="text", text='{"status": "error", "error_code": "permission_denied"}')]),
    ])
    api = oa.OrchestratorAPI(store, client, use_fallbacks=False)
    r = api.handle({"instruction": "Promote the working state to baseline 2026-05"})
    assert r["status"] == "error" and r["error"]["error_code"] == "permission_denied"
    assert baselines(store) == ["baseline_2026-04"] and not r["conversation_ended"]


def test_instruction_without_tools(store):
    client = Scripted([resp([BetaTextBlock(type="text", text="Which company do you mean?")]),
                       resp([BetaTextBlock(type="text", text='```json\n{"status": "error", "error": '
                                                             '{"error_code": "permission_denied"}}\n```')])])
    api = oa.OrchestratorAPI(store, client, use_fallbacks=False)
    r = api.handle({"instruction": "Show the cost"})
    assert r["status"] == "needs_input" and r["message"] == "Which company do you mean?" and r["tool_calls"] == []
    r = api.handle({"instruction": "Refresh the baseline"})
    assert r["status"] == "error" and r["error"] == {"error_code": "permission_denied"}


def test_new_conversation_starts_fresh_and_failures_are_reported(api, store):
    api.handle({"instruction": "What is the consolidated EBT this month?"})
    api.handle({"instruction": "Show the billet cost for all companies", "new_conversation": True})
    hist = api._session.history()
    assert [h["status"] for h in hist] == ["active", "closed"] and hist[1]["close_reason"] == "new_conversation"
    assert api._session.router.messages[0]["content"][0]["text"].startswith("[Runtime header]")

    def boom(**_):
        raise ConnectionError("down")
    api._session.router.client = NS(messages=NS(create=boom), beta=NS(messages=NS(create=boom)))
    r = api.handle({"instruction": "Show the consolidated P&L"})
    assert r["status"] == "error" and r["error"]["error_code"] == "tool_unavailable" and "down" in r["error"]["error_message"]


def test_shared_working_state_with_the_user(api, store):
    import session_manager as ses
    user = ses.SessionManager(store, SimulatedClaude(), use_fallbacks=False)
    user.connect()
    api.call_tool("update_input", {"path": "dri.ERM.iop_landed_usd_t", "value": 150})
    c = ses.SessionManager(store, SimulatedClaude(), use_fallbacks=False).connect()
    assert c["status"] == "resume_offered" and "dri.ERM.iop_landed_usd_t" in c["message"]


# ---- HTTP ------------------------------------------------------------------------------------------ #

def test_http(api):
    c = TestClient(oa.create_app(api))
    assert c.get("/v1/health").json() == {"status": "ok"}
    assert c.get("/v1/tools").json()["caller"] == "orchestrator"
    assert c.get("/v1/state").json()["working_session"]["base_month_label"] == "2026-04"
    r = c.post("/v1/tools/get_pnl", json={"scope": "consolidated"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    r = c.post("/v1/tools/get_pnl", json={"scope": "standalone", "company": "XYZ"})
    assert r.status_code == 200 and r.json()["status"] == "error"                      # a tool-level error
    r = c.post("/v1/tools/commit_state", json={"action": "promote_to_baseline", "month_label": "2026-05"})
    assert r.status_code == 403 and r.json()["error"]["error_code"] == "permission_denied"
    r = c.post("/v1/requests", json={"tool": "manage_baseline_refresh", "args": {"action": "generate_template"},
                                     "request_id": 3})
    assert r.status_code == 403 and r.json()["request_id"] == 3
    r = c.post("/v1/requests", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["error_code"] == "schema_validation_error"
    r = c.post("/v1/requests", json={"tool": "get_pnl", "args": {"scope": "consolidated"}, "mode": "user"})
    assert r.status_code == 400
    r = c.post("/v1/requests", json={"instruction": "set sales.EZDK.Rebar.local_kt to 120"})
    assert r.status_code == 200 and r.json()["tool_called"] == "update_input"


def test_http_token(api):
    c = TestClient(oa.create_app(api, token="s3cret"))
    assert c.get("/v1/health").status_code == 401
    assert c.get("/v1/health", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/v1/health", headers={"Authorization": "Bearer s3cret"}).status_code == 200


# ---- CLI --------------------------------------------------------------------------------------------- #

def test_stdin_mode(tmp_path, monkeypatch, capsys):
    lines = [json.dumps({"tool": "get_pnl", "args": {"scope": "consolidated"}, "request_id": 1}), "",
             json.dumps({"tool": "commit_state", "args": {"action": "promote_to_baseline", "month_label": "2026-05"}}),
             "garbage"]
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    oa.main(["--stdin", "--db", str(tmp_path / "cli.db")])
    out = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [o["status"] for o in out] == ["ok", "error", "error"]
    assert out[0]["request_id"] == 1 and out[1]["error"]["error_code"] == "permission_denied"
    assert out[2]["error"]["error_code"] == "schema_validation_error"


def test_serving_beyond_this_machine_needs_a_token(tmp_path, monkeypatch):
    monkeypatch.delenv("FANTOMAAS_API_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        oa.main(["--serve", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")])
