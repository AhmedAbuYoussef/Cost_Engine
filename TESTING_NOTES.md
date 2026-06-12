# Testing Notes — Ezz Steel cost_engine

This document records test-side decisions that diverge from a strict
default-tolerance reading of `step1_brief_cost_engine_v2.md` §6. Every
divergence is scoped (specific cells, specific tolerance) and tied back to a
documented data-gap or precision-cascade source.

The default tolerance policy from the brief stands:

- Integer LE/t cells: exact after rounding, or `|diff| ≤ 1` for cumulative
  rounding drift.
- USD/t 2dp cells: `|round(actual, 2) − target| ≤ 0.01`.

Per-cell tolerance overrides live in `tests/test_cost_engine.py` in the
`_USD_TOL_OVERRIDES` dict, keyed by `(section, company, cell)`. Anything not
listed there uses `ABS_TOL_USD = 0.01`. The intent of every override is that
a regression beyond the documented drift fails loudly; tolerances are sized
just wide enough to absorb the known data-precision gap, not to mask future
engine bugs.

---

## Stage 1 — DRI

### Scope of the override

Six §1.3 USD/t cells are widened from `±0.01` to `±0.06`:

- `EZDK.other_conversion_usd_t` (target 57.62)
- `EZDK.total_conversion_usd_t` (target 130.39)
- `EZDK.total_variable_mfg_usd_t` (target 285.23)
- `ERM.other_conversion_usd_t`  (target 58.68)
- `ERM.total_conversion_usd_t`  (target 133.63)
- `ERM.total_variable_mfg_usd_t` (target 307.94)

All other §1.3 cells (`material_price_usd_t`, `mrmr_effect_usd_t` for both
companies) remain at `±0.01`. All §1.2 LE/t cells remain at `±1 LE`.

### Engine vs verification

The full-precision engine — formulas applied verbatim from Rulebook §3 to
`model_initial_state.json` as committed — produces:

| Cell                                | Engine     | Verification §1.3 | Δ      |
|-------------------------------------|-----------:|------------------:|-------:|
| EZDK other_conversion_usd_t         | 57.673     | 57.62             | +0.053 |
| EZDK total_conversion_usd_t         | 130.448    | 130.39            | +0.058 |
| EZDK total_variable_mfg_usd_t       | 285.288    | 285.23            | +0.058 |
| ERM  other_conversion_usd_t         | 58.718     | 58.68             | +0.038 |
| ERM  total_conversion_usd_t         | 133.671    | 133.63            | +0.041 |
| ERM  total_variable_mfg_usd_t       | 307.981    | 307.94            | +0.041 |

The drift is +0.05 USD/t for EZDK and +0.04 USD/t for ERM, in the same
direction (engine higher). All other cells match within `±0.01`.

### Root cause

Rulebook §13 (Known Data Gaps) explicitly names:

> "Exact consumption decimals for ERM DRI Nitrogen & Water (currently using
> dummies that satisfy the output equations)."

And `model_verification.md` §9 (Known Data Gaps) broadens this to: certain
consumption decimals use back-calculated dummies; replace with true Excel
values when updating.

In practice the dummy values committed in `model_initial_state.json` do not
fully back-solve to the §1.3 USD/t targets — they are off by ~0.84 LE/t on
EZDK and ~1.01 LE/t on ERM in the Σ-conversion-items sum that feeds
`other_conversion_usd_t = (Σ items LE − IOP LE) ÷ FX`. After division by
FX = 15.92, that converts to the +0.05 / +0.04 USD/t drift seen above. The
drift cascades by construction into `total_conversion_usd_t` and
`total_variable_mfg_usd_t`.

### Why the chosen response

1. **JSON is not modified.** EZDK is the cell-for-cell reference baseline
   per the brief; its inputs are never tuned to close model gaps. ERM
   dummies are left intact pending the first real-data refresh that the
   §13 known-data-gap framing anticipates.
2. **`model_verification.md` is not modified.** The verification sheet is
   the trust anchor.
3. **No reconciliation residual block is introduced for DRI.** The gap is
   mechanical (data precision in stated-as-dummy inputs), not structural
   (no missing or mis-applied formula). A reconciliation residual would
   over-engineer a transient data-quality issue.
4. **Tolerance is widened to ±0.06**, just above the observed +0.058 max
   drift, so a future regression beyond this band fails loudly.

### Precedent

This is the same pattern adjudicated for Stage 2c (material_price and
other_conversion drift for EFS billet), where scoped tolerance widening
with documented justification was preferred over JSON tuning or a
reconciliation cascade. Stage 1 applies that precedent.

### Downstream propagation note

`compute_dri_conversion(state, "ERM").total_variable_mfg_usd_t` (engine
307.98) is the value Stage 2 reads as the DRI input price for EFS billet
material (per Rulebook §4.5). The verification sheet uses 307.94. This
0.04 USD/t difference at the source feeds the Stage 2c EFS material-price
cascade drift documented separately in that stage's notes when sealed.
Both drifts share a single root: the JSON's §13-class dummies.

### Expected resolution

At the next quarterly refresh, when real Excel-precision consumption
decimals replace the §13 dummies, this drift resolves naturally and the
tolerance overrides for these six cells can be removed (restoring
`±0.01`). The override dict is structured so removing the six entries
restores default behavior with a one-line diff per cell.

---

## Stage 2 — Unit Conventions

The JSON's `_kg` suffix in `billet.<company>.eaf_unit_prices_usd` and
`billet.<company>.bccm_unit_prices_usd` is overloaded. Two distinct
conventions co-exist; the engine encodes both:

| Field | Unit interpretation | Engine handling |
|---|---|---|
| `eaf_unit_prices_usd.aux_materials_kg` (59.40)        | True `$/kg`. | Direct: `consumption_kg × price`. |
| `eaf_unit_prices_usd.refractories_kg`  (28.54)        | `$/MT` in disguise. | `consumption_kg × price ÷ 1000`. |
| `eaf_unit_prices_usd.electrodes_kg`    (5841.40)      | `$/MT` in disguise. | `consumption_kg × price ÷ 1000`. |
| `eaf_unit_prices_usd.other_fillers_kg` (233.46)       | `$/MT` in disguise. | `consumption_kg × price ÷ 1000`. |
| `bccm_unit_prices_usd.aux_materials_kg` (559.9)       | `$/MT` in disguise. | `consumption_kg × price ÷ 1000`. |
| `bccm_unit_prices_usd.refractories_kg` (678.1)        | `$/MT` in disguise. | `consumption_kg × price ÷ 1000`. |
| All `_t` suffixed prices                              | `$/ton`. | Direct. |
| All `electricity_kwh`, `natural_gas_nm3`, `water_m3`, `oxygen_nm3`, `nitrogen_nm3`, `argon_nm3` | Native unit. | Direct. |

This is a locked-decision-by-inheritance from the prior session and is the
only way the magnitudes reconcile to verification §2.2 for EZDK. The
EAF aux ($/kg) vs BCCM aux ($/MT) split is a known JSON-convention wart;
it is **not** to be "fixed" by harmonizing the JSON — the verification
sheet's numbers depend on it. Open question for the next rulebook revision
to standardize the field naming.

---

## Stage 2 — EZDK Billet Reconciliation

### Surfaced gap

Applying Rulebook §4.2–§4.4 to `model_initial_state.json` produces a
structural shortfall on EZDK Billet Total VC that the §13 propagation
explanation does **not** cover:

| Cell                       | Engine (pre-residual) | Verification §2.2 | Diff      | Explanation                |
|----------------------------|----------------------:|------------------:|----------:|----------------------------|
| Material Price             | 263.2514              | 263.21            | +0.041    | DRI VC propagation (§13)   |
| Yield Effect               |  46.7029              |  46.70            | +0.003    | Trivial propagation        |
| **Other Conversion**       |  **99.1109**          |  **99.61**        | **−0.499**| **Structural residual**    |
| Total Conversion           | 145.8138              | 146.31            | −0.496    | Propagates from Other Conv |
| Total Variable Mfg         | 409.0651              | 409.52            | −0.455    | Propagates from Other Conv |

The −0.499 USD/t residual at Other Conversion is the precise gap (99.61 −
99.1109 = 0.4991, rounded to 3dp = **0.499**). It cannot be closed by
adjusting any single JSON line item within stated unit conventions.

### Adjudication — reconciliation residual block

Per step 2 decision (option 1 from the surfacing turn):

- **Residual value:** `0.499 USD/t`
- **State location:** `state["reconciliation"]["billet_EZDK_excel_to_engine_usd_t"]`
- **Seeded:** `tests/conftest.py` after deep copy from `model_initial_state.json`.
  **NOT** written into the JSON — that file remains pristine. Brief §11
  forward-log placeholder for `state_manager.py` (SQLite) to take over the
  persistence path in a later step.
- **Engine application:** added to Other Conversion only (not to Material,
  Yield Effect, EAF buildup, or BCCM buildup). Cleanly-named intermediates
  `_other_conversion_before_residual` and `_reconciliation_residual_usd_t`
  are returned alongside the headline `other_conversion_usd_t` so the
  residual is visible at the function boundary. Sensitivity analysis in
  step 8 will need to recognize the residual is structural overhead, not a
  marginal cost driver.
- **Propagation:** `total_conversion = yield_effect + other_conversion`
  picks the residual up; `total_variable_mfg = material + total_conversion`
  picks it up by composition. The trade-off matrix's intercompany price
  (`seller_vc × ratio`) picks it up because `seller_vc` is the
  residual-included Total VC. No special-casing in `compute_tradeoff_matrix`.
- **Scope of residual:** EZDK only. `_billet_reconciliation_residual_usd_t`
  returns 0.0 for EFS, ESR, and any future caller, so other companies
  cannot accidentally absorb an EZDK-keyed residual when they're wired up
  in step 3.

### Result after applying the residual

| Cell                  | Engine    | Target    | Diff      | Tolerance       | Status |
|-----------------------|----------:|----------:|----------:|-----------------|--------|
| Material Price        | 263.2514  | 263.21    | +0.040    | ±0.05 (override) | ✓     |
| Yield Effect          |  46.7029  |  46.70    | +0.000    | ±0.01 (default)  | ✓     |
| Other Conversion      |  99.6099  |  99.61    | +0.000    | ±0.01 (default)  | ✓     |
| Total Conversion      | 146.3128  | 146.31    | +0.000    | ±0.01 (default)  | ✓     |
| Total Variable Mfg    | 409.5641  | 409.52    | +0.040    | ±0.05 (override) | ✓     |
| Trade-off EZDK offer  | 478.7805  | 478.73    | +0.050    | ±0.06 (override) | ✓     |

The residual closes Yield Effect, Other Conversion, and Total Conversion
to within `±0.01`. Material Price and Total Variable Mfg keep their §13
propagation drift inside `±0.05`. The trade-off offer absorbs the same
drift multiplied by 1.169 inside `±0.06`.

### Per-cell tolerance overrides added in step 2

Appended to `_USD_TOL_OVERRIDES` in `tests/test_cost_engine.py`:

- `("billet_conversion", "EZDK", "material_price_usd_t"): 0.05` — DRI VC
  propagation, §13 class.
- `("billet_conversion", "EZDK", "total_variable_mfg_usd_t"): 0.05` — DRI
  VC propagation through Total VC.
- `("tradeoff_matrix",   "EZDK", "offer_usd_t"): 0.06` — propagation × 1.169
  trade-off ratio.

`yield_effect_usd_t`, `other_conversion_usd_t`, and `total_conversion_usd_t`
all stay at the default ±0.01 because the residual closes them exactly.

### Forward flags

- The residual is structural in the sense that the JSON's reconstructed
  EZDK-billet inputs cannot back-solve to the verification target without
  it. When real Excel-precision consumption decimals replace this class of
  values for EZDK billet detail, the residual must be revisited (and
  ideally driven back to 0). The conftest fixture is the only place to
  edit; engine logic does not need to change.
- **No residual is yet introduced for EFS or ESR.** Their detailed inputs
  are dummies satisfying the summary outputs (467.96 and 450.31 $/t
  respectively); whether they need their own residuals or scoped tolerance
  widening will be adjudicated in step 3 when those source rows are wired
  into the trade-off matrix and the conversion view.
- The residual does **not** affect the EAF or BCCM per-stage detailed cells
  (`total_usd_t_ms`, `total_usd_t_billet` pre-residual). Those remain pure
  engineering buildups; the residual lives at the top-level Other
  Conversion line only.

---

---

## Step 3 — EFS/ESR Billet Summary + Trade-off Matrix Completion

### Conftest seeding (no JSON modification)

`model_initial_state.json` only carries yields, blending, and the
trade-off ratio for EFS and ESR billet. The verification document
(`model_verification.md`) supplies the rest in §2.1 and §2.2. Per the
established pattern (same as the step-2 reconciliation residual), the
missing fields are seeded in `tests/conftest.py` after the JSON deep
copy. The JSON stays pristine; `state_manager.py` (a later step) is the
eventual home for persistence.

| Field                                                | Source                  | EFS    | ESR    |
|------------------------------------------------------|-------------------------|-------:|-------:|
| `eaf_unit_prices_usd.local_scrap_t`                  | verification §2.1       | 270.10 | 270.10 |
| `eaf_unit_prices_usd.imported_scrap_t`               | verification §2.1       | 307.56 | 307.56 |
| `summary_other_conversion_usd_per_ton`               | verification §2.2 "Other Conv" | 107.26 | 97.97 |

### Engine: `billet_mode` dispatch

`compute_billet_conversion` now dispatches on what's available in state:

| Mode                       | Trigger                                                  | Engine path                                         |
|----------------------------|----------------------------------------------------------|-----------------------------------------------------|
| `detailed_with_residual`   | `eaf_consumptions_per_ton_ms` present (EZDK)             | Full EAF+BCCM buildup + Other-Conv residual (0.499) |
| `summary_fitted`           | only `summary_other_conversion_usd_per_ton` present      | Direct §4.4 summary, residual = 0.0                 |

When real Excel data lands for EFS/ESR detailed EAF+BCCM, the dispatch
will automatically pick up `detailed_with_residual` and the
`summary_other_conversion_usd_per_ton` seed should be removed from
conftest. No engine change required at that point.

### EFS — verification §2.2 reconciliation

| Cell                  | Engine     | Target  | FP diff   | Round diff | Tolerance        | Source of drift                |
|-----------------------|-----------:|--------:|----------:|-----------:|------------------|--------------------------------|
| Material Price        | 300.0257   | 299.98  | +0.0457   | +0.0500    | ±0.05 (override) | ERM DRI VC propagation × 0.70  |
| Yield Effect          |  60.7295   |  60.72  | +0.0095   | +0.0100    | ±0.01 (default)  | Material × (1/Y−1) propagation |
| Other Conversion      | 107.2600   | 107.26  | +0.0000   | +0.0000    | ±0.01 (default)  | seeded scalar, exact           |
| Total Conversion      | 167.9895   | 167.98  | +0.0095   | +0.0100    | ±0.01 (default)  | propagated from Yield Effect   |
| Total Variable Mfg    | 468.0151   | 467.96  | +0.0551   | +0.0600    | ±0.06 (override) | propagated from Material       |

### ESR — verification §2.2 reconciliation

| Cell                  | Engine     | Target  | FP diff   | Round diff | Tolerance        | Source of drift                |
|-----------------------|-----------:|--------:|----------:|-----------:|------------------|--------------------------------|
| Material Price        | 303.1586   | 303.15  | +0.0086   | +0.0100    | ±0.01 (default)  | ERM DRI VC propagation × 0.20  |
| Yield Effect          |  49.1885   |  49.19  | −0.0015   | +0.0000    | ±0.01 (default)  | rounding noise                 |
| Other Conversion      |  97.9700   |  97.97  | +0.0000   | +0.0000    | ±0.01 (default)  | seeded scalar, exact           |
| Total Conversion      | 147.1585   | 147.16  | −0.0015   | +0.0000    | ±0.01 (default)  | propagated                     |
| Total Variable Mfg    | 450.3172   | 450.31  | +0.0072   | +0.0100    | ±0.01 (default)  | propagated                     |

ESR lands within default ±0.01 everywhere because its DRI blend weight is
0.20 (vs EFS's 0.70), so the same ERM DRI VC propagation drift is damped
3.5× compared to EFS.

### Per-cell tolerance overrides added in step 3

Appended to `_USD_TOL_OVERRIDES`:

- `("billet_conversion", "EFS", "material_price_usd_t"): 0.05` — ERM DRI VC
  propagation, §13 class.
- `("billet_conversion", "EFS", "total_variable_mfg_usd_t"): 0.06` —
  propagated from Material.
- `("tradeoff_matrix", "EFS", "offer_usd_t"): 0.07` — propagation × 1.016.

**No reconciliation residual block is introduced for EFS or ESR.** Unlike
EZDK in step 2, the EFS/ESR gap is pure ERM-DRI-VC propagation — a §13
data-precision artifact, not a structural Excel-to-engine residual. The
`summary_other_conversion_usd_per_ton` seed is itself the fit to the
verification target; no additional residual is needed.

### Trade-off matrix completion — full 4×4 with minimums

Engine values vs verification §2.3:

| Source ↓    | Offer ($/t)   | To EZDK     | To EFS     | To ERM     | To ESR     |
|-------------|---------------|-------------|------------|------------|------------|
| EZDK ×1.169 | 478.7805      | 409.5641    | 478.7805   | 478.7805   | 478.7805   |
| EFS  ×1.016 | 475.5034      | 475.5034    | 468.0151   | 475.5034   | 475.5034   |
| ESR  ×1.017 | 457.9726      | 457.9726    | 457.9726   | 457.9726   | 450.3172   |
| Market      | 590           | 590         | 590        | 590        | 590        |
| **Minimum** |               | **409.56**  | **457.97** | **457.97** | **450.32** |
| **Source**  |               | EZDK own VC | ESR offer  | ESR offer  | ESR own VC |

Verification §2.3 minimum row: 409.52 / 457.97 / 457.97 / 450.31.

| Minimum       | Engine     | Target  | FP diff   | Tolerance        | Tolerance source                       |
|---------------|-----------:|--------:|----------:|------------------|----------------------------------------|
| To EZDK       | 409.5641   | 409.52  | +0.0441   | ±0.05 (inherited) | EZDK Total VC override (own-VC cell)   |
| To EFS        | 457.9726   | 457.97  | +0.0026   | ±0.01 (default)   | ESR offer (no ESR override)            |
| To ERM        | 457.9726   | 457.97  | +0.0026   | ±0.01 (default)   | ESR offer                              |
| To ESR        | 450.3172   | 450.31  | +0.0072   | ±0.01 (default)   | ESR own VC (no ESR override)           |

The `minimum_per_buyer` cells are **not** independent overrides in
`_USD_TOL_OVERRIDES`. The minimum value is identical, by construction, to
whichever source cell produced it; the tolerance of that source cell
applies. The test for minimums (`test_minimum_per_buyer_matches_verification`)
encodes this inheritance inline: for buyer EZDK the tolerance is
`_tol_for("billet_conversion", "EZDK", "total_variable_mfg_usd_t")` =
±0.05; for the others, default ±0.01.

ERM appears only as a buyer column. By Rulebook §1.4 it never produces
billet; the engine asserts this structurally (`ERM` not in `tm["rows"]`
and not in `tm["sources"]`).

### Cross-stage drift summary

After step 3, the cumulative tolerance budget consumed against the
verification sheet is:

| Stage / Cell                                       | Override   | Max drift  |
|----------------------------------------------------|------------|-----------:|
| Stage 1 — DRI conv. (6 cells, both companies)      | ±0.06      |   0.058    |
| Stage 2 — Billet Material Price (EZDK)             | ±0.05      |   0.040    |
| Stage 2 — Billet Total VC (EZDK)                   | ±0.05      |   0.040    |
| Stage 2 — Trade-off EZDK offer                     | ±0.06      |   0.050    |
| Step 3 — Billet Material Price (EFS)               | ±0.05      |   0.046    |
| Step 3 — Billet Total VC (EFS)                     | ±0.06      |   0.055    |
| Step 3 — Trade-off EFS offer                       | ±0.07      |   0.053    |
| All other cells (ESR, minimums, market, etc.)      | ±0.01 LE/USD | within   |

Every override has a documented root cause: §13 data-gap propagation
(Stage 1 DRI cells, EFS/ESR cells) or a structural Excel-to-engine
residual absorbed at a single line (EZDK billet Other Conversion).
Removing any override should fail loudly the next time the JSON or
verification source changes.

---

## Step 4 — Finished Products, Excel-independent subset

**Session date:** 2026-06-12. Scope per user instruction: structural guard,
sourcing dispatch, yield-effect and material-price rows, EZDK Sc1 home
scrap, ERM Sc1=Sc2 invariant, HRC skeleton, currency tags. Everything else
is deliberately unasserted pending Excel-confirmed values.

### Conftest seeding (no JSON modification)

1. `sourcing_decision` defaults (brief §4.3 Q2 ruling): Rebar EZDK/EFS/ESR
   and Wire Rod EZDK → `"own"`; Rebar ERM → `"market"`. HRC carries no
   sourcing field (flat line buys no billet).
2. Rebar EFS/ERM/ESR `summary_other_conversion_usd_per_ton` = 11.32 /
   17.18 / 20.64, transcribed from verification §3.1 Sc1 (item-3 ruling,
   Step 3 billet precedent). **Circularity record:** the Sc1 Other
   Conversion line item for these companies is *plumbing-verified* — the
   asserted value is the seeded value. The non-circular arithmetic
   cross-check is the Sc2 column and the Difference (Sc1 − Sc2) line,
   which exercise the same scalar against independently-computed material
   and yield-effect terms; these get wired when home-scrap inputs land.
   Real consumption detail replaces the scalars at the quarterly refresh.
3. HRC EZDK/EFS `summary_other_conversion_usd_per_ton` = 108.87 / 128.60
   from §3.3 (item-6 ruling, Q4-extension). Summary-level assertions only;
   none wired yet in this sub-step.

NOT seeded (pending user-supplied Excel formula-bar values, never
back-solved): EFS/ERM/ESR rebar home-scrap % + byproduct price; HRC
`flat_line_scrap_prices_usd` (independent of billet scrap prices); EZDK
Rebar unit-price overrides (suspected display-rounded NG 0.25 vs 0.2507,
water 0.27 vs 0.2716 — engine Other Conversion 16.2282 vs sheet 16.29,
Total VC 434.50 vs 434.52; both **unasserted**, per direction no tolerance
widening).

### Per-cell tolerance overrides added in step 4

| Cell                                  | Override | Measured drift | Root cause |
|---------------------------------------|----------|---------------:|---|
| Sc1 Material Price (EZDK)             | ±0.05    | 0.044          | Own-billet-VC propagation (= billet Total VC override) |
| Sc1 Material Price (EFS)              | ±0.06    | 0.055          | Same, EFS chain |
| Sc1/Sc2 Yield Effect (ERM)            | ±0.03    | 0.017          | 4dp display-rounded JSON yield (below) |
| Sc1/Sc2 Yield Effect (ESR)            | ±0.03    | 0.010 / 0.018  | Same |

**Yield-effect drift derivation.** The JSON rebar yields are 4dp
display-rounded (0.9792, 0.9682). The sheet's ERM cells (12.55) imply a
full-precision yield ≈ 0.979174 — which itself rounds to 0.9792 — so this
is the §13 display-rounding class, not an engine defect. Bound:
`d(YE) = material × Δ(1/y) ≈ 590 × 0.00005 / 0.9584 ≈ 0.031` → ±0.03.
EZDK/EFS yield effects stay at the default ±0.01. Tightens to ±0.01 when
Excel formula-bar yields arrive.

### NEW FINDING — §3.3 Combined Yield cells (PENDING-EXCEL)

The sheet's Combined Yield cells do not reproduce from the full-precision
product of its own displayed stage yields, and they contradict the sheet's
own Yield Effect row:

| Company | Sheet Combined | EAF×TSC×HSM (full precision) | YE-implied combined |
|---|---|---|---|
| EZDK | 82.37 | 82.4100 (0.8574 × 0.9852 × 0.9756) | 82.4100 (59.92 = 280.73 × (1/0.82410 − 1)) |
| EFS  | 81.43 | 81.4611 (0.8482 × 0.98 × 0.98)     | 81.4611 (68.26 = 299.96 × (1/0.81461 − 1)) |

The Yield Effect row (59.92 / 68.26) is consistent with the full-precision
product and inconsistent with the displayed Combined Yield cells (would
give 60.09 / 68.41). The Combined Yield cells are therefore suspected
display anomalies in the verification sheet. Engine asserts the
**identity** (combined = eaf × tsc × hsm) only; the sheet-cell assertion
is held until the Excel pull adjudicates. No tolerance was widened and no
value was fudged to force a pass.

### Assertions deliberately pending (wire-up list for next sub-step)

- Group (a): EZDK Rebar Sc2 Home Scrap, Total Conversion, Total VC,
  Difference.
- Group (b): HRC Material Price (281 / 300 targets), Yield Effect — on
  arrival of `flat_line_scrap_prices_usd` seeds.
- Group (c) NEW: §3.3 Combined Yield sheet cells (above).
- EZDK Rebar Other Conversion + Total VC (Sc1/Sc2) — on arrival of
  unit-price overrides.
- EFS/ERM/ESR Rebar Home Scrap rows, Total Conversion, Total VC,
  Difference — on arrival of home-scrap % + byproduct prices.
- HRC Other Conversion + Total VC summary assertions (item-6).
