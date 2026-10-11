"""Real Claude, end to end.  Skipped unless credentials are configured (ANTHROPIC_API_KEY,
ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile, opted in with EZZ_LIVE_LLM=1).
Each test makes real, billed API calls."""

import os

import pytest

import cost_engine as ce
import llm_router
import state_manager as sm
from tools import ToolBox

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
         or os.environ.get("EZZ_LIVE_LLM") == "1"),
    reason="no Anthropic credentials configured")


@pytest.fixture
def live(tmp_path):
    store = sm.StateStore(str(tmp_path / "m.db"))
    yield llm_router.Router(ToolBox(store, template_dir=str(tmp_path))), store
    store.close()


def test_consolidated_ebt(live):
    router, store = live
    r = router.ask("What is the consolidated EBT this month, in USD?")
    ebt = ce.compute_all(store.get_state())["consolidated"]["usd_monthly"]["consolidated"]["ebt"]
    assert "get_pnl" in [c["name"] for c in r.tool_calls]
    assert f"{abs(ebt):.2f}" in r.text.replace(",", "")


def test_structural_absence_is_explained(live):
    router, _ = live
    r = router.ask("What's the HRC cost at ESR?")
    assert "ESR" in r.text and "HRC" in r.text


def test_amendment_goes_to_working_state_only(live):
    router, store = live
    router.ask("Set EZDK's local rebar sales to 120 kt.")
    assert store.read("sales.EZDK.Rebar.local_kt") == 120
    assert store.read("sales.EZDK.Rebar.local_kt", "baseline_2026-04") == 100
