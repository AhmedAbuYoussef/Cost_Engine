# Step 1 Brief — `cost_engine.py` (v2, locked for implementation)

**Companion to:** `EzzSteel_FinancialModel_Rulebook.md`, `model_initial_state.json`, `model_verification.md`, `ezz_steel_bot_system_prompt_v2.md` (Appendix C §1, Appendix D §6).

**Purpose:** Pin down the scope, architecture, interface, and test plan for `cost_engine.py` **before writing code**, so the build is a mechanical translation of an agreed spec rather than an open-ended exercise.

**Status:** v2 — all open questions resolved. Ready for implementation in Claude Code.

**Changes from v1:**
- §8 open questions closed. Locked decisions moved into the body of the brief where they belong.
- §4.3 Finished Products — Sc1 material-price rule rewritten to reflect producer-own-VC rule (Q1).
- §4.7 Integrity checks — count reduced from 7 to 6; check 3 dropped by design, check 5 reframed as runtime view-currency-consistency check (Q3).
- §5 Precision discipline — full-precision rule confirmed explicitly (Q5).
- §7 File layout — confirmed package root.
- New §11 — CHANGES/open-flags forward log.

---

## 1. Goal & done-criterion

**Goal.** A pure-Python module that, given the initial-state JSON, reproduces every number in `model_verification.md` — EZDK as the cell-for-cell reference, EFS/ERM/ESR at the summary level (since their detailed consumptions are dummies satisfying only the summary outputs).

**Done-criterion (Appendix C §1, verbatim):**
> Every number in `model_verification.md` reproduces within rounding tolerance.

Operationalized: a `tests/test_cost_engine.py` runs assertions against every value in §1 through §8 of the verification sheet and all assertions pass. No assertion passes because of a hand-tuned fudge factor; every value falls out of the formulas in the rulebook applied to the JSON state.

Until this test file is green, Step 2 (`state_manager.py`) does not start.

---

## 2. Scope — what's in Step 1, what's explicitly deferred

### In scope
- All formulas from Rulebook §3–§8 (DRI cost, Billet cost, Finished Products cost, Sales & Production cascade, Fixed Cost allocation, P&L standalone, P&L consolidated with eliminations).
- The trade-off matrix (§4.6) computed fully dynamically — no hardcoded cells anywhere.
- **Six** integrity checks (Rulebook §12 minus check 3, plus check 5 reframed as a runtime view-currency-consistency check — see §4.7 of this brief). Each is a separate function returning `(bool, detail_string)`, plus a master function that runs them in order and reports the first failure.
- A `compute_all(state)` top-level function that returns a fully-populated outputs dict matching the structure of the verification sheet.
- `tests/test_cost_engine.py` with one assertion per verification-sheet cell.

### Explicitly deferred to later steps
- SQLite persistence, baseline/scenario semantics, working-state checkpoints (Step 2).
- Any tool wiring, LLM routing, Gradio UI (Steps 3–6).
- The optimizer (`find_optimal_mix`) — Step 8, gated on Appendix D verification cases.
- XLSX refresh template generation (Step 3 via `manage_baseline_refresh`).
- Chart rendering — the engine emits numeric outputs only; charts are the UI's job.

### Out of scope forever
- Any arithmetic that isn't driven by the rulebook formulas. The engine computes; it does not estimate.
- Any I/O inside calculation functions. State flows in as a dict, outputs flow out as a dict. File read/write lives at module boundary only (loading the JSON in tests).

---

## 3. Module architecture

Single module, `cost_engine.py`. Pure-function design:

- Every calculation function takes a dict-slice of state (plus scalar args where needed) and returns a dict-slice of outputs. No globals, no class state, no hidden caches.
- No randomness, no clock reads, no network, no file I/O. Deterministic: same state → same outputs bit-for-bit.
- No LLM calls. The engine is stupid on purpose — it's the trust anchor the bot reports from under Rule 1 ("Never Calculate").
- Full precision held in float throughout. Rounding is the caller's job (display layer). The rulebook's §2.3 precision rule is enforced at the *presentation* boundary, not inside the engine.
- No `eval`, no dynamic attribute magic, no metaprogramming. Every function has an explicit signature; every calculation is traceable by reading the source top to bottom.

The top-level entry point:

```python
def compute_all(state: dict) -> dict:
    """
    Given the full model state (same shape as model_initial_state.json),
    return a dict containing every output the verification sheet defines.
    Runs integrity checks first; raises IntegrityError on failure.
    """
```

Secondary public entry points (for the tools to call individual views):

```python
def compute_dri_detailed(state, company)          -> dict   # Verification §1.2
def compute_dri_conversion(state, company)        -> dict   # §1.3
def compute_billet_detailed(state, company)       -> dict   # §2 + rulebook §4.2, §4.3
def compute_billet_conversion(state, company)     -> dict   # §2.2
def compute_tradeoff_matrix(state)                -> dict   # §2.3
def compute_finished_sc1(state, company, product) -> dict   # §3.1 Sc1
def compute_finished_sc2(state, company, product) -> dict   # §3.1 Sc2
def compute_production_cascade(state)             -> dict   # §5
def compute_fixed_allocation(state)               -> dict   # §6
def compute_standalone_pnl(state, company)        -> dict   # §7
def compute_consolidated_pnl(state)               -> dict   # §8
def run_integrity_checks(state)                   -> list[tuple[bool, str]]
```

Each secondary function is independently callable so tools can serve narrow queries ("just the EZDK billet conversion sheet") without computing everything.

**Every output dict carries a `"_currency"` tag** — either `"USD"` or `"EGP"` — declaring the view's native currency. This powers integrity check 5 (§4.7 of this brief).

---

## 4. Function inventory, keyed to rulebook sections

### 4.1 Stage 1 — DRI (Rulebook §3)

| Function | Returns | Notes |
|---|---|---|
| `_dri_iop_cost_le(mrmr, iop_le_ton)` | LE/t | MRMR × IOP landed (EGP) |
| `_dri_conversion_line_le(consumption, unit_price)` | LE/t | For each of the nine conversion items |
| `_dri_variable_cost_le(company_dri_state)` | LE/t | Sum of IOP + nine conversion items |
| `_dri_fixed_cost_le(fixed_costs_le, production_volume)` | LE/t | (Labor + Dep + Other) ÷ volume |
| `_dri_mrmr_effect_usd(mrmr, iop_usd_ton)` | $/t | (MRMR − 1) × IOP $ |
| `_dri_other_conversion_usd(variable_cost_le, iop_cost_le, fx)` | $/t | (VC − IOP cost) ÷ FX |
| `compute_dri_detailed(state, company)` | dict (EGP) | Verification §1.2 full breakdown |
| `compute_dri_conversion(state, company)` | dict (USD) | Verification §1.3 view |

The DRI selling price (§3.4) is input-only; no computation. It feeds Stage 2 via `_resolve_dri_price_for_buyer()` below.

### 4.2 Stage 2 — Billet (Rulebook §4)

For **EZDK only**, full detailed EAF + BCCM build-up (the JSON has real consumptions). For **EFS and ESR**, the detailed block is dummies — the engine computes them but the only assertion we can make at the summary level is the `Total Variable Mfg Cost` matches the verification sheet (467.96 and 450.31 $/t respectively). Output for EFS/ESR detailed view carries `"_note": "detailed breakdown is reconstructed; only summary total is verified"` (Q4 ruling: Option (a) — compute and flag).

| Function | Returns | Notes |
|---|---|---|
| `_resolve_dri_price_for_buyer(state, buyer)` | $/t | EZDK → own DRI VC; EFS → ERM DRI VC; ESR → ERM DRI VC + intercompany margin (§4.5) |
| `_eaf_material_cost_per_ton_ms(blending_pct, unit_prices_usd, eaf_yield, dri_price_usd)` | $/t MS | Per-material: (Blending % ÷ EAF Yield) × Unit Price, summed |
| `_eaf_byproduct_credit(solid_charge, byproduct_pct, byproduct_price, ms_tons)` | $/t MS | Negative number |
| `_eaf_conversion_cost_per_ton_ms(consumptions, unit_prices)` | $/t MS | Sum of all conversion items |
| `_eaf_variable_cost_per_ton_ms(...)` | $/t MS | Materials + byproduct + conversion |
| `_bccm_variable_cost_per_ton_billet(ms_vc_per_ton, ccp_yield, bccm_consumptions, bccm_prices)` | $/t billet | MS carried + BCCM add-ons |
| `compute_billet_detailed(state, company)` | dict (USD) | EAF stage + BCCM stage; EZDK only has real numbers |
| `_billet_material_price_summary(blending_pct, prices)` | $/t | Rulebook §4.4: weighted average of DRI/LS/IS prices |
| `_billet_yield_effect(material_price, combined_yield)` | $/t | Material × (1/combined − 1) |
| `compute_billet_conversion(state, company)` | dict (USD) | Material + Yield Effect + Other Conversion + Total VC |
| `_intercompany_billet_price(seller_vc, seller_tradeoff_ratio)` | $/t | §4.6 |
| `_market_billet_price(state)` | $/t | Base + Safe Guards + Other Costs |
| `compute_tradeoff_matrix(state)` | dict (USD) | Rows: sources (EZDK, EFS, ESR, Market); cols: buyers; min per buyer |

**Trade-off matrix design:** ERM never appears as a *source* row (it doesn't produce billet). It appears as a *buyer* column. The minimum across sources for each buyer is computed and displayed. The matrix is **a view, not a pipeline step** — it is never read during default P&L generation. It is consumed only by reports, scenario analysis, and (later) the optimizer.

### 4.3 Stage 3 — Finished Products (Rulebook §5)

**Sc1 material price rule (Q1 — locked):**

| Company | Role | Default Sc1 source | Why |
|---|---|---|---|
| EZDK | Producer | Own billet VC (409.52) | Own EAF is running and cannot be economically shut down |
| EFS | Producer | Own billet VC (467.96) | Same — EFS uses own VC even though ESR offers a cheaper external price (457.97) |
| ESR | Producer | Own billet VC (450.31) | Same |
| ERM | Non-producer | Market ($590) by default; user can switch to internal minimum from trade-off matrix | No own EAF — must buy; sourcing is a user decision per Rulebook §4.7 |

**Rationale for producer-own-VC rule:** EZDK, EFS, and ESR each operate their own electric arc furnaces. EAFs carry very large fixed operating costs (labor, refractory maintenance, standby power) that continue whether they produce or not. Cold-starting an EAF is expensive and slow. Producers therefore keep their furnaces running and consume their own billet at their own VC, using external sourcing only under force-majeure conditions when their own production is halted. The trade-off matrix is **decision-support** — it shows what external sourcing would cost — but it does not drive Sc1 automatically for producers.

**State representation (Q2 — locked):**

New field at `state["finished_products"][product][company]["sourcing_decision"]`. Legal values:

- `"own"` — use own billet VC. Default for EZDK, EFS, ESR.
- `"market"` — use market price ($590). Default for ERM.
- `"internal_minimum"` — use the cheapest external offer from the trade-off matrix. User-selectable for ERM; user-selectable for producers only in force-majeure scenarios.

The engine reads this flag from state. No automatic "pick the cheapest" logic anywhere in the default path.

**Functions:**

| Function | Returns | Notes |
|---|---|---|
| `_finished_material_price_sc1(state, company, product)` | $/t | Dispatches on `sourcing_decision`: own → own billet VC; market → 590; internal_minimum → trade-off matrix minimum across external sources only |
| `_finished_material_price_sc2(state)` | $/t | Market: always $590 regardless of state |
| `_finished_yield_effect(material_price, finished_yield)` | $/t | Material × (1/yield − 1). Finished yield only — EAF × CCP already embedded in billet cost |
| `_finished_home_scrap_deduction(billets_used, home_scrap_pct, byproduct_price, finished_qty)` | $/t | Negative |
| `_finished_other_conversion(consumptions, prices)` | $/t | Refractories + electricity + NG + water + work roll |
| `compute_finished_sc1(state, company, product)` | dict (USD) | Rulebook §5.2 |
| `compute_finished_sc2(state, company, product)` | dict (USD) | §5.1 with market material price |
| `compute_hrc_summary(state, company)` | dict (USD) | Three-stage yield chain; Rulebook §5.3 |
| `_fixed_cost_per_finished_ton(product_total_fixed_usd, production_qty_tons)` | $/t | §5.4 |

### 4.4 Production cascade (Rulebook §6)

Sales drive production, as per integrity check 4. Given per-company per-product sales, cascade upstream to billet, molten steel, solid charge, DRI, scrap, and IOP.

| Function | Returns | Notes |
|---|---|---|
| `compute_production_cascade(state)` | dict | Nested by company and line (long line vs flat line), ending at IOP |
| `_long_line_cascade(rebar_qty, wire_qty, rebar_yield, wire_yield, yields, blending, mrmr)` | dict | §6.4 |
| `_flat_line_cascade(hrc_qty, yields, blending, mrmr)` | dict | §6.5 |
| `_erm_dri_supply_aggregation(state)` | dict | ERM DRP supplies EFS + ESR; IOP for ERM = (EFS DRI + ESR DRI) × MRMR_ERM |

### 4.5 Fixed cost allocation (Rulebook §7)

| Function | Returns | Notes |
|---|---|---|
| `compute_fixed_allocation(state)` | dict (USD) | Per company per product: Mfg / SG&A / NetFin / Dep, each × distribution % |
| `_fixed_cost_per_ton(allocated_fixed_usd_m, production_qty_tons)` | $/t | Value × 1,000,000 ÷ qty |

### 4.6 P&L (Rulebook §8)

| Function | Returns | Notes |
|---|---|---|
| `_revenue_local_usd(local_qty, local_price_le, fx)` | $ | Qty × Price ÷ FX |
| `_revenue_export_usd(export_qty, export_price_usd)` | $ | |
| `_variable_cogs_usd(total_qty, variable_cost_per_ton)` | $ | |
| `_export_expenses_usd(export_qty, export_expense_rate)` | $ | |
| `_contribution_margin(revenue, vcogs, export_exp)` | $ | |
| `_ebtd(cm, total_fixed)` | $ | |
| `_ebt(ebtd, depreciation)` | $ | |
| `_break_even_qty(total_fixed, cm_per_ton)` | tons | Returns 0 if sales qty = 0 (integrity check 7) |
| `compute_standalone_pnl(state, company)` | dict (USD) | Full P&L per company with all products + sub-total (verification §7.1–§7.4) |
| `_intercompany_eliminations(state)` | dict (USD) | DRI revenue/COGS netting; margin line separate (§8.6) |
| `compute_consolidated_pnl(state)` | dict (USD) | Four-company table + Eliminations column + Consolidated column (§8.4) |
| `_consolidated_avg_local_price(total_local_revenue, total_local_qty)` | $/t | §8.5: revenue ÷ volume, not a weighted average of unit prices |

### 4.7 Integrity checks — locked at six (Q3 ruling)

**Check count: 6**, not 7. Rulebook §12's check 3 is dropped; check 5 is reframed as a real runtime view-currency-consistency check.

| # | Check | Type | How implemented |
|---|---|---|---|
| 1 | Fixed cost distribution % sums to 100% per company | Runtime (state) | Per-company sum over DRI / Rebar / Wire / HRC. Tolerance ±0.01. |
| 2 | Blending ratios sum to 100% per production line | Runtime (state) | Per company per line (billet long, HRC flat). Tolerance ±0.01. |
| ~~3~~ | ~~Trade-off matrix fully dynamic~~ | **DROPPED** | Enforced by construction — the matrix is never stored, always computed on demand. No runtime check because no failure mode exists. |
| 4 | Sales drive production — no orphan production figures | Runtime (state) | Every production qty is derivable from sales via the cascade; no free-floating production inputs. |
| 5 | No output view mixes currencies | Runtime (output) | Every output-producing function returns a dict tagged with `"_currency"`. A walker (`_check_currency_consistency`) asserts every numeric leaf in a view matches the declared currency. Detailed cost sheets are natively EGP; conversion sheets and P&L are USD (or EGP if toggled). |
| 6 | Intercompany transactions match between seller revenue and buyer cost | Runtime (state) | ERM DRI revenue to EFS/ESR = EFS+ESR DRI cost embedded from ERM. Equality check in USD. |
| 7 | Break-even = 0 when Total Sales Qty = 0 | Runtime (output) | Sentinel in `_break_even_qty()`. |

**Check 3 rationale for record:** The trade-off matrix is a computed view, not stored data. Every cell is `seller_vc × seller_ratio` emitted by `compute_tradeoff_matrix(state)` on demand. No user input, no tool, no code path writes directly into a cell. A check that defends against a failure mode that cannot occur by construction is theater and will be dropped.

**Check 5 rationale for record (user's framing):** Raw materials other than local scrap are naturally in USD; fixed costs like depreciation and salaries are naturally EGP. Detailed cost sheets legitimately contain both — that's their native form. But an **output view** (conversion cost sheet, P&L) must not mix currencies within itself. The check enforces this at the view level, not the underlying-data level.

**Implementation:**

```python
def _check_fixed_distribution_sums(state) -> tuple[bool, str]: ...
def _check_blending_ratios_sum(state)     -> tuple[bool, str]: ...
def _check_sales_drive_production(state)  -> tuple[bool, str]: ...
def _check_currency_consistency(output)   -> tuple[bool, str]: ...  # takes output, not state
def _check_intercompany_reconciliation(state) -> tuple[bool, str]: ...
def _check_break_even_zero_when_no_sales(output) -> tuple[bool, str]: ...

def run_integrity_checks(state: dict, outputs: dict | None = None) -> list[tuple[bool, str]]:
    """
    Runs the six integrity checks in order. State-only checks (1, 2, 4, 6) run
    from `state`. Output-dependent checks (5, 7) run from `outputs` if provided;
    otherwise they are skipped and flagged as such in the return list.

    Returns a list of (passed, detail) tuples. Caller may stop at first False.
    """
```

`compute_all()` invokes `run_integrity_checks(state)` first, computes all outputs, then re-runs output-dependent checks on the results. Any failure raises `IntegrityError` with the offending check's detail string. Downstream tools cannot bypass it (Appendix D §6 discipline).

**Appendix D §6 compliance note for future patch:** The system prompt's Appendix D §6 says "all seven checks must be implemented as separate functions". This brief honors the spirit (checks as separate functions, runnable, non-bypassable) while ruling that check 3 is a design principle not a runtime check, bringing the count to 6. The system prompt needs a corrective patch — logged in §11 of this brief.

---

## 5. Precision & units discipline (Q5 — locked)

**Storage: float throughout.** No `Decimal`. The verification sheet rounds to displayed precision; the engine does not pre-round. Tests apply rounding at assertion time with explicit tolerances.

**Full precision carried through all intermediate calculations.** Rounding happens only at the display boundary (UI or orchestrator response formatter), not at stage boundaries inside the engine. This matches Rulebook §2.3: "Model stores full precision; display layer rounds at presentation."

**Unit convention (function name suffix):**
- `_le` or `_egp` — Egyptian Pounds
- `_usd` — US Dollars
- `_per_ton`, `_per_ton_ms`, `_per_ton_billet` — per physical output ton at that stage
- `_pct` — percentage as fraction (0.60, not 60)
- `_t`, `_kt`, `_musd` — tons, kilotons, millions of USD

**FX rate is always passed explicitly** as a function argument or pulled from `state["global"]["fx_rate_egp_usd"]`. No global FX constant inside the engine.

**Conversion discipline:** LE → USD is always `value_le / fx`. USD → LE is `value_usd * fx`. Mixed-currency output views are forbidden (integrity check 5, runtime enforced).

---

## 6. Test strategy

Companion file `tests/test_cost_engine.py`. One test class per verification-sheet section.

| Test class | Source section | Cell count (approx) |
|---|---|---|
| `TestStage1DRI_Detailed` | §1.2 | ~30 cells (EZDK + ERM) |
| `TestStage1DRI_Conversion` | §1.3 | 10 |
| `TestStage2Billet_Conversion` | §2.2 | 15 |
| `TestStage2TradeoffMatrix` | §2.3 | 24 (4 sources × 4 buyers + minima + own-VCs) |
| `TestStage2MarketBilletBuildup` | §2.4 | 4 |
| `TestStage3Rebar_Sc1` | §3.1 Sc1 | 24 |
| `TestStage3Rebar_Sc2` | §3.1 Sc2 | 28 |
| `TestStage3HRC` | §3.3 | 16 |
| `TestSales_MarketShare` | §4.4 | 6 |
| `TestProductionCascade` | §5 | ~45 |
| `TestFixedCosts_Allocation` | §6.3 | ~35 |
| `TestStandalonePnL_EZDK` | §7.1 | ~50 |
| `TestStandalonePnL_EFS` | §7.2 | ~35 |
| `TestStandalonePnL_ERM` | §7.3 | ~20 |
| `TestStandalonePnL_ESR` | §7.4 | ~15 |
| `TestConsolidatedPnL` | §8 | ~50 |
| `TestIntegrityChecks_HappyPath` | — | 6 (each check passes on clean state) |
| `TestIntegrityChecks_Violations` | — | 6 (each check fires on deliberately broken state) |
| `TestSc1SourcingDispatch` | §4.3 of this brief | 4 (own/market/internal_minimum paths + ERM default) |

**Tolerance policy:**
- Values displayed as integer LE/t: engine output rounded to nearest integer must match exactly (or `abs(diff) ≤ 1` for cumulative rounding drift).
- Values displayed to 2 dp in USD/t: `abs(diff) ≤ 0.01` after rounding.
- Values displayed to 0 dp in USD M: `abs(diff) ≤ 0.01` after rounding to 2 dp first, then to 2 dp display.
- Percentages displayed as integers: `abs(diff) ≤ 1 pp` after rounding.

Break-even qty and any integer-kton value: exact match after rounding.

**Fixture:** `state = json.load(open("model_initial_state.json"))` loaded once per test session via `tests/conftest.py`; no mutation during tests. Tests that need to simulate integrity-check violations deep-copy the fixture first.

**Test harness:** `pytest`. No external dependencies beyond stdlib + pytest. The engine itself has zero third-party dependencies.

---

## 7. File layout (confirmed)

```
fantomaas/
├── cost_engine.py            # the module
├── model_initial_state.json  # read-only; loaded by tests; later by state_manager
├── tests/
│   ├── test_cost_engine.py
│   └── conftest.py           # loads the JSON fixture
└── [later: state_manager.py, tools.py, llm_router.py, ...]
```

Target size for `cost_engine.py`: 600–900 lines including docstrings. If it exceeds ~1,100 lines, the design is probably too monolithic and should be split into `cost_engine/__init__.py` + stage modules, but not before the green test suite — premature splitting hurts auditability.

---

## 8. Locked decisions (formerly open questions)

This section records every Q1–Q6 resolution so anyone picking this up later sees the reasoning without scrolling.

| Q | Question | Ruling | Rationale |
|---|---|---|---|
| Q1 | Sc1 material price for billet producers vs non-producers | Producers (EZDK/EFS/ESR) use own billet VC by default; ERM defaults to market. | Producers can't shut down EAFs economically — they produce and consume their own. Trade-off matrix is decision-support, not an auto-dispatch rule. Matches verification sheet exactly (EFS uses 467.96 own VC, not ESR's 457.97 offer). |
| Q2 | Where does the sourcing decision live in state? | `state["finished_products"][product][company]["sourcing_decision"]` with values `"own"` / `"market"` / `"internal_minimum"`. Defaults: producers → `"own"`; ERM → `"market"`. | Clean first-class state, scenario-friendly, makes §4.7's "user decision" explicit rather than implicit. |
| Q3 | Integrity checks 3 and 5 at runtime | Check 3 dropped entirely (design principle, not runtime check). Check 5 reframed as real runtime check: no output view mixes currencies. Check count = 6. | Check 3 defended against a failure mode that can't occur by construction. Check 5's user-provided framing turns it from code-review property into a checkable view-level invariant. |
| Q4 | Detailed-view behavior for EFS/ESR billet and HRC (dummy consumptions) | Compute anyway; tag output with `_note: "detailed breakdown is reconstructed; only summary total is verified"`. Tests assert summary total only. | Honest; guards what matters; swap to real data is a data-only change. |
| Q5 | Rounding inside the engine | Full precision throughout. Rounding only at display boundary. | Matches Rulebook §2.3 explicitly. |
| Q6 | Nullable HRC local market | `{"hrc_market_share": None, "hrc_market_share_note": "HRC total local market not yet provided"}`. No exception. | Matches Rulebook §13 "known data gap" framing. |

---

## 9. Build order inside Step 1

In Claude Code, work through these in order. Stop after each numbered step, report the green test output, wait for go-ahead.

1. **Day 1 (half-day):** Scaffold (`cost_engine.py`, `tests/conftest.py`, empty `tests/test_cost_engine.py`). Stage 1 DRI (§3) — both views, both companies. `TestStage1DRI_*` green.
2. **Day 1 (half-day):** Stage 2 Billet (§4) for **EZDK only**, full detail. `TestStage2Billet_Conversion` for EZDK green; trade-off matrix framework green. Integrity check 2 wired.
3. **Day 2 (half-day):** Trade-off matrix for all four companies and market. EFS/ESR summary-only billet via dummies. `TestStage2TradeoffMatrix` and `TestStage2MarketBilletBuildup` green.
4. **Day 2 (half-day):** Stage 3 Finished Products, both scenarios, all four companies. Sourcing-decision dispatch wired. `TestStage3*` and `TestSc1SourcingDispatch` green.
5. **Day 3 (half-day):** Production cascade (§6), sales & market share. `TestProductionCascade` and `TestSales_MarketShare` green. Integrity check 4 wired.
6. **Day 3 (half-day):** Fixed cost allocation, standalone P&L. Integrity check 1 wired. Integrity check 7 wired inside `_break_even_qty`.
7. **Day 4 (half-day):** Consolidated P&L with eliminations (§8). Integrity check 6 wired.
8. **Day 4 (half-day):** Currency tagging on all output dicts; integrity check 5 wired. `compute_all()` wired; integrity-check violation tests; run full suite; fix rounding and edge cases until all green.

Total estimated: 4 working half-days to green. Budget a fifth for unexpected reconciliation issues (there will be at least one number off by a few units because of a rounding convention mismatch — this is the nature of model verification).

---

## 10. Handoff to Claude Code

**Files to attach to the Claude Code session:**

1. `EzzSteel_FinancialModel_Rulebook.md`
2. `model_initial_state.json`
3. `model_verification.md`
4. `ezz_steel_bot_system_prompt_v2.md`
5. This brief (`step1_brief_cost_engine_v2.md`)

**Opening instruction to Claude Code:**

> Build `cost_engine.py` and `tests/test_cost_engine.py` per the attached Step 1 brief (v2). The brief is authoritative. Rulebook §12 wins over the brief for business rules; the brief wins over the system prompt for Step 1 scope.
>
> Read all five attached files end-to-end first. Then outline which functions you'll write in what order, following Build Order §9 of the brief. Wait for my go-ahead before writing any code.
>
> After each numbered build step, run the tests for that step, paste the green output, and wait for my go-ahead before continuing. Do not improvise scope. If you find a gap in the brief, stop and ask.
>
> Do not use Plan Mode. Planning is complete; we're in execution.

---

## 11. Forward log — items to address after Step 1 ships

These are not Step 1 blockers but need attention in subsequent steps or the next system-prompt revision.

- **System prompt Appendix D §6** currently says "all seven checks must be implemented as separate functions". After Q3 ruling, count is 6. Needs corrective patch in the next system-prompt revision.
- **System prompt decision log line 20** ("Integrity check count: 7") — same patch.
- **Rulebook §12 check 3** should be restated as a design principle paragraph (not numbered check) in the next rulebook revision.
- **Rulebook §5.1** phrasing "Sc1: In-house billet (minimum from trade-off matrix)" is literally correct only for ERM (and only when ERM is switched to `internal_minimum`). For producers, Sc1 is own VC. Next rulebook revision should rewrite §5.1 per the Q1 table in this brief's §4.3.
- **`model_initial_state.json`** currently has no `sourcing_decision` field. Step 2 (`state_manager.py`) will add it on baseline load with defaults per Q2 ruling, or Step 1 can seed it at test-load time if more convenient. Either is fine; decide at implementation.

---

*End of brief v2.*
