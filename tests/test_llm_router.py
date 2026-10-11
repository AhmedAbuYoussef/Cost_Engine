"""Step 4 — the router.  Loop mechanics are tested against a scripted client; end-to-end
answers against the simulated Claude.  (tests/test_llm_live.py runs real Claude when an
API key is configured.)"""

import copy
import json
from types import SimpleNamespace as NS

import pytest

import cost_engine as ce
import llm_router
import state_manager as sm
from llm_sim import SimulatedClaude
from tools import ToolBox


def resp(content, stop="end_turn", **usage):
    return NS(content=content, stop_reason=stop, stop_details=None,
              usage=NS(input_tokens=usage.get("i", 10), output_tokens=usage.get("o", 5),
                       cache_read_input_tokens=usage.get("cr", 0), cache_creation_input_tokens=0))


def text(t):
    return NS(type="text", text=t)


def tool(name, args, id_):
    return NS(type="tool_use", id=id_, name=name, input=args)


class Scripted:
    """Returns the scripted responses in order; records each request as sent."""

    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.beta = NS(messages=NS(create=self._create))
        self.messages = NS(create=self._create)

    def _create(self, **req):
        self.requests.append({**req, "messages": copy.copy(req["messages"])})
        r = self.responses.pop(0)
        return r(req) if callable(r) else r


@pytest.fixture
def store(tmp_path):
    s = sm.StateStore(str(tmp_path / "m.db"))
    yield s
    s.close()


def router(store, responses, mode="user", **kw):
    return llm_router.Router(ToolBox(store, mode=mode, template_dir="/tmp/unused"), Scripted(responses), **kw)


# ---- the request ---------------------------------------------------------------------- #

def test_request_shape(store):
    r = router(store, [resp([text("hi")])])
    r.ask("hello")
    req = r.client.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["max_tokens"] == 16000
    assert req["output_config"] == {"effort": "high"}
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["cache_control"] == {"type": "ephemeral"}
    assert req["betas"] == ["server-side-fallback-2026-07-01"] and req["fallbacks"] == "default"
    assert "tool_choice" not in req and "thinking" not in req     # auto; adaptive thinking by default
    names = [t["name"] for t in req["tools"]]
    assert len(names) == 13 and "find_optimal_mix" not in names
    assert all(set(t) == {"name", "description", "input_schema"} for t in req["tools"])


def test_requests_without_fallback_use_the_plain_endpoint(store):
    calls = []
    client = NS(messages=NS(create=lambda **q: calls.append(q) or resp([text("ok")])),
                beta=NS(messages=NS(create=lambda **q: pytest.fail("beta endpoint used"))))
    r = llm_router.Router(ToolBox(store), client, use_fallbacks=False)
    r.ask("hello")
    assert "betas" not in calls[0] and "fallbacks" not in calls[0]


def test_tool_list_and_prompt_are_stable_between_requests(store):
    r = router(store, [resp([text("a")]), resp([text("b")])])
    r.ask("one")
    r.ask("two")
    a, b = r.client.requests
    assert a["system"] == b["system"] and a["tools"] == b["tools"]       # cache prefix unchanged


def test_system_prompt_is_the_runtime_part_plus_implementation_notes(store):
    s = llm_router.build_system_prompt("user", store.get_state())
    assert "## 1. Identity & Mission" in s and "## 5. State Awareness" in s
    assert "## Revision notes" not in s and "## Appendix A" not in s and "## Appendix D" not in s
    assert "Caller mode for this conversation: user" in s
    assert "`sales.EZDK.Rebar.local_kt`" in s
    o = llm_router.build_system_prompt("orchestrator", store.get_state())
    assert "Fantomaas orchestrator" in o and "no baseline commits" in o


# ---- the loop -------------------------------------------------------------------------- #

def test_runtime_header_on_first_turn_only(store):
    r = router(store, [resp([text("a")]), resp([text("b")])])
    r.ask("first")
    r.ask("second")
    first, second = r.messages[0]["content"], r.messages[2]["content"]
    assert first[0]["text"].startswith("[Runtime header] Current state: baseline 2026-04 loaded")
    assert first[1]["text"] == "first"
    assert second == [{"type": "text", "text": "second"}]


def test_parallel_tool_calls_and_errors(store):
    r = router(store, [
        resp([text("checking"), tool("get_pnl", {"scope": "consolidated"}, "t1"),
              tool("get_cost_sheet", {"stage": "dri", "company": "EFS"}, "t2")], "tool_use"),
        resp([text("Group EBT is -14.02 M$; EFS has no DRI plant.")]),
    ])
    reply = r.ask("EBT and EFS DRI cost?")
    results = r.messages[2]["content"]
    assert r.messages[2]["role"] == "user" and [x["tool_use_id"] for x in results] == ["t1", "t2"]
    assert "is_error" not in results[0]
    assert results[1]["is_error"] is True
    assert json.loads(results[1]["content"])["error_code"] == "structural_non_existence"
    assert [(c["name"], c["status"]) for c in reply.tool_calls] == [("get_pnl", "ok"), ("get_cost_sheet", "error")]
    assert reply.text == "Group EBT is -14.02 M$; EFS has no DRI plant." and reply.rounds == 2


def test_tool_results_are_compact_json_with_six_significant_digits(store):
    r = router(store, [resp([tool("get_pnl", {"scope": "consolidated"}, "t1")], "tool_use"), resp([text("ok")])])
    r.ask("pnl")
    payload = json.loads(r.messages[2]["content"][0]["content"])
    ebt = next(x for x in payload["table"]["rows"] if x["label"] == "EBT")["values"]["Consolidated"]
    exact = ce.compute_all(store.get_state())["consolidated"]["usd_monthly"]["consolidated"]["ebt"]
    assert ebt == float(f"{exact:.6g}")


def test_history_is_append_only_and_responses_stored_as_returned(store):
    thinking = NS(type="thinking", thinking="", signature="sig-abc")
    first = resp([thinking, text("a")])
    r = router(store, [first, resp([text("b")])])
    r.ask("one")
    snapshot = [(id(m), m["role"], list(m["content"])) for m in r.messages]
    r.ask("two")
    assert [(id(m), m["role"], list(m["content"])) for m in r.messages[:len(snapshot)]] == snapshot
    assert r.messages[1]["content"][0] is thinking        # thinking block kept, untouched
    assert r.client.requests[1]["messages"][1]["content"][0] is thinking


def test_refusal_and_max_tokens(store):
    refused = resp([], "refusal")
    refused.stop_details = NS(category="cyber")
    r = router(store, [refused, resp([text("partial answer")], "max_tokens"), resp([text("fine")])])
    a = r.ask("something odd")
    assert a.stop_reason == "refusal" and "(cyber)" in a.text
    b = r.ask("long report")
    assert b.stop_reason == "max_tokens" and "cut off" in b.text
    assert r.ask("again").text == "fine"


def test_round_limit_leaves_a_valid_history(store):
    loop = lambda req: resp([tool("list_states", {}, f"t{len(req['messages'])}")], "tool_use")
    r = router(store, [loop, loop, loop, resp([text("recovered")])], max_tool_rounds=3)
    a = r.ask("loop forever")
    assert a.stop_reason == "tool_round_limit" and len(a.tool_calls) == 3
    assert r.messages[-1]["role"] == "user" and r.messages[-1]["content"][0]["type"] == "tool_result"
    assert r.ask("stop").text == "recovered"


def test_usage_is_summed_over_rounds(store):
    r = router(store, [resp([tool("list_states", {}, "t1")], "tool_use", i=100, o=20, cr=80),
                       resp([text("done")], i=150, o=30, cr=120)])
    assert r.ask("q").usage == {"input_tokens": 250, "output_tokens": 50,
                                "cache_read_input_tokens": 200, "cache_creation_input_tokens": 0}


def test_orchestrator_mode_is_enforced_inside_the_loop(store):
    r = router(store, [resp([tool("commit_state", {"action": "promote_to_baseline", "month_label": "2026-05"},
                                  "t1")], "tool_use"), resp([text("Not permitted.")])], mode="orchestrator")
    r.ask("promote it")
    res = r.messages[2]["content"][0]
    assert res["is_error"] and json.loads(res["content"])["error_code"] == "permission_denied"
    assert "manage_baseline_refresh" not in [t["name"] for t in r.client.requests[0]["tools"]]
    assert [b["id"] for b in store.list_states("baselines")] == ["baseline_2026-04"]


# ---- end to end with the simulated Claude ------------------------------------------------ #

@pytest.fixture
def sim(store):
    return llm_router.Router(ToolBox(store, template_dir="/tmp/unused"), SimulatedClaude(), use_fallbacks=False)


def test_e2e_answers_carry_the_engines_numbers(sim, store):
    o = ce.compute_all(store.get_state())
    ebt = o["consolidated"]["usd_monthly"]["consolidated"]["ebt"]
    a = sim.ask("What is the consolidated EBT this month?")
    assert f"{ebt:,.2f}" in a.text and "Source: working state" in a.text
    efs = o["billet"]["EFS"]["total_variable_cost"]
    assert f"{efs:,.2f}" in sim.ask("Show the billet cost for all companies").text
    a = sim.ask("Show me the EZDK P&L in EGP")
    sub = o["pnl"]["le_monthly"]["columns"]["EZDK/Sub-Total"]["ebt"]
    assert f"{sub:,.2f}" in a.text and "M LE" in a.text


def test_e2e_amend_save_compare(sim, store):
    a = sim.ask("set sales.EZDK.Rebar.local_kt to 120")
    assert "100.0 → 120.0" in a.text and "over capacity" in a.text
    assert store.read("sales.EZDK.Rebar.local_kt") == 120
    assert "Saved as 'rebar push'" in sim.ask("save this as scenario rebar push").text
    assert "rebar push" in sim.ask("list my saved scenarios").text
    c = sim.ask("compare with the 2026-04 baseline")
    assert "sales.EZDK.Rebar.local_kt" in c.text and "Group EBT" in c.text


def test_e2e_asks_for_hrc_market_and_explains_absent_steps(sim):
    a = sim.ask("What is the HRC market share?")
    assert a.tool_calls[0]["status"] == "needs_input" and "HRC" in a.text
    b = sim.ask("What is the HRC market share if the hrc market is 150")
    assert "35%" in b.text and "ERM share" not in b.text
    c = sim.ask("what is the DRI cost at EFS")
    assert "EFS does not produce DRI" in c.text
    d = sim.ask("good morning")
    assert d.tool_calls == [] and "What would you like to do?" in d.text


def test_e2e_sensitivity_and_flow(sim):
    a = sim.ask("run a sensitivity of sales.ESR.Rebar.local_price_le_t on ebt for ESR")
    assert a.tool_calls[0]["name"] == "run_sensitivity" and a.tool_calls[0]["status"] == "ok"
    b = sim.ask("show the production flow")
    assert "```mermaid" in b.text
