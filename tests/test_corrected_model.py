"""The corrected model: each fix behaves as documented in MODEL_FIXES.md, the model is
internally consistent, and the shipped baseline is reproducible from the workbook."""

import copy
import json
import os

import pytest

import cost_engine as ce
import model_fixes
from conftest import ROOT


@pytest.fixture(scope="module")
def corrected_base(reference_state):
    state, _ = model_fixes.to_corrected(reference_state)
    return state


@pytest.fixture
def cs(corrected_base):
    return copy.deepcopy(corrected_base)


def run(state):
    return ce.compute_all(state)


def usd(out):
    return out["pnl"]["usd_monthly"]["columns"]


# ---- the baseline ----------------------------------------------------------- #

def test_shipped_baseline_is_regenerated_from_workbook(corrected_base):
    with open(os.path.join(ROOT, "model_initial_state.json")) as f:
        shipped = json.load(f)
    assert shipped == json.loads(json.dumps(corrected_base)), \
        "model_initial_state.json is stale — run `python model_fixes.py`"


def test_baseline_passes_every_integrity_check(cs):
    out = ce.compute_all(cs, strict=True)
    assert {c["check"] for c in out["integrity"]} == {
        "fixed_distribution_100", "blending_100", "no_hardcoded_results", "currency_tagged",
        "break_even_zero", "intercompany_reconciles", "summary_matches_detail"}
    assert all(c["passed"] for c in out["integrity"])


def test_corrected_state_has_no_legacy_artefacts(cs):
    text = json.dumps(cs)
    assert cs["rules_profile"] == "corrected"
    assert cs["billet"]["tradeoff_overrides"] == {}
    for legacy_key in ("export_expense_rate", "intercompany_gain_dri_musd", "same_as",
                       "billet_price", "selling_price_source"):
        assert legacy_key not in text, legacy_key
    assert "dri_margin_from_erm_usd_t" not in cs["flat"]["EFS"]


def test_every_rule_is_on(cs):
    assert run(cs)["rules"] == ce.CORRECTED_RULES


@pytest.mark.parametrize("rule", sorted(ce.RULES))
def test_each_rule_can_be_switched_off_alone(cs, rule):
    """Every fix is independent: the model runs with any single one switched off."""
    out = ce.compute_all(cs, rules={**ce.CORRECTED_RULES, rule: False})
    assert out["consolidated"]["usd_monthly"]["consolidated"]["ebt"] is not None


def test_bridge_ends_at_the_corrected_model(reference_state, cs):
    rows = model_fixes.bridge(reference_state)
    assert rows[0][3]["Group EBT"] == pytest.approx(-10.869771756723049, abs=1e-9)
    final = run(cs)["consolidated"]["usd_monthly"]["consolidated"]["ebt"]
    assert rows[-1][3]["Group EBT"] == pytest.approx(final, abs=1e-9)


# ---- A1 export expenses ---------------------------------------------------------- #

def test_export_expenses_scale_with_volume(cs):
    assert cs["pnl"]["export_expense_usd_t"]["EZDK"]["HRC"] == pytest.approx(20.0)
    base = usd(run(cs))["EZDK/HRC"]["export_expenses"]
    assert base == pytest.approx(40 * 20 / 1000)          # 40 kt × $20/t
    cs["sales"]["EZDK"]["HRC"]["export_kt"] *= 2
    assert usd(run(cs))["EZDK/HRC"]["export_expenses"] == pytest.approx(2 * base)


# ---- A2/A3/B6 exports and annual views -------------------------------------------- #

def test_rebar_exports_are_produced_and_priced(cs):
    base = run(cs)
    cs["sales"]["EFS"]["Rebar"]["export_kt"] = 10.0
    out = run(cs)
    c = usd(out)["EFS/Rebar"]
    assert c["export_value"] == pytest.approx(10 * cs["sales"]["EFS"]["Rebar"]["export_price_usd_t"] / 1000)
    added = out["production"]["long"]["EFS"]["rebar"] - base["production"]["long"]["EFS"]["rebar"]
    assert added == pytest.approx(10.0)
    assert out["production"]["long"]["EFS"]["billet"] > base["production"]["long"]["EFS"]["billet"]


@pytest.mark.parametrize("key", ["total_qty", "total_value", "variable_cogs", "export_expenses",
                                 "contribution_margin", "total_fixed", "ebtd", "depreciation", "ebt"])
def test_annual_is_twelve_months(cs, key):
    cs["sales"]["EZDK"]["Rebar"]["export_kt"] = 5.0
    cs["sales"]["ESR"]["Rebar"]["export_kt"] = 3.0
    out = run(cs)
    m, a = out["pnl"]["usd_monthly"]["columns"], out["pnl"]["usd_annual"]["columns"]
    for col in m:
        assert a[col][key] == pytest.approx(12 * m[col][key], rel=1e-12, abs=1e-12), col


@pytest.mark.parametrize("key", ["total_value", "variable_cogs", "export_expenses",
                                 "contribution_margin", "total_fixed", "ebt"])
def test_le_is_usd_times_fx(cs, key):
    out = run(cs)
    fx = cs["fx_egp_per_usd"]
    m, le = out["pnl"]["usd_monthly"]["columns"], out["pnl"]["le_monthly"]["columns"]
    for col in m:
        assert le[col][key] == pytest.approx(fx * m[col][key], rel=1e-12, abs=1e-12), col


# ---- A4, A5 ------------------------------------------------------------------------ #

def test_erm_dri_volume_covers_all_its_customers(cs):
    out = run(cs)
    d = out["detail"]
    expected = d["EFS Rebar"]["s1.t.dri"] + d["EFS Flat"]["s1.t.dri"] + d["ESR Rebar"]["s1.t.dri"]
    assert out["dri"]["ERM"]["production_t"] == pytest.approx(expected)
    assert usd(out)["ERM/DRI"]["total_qty"] == pytest.approx(expected / 1000)


def test_hrc_market_share(cs):
    out = run(cs)
    assert out["market_share"]["group_local_kt"]["HRC"] == pytest.approx(45 + 7.5)
    assert out["market_share"]["ezz_share_pct"]["HRC"] is None      # market size unknown
    cs["total_local_market_kt"]["HRC"] = 200.0
    out = run(cs)
    assert out["market_share"]["ezz_share_pct"]["HRC"] == pytest.approx(52.5 / 200 * 100)
    assert out["market_share"]["company_pct_of_group"]["HRC"]["EFS"] == pytest.approx(7.5 / 52.5 * 100)


# ---- A6/A7 data fixes ------------------------------------------------------------- #

def test_data_fixes(cs):
    assert cs["billet"]["companies"]["ESR"]["electricity_usd_kwh"] == pytest.approx(0.07)
    for co in ce.BILLET_PRODUCERS:
        assert sum(cs["billet"]["companies"][co]["blend_pct"].values()) == pytest.approx(100)


def test_blend_with_home_scrap_is_checked_and_costed(cs):
    """Home scrap is a charge material too: it must be in the blend total and in the
    billet summary's material price."""
    cs["detail"]["EZDK Rebar"]["stage1"]["blend_pct"]["home_scrap"] = 0.05
    cs["detail"]["EZDK Rebar"]["stage1"]["prices_usd"]["home_scrap_t"] = 250.0
    out = run(cs)
    checks = {c["check"]: c["passed"] for c in out["integrity"]}
    assert not checks["blending_100"]            # 105% now
    assert checks["summary_matches_detail"]      # home scrap is in both
    cs["billet"]["companies"]["EZDK"]["blend_pct"]["imported_scrap"] -= 5
    assert all(c["passed"] for c in run(cs)["integrity"])


# ---- B1 billet sourcing and cascade -------------------------------------------------- #

def test_erm_buys_from_cheapest_source(cs):
    out = run(cs)
    t = out["billet"]["tradeoff"]
    assert out["sourcing"]["price_usd_t"] == pytest.approx(t["minimum"]["ERM"])
    assert out["sourcing"]["supplier"] == t["cheapest_source"]["ERM"] == "EZDK"
    assert t["rows"]["EZDK"]["ERM"] == pytest.approx(
        out["billet"]["EZDK"]["total_variable_cost"] * cs["billet"]["companies"]["EZDK"]["tradeoff_ratio"])


def test_internal_purchase_raises_supplier_production(cs):
    out = run(cs)
    d = out["detail"]
    own = d["EZDK Rebar"]["s3.feed.produced_t"] + d["EZDK Wire"]["billets_t"]
    assert d["EZDK Rebar"]["s2.output_t"] - own == pytest.approx(d["ERM Rolling"]["t.produced"])
    assert "EZDK/Billet" in usd(out)
    # buying from the market instead: EZDK produces less, no intercompany billet sale
    cs["sourcing"]["ERM_rebar_billet"] = "market"
    out2 = run(cs)
    assert "EZDK/Billet" not in usd(out2)
    assert out2["detail"]["EZDK Rebar"]["s2.output_t"] == pytest.approx(own)
    assert out2["production"]["long"]["EZDK"]["dri"] < out["production"]["long"]["EZDK"]["dri"]


def test_buying_from_esr_moves_the_volume_to_esr(cs):
    base = run(cs)
    cs["sourcing"]["ERM_rebar_billet"] = "offer:ESR"
    out = run(cs)
    assert "ESR/Billet" in usd(out) and "EZDK/Billet" not in usd(out)
    added = out["detail"]["ESR Rebar"]["s1.billets_t"] - base["detail"]["ESR Rebar"]["s1.billets_t"]
    assert added == pytest.approx(out["detail"]["ERM Rolling"]["t.produced"])
    assert all(c["passed"] for c in out["integrity"])


@pytest.mark.parametrize("change", ["tradeoff_ratio", "dri_margin"])
def test_intercompany_prices_do_not_change_group_profit(cs, change):
    """A transfer price moves profit between companies, never the group's."""
    base = run(cs)
    if change == "tradeoff_ratio":
        cs["sourcing"]["ERM_rebar_billet"] = "offer:EZDK"
        base = run(cs)
        cs["billet"]["companies"]["EZDK"]["tradeoff_ratio"] *= 1.05
        movers = ("EZDK", "ERM")
    else:
        cs["billet"]["companies"]["ESR"]["dri_margin_from_erm_usd_t"] += 10
        movers = ("ESR", "ERM")
    out = run(cs)
    g0 = base["consolidated"]["usd_monthly"]["consolidated"]
    g1 = out["consolidated"]["usd_monthly"]["consolidated"]
    assert g1["ebt"] == pytest.approx(g0["ebt"], abs=1e-9)
    assert g1["total_value"] == pytest.approx(g0["total_value"], abs=1e-9)
    a, b = (usd(out)[f"{c}/Sub-Total"]["ebt"] - usd(base)[f"{c}/Sub-Total"]["ebt"] for c in movers)
    assert a == pytest.approx(-b) and abs(a) > 0.01


# ---- B2 ERM DRI P&L and consolidation -------------------------------------------------- #

def test_erm_fixed_costs_follow_distribution(cs):
    out = run(cs)
    cols, fc = usd(out), cs["fixed_cost"]["ERM"]
    assert cols["ERM/DRI"]["manufacturing_fixed"] == pytest.approx(0.70 * fc["manufacturing_musd"])
    assert cols["ERM/Rebar"]["manufacturing_fixed"] == pytest.approx(0.30 * fc["manufacturing_musd"])
    assert cols["ERM/Sub-Total"]["total_fixed"] == pytest.approx(
        fc["manufacturing_musd"] + fc["sga_musd"] + fc["net_finance_musd"])
    assert cols["ERM/Rebar"]["intercompany_gain_dri"] is None


def test_erm_dri_margin_is_computed(cs):
    out = run(cs)
    d = out["detail"]
    m = cs["billet"]["companies"]
    expected = (m["EFS"]["dri_margin_from_erm_usd_t"] * (d["EFS Rebar"]["s1.t.dri"] + d["EFS Flat"]["s1.t.dri"])
                + m["ESR"]["dri_margin_from_erm_usd_t"] * d["ESR Rebar"]["s1.t.dri"]) / 1e6
    assert usd(out)["ERM/DRI"]["contribution_margin"] == pytest.approx(expected)


def test_consolidation_eliminates_intercompany_sales(cs):
    out = run(cs)
    cols = usd(out)
    con = out["consolidated"]["usd_monthly"]
    interco = cols["ERM/DRI"]["total_value"] + cols["EZDK/Billet"]["total_value"]
    assert con["eliminations"]["total_value"] == pytest.approx(-interco)
    assert con["eliminations"]["variable_cogs"] == pytest.approx(-interco)
    external = sum(c["total_value"] for c in cols.values() if "product" in c and not c["intercompany"])
    assert con["consolidated"]["total_value"] == pytest.approx(external)
    assert con["consolidated"]["contribution_margin"] == pytest.approx(cols["Total"]["contribution_margin"])
    assert con["consolidated"]["ebt"] == pytest.approx(cols["Total"]["ebt"])
    local_q = sum(c["local_qty"] for c in cols.values() if "product" in c and not c["intercompany"])
    assert con["consolidated"]["local_qty"] == pytest.approx(local_q)


# ---- B4 break-even --------------------------------------------------------------- #

def test_break_even_uses_contribution_margin(cs):
    out = run(cs)
    for key, c in usd(out).items():
        if c["total_qty"] and c["cm_per_t"] and c["cm_per_t"] > 0:
            assert c["break_even_qty"] == pytest.approx(
                (c["total_fixed"] + c["depreciation"]) * 1000 / c["cm_per_t"]), key
            assert c["cash_break_even_qty"] == pytest.approx(c["total_fixed"] * 1000 / c["cm_per_t"]), key
        elif c["total_qty"]:
            assert c["break_even_qty"] is None, key      # every ton loses money


# ---- C summaries ------------------------------------------------------------------ #

def test_summaries_equal_detail(cs):
    out = run(cs)
    assert out["billet"]["EZDK"]["total_variable_cost"] == pytest.approx(
        out["detail"]["EZDK Rebar"]["s2.variable_cost"], rel=1e-12)
    assert out["flat"]["EFS"]["total_variable_cost"] == pytest.approx(
        out["detail"]["EFS Flat"]["s3.variable_cost"], rel=1e-12)
    assert out["rebar"]["ERM"]["sc1"]["total_variable_cost"] == pytest.approx(
        usd(out)["ERM/Rebar"]["cost_per_t"], rel=1e-12)
