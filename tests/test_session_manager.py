"""Step 5 — sessions.  Done-criterion (Appendix C): a simulated browser close and reopen
preserves the state — working inputs, the conversation, and the currency preference."""

import copy
import datetime as dt
import json
from types import SimpleNamespace as NS

import pytest
from anthropic.types.beta import BetaTextBlock, BetaThinkingBlock, BetaToolUseBlock

import session_manager as ses
import state_manager as sm
from llm_sim import SimulatedClaude


class Clock:
    def __init__(self):
        self.t = dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.timezone.utc)

    def __call__(self):
        return self.t


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "s.db")


def open_session(db, clock=None, channel="user", client=None):
    store = sm.StateStore(db, clock=clock)
    s = ses.SessionManager(store, client or SimulatedClaude(), channel=channel, clock=clock,
                           use_fallbacks=False)
    return store, s


def resp(content, stop="end_turn"):
    return NS(content=content, stop_reason=stop, stop_details=None,
              usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class Scripted:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.messages = NS(create=self._create)
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **req):
        self.requests.append(copy.deepcopy(ses.to_jsonable(req["messages"])))
        return self.responses.pop(0)


# ---- the done-criterion ----------------------------------------------------------------- #

def test_browser_close_and_reopen_preserves_everything(db):
    clock = Clock()
    store, s = open_session(db, clock)
    assert s.connect()["status"] == "new"
    s.ask("Show the EZDK P&L in EGP")
    s.ask("set sales.EZDK.Rebar.local_kt to 120")
    before = json.dumps(ses.to_jsonable(s.router.messages))
    store.close()                                             # the browser closes; the process may die

    clock.t += dt.timedelta(hours=2)
    store2, s2 = open_session(db, clock)
    c = s2.connect()
    assert c["status"] == "resume_offered"
    assert c["message"] == ("You have an in-progress session from 2026-10-12 09:00 UTC, based on baseline "
                            "2026-04. You had updated sales.EZDK.Rebar.local_kt (100.0 → 120.0). Would you "
                            "like to resume, save it as a scenario now, or discard it?")
    assert c["preferences"] == {"currency": "EGP"}
    assert store2.read("sales.EZDK.Rebar.local_kt") == 120                 # working state
    assert json.dumps(ses.to_jsonable(s2.router.messages)) == before       # conversation, unchanged
    assert [t["role"] for t in c["transcript"]] == ["user", "assistant", "user", "assistant"]

    r = s2.ask("Show the consolidated P&L")                                # no currency named
    assert "M LE" in r.text                                                # preference applied
    sent = s2.client.requests[-1]["messages"]
    assert json.dumps(ses.to_jsonable(sent[:len(json.loads(before))])) == before   # append-only
    note = sent[len(json.loads(before))]["content"][0]["text"]
    assert note.startswith("[Session note] The user reconnected at 2026-10-12 11:00 UTC")
    assert "Would you like to resume" in note and "Currency preference: EGP" in note
    assert s2.ask("Show the consolidated P&L again").tool_calls             # note is sent once only
    assert "[Session note]" not in json.dumps(ses.to_jsonable(s2.client.requests[-1]["messages"][-1]))
    store2.close()


def test_reopen_without_unsaved_changes_just_resumes(db):
    store, s = open_session(db)
    s.connect()
    s.ask("What is the consolidated EBT this month?")
    store.close()
    store2, s2 = open_session(db)
    c = s2.connect()
    assert c["status"] == "resumed" and c["message"] is None
    s2.ask("Show the billet cost for all companies")
    user_turns = [m for m in ses.to_jsonable(s2.router.messages) if m["role"] == "user"]
    assert "[Session note] The user reconnected" in json.dumps(user_turns[-2])
    store2.close()


# ---- currency preference ------------------------------------------------------------ #

def test_currency_preference(db):
    store, s = open_session(db)
    s.connect()
    r = s.ask("What is the consolidated EBT this month?")
    assert "(USD)" in r.text                                    # default
    s.ask("Show the billet cost in EGP")
    assert s.preferences == {"currency": "EGP"}
    r = s.ask("Show the fixed cost report")
    assert "(EGP)" in r.text
    result = json.loads(s.router.messages[-2]["content"][0]["content"])
    assert result["currency_from_preference"] == "EGP"
    s.ask("Show the consolidated P&L in dollars")
    assert s.preferences == {"currency": "USD"}
    s.set_preference("currency", "EGP")
    assert open_session(db)[1].connect()["preferences"] == {"currency": "EGP"}
    with pytest.raises(ValueError):
        s.set_preference("currency", "EUR")
    store.close()


# ---- session end (Pattern F) --------------------------------------------------------- #

@pytest.mark.parametrize("action, extra", [("discard", {}),
                                           ("promote_to_baseline", {"month_label": "2026-05"})])
def test_promote_or_discard_ends_the_session(db, action, extra):
    client = Scripted([
        resp([BetaToolUseBlock(type="tool_use", id="t1", name="update_input",
                               input={"path": "sales.EZDK.Rebar.local_kt", "value": 120})], "tool_use"),
        resp([BetaTextBlock(type="text", text="Done.")]),
        resp([BetaToolUseBlock(type="tool_use", id="t2", name="commit_state",
                               input={"action": action, **extra})], "tool_use"),
        resp([BetaTextBlock(type="text", text="Session closed.")]),
        resp([BetaTextBlock(type="text", text="Hello again.")]),
    ])
    store, s = open_session(db, client=client)
    s.connect()
    s.ask("set it")
    s.set_preference("currency", "EGP")
    r = s.ask(f"{action} please")
    assert r.session_ended
    r = s.ask("hi")                                             # a fresh conversation
    first = client.requests[-1][0]["content"][0]["text"]
    assert first.startswith("[Runtime header]") and len(client.requests[-1]) == 1
    assert s.preferences == {"currency": "USD"}
    hist = s.history()
    assert [h["status"] for h in hist] == ["active", "closed"] and hist[1]["close_reason"] == action
    store.close()


def test_saving_a_scenario_does_not_end_the_session(db):
    store, s = open_session(db)
    s.connect()
    s.ask("set sales.EZDK.Rebar.local_kt to 120")
    r = s.ask("save this as scenario push")
    assert not r.session_ended and len(s.history()) == 1
    store.close()


# ---- channels -------------------------------------------------------------------------- #

def test_orchestrator_has_its_own_conversation_on_the_shared_working_state(db):
    store, user = open_session(db)
    user.connect()
    orch = ses.SessionManager(store, SimulatedClaude(), channel="orchestrator", use_fallbacks=False)
    assert orch.connect()["status"] == "new"
    orch.ask("set dri.ERM.iop_landed_usd_t to 150")
    assert store.read("dri.ERM.iop_landed_usd_t") == 150            # one working state
    assert user.transcript() == [] and len(orch.transcript()) == 2   # separate conversations
    store.close()
    store2, user2 = open_session(db)
    assert user2.connect()["status"] == "resume_offered"             # the orchestrator's change shows up
    store2.close()


# ---- serialisation ---------------------------------------------------------------------- #

def test_sdk_blocks_round_trip_with_every_field():
    blocks = [BetaThinkingBlock(type="thinking", thinking="", signature="sig-123"),
              BetaTextBlock(type="text", text="hi", citations=None),
              BetaToolUseBlock(type="tool_use", id="t1", name="get_pnl", input={"scope": "consolidated"})]
    out = ses.to_jsonable([{"role": "assistant", "content": blocks}])
    assert out[0]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-123"}
    assert out[0]["content"][1] == {"type": "text", "text": "hi"}               # None fields dropped
    assert out[0]["content"][2]["input"] == {"scope": "consolidated"}
    assert json.loads(json.dumps(out)) == out
