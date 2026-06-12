"""Pytest fixtures for the Ezz Steel cost-engine test suite.

The baseline JSON state is loaded once per session and deep-copied per test
so mutations cannot bleed between tests.
"""

import copy
import json
import os
import sys

import pytest


_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_STATE_PATH = os.path.join(_PROJECT_ROOT, "model_initial_state.json")

# Make cost_engine importable when pytest is run from anywhere.
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


@pytest.fixture(scope="session")
def _baseline_state():
    with open(_STATE_PATH, "r") as f:
        return json.load(f)


@pytest.fixture
def state(_baseline_state):
    """Per-test deep copy with the reconciliation residual block and the
    step-3 EFS/ESR billet summary fields seeded.

    None of these additions are written into model_initial_state.json per
    brief §11 forward log; state_manager.py / SQLite is the eventual home
    for persistence.

    Seeded fields:

    1. Reconciliation residual (step 2):
       state["reconciliation"]["billet_EZDK_excel_to_engine_usd_t"] = 0.499
       Closes the structural Excel-to-engine gap at EZDK billet Other
       Conversion. See TESTING_NOTES.md "Stage 2 — EZDK Billet Reconciliation".

    2. EFS billet inputs (step 3) — sourced from model_verification.md:
       - eaf_unit_prices_usd.local_scrap_t    = 270.10 (verification §2.1)
       - eaf_unit_prices_usd.imported_scrap_t = 307.56 (verification §2.1)
       - summary_other_conversion_usd_per_ton = 107.26 (verification §2.2)
       JSON has only yields/blending/trade-off ratio for EFS; the rest is
       reconstructed dummies satisfying the summary output 467.96 $/t. The
       engine consumes these via the "summary_fitted" billet_mode dispatch.

    3. ESR billet inputs (step 3) — same pattern:
       - eaf_unit_prices_usd.local_scrap_t    = 270.10 (verification §2.1)
       - eaf_unit_prices_usd.imported_scrap_t = 307.56 (verification §2.1)
       - summary_other_conversion_usd_per_ton =  97.97 (verification §2.2)
       Summary output 450.31 $/t.

    When real Excel data lands for EFS/ESR detailed EAF+BCCM, the engine's
    billet_mode dispatch will pick up the "detailed_with_residual" path on
    detection of `eaf_consumptions_per_ton_ms`; the summary_other_conversion
    seed should then be removed.
    """
    s = copy.deepcopy(_baseline_state)

    # Step 2 — EZDK reconciliation residual.
    s.setdefault("reconciliation", {})
    s["reconciliation"]["billet_EZDK_excel_to_engine_usd_t"] = 0.499

    # Step 3 — EFS billet summary inputs.
    s["billet"]["EFS"]["eaf_unit_prices_usd"] = {
        "local_scrap_t":    270.10,
        "imported_scrap_t": 307.56,
    }
    s["billet"]["EFS"]["summary_other_conversion_usd_per_ton"] = 107.26

    # Step 3 — ESR billet summary inputs.
    s["billet"]["ESR"]["eaf_unit_prices_usd"] = {
        "local_scrap_t":    270.10,
        "imported_scrap_t": 307.56,
    }
    s["billet"]["ESR"]["summary_other_conversion_usd_per_ton"] = 97.97

    # Step 4 — sourcing_decision defaults (brief §4.3 Q2 ruling): producers
    # → "own", ERM → "market". HRC is flat-line (no billet) and carries no
    # sourcing_decision.
    for co in ("EZDK", "EFS", "ESR"):
        s["finished_products"]["Rebar"][co]["sourcing_decision"] = "own"
    s["finished_products"]["Rebar"]["ERM"]["sourcing_decision"] = "market"
    s["finished_products"]["Wire Rod"]["EZDK"]["sourcing_decision"] = "own"

    # Step 4 — EFS/ERM/ESR Rebar Other Conversion seeded as per-company
    # scalars from verification §3.1 Sc1 (item-3 ruling; Step 3 EFS/ESR
    # billet precedent). The Sc1 line item is plumbing-verified only; the
    # Sc2 column and Difference line are the non-circular cross-check once
    # home-scrap inputs land. Real consumption detail replaces these at the
    # quarterly refresh. See TESTING_NOTES.md "Step 4".
    s["finished_products"]["Rebar"]["EFS"]["summary_other_conversion_usd_per_ton"] = 11.32
    s["finished_products"]["Rebar"]["ERM"]["summary_other_conversion_usd_per_ton"] = 17.18
    s["finished_products"]["Rebar"]["ESR"]["summary_other_conversion_usd_per_ton"] = 20.64

    # Step 4 — HRC Other Conversion scalars from verification §3.3 (item-6
    # ruling; Q4-extension, summary-level assertions only).
    s["finished_products"]["HRC"]["EZDK"]["summary_other_conversion_usd_per_ton"] = 108.87
    s["finished_products"]["HRC"]["EFS"]["summary_other_conversion_usd_per_ton"] = 128.60

    # Step 4 — NOT seeded (pending Excel-confirmed values from the user):
    # - EFS/ERM/ESR Rebar home_scrap_pct_of_billets_used / byproduct_price_usd_t
    # - HRC flat_line_scrap_prices_usd (independent of billet scrap prices)
    # - EZDK Rebar unit-price overrides (suspected display-rounded NG/water)

    return s
