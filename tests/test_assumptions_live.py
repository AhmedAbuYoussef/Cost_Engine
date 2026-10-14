"""Every judgement call listed in MODEL_FIXES.md and BLEND_LIMITS.md can be changed by chatting to the
bot: the change lands in the working session, the model recomputes, undo restores it, and the
optimizer's next run uses it."""

import pytest

import llm_router
import state_manager as sm
import tools
from llm_sim import SimulatedClaude

ASSUMPTIONS = [                                   # (what, path, a different value)
    ("ESR electricity tariff", "billet.companies.ESR.electricity_usd_kwh", 0.09),
    ("ERM rolling scrap value", "detail.ERM Rolling.prices_le.byproduct_t", 5133.0),
    ("export expense", "pnl.export_expense_usd_t.EZDK.HRC", 11.0),
    ("EZDK DRI capacity", "capacity_ceilings.dri.EZDK", 270000.0),
    ("EZDK wire rod capacity", "capacity_ceilings.finished.EZDK.Wire Rod", 60000.0),
    ("EZDK flat local scrap price", "flat.EZDK.local_scrap_usd_t", 300.0),
    ("EZDK long local scrap price", "billet.companies.EZDK.local_scrap_usd_t", 248.87),
    ("DRI minimum, EZDK long", "blend_limits.furnaces.EZDK long.dri.min_pct", 70.0),
    ("local scrap supply", "blend_limits.local_scrap_supply_kt", 60.0),
    ("HRC policy floor", "policy_floors.local_share_min.HRC", 0.3),
    ("ERM billet sourcing", "sourcing.ERM_rebar_billet", "market"),
    ("ERM partial sourcing", "sourcing.ERM_rebar_billet", "split:EZDK:0.5"),
]


@pytest.fixture
def chat(tmp_path):
    store = sm.StateStore(str(tmp_path / "a.db"))
    yield store, llm_router.Router(tools.ToolBox(store), SimulatedClaude(), use_fallbacks=False)
    store.close()


@pytest.mark.parametrize("what, path, value", ASSUMPTIONS, ids=[a[0] for a in ASSUMPTIONS])
def test_each_assumption_can_be_changed_by_chat_and_undone(chat, what, path, value):
    store, router = chat
    before, figures = store.read(path), store.compute("working")["consolidated"]
    a = router.ask(f"set {path} to {value}")
    assert [(c["name"], c["status"]) for c in a.tool_calls] == [("update_input", "ok")], a.text
    assert store.read(path) == value
    if not path.startswith(("blend_limits", "policy_floors", "capacity_ceilings")):
        assert store.compute("working")["consolidated"] != figures          # the model recomputed
    u = router.ask("undo the last change")
    assert u.tool_calls[0]["status"] == "ok" and store.read(path) == before


def test_an_impossible_limit_is_refused_in_plain_words(chat):
    store, router = chat
    a = router.ask("set blend_limits.furnaces.ESR long.dri.min_pct to 40")
    assert a.tool_calls[0]["error_code"] == "schema_validation_error" and "≤ max_pct (30.0)" in a.text
    assert store.read("blend_limits.furnaces.ESR long.dri.min_pct") == 0.0


def test_a_limit_changed_by_chat_reaches_the_optimizer(chat):
    store, router = chat
    router.ask("set blend_limits.furnaces.EZDK flat.dri.min_pct to 85")
    a = router.ask("Find the optimal mix, the HRC market is 120")
    r = a.results[0]
    assert r["status"] == "ok" and "EZDK flat charge mix: dri 85–95%" in r["formulation"]
    dri = next(b for b in r["plan"]["blending"] if b["furnace"] == "EZDK flat" and b["material"] == "dri")
    assert dri["optimal_pct"] >= 85 - 1e-6
