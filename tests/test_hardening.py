"""Step 9 — integrity checks enforced before every output, edge cases hardened, every error in the
system prompt's format (Appendix C, step 9; D.6: "downstream tools must not be able to bypass the
master check")."""

import json
import random

import pytest

import llm_router
import orchestrator_api as oa
import state_manager as sm
import state_schema as schema
import tools
from llm_sim import SimulatedClaude

HRC = {"local_market_ceilings": {"HRC": 120}}


@pytest.fixture
def store(tmp_path):
    s = sm.StateStore(str(tmp_path / "h.db"))
    yield s
    s.close()


@pytest.fixture
def box(store, tmp_path):
    return tools.ToolBox(store, template_dir=str(tmp_path / "tpl"))


def well_formed_error(r):
    return (r["status"] == "error" and r.get("error_code") in schema.ERROR_CODES
            and isinstance(r.get("error_message"), str) and r["error_message"])


# ---- every error in one format; nothing crashes ----------------------------------------------------- #

WEIRD = [None, "", "x" * 300, -1, 0, 1e308, float("nan"), float("inf"), True, [], {}, [1, "a"], {"a": 1},
         "working", "baseline_2026-04", "baseline_1999-01", "nope", "EZDK", "ERM", "HRC", "all", "سلام", "../x"]


@pytest.mark.parametrize("name", sorted(tools.TOOL_SPECS))
def test_fuzzed_arguments_never_crash_and_errors_are_well_formed(box, name):
    rnd = random.Random(name)
    spec = tools.TOOL_SPECS[name]["input_schema"]["properties"]
    for _ in range(60):
        args = {}
        for p, d in spec.items():
            if rnd.random() < 0.6:
                args[p] = rnd.choice(d["enum"]) if d.get("enum") and rnd.random() < 0.6 else rnd.choice(WEIRD)
        if rnd.random() < 0.1:
            args["bogus"] = 1
        r = box.call(name, args)
        json.dumps(r, allow_nan=False, default=str)
        assert r["status"] in ("ok", "needs_input") or well_formed_error(r), (name, args, r)


def test_an_unexpected_failure_is_reported_not_raised(box, store, monkeypatch):
    monkeypatch.setattr(tools.ToolBox, "get_pnl", lambda self, **_: 1 / 0)
    r = box.call("get_pnl", {"scope": "consolidated"})
    assert well_formed_error(r) and r["error_code"] == "internal_error" and "nothing was stored" in r["error_message"]
    router = llm_router.Router(box, SimulatedClaude(), use_fallbacks=False)
    a = router.ask("Show the consolidated P&L")                     # the conversation carries on
    assert a.tool_calls[0]["error_code"] == "internal_error" and "couldn't" in a.text
    assert router.ask("Show the billet cost for all companies").tool_calls[0]["status"] == "ok"


def test_null_optional_arguments_take_their_defaults(box):
    assert box.call("get_tradeoff_matrix", {"buyer": None})["status"] == "ok"
    assert box.call("get_pnl", {"scope": "consolidated", "currency": None, "state_id": None})["status"] == "ok"


@pytest.mark.parametrize("changes", [[1, "a"], [], [{"value": 3}], [{"path": "sales.EZDK.Rebar.local_kt"}], "x"])
def test_malformed_change_lists_are_refused(box, changes):
    r = box.call("update_input", {"changes": changes})
    assert well_formed_error(r) and r["error_code"] == "schema_validation_error"


# ---- the integrity checks cannot be bypassed ---------------------------------------------------------- #

def corrupt_scenario(store):
    """A stored state broken behind the store's back (as a damaged file would be)."""
    sid = store.commit_state("save_as_scenario", actor="user", name="damaged")["scenario_id"]
    body = json.loads(store.connection.execute("SELECT body FROM states WHERE id = ?", (sid,)).fetchone()[0])
    body["billet"]["companies"]["EZDK"]["blend_pct"]["dri"] = 95          # the line now sums to 115%
    with store.connection:
        store.connection.execute("UPDATE states SET body = ? WHERE id = ?", (json.dumps(body), sid))
    return sid


COMPUTING = {
    "get_cost_sheet": {"stage": "dri", "company": "all"}, "get_pnl": {"scope": "consolidated"},
    "get_sales_report": {"company": "all", "product": "all"}, "get_fixed_cost_report": {"company": "all"},
    "get_production_report": {"company": "all"}, "get_tradeoff_matrix": {},
    "run_sensitivity": {"input_path": "dri.ERM.iop_landed_usd_t", "output_metric": "ebt", "company": "ERM",
                        "variation": {"type": "delta_pct", "values": [-5, 0, 5]}},
    "find_optimal_mix": {"objective": "group_cm", "run_constraints": HRC},
}


@pytest.mark.parametrize("name", sorted(COMPUTING))
def test_no_tool_computes_from_a_state_that_fails_a_check(box, store, name):
    sid = corrupt_scenario(store)
    r = box.call(name, {**COMPUTING[name], "state_id": sid})
    assert r["error_code"] == "integrity_check_failed" and "blending_100" in r["error_message"]


def test_comparisons_of_results_need_both_states_sound(box, store):
    sid = corrupt_scenario(store)
    for a, b in (("baseline_2026-04", sid), (sid, "working")):
        r = box.call("compare_states", {"state_a_id": a, "state_b_id": b})
        assert r["error_code"] == "integrity_check_failed"
    r = box.call("compare_states", {"state_a_id": "baseline_2026-04", "state_b_id": sid, "comparison_type": "inputs"})
    assert r["status"] == "ok" and r["inputs"]                       # inputs only: no computed number


def test_reading_a_broken_state_shows_the_inputs_and_says_it_is_broken(box, store):
    sid = corrupt_scenario(store)
    r = box.call("read_state", {"path": "billet.companies.EZDK.blend_pct", "state_id": sid})
    assert r["status"] == "ok" and r["value"]["dri"] == 95 and "blending_100" in r["integrity_warning"]
    assert "integrity_warning" not in box.call("read_state", {"path": "sales"})


# ---- edge values ---------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("value, needle", [(float("nan"), "finite"), (float("inf"), "finite"),
                                          (-5.0, "≥ 0"), (1e308, "realistic")])
def test_impossible_input_values_are_refused(box, store, value, needle):
    r = box.call("update_input", {"path": "sales.EZDK.Rebar.local_kt", "value": value})
    assert r["error_code"] == "schema_validation_error" and needle in r["error_message"]
    assert store.read("sales.EZDK.Rebar.local_kt") == 100.0


def test_orchestrator_json_nan_is_refused(store):
    r = oa.OrchestratorAPI(store).handle('{"tool": "update_input", "args": {"path": "dri.ERM.iop_landed_usd_t", '
                                         '"value": NaN}}')
    assert r["status"] == "error" and r["error"]["error_code"] == "schema_validation_error"


@pytest.mark.parametrize("rc, field", [
    ({"local_market_ceilings": {"HRC": -10}}, "local_market_ceilings.HRC"),
    ({"local_market_ceilings": {"HRC": "lots"}}, "local_market_ceilings.HRC"),
    ({**HRC, "capacity_ceilings": {"dri": {"EZDK": -1}}}, "capacity_ceilings.dri.EZDK"),
    ({**HRC, "blend_limits": {"local_scrap_supply_kt": float("nan")}}, "blend_limits.local_scrap_supply_kt"),
    ({**HRC, "additional_constraints": [{"variable": "sales.ESR.Rebar.local_kt", "max": "x"}]},
     "additional_constraints[0].max"),
])
def test_optimizer_run_constraints_are_validated(box, rc, field):
    r = box.call("find_optimal_mix", {"objective": "group_cm", "run_constraints": rc})
    assert r["error_code"] == "schema_validation_error" and r["field"] == field


def test_a_month_with_no_sales_at_all(box, store):
    w = store.get_state("working")
    zero = [{"path": f"sales.{c}.{p}.{k}", "value": 0} for c in w["sales"] for p in w["sales"][c]
            for k in ("local_kt", "export_kt")]
    assert box.call("update_input", {"changes": zero})["status"] == "ok"
    for name, args in COMPUTING.items():
        r = box.call(name, args)
        assert r["status"] == "ok", (name, r.get("error_message"))
    pnl = box.call("get_pnl", {"scope": "standalone", "company": "EZDK"})["table"]
    be = next(r for r in pnl["rows"] if "reak" in r["label"] and r["kind"] == "qty")
    assert all(v in (0, 0.0, None) for v in be["values"].values())        # break-even 0 at zero sales
