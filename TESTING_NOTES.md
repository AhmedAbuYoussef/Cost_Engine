# Testing Notes — Cost Engine

Living document for tolerance decisions, deferred work, and follow-ups
discovered during the test build. Items here must be revisited at every
quarterly state refresh; if a refresh brings finer-precision inputs the
matching tolerance/xfail should be tightened or removed.

---

## Tolerance widening — DRI conversion view (§1.3)

**Decision date:** 2026-04-24
**Cells affected:** 6 — Other Conversion, Total Conversion, Total Variable
Mfg Cost for both EZDK and ERM in `compute_dri_conversion`.
**Tolerance:** ±0.10 USD/t (vs default ±0.01).
**Reason:** the JSON's nine DRI conversion-item consumptions are stored at
1 dp / 3 dp display precision, while the Excel verification model carried
finer underlying precision. The engine keeps full float precision per brief
§5 (non-negotiable); the gap surfaces as a bounded drift of ≤0.05 USD/t on
the aggregate cells. Rulebook §13 already documents the data gap (back-
calculated dummies for ERM Nitrogen and Water; analogous issue for EZDK).
**TODO at next quarterly refresh:** when real consumption decimals replace
the dummies in `model_initial_state.json`, tighten `TOL_USD_PER_T_LE_AGGREGATE`
back to ±0.01 in `tests/test_cost_engine.py` and re-run. If the cells still
miss after real decimals are in, that's a new investigation.

---

## Out-of-scope-for-this-run integrity checks

Two of the six runtime integrity checks listed in brief §4.7 depend on the
P&L stage, which is not in scope for this Step 1 run (scope was DRI / billet
/ finished products + integrity checks):

- **Check 6 — Intercompany seller revenue = buyer cost.** Requires
  consolidated P&L stage. Implemented as a deferred stub that returns
  `(True, "deferred — requires P&L stage")` so the master callable is not
  bypassable structurally; the stub is wired into `run_integrity_checks`
  and will be replaced with the real implementation when P&L lands.
- **Check 7 — Break-even = 0 when Total Sales Qty = 0.** Same disposition
  as Check 6. The check itself is small but its inputs (per-product CM/t
  and total fixed) only exist after the P&L stage runs.

When the P&L stage is built, both stubs need to be replaced with real
implementations and the corresponding tests added.

---

## EZDK Rebar Sc2 home scrap typo (resolved)

The original `model_verification.md` had `(7.33)` for EZDK Rebar Sc2 Home
Scrap Deduction. Sc1 and Sc2 share identical inputs for this line item per
Rulebook §5.2 (`billets used × home-scrap % × byproduct price ÷ finished
qty` is independent of billet sourcing scenario), so Sc2 must equal Sc1 =
`(14.48)`. Corrected on 2026-04-24 along with the cascaded cells (Total
Conversion 42.37 → 35.23, Total VC 632.37 → 625.23, Difference (197.85) →
(190.71)). See the `## Corrections` block at the top of
`model_verification.md`.
