"""Step 2 — state manager.  Done-criterion (system prompt, Appendix C): round-trip
save-load-diff works for baselines and scenarios; the state schema is enforced."""

import datetime as dt
import json
import os

import pytest

import cost_engine as ce
import state_manager as sm
import state_schema as schema
from conftest import REFERENCE_WORKBOOK, ROOT
from state_schema import ModelError


class Clock:
    def __init__(self, t=dt.datetime(2026, 4, 30, 9, 0, tzinfo=dt.timezone.utc)):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += dt.timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "model.db")


@pytest.fixture
def store(db, clock):
    s = sm.StateStore(db, clock=clock)
    yield s
    s.close()


def baseline_file():
    with open(os.path.join(ROOT, "model_initial_state.json")) as f:
        return json.load(f)


def err(fn, *a, **kw):
    with pytest.raises(ModelError) as e:
        fn(*a, **kw)
    return e.value


# ---- bootstrap and round trips ----------------------------------------------------- #

def test_first_open_loads_initial_state_as_baseline(store):
    assert [s["id"] for s in store.list_states("baselines")] == ["baseline_2026-04"]
    assert store.get_state("baseline_2026-04") == baseline_file()
    assert store.get_state("working") == baseline_file()
    assert store.runtime_header() == ("Current state: baseline 2026-04 loaded, 0 scenarios saved "
                                      "(none), working session untouched.")


def test_round_trip_is_exact_and_engine_identical(store):
    """What is stored is exactly what comes back — numbers included — so a stored state
    computes to the same figures as the file it came from."""
    a = ce.key_figures(ce.compute_all(baseline_file()))
    b = ce.key_figures(store.compute("baseline_2026-04"))
    assert a == b


def test_working_session_survives_reopen(db, clock):
    s = sm.StateStore(db, clock=clock)
    s.update_input("sales.EZDK.Rebar.local_kt", 120)
    s.close()
    s2 = sm.StateStore(db, clock=clock)                  # browser closed and reopened
    assert s2.read("sales.EZDK.Rebar.local_kt") == 120
    assert s2.session_summary()["status"] == "in_progress"
    assert "in progress with 1 changes" in s2.runtime_header()
    s2.close()


def test_scenario_round_trip_save_load_diff(store):
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    store.update_input("dri.EZDK.iop_landed_usd_t", 140)
    sc = store.commit_state("save_as_scenario", name="push", description="d", tags=["chairman"])
    assert sc["parent_baseline_id"] == "baseline_2026-04"
    assert set(sc["changed_inputs"]) == {"sales.EZDK.Rebar.local_kt", "dri.EZDK.iop_landed_usd_t"}
    # frozen: later working changes do not touch it
    store.update_input("sales.EZDK.Rebar.local_kt", 130)
    assert store.read("sales.EZDK.Rebar.local_kt", sc["scenario_id"]) == 120
    d = store.diff("baseline_2026-04", sc["scenario_id"])
    assert {r["path"] for r in d["inputs"]} == set(sc["changed_inputs"])
    rebar = next(r for r in d["inputs"] if r["path"] == "sales.EZDK.Rebar.local_kt")
    assert rebar["pct"] == pytest.approx(20.0)
    # output side is each state computed on its own
    expected = (ce.compute_all(store.get_state(sc["scenario_id"]))["consolidated"]["usd_monthly"]
                ["consolidated"]["ebt"])
    assert d["group_ebt"]["b"] == pytest.approx(expected)
    assert d["group_ebt"]["a"] == pytest.approx(
        ce.compute_all(baseline_file())["consolidated"]["usd_monthly"]["consolidated"]["ebt"])


def test_diff_threshold_filters_small_moves(store):
    store.update_inputs([{"path": "sales.EZDK.Rebar.local_kt", "value": 100.5},
                         {"path": "sales.EFS.Rebar.local_kt", "value": 90}])
    d = store.diff("baseline_2026-04", "working", threshold_pct=1)
    assert [r["path"] for r in d["inputs"]] == ["sales.EFS.Rebar.local_kt"]


# ---- update_input ------------------------------------------------------------------ #

def test_update_returns_old_new_and_impact(store):
    r = store.update_input("sales.EZDK.Rebar.local_kt", 120)
    assert r["changes"] == [{"path": "sales.EZDK.Rebar.local_kt", "old": 100.0, "new": 120}]
    group = {x["figure"]: x for x in r["impact"]}
    assert group["Group EBT M$"]["delta"] == pytest.approx(
        ce.compute_all(store.get_state())["consolidated"]["usd_monthly"]["consolidated"]["ebt"]
        - ce.compute_all(baseline_file())["consolidated"]["usd_monthly"]["consolidated"]["ebt"])
    assert any(w["check"] == "capacity_within_limits" for w in r["warnings"])


def test_scope_fans_out_where_the_input_exists(store):
    r = store.update_input("sales.EZDK.Rebar.local_price_le_t", 9500, scope="all_companies")
    assert {c["path"] for c in r["changes"]} == {f"sales.{co}.Rebar.local_price_le_t"
                                                 for co in ("EZDK", "EFS", "ERM", "ESR")}
    r = store.update_input("sales.EZDK.Rebar.export_price_usd_t", 500, scope="all_products")
    assert {c["path"] for c in r["changes"]} == {f"sales.EZDK.{p}.export_price_usd_t"
                                                 for p in ("Rebar", "Wire Rod", "HRC")}


def test_noop_update_stores_nothing(store):
    r = store.update_input("sales.EZDK.Rebar.local_kt", 100.0)
    assert r["changes"] == [] and store.session_summary()["change_batches"] == 0


@pytest.mark.parametrize("path, value, code", [
    ("sales.ESR.HRC.local_kt", 5, "structural_non_existence"),
    ("dri.EFS.mrmr", 1.4, "structural_non_existence"),
    ("billet.companies.ERM.eaf_yield_pct", 85, "structural_non_existence"),
    ("detail.ESR Flat.stage1", {}, "structural_non_existence"),
    ("sales.EZDK.Rebr.local_kt", 5, "invalid_path"),
    ("sales..local_kt", 5, "invalid_path"),
    ("month_label", "2026-05", "invalid_path"),
    ("rules_profile", "legacy", "invalid_path"),
    ("sales.EZDK.Rebar.local_kt", -5, "schema_validation_error"),
    ("sales.EZDK.Rebar.local_kt", "lots", "schema_validation_error"),
    ("sales.EZDK.Rebar.local_kt", float("nan"), "schema_validation_error"),
    ("sales.EZDK.Rebar.local_kt", True, "schema_validation_error"),
    ("finishing_yield_pct.Rebar.EZDK", 140, "schema_validation_error"),
    ("dri.ERM.mrmr", 0.8, "schema_validation_error"),
    ("sourcing.ERM_rebar_billet", "offer:ERM", "schema_validation_error"),
    ("sales.EZDK.Rebar", {"local_kt": 5}, "schema_validation_error"),
    ("billet.companies.EZDK.blend_pct.dri", 70, "integrity_check_failed"),
    ("fixed_cost.EZDK.distribution_pct.Rebar", 30, "integrity_check_failed"),
    ("billet.tradeoff_overrides", {"EZDK": {"ERM": 400}}, "integrity_check_failed"),
])
def test_bad_updates_are_refused_and_nothing_is_stored(store, path, value, code):
    before = store.get_state()
    e = err(store.update_input, path, value)
    assert e.code == code, e.message
    assert e.to_dict()["status"] == "error"
    assert store.get_state() == before
    assert store.session_summary()["change_batches"] == 0


def test_balancing_changes_go_through_together(store):
    """A blend change alone breaks the 100% check; with its balancing change it passes."""
    r = store.update_inputs([{"path": "billet.companies.EZDK.blend_pct.dri", "value": 70},
                             {"path": "billet.companies.EZDK.blend_pct.imported_scrap", "value": 26}])
    assert len(r["changes"]) == 2
    assert store.undo()["reverted"][0]["path"].startswith("billet.companies.EZDK.blend_pct")
    assert store.get_state() == baseline_file()


def test_money_inputs_accept_le_or_usd(store):
    store.update_input("detail.ESR Rebar.stage1.prices_usd.electrodes_kg", {"le": 230000})
    store.update_input("detail.ESR Rebar.stage1.prices_usd.electrodes_kg", 14000)
    assert err(store.update_input, "sales.EZDK.Rebar.local_kt", {"le": 5}).code == "schema_validation_error"


def test_undo_walks_back_batches(store):
    store.update_input("sales.EZDK.Rebar.local_kt", 110)
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    store.undo()
    assert store.read("sales.EZDK.Rebar.local_kt") == 110
    store.undo()
    assert store.get_state() == baseline_file()
    assert err(store.undo).code == "nothing_to_undo"


def test_orchestrator_can_work_but_not_commit(store):
    store.update_input("sales.EZDK.Rebar.local_kt", 110, actor="orchestrator")
    store.commit_state("save_as_scenario", name="fantomaas run", actor="orchestrator")
    assert err(store.commit_state, "promote_to_baseline", actor="orchestrator",
               month_label="2026-05").code == "permission_denied"
    assert err(store.refresh_baseline, baseline_file(), "2026-05",
               actor="orchestrator").code == "permission_denied"
    assert err(store.import_workbook, REFERENCE_WORKBOOK, "2019-12",
               actor="orchestrator").code == "permission_denied"
    assert [b["id"] for b in store.list_states("baselines")] == ["baseline_2026-04"]


# ---- commits ---------------------------------------------------------------------- #

def test_promote_creates_month_and_resets_session(store, clock):
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    clock.advance(days=31)
    r = store.commit_state("promote_to_baseline", month_label="2026-05")
    assert r["baseline_id"] == "baseline_2026-05" and r["previous_baseline_id"] == "baseline_2026-04"
    assert [x["path"] for x in r["diff_vs_previous"]["inputs"]] == ["sales.EZDK.Rebar.local_kt"]
    assert store.read("month_label", "baseline_2026-05") == "2026-05"
    assert store.get_state("baseline_2026-04") == baseline_file()        # old month untouched
    s = store.session_summary()
    assert s["base_baseline_id"] == "baseline_2026-05" and s["status"] == "untouched"
    assert store.runtime_header().startswith("Current state: baseline 2026-05 loaded")


def test_promote_needs_month_and_respects_existing(store):
    assert err(store.commit_state, "promote_to_baseline").code == "missing_required_arg"
    assert err(store.commit_state, "promote_to_baseline", month_label="April").code == "schema_validation_error"
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    assert err(store.commit_state, "promote_to_baseline", month_label="2026-04").code == "baseline_exists"
    r = store.commit_state("promote_to_baseline", month_label="2026-04", overwrite_if_exists=True)
    assert r["overwrote"] and store.read("sales.EZDK.Rebar.local_kt", "baseline_2026-04") == 120


def test_discard_returns_to_latest_baseline(store):
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    store.commit_state("discard")
    assert store.get_state() == baseline_file()
    assert store.session_summary()["change_batches"] == 0


def test_refresh_is_atomic(store):
    bad = baseline_file()
    bad["sales"]["EZDK"]["Rebar"]["local_kt"] = "n/a"
    assert err(store.refresh_baseline, bad, "2026-05").code == "schema_validation_error"
    unbalanced = baseline_file()
    unbalanced["billet"]["companies"]["EFS"]["blend_pct"]["dri"] = 60
    assert err(store.refresh_baseline, unbalanced, "2026-05").code == "integrity_check_failed"
    missing = baseline_file()
    del missing["policy_floors"]
    assert err(store.refresh_baseline, missing, "2026-05").code == "schema_validation_error"
    assert [b["id"] for b in store.list_states("baselines")] == ["baseline_2026-04"]
    good = baseline_file()
    good["dri"]["ERM"]["iop_landed_usd_t"] = 150
    r = store.refresh_baseline(good, "2026-05")
    assert [x["path"] for x in r["diff_vs_previous"]["inputs"]] == ["dri.ERM.iop_landed_usd_t"]
    assert any(o["figure"] == "DRI ERM VC $/t" for o in r["diff_vs_previous"]["outputs"])


def test_import_workbook_as_baseline(store):
    r = store.import_workbook(REFERENCE_WORKBOOK, "2019-12")
    assert r["baseline_id"] == "baseline_2019-12"
    assert [f["fix"] for f in r["fixes_applied"]][0] == "A1"
    imported = store.get_state("baseline_2019-12")
    expected = baseline_file()
    expected["month_label"] = "2019-12"
    assert imported["sales"] == expected["sales"]
    assert ce.key_figures(ce.compute_all(imported)) == ce.key_figures(ce.compute_all(expected))
    # the newest month stays the session's default
    assert store.list_states("baselines")[0]["month_label"] in ("2019-12", "2026-04")


def test_import_rejects_a_workbook_with_different_formulas(store, tmp_path):
    import openpyxl
    wb = openpyxl.load_workbook(REFERENCE_WORKBOOK)
    wb["Billet"]["E24"] = "=E8*E13%"
    path = tmp_path / "other.xlsx"
    wb.save(path)
    e = err(store.import_workbook, str(path), "2026-05")
    assert e.code == "schema_validation_error" and "Billet!E24" in e.message


# ---- scenarios: listing, loading, retention ------------------------------------------- #

def test_list_filters(store, clock):
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    a = store.commit_state("save_as_scenario", name="a", tags=["export"])
    clock.advance(days=10)
    store.commit_state("discard")
    store.update_input("dri.ERM.iop_landed_usd_t", 150)
    b = store.commit_state("save_as_scenario", name="b", tags=["iop"],
                           requested_outputs=["consolidated_pnl"])
    ids = lambda **f: [x["id"] for x in store.list_states("scenarios", f)]
    assert ids() == [b["scenario_id"], a["scenario_id"]]
    assert ids(tags=["export"]) == [a["scenario_id"]]
    assert ids(changed_inputs=["dri."]) == [b["scenario_id"]]
    assert ids(requested_outputs=["consolidated_pnl"]) == [b["scenario_id"]]
    assert ids(date_from="2026-05-05") == [b["scenario_id"]]
    assert ids(month_label="2026-04") == [b["scenario_id"], a["scenario_id"]]
    assert ids(month_label="2026-05") == []
    assert len(store.list_states("all")) == 3
    assert err(store.list_states, "scenarios", {"colour": "red"}).code == "schema_validation_error"


def test_open_working_from_scenario(store):
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    sc = store.commit_state("save_as_scenario", name="a")["scenario_id"]
    store.update_input("sales.EZDK.Rebar.local_kt", 140)
    assert err(store.open_working_from, sc).code == "missing_required_arg"
    store.open_working_from(sc, discard_changes=True)
    assert store.read("sales.EZDK.Rebar.local_kt") == 120
    s = store.session_summary()
    assert s["base_baseline_id"] == "baseline_2026-04"
    assert [c["path"] for c in s["net_changes"]] == ["sales.EZDK.Rebar.local_kt"]


def test_scenarios_older_than_twelve_months_are_pruned(db, clock):
    s = sm.StateStore(db, clock=clock)
    old = s.commit_state("save_as_scenario", name="old")["scenario_id"]
    clock.advance(days=200)
    new = s.commit_state("save_as_scenario", name="new")["scenario_id"]
    s.close()
    clock.advance(days=170)                       # 'old' is now > 12 months
    s2 = sm.StateStore(db, clock=clock)
    assert [x["id"] for x in s2.list_states("scenarios")] == [new]
    assert err(s2.get_state, old).code == "scenario_not_found"
    assert any(a["action"] == "retention_prune" for a in s2.audit_log())
    s2.close()


def test_delete_scenario_and_not_found_codes(store):
    sc = store.commit_state("save_as_scenario", name="x")["scenario_id"]
    store.delete_scenario(sc)
    assert err(store.get_state, sc).code == "scenario_not_found"
    assert err(store.get_state, "baseline_2030-01").code == "baseline_not_found"
    assert err(store.delete_scenario, "baseline_2026-04").code == "scenario_not_found"


def test_audit_records_commits(store):
    store.commit_state("save_as_scenario", name="x")
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    store.commit_state("promote_to_baseline", month_label="2026-05")
    actions = [a["action"] for a in store.audit_log()]
    assert actions[:3] == ["promote_to_baseline", "save_as_scenario", "bootstrap"]


# ---- schema module ---------------------------------------------------------------- #

def test_template_is_valid_and_legacy_states_are_not():
    schema.validate(baseline_file())
    import excel_io
    with pytest.raises(ModelError) as e:
        schema.validate(excel_io.extract_state(REFERENCE_WORKBOOK))
    assert e.value.code == "schema_validation_error"


def test_read_paths(store):
    assert store.read("dri.EZDK.mrmr") == 1.5
    assert store.read("*") == baseline_file()
    assert err(store.read, "dri.EZDK.nope").code == "invalid_path"
    assert err(store.read, "").code == "missing_required_arg"
