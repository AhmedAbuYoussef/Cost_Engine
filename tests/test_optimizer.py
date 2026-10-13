"""Step 8 — find_optimal_mix.  Appendix D: the four verification cases (D.2) gate the tool (D.3);
the three self-checks (D.4) run on every solve and turn any doubt into an error, never a number."""

import copy
import json
import random

import pytest

import cost_engine as ce
import excel_io
import optimizer as opt
import state_manager as sm
import tools
from conftest import REFERENCE_WORKBOOK
from state_schema import ModelError

HRC = {"local_market_ceilings": {"HRC": 120.0}}


@pytest.fixture
def base():
    return opt._baseline()


def gcm(state):
    return ce.compute_all(state)["consolidated"]["usd_monthly"]["consolidated"]["contribution_margin"]


# ---- D.2: the four verification cases ------------------------------------------------------- #

@pytest.mark.parametrize("name, case", opt.CASES)
def test_verification_case(base, name, case):
    ok, detail = case(base)
    assert ok, detail


def test_ship_gate_opens_only_when_all_cases_pass(monkeypatch):
    assert opt.verify()["passed"]
    monkeypatch.setattr(opt, "CASES", opt.CASES + (("broken", lambda b: (False, "nope")),))
    v = opt.verify()
    assert not v["passed"] and v["cases"][-1] == {"case": "broken", "passed": False, "detail": "nope"}
    monkeypatch.setattr(opt, "CASES", (("crash", lambda b: 1 / 0),))
    assert opt.verify()["cases"][0]["detail"].startswith("ZeroDivisionError")


def test_parity_with_the_workbooks_own_answer():
    """Case 2, Excel side: on the workbook's own data and rules, the optimizer's answer to ERM's
    billet sourcing is the workbook's (the trade-off minimum it caches in Billet!G44).  The legacy
    state carries the workbook's known quirks, so the self-checks are run by hand here."""
    leg = excel_io.extract_state(REFERENCE_WORKBOOK)
    leg["policy_floors"] = {"local_share_min": {"Rebar": 0.5, "Wire Rod": 0.2, "HRC": 0.2}}
    excel_min = excel_io.extract_expected(REFERENCE_WORKBOOK)["Billet!G44"]
    out = ce.compute_all(leg)
    big = opt._ceilings_covering(leg, out)
    r = opt.optimize(leg, objective="company_cm", company="ERM", free_variables=["billet_sourcing"],
                     run_constraints={**HRC, "capacity_ceilings": big}, check=False)
    plan = copy.deepcopy(leg)
    for c in r["changes"]:
        plan["sourcing"]["ERM_rebar_billet"] = c["value"]
    got = ce.compute_all(plan)["sourcing"]
    assert got["price_usd_t"] == pytest.approx(excel_min, abs=0.005)            # Excel shows 2 dp
    assert got["supplier"] == out["billet"]["tradeoff"]["cheapest_source"]["ERM"]
    erm = ce.compute_all(plan)["consolidated"]["usd_monthly"]["companies"]["ERM"]["contribution_margin"]
    assert erm == pytest.approx(r["cm"]["optimal"], rel=1e-12)                   # engine cross-check


# ---- D.4: every run checks itself ------------------------------------------------------------- #

def test_a_normal_run_passes_all_three_self_checks(base):
    r = opt.optimize(base, run_constraints=HRC)
    sc = r["self_checks"]
    assert sc["all_passed"] and sc["engine_cross_check"]["passed"] and sc["integrity"]["passed"]
    assert abs(sc["engine_cross_check"]["difference_usd"]) < 1e-3                  # on ~65 M$
    assert sc["perturbation"]["passed"] and sc["perturbation"]["feasible"] > 0
    assert r["cm"]["optimal"] >= r["cm"]["current"]
    assert r["formulation"].startswith("Maximize group contribution margin")
    assert {"plan", "changes", "by_company", "volumes", "binding_constraints"} <= set(r)


def test_engine_cross_check_catches_a_wrong_coefficient(base, monkeypatch):
    real = opt._Linearisation.__init__

    def broken(self, *a, **k):
        real(self, *a, **k)
        self.a = self.a * 1.01                                  # a 1% error in the CM per ton sold
    monkeypatch.setattr(opt._Linearisation, "__init__", broken)
    with pytest.raises(ModelError) as e:
        opt.optimize(base, run_constraints=HRC)
    assert e.value.details["self_check"] == "engine_cross_check"


def test_integrity_check_catches_a_plan_that_breaks_a_constraint(base, monkeypatch):
    real = opt._plan

    def overfull(m, x, state, current):
        P, plan = real(m, x, state, current)
        P["sales"]["EZDK"]["Rebar"]["export_kt"] += 50          # beyond EZDK's rebar capacity
        return P, plan
    monkeypatch.setattr(opt, "_plan", overfull)
    monkeypatch.setattr(opt, "REL_TOL", 1.0)                   # let it past the cross-check
    with pytest.raises(ModelError) as e:
        opt.optimize(base, run_constraints=HRC)
    assert e.value.details["self_check"] == "integrity" and "Rebar EZDK" in e.value.message


def test_perturbation_check_finds_a_better_neighbour_of_a_non_optimum(base):
    """The current plan is not optimal: some ±5% move improves it (with capacity covering it)."""
    out = ce.compute_all(base)
    rc = {**HRC, "capacity_ceilings": opt._ceilings_covering(base, out)}
    settings = opt._run_settings(base, rc)
    free = opt._free_set(base, None)
    lin = opt._Linearisation(base, "group_cm", None)
    m = opt._Model(lin, settings, free, "EZDK", opt._current(base))
    p = opt._perturbation(m, base, gcm(base) * 1e6, "group_cm", None,
                          {"sales": free[0], "furnaces": free[1], "sourcing": True})
    assert not p["passed"] and p["best_gain_usd"] > 0 and p["better_move"]


# ---- answers ----------------------------------------------------------------------------------- #

def test_applying_the_plan_reproduces_the_optimum(tmp_path):
    store = sm.StateStore(str(tmp_path / "o.db"))
    box = tools.ToolBox(store)
    r = box.call("find_optimal_mix", {"objective": "group_cm", "run_constraints": HRC})
    assert r["status"] == "ok" and r["source"] == "Source: working state"
    assert store.session_summary()["status"] != "in_progress"            # nothing applied
    u = box.call("update_input", {"changes": r["changes"]})
    assert u["status"] == "ok"
    out = store.compute("working")
    assert out["consolidated"]["usd_monthly"]["consolidated"]["contribution_margin"] == \
        pytest.approx(r["cm"]["optimal"], rel=1e-12)
    assert ce.failed_errors(out) == [] and all(c["passed"] for c in out["integrity"])
    store.close()


def test_shadow_prices_match_a_re_solve(base):
    """'+$X per extra ton of EZDK DRI capacity' — checked by raising the ceiling 1,000 t."""
    r = opt.optimize(base, run_constraints=HRC)
    sp = next(b for b in r["binding_constraints"] if b["constraint"] == "DRI capacity EZDK")
    caps = copy.deepcopy(base["capacity_ceilings"])
    caps["dri"]["EZDK"] += 1000
    r2 = opt.optimize(base, run_constraints={**HRC, "capacity_ceilings": caps})
    assert (r2["cm"]["optimal"] - r["cm"]["optimal"]) * 1e6 / 1000 == pytest.approx(sp["shadow_price"], rel=1e-6)


def test_bounds_and_locks_are_respected(base):
    path = "billet.companies.EZDK.blend_pct.dri"
    extra = [{"variable": path, "min": 70, "max": 75},
             {"variable": "sales.ESR.Rebar.local_kt", "max": 60},
             {"variable": "sourcing.ERM_internal_share", "max": 0.5}]
    r = opt.optimize(base, free_variables=["local_sales", "billet_sourcing", "blending"],
                     run_constraints={**HRC, "additional_constraints": extra})
    assert r["self_checks"]["all_passed"]
    row = next(b for b in r["plan"]["blending"] if b["path"] == path)
    assert 70 - 1e-6 <= row["optimal_pct"] <= 75 + 1e-6
    sales = {s["path"]: s for s in r["plan"]["sales"]}
    assert sales["sales.ESR.Rebar.local_kt"]["optimal_kt"] <= 60 + 1e-9
    assert all(s["optimal_kt"] == s["current_kt"] for p, s in sales.items() if p.endswith("export_kt"))
    assert r["plan"]["billet_sourcing"]["internal_share"] <= 0.5 + 1e-9
    total = sum(b["optimal_pct"] for b in r["plan"]["blending"] if b["furnace"] == "EZDK long")
    assert total == pytest.approx(100.0, abs=1e-9)                       # blending_100 by construction


@pytest.mark.parametrize("company", ["EZDK", "EFS", "ERM", "ESR"])
def test_company_objective(base, company):
    r = opt.optimize(base, objective="company_cm", company=company, run_constraints=HRC)
    row = next(x for x in r["by_company"]["rows"] if x["company"] == company)
    assert r["self_checks"]["all_passed"] and row["optimal"] >= row["current"] - 1e-9
    assert r["cm"]["optimal"] == pytest.approx(row["optimal"])
    assert f"{company}'s contribution margin" in r["formulation"]
    held = ["EZDK long", "EFS long", "ESR long"] if company == "ERM" else [f"{company} long"]
    assert r["notes"] and all(f in r["notes"][0] for f in held)          # the coupled blend is held, and said


def test_company_objective_refuses_an_explicit_non_linear_request(base):
    with pytest.raises(ModelError) as e:
        opt.optimize(base, objective="company_cm", company="ERM", free_variables=["billet_sourcing", "blending"],
                     run_constraints=HRC)
    assert e.value.code == "schema_validation_error" and "non-linear" in e.value.message


@pytest.mark.parametrize("seed", range(4))
def test_random_prices_still_pass_every_self_check(base, seed):
    rnd = random.Random(seed)
    s = copy.deepcopy(base)
    for co in s["sales"]:
        for prod in s["sales"][co].values():
            prod["export_price_usd_t"] *= rnd.uniform(0.8, 1.2)
            prod["local_price_le_t"] *= rnd.uniform(0.8, 1.2)
    for co in ("EZDK", "EFS", "ESR"):
        s["billet"]["companies"][co]["local_scrap_usd_t"] *= rnd.uniform(0.8, 1.2)
    s["dri"]["ERM"]["iop_landed_usd_t"] *= rnd.uniform(0.8, 1.2)
    r = opt.optimize(s, run_constraints={"local_market_ceilings": {"HRC": rnd.uniform(20, 150)}})
    assert r["self_checks"]["all_passed"]


# ---- refusals ---------------------------------------------------------------------------------- #

def test_hrc_market_is_asked_every_run(base):
    r = opt.optimize(base)
    assert r["status"] == "needs_input" and r["field"] == "run_constraints.local_market_ceilings.HRC"


@pytest.mark.parametrize("kwargs, code", [
    ({"objective": "max_ebt"}, "schema_validation_error"),
    ({"objective": "company_cm"}, "missing_required_arg"),
    ({"objective": "group_cm", "free_variables": ["prices"]}, "invalid_path"),
    ({"objective": "group_cm", "run_constraints": {**HRC, "budget": 1}}, "schema_validation_error"),
    ({"objective": "group_cm", "run_constraints": {**HRC, "additional_constraints": [{"variable": "x.y", "max": 1}]}},
     "invalid_path"),
    ({"objective": "group_cm", "run_constraints": {**HRC, "policy_floors": {"local_share_min": {"HRC": 2}}}},
     "schema_validation_error"),
    ({"objective": "group_cm", "run_constraints": {**HRC, "capacity_ceilings": {"dri": {"ESR": 1}}}},
     "structural_non_existence"),
])
def test_bad_arguments(base, kwargs, code):
    with pytest.raises(ModelError) as e:
        opt.optimize(base, **kwargs)
    assert e.value.code == code


def test_infeasible_names_a_minimal_conflict_and_returns_no_number(base):
    free = ["local_sales", "billet_sourcing", "blending"] + \
        [p for p in opt._sales_paths(base) if p.endswith("export_kt") and ".HRC." not in p]
    rc = {"local_market_ceilings": {"HRC": 0.0}, "policy_floors": {"local_share_min": {"HRC": 0.2}}}
    with pytest.raises(ModelError) as e:
        opt.optimize(base, free_variables=free, run_constraints=rc)
    d = e.value.to_dict()
    assert d["error_code"] == "infeasible_optimization" and "cm" not in d
    names = [c["constraint"] for c in d["conflict"]]
    assert "policy floor HRC" in names and "local market ceiling HRC" in names
    assert "Nothing was relaxed" in d["error_message"] and d["formulation"]
    # the named groups are the cause: freeing the held HRC exports, or opening the market, solves it
    assert any(n.startswith("held fixed: sales.") and ".HRC.export_kt" in n for n in names)
    hrc_exports = [p for p in opt._sales_paths(base) if ".HRC.export_kt" in p]
    assert opt.optimize(base, free_variables=free + hrc_exports, run_constraints=rc)["status"] == "ok"
    assert opt.optimize(base, free_variables=free, run_constraints={**rc, "local_market_ceilings": {"HRC": 50}})["status"] == "ok"


def test_through_the_tool_and_the_orchestrator(tmp_path):
    import orchestrator_api as oa
    store = sm.StateStore(str(tmp_path / "f.db"))
    api = oa.OrchestratorAPI(store)
    r = api.call_tool("find_optimal_mix", {"objective": "group_cm", "run_constraints": HRC})
    assert r["status"] == "ok" and r["integrity_checks"] == "passed"
    json.dumps(r, allow_nan=False)
    r = api.call_tool("find_optimal_mix", {"objective": "group_cm"})
    assert r["status"] == "needs_input"
    store.close()


# ---- in the conversation and on the page ---------------------------------------------------------- #

def test_simulated_conversation_asks_runs_and_applies_exactly(tmp_path):
    import llm_router
    from llm_sim import SimulatedClaude
    store = sm.StateStore(str(tmp_path / "c.db"))
    router = llm_router.Router(tools.ToolBox(store), SimulatedClaude(), use_fallbacks=False)
    a = router.ask("Find the optimal mix")
    assert a.tool_calls[0]["status"] == "needs_input" and "HRC market" in a.text
    a = router.ask("Find the optimal mix, the HRC market is 120")
    assert a.tool_calls[0]["status"] == "ok" and "apply this plan" in a.text and "Maximize" in a.text
    sent = json.loads(router.messages[-2]["content"][0]["content"])
    full, best = a.results[0]["changes"], a.results[0]["cm"]["optimal"]
    assert sent["changes"] == full                                   # the plan reaches Claude unrounded
    a = router.ask("Apply the plan")
    assert [c["name"] for c in a.tool_calls] == ["update_input"] and a.tool_calls[0]["status"] == "ok"
    out = store.compute("working")
    assert out["consolidated"]["usd_monthly"]["consolidated"]["contribution_margin"] == pytest.approx(best, rel=1e-12)
    assert all(c["passed"] for c in out["integrity"])
    store.close()


def test_the_page_draws_the_optimizer_result(base):
    import re
    import ui_render as ui
    r = opt.optimize(base, run_constraints=HRC)
    arts = ui.artifacts("find_optimal_mix", r)
    assert [a["kind"] for a in arts] == ["optimizer"]
    h = arts[0]["html"]
    assert "Optimal plan" in h and "Self-checks" in h and "not applied" in h
    assert "up-good" in h                                            # CM up → green ▲
    assert "EZDK DRI ≤ 250,000 t" in h and "Shadow price" in h
    for tag in ("div", "table", "tr", "td"):
        assert len(re.findall(rf"<{tag}[\s>]", h)) == h.count(f"</{tag}>"), tag
