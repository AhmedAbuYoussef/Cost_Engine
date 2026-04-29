# Run Report — Cost Engine Step 1

**Session date:** 2026-04-24
**Branch:** `claude/build-cost-engine-ddAtB`
**Final test status:** **140 / 140 passing**

---

## Files created

| File | Purpose | LoC |
|---|---|---|
| `state_manager.py` | JSON load + sourcing-decision seeding + schema validation | ~110 |
| `cost_engine.py` | Pure-Python engine: DRI, billet, finished products, six integrity checks, `compute_all` | ~570 |
| `tests/conftest.py` | Session-scoped `state` fixture loading via `state_manager.load_state` | ~25 |
| `tests/test_cost_engine.py` | 140 assertions across every verified cell + guardrails + integrity-check happy/violation pairs | ~700 |
| `TESTING_NOTES.md` | Tolerance derivations + deferred-work log | ~140 |
| `.gitignore` | `__pycache__/`, `.pytest_cache/` | 3 |

Files corrected (one-time):
- `model_initial_state.json` — added `eaf_unit_prices_usd` for EFS/ESR (Part A
  scrap-price transcription from verification §2.1), full reconstructed-dummy
  EAF/BCCM blocks for EFS/ESR billet (Part B), `_reconciliation_residual_usd_per_ton`
  on every billet and finished-product producer block, full Rebar / Wire Rod /
  HRC consumption+price blocks for non-EZDK producers, new `flat_line_scrap_prices_usd`
  blocks on HRC (resolves the §3.3 Material Price gap), `/1000` unit-scale fix
  on four billet prices (refractories EAF, electrodes EAF, other_fillers EAF,
  BCCM refractories) and one rebar price (refractories rebar).
- `model_verification.md` — corrected the EZDK Rebar Sc2 home-scrap typo
  `(7.33) → (14.48)` and the three cascaded cells (Total Conversion 42.37 →
  35.23, Total VC 632.37 → 625.23, Difference (197.85) → (190.71)). Added
  `## Corrections` heading.

---

## Test count by class

| Test class | Verifies | Count |
|---|---|---|
| `TestStage1DRI_Detailed` | §1.2 EZDK + ERM, all line items + totals | 35 |
| `TestStage1DRI_Conversion` | §1.3 USD/t conversion view | 11 |
| `TestStage2Billet_Conversion` | §2.2 EZDK + EFS + ESR + dummy warnings + EZDK residual anchor | 16 |
| `TestStage2TradeoffMatrix` | §2.3 trade-off matrix entries + minima | 12 |
| `TestStage2MarketBilletBuildup` | §2.4 market price components | 4 |
| `TestStage3Rebar_Sc1` | §3.1 Sc1 all four producers | 13 |
| `TestStage3Rebar_Sc2` | §3.1 Sc2 all four + Sc1−Sc2 difference + ERM Sc1=Sc2 invariant | 8 |
| `TestStage3WireRod` | §3.2 EZDK formula chain (no target) | 3 |
| `TestStage3HRC` | §3.3 EZDK + EFS + dummy warnings | 9 |
| `TestSc1SourcingDispatch` | own/market/internal_minimum dispatch + illegal cases | 5 |
| `TestStrictFieldAccess` | engine raises on missing/illegal company×product | 3 |
| `TestIntegrityChecks_HappyPath` | 6 checks + 2 deferred stubs on clean state | 6 |
| `TestIntegrityChecks_Violations` | each check fires on broken state | 6 |
| `TestComputeAll` | top-level entry point + currency tags + production-matrix gating | 6 |
| Misc currency tags | output-view `_currency` smoke checks | 3 |

Total: **140 passing, 0 failing.**

---

## Decisions made autonomously (within delegated authority)

- **Module structure:** single `cost_engine.py` at ~570 LoC, well under the
  brief's 1100-line "split it" threshold. State loader split into
  `state_manager.py` per user direction.
- **Test framework:** pytest 9.0.2 with session-scoped fixture; deepcopy
  pattern for violation tests.
- **Tolerance bucket names** and per-class derivations — every widening has
  a stated upper-bound calculation in `TESTING_NOTES.md`, no magic numbers.
- **Internal helper signatures** (e.g., `_long_line_total_vc(state, company,
  product, material_price)`) — chosen so Sc1 and Sc2 share one chain with
  Material Price as the only differing input.
- **Integrity-check output format** — `(bool, detail_string)` tuples per
  brief §4.7; master `run_integrity_checks` runs in defined order and returns
  the full list (so the caller can stop at first failure or aggregate).
- **`compute_all` shape** — returns a flat dict keyed by view-name strings
  like `"finished_sc1_Rebar_EZDK"`, plus `_integrity_checks` for the audit
  trail. Production-matrix-gated so non-existent combinations don't appear.

## Decisions escalated to user (in chronological order)

1. EZDK Rebar Sc2 home-scrap typo in `model_verification.md` — approved fix.
2. Tolerance approach for the 6 USD/t cells in DRI §1.3 conversion view —
   approved option 3 (widen to ±0.10, document Rulebook §13 precedent).
3. Missing EFS/ESR billet input data — approved Part A (transcribe scrap
   prices) + Part B (clone-with-residual recipe).
4. JSON unit-scale mislabel on four `_kg` price entries — approved uniform
   `/1000` correction.
5. EZDK billet 0.45 USD/t residual gap (regression-anchor-vs-precision) —
   approved widening tolerance to ±0.60 with derivation rather than
   absorbing into residual.
6. Three Stage D issues (rebar refractories `/1000`, clone-with-residual
   for non-EZDK producers, HRC scrap prices distinct from billet) —
   approved as a batch with the new `flat_line_scrap_prices_usd` field.

Each escalation was triggered by the explicit guardrail
*"do not invent input fields, relax tolerance, or edit the verification
file"*. No tolerance was widened without a stated upper-bound derivation.

---

## Coverage map — verification file → engine

| Verification section | Engine entry point | Test class |
|---|---|---|
| §1.2 DRI Detailed (LE/t) | `compute_dri_detailed` | `TestStage1DRI_Detailed` |
| §1.3 DRI Conversion ($/t) | `compute_dri_conversion` | `TestStage1DRI_Conversion` |
| §2.2 Billet Conversion | `compute_billet_conversion` | `TestStage2Billet_Conversion` |
| §2.3 Trade-off Matrix | `compute_tradeoff_matrix` | `TestStage2TradeoffMatrix` |
| §2.4 Market Build-up | `_market_billet_price` | `TestStage2MarketBilletBuildup` |
| §3.1 Rebar Sc1+Sc2 | `compute_finished_sc1` / `compute_finished_sc2` | `TestStage3Rebar_*` |
| §3.2 Wire Rod EZDK | `compute_finished_sc1` | `TestStage3WireRod` |
| §3.3 HRC | `compute_hrc_summary` | `TestStage3HRC` |
| §4 Sales | (out of scope this run — no engine code) | — |
| §5 Production Cascade | (out of scope this run) | — |
| §6 Fixed Cost Allocation | (out of scope this run) | — |
| §7 Standalone P&L | (out of scope this run) | — |
| §8 Consolidated P&L | (out of scope this run) | — |

---

## Open issues for follow-up work

(Full details in `TESTING_NOTES.md`.)

1. **Real consumption decimals** to replace JSON-precision dummies for
   EZDK DRI, EZDK billet, and the cloned EFS/ESR/ERM/Wire-Rod/HRC blocks.
   When real data lands: tighten `TOL_BILLET_AGGREGATE`, `TOL_DRI_CONVERSION`,
   `TOL_FINISHED_SC1_TOTAL`, `TOL_FINISHED_TOTAL_CONVERSION` back toward
   the strict ±0.01–0.10 ranges.
2. **Reconciliation residuals** on EFS/ESR billet, EFS/ERM/ESR rebar, HRC
   EZDK/EFS — return to 0 once underlying consumption blocks stop being
   reconstructed dummies. A regression test mirroring
   `test_ezdk_residual_is_zero` should be added per producer.
3. **Integrity checks 6 and 7** are deferred-stub functions; replace with
   real implementations when the P&L stage lands. The master
   `run_integrity_checks` already calls them so wiring is in place.
4. **Rulebook §5.3 patch** — should explicitly state that HRC scrap prices
   are independent inputs from billet scrap prices. Verification §3.3
   already implies this; the JSON now carries the data; the rulebook
   should follow.
5. **Rulebook §12 patch** — count is 6 not 7 per Q3 ruling (drop check 3 by
   construction). System prompt Appendix D §6 needs the matching update.
6. **Out-of-scope-for-this-run engine pieces** to be built next:
   production cascade (§5), sales / market share aggregation (§4),
   fixed cost allocation (§6), standalone + consolidated P&L (§7, §8).
   Engine architecture (pure functions, dict-slice in/out, currency tags)
   is in place to absorb these.

---

## Final test output

```
140 passed in 0.10s
```

Branch state at session end:
```
ce4cbdd  Fix EZDK Rebar Sc2 home scrap typo and cascaded cells
f168b2c  WIP Stage A+B: scaffold, state_manager, DRI stage (44/50 tests passing)
ea767ea  Stage B green: widen DRI conversion-view tolerance to ±0.10 (50/50)
52a1115  Part A: transcribe EFS/ESR scrap prices from verification §2.1 into JSON
adf3216  WIP Stage C Commit 1: billet engine + EFS/ESR cloned dummies (67/84)
40239d1  Fix billet unit-scale: divide refractories/electrodes/other_fillers prices by 1000
5654a7d  Stage C green: populate EFS/ESR billet residuals; widen tolerance to ±0.60
3bb5567  Stage D green: finished products (Sc1/Sc2/HRC) + sourcing dispatch (122/122)
…       Stage E green: integrity checks + compute_all + final docs (140/140)
```
