# Run Report — Cost Engine Step 1 (governed line)

**Branch:** `claude/complete-pricing-model-stage-VvEl3`
**Status: IN PROGRESS — Step 4 partially landed (Excel-independent subset only)**
**Last update:** 2026-06-12 — suite green at **84 / 84**

This report tracks the governed line of work only. The disqualified
`claude/build-cost-engine-ddAtB` branch is not a source of code or data;
its audit lives in the session log (2026-06-12) and is not reproduced here.

---

## Build-order position (brief §9)

| Step | Scope | Status | Tests |
|---|---|---|---|
| 1 | Scaffold + Stage 1 DRI (both views, EZDK + ERM) | DONE | 9 → green |
| 2 | Stage 2 Billet EZDK detailed + trade-off framework + check 2 | DONE | 37 → green |
| 3 | EFS/ESR billet summary + full trade-off matrix + market build-up | DONE | 56 → green |
| 4 | Finished Products Sc1/Sc2 + sourcing dispatch + HRC | **IN PROGRESS** | 84 → green (Excel-independent subset) |
| 5–8 | Cascade, fixed allocation, P&Ls, compute_all/check wiring | NOT STARTED | — |

## Step 4 — landed in this sub-step (2026-06-12)

- `_require_finished_producer` structural guard (Rebar×4, Wire Rod×EZDK,
  HRC×{EZDK, EFS}).
- `sourcing_decision` conftest seeding: producers → `"own"`, ERM →
  `"market"`, Wire Rod EZDK → `"own"`; no field for HRC. No JSON edits.
- `_finished_material_price_sc1` / `_finished_material_price_sc2` dispatch:
  own (full-precision own billet VC), market (590), internal_minimum
  (cheapest EXTERNAL trade-off offer; ERM → 457.97 via ESR), illegal-value
  / missing / ERM-"own" raises.
- `_finished_yield_effect`; §3.1 Sc1 + Sc2 Material Price and Yield Effect
  rows asserted for all four companies.
- EZDK Rebar Sc1 Home Scrap Deduction asserted (−14.49 vs sheet −14.48,
  standard ±0.01).
- ERM Sc1 = Sc2 invariant under market sourcing.
- `compute_finished_sc1/sc2` (long line), `compute_hrc_summary` skeleton
  (full-precision combined-yield identity + blending echo asserted).
- `_currency: "USD"` tags on all new output views.
- Rebar EFS/ERM/ESR + HRC Other Conversion scalars conftest-seeded per
  item-3/item-6 rulings (plumbing only; no assertions yet).

## Step 4 — deliberately pending (awaiting Excel-confirmed values)

| Pending group | Cells | Blocking input |
|---|---|---|
| (a) | EZDK Rebar Sc2 Home Scrap + Total Conversion + Total VC + Difference | User's Excel check of the 7.33-vs-14.48 fork |
| (b) | HRC Material Price (280.73 / 299.96) + Yield Effect | `flat_line_scrap_prices_usd` (user-supplied; independent of billet scrap prices; never back-solved) |
| (c) NEW | §3.3 Combined Yield sheet cells (82.37 / 81.43) | Sheet cells disagree with full-precision yield product AND the sheet's own Yield Effect row — see TESTING_NOTES.md "Step 4" |
| — | EZDK Rebar Other Conversion + Total VC (both scenarios) | Excel formula-bar unit prices (suspected display-rounded NG/water); per direction: no tolerance widening |
| — | EFS/ERM/ESR Rebar Home Scrap + totals + Difference | Excel-confirmed home-scrap % + byproduct prices |
| — | HRC Other Conversion + Total VC (summary-level) | Item-6 wiring sub-step |

## Test count by class (84 total)

| Class | Count |
|---|---|
| TestStage1DRI_Detailed / _Conversion | 9 |
| TestStage2BilletEZDK_Conversion / _Detailed | 17 |
| TestStage2BilletEFS_Summary / ESR_Summary | 10 |
| TestSc2Dispatch_BilletMode | 4 |
| TestStage2TradeoffMatrix_Full / MarketBilletBuildup | 12 |
| TestIntegrityCheck2_Blending | 4 |
| TestFinishedProducerGuard | 5 |
| TestSc1SourcingDispatch | 7 |
| TestStage3Rebar_Sc1 / _Sc2 | 8 |
| TestStage3WireRod_Structural | 4 |
| TestStage3HRC_Skeleton | 4 |

Tolerance discipline: brief §6 defaults (±0.01 USD 2dp, ±1 LE integer) with
per-cell documented overrides only — full register and derivations in
TESTING_NOTES.md.
