# `find_optimal_mix` — the LP formulation (Appendix D.1)

Written and checked against the engine before any solver code, as D.1 requires. Everything here is
monthly. Quantities are in kt unless marked t. Money is in USD. Contribution margin (CM) is the
model's: revenue − variable COGS − export expenses. Fixed costs never enter it.

## 1. Why a linear program is exact for this model

In the engine, every per-ton cost is independent of volume:
- yields, consumptions and prices are inputs;
- fixed costs sit below CM.

The engine's CM, as a function of the sales volumes *v* and the furnace blends *b*, therefore has
exactly this form:

    CM(v, b) = K(v) + Σ_f F_f(v) · Σ_k b_fk · w_fk

- *K* and *F_f* are affine in *v*. *F_f* is the tonnage of free charge (DRI + local scrap +
  imported scrap) into furnace *f*.
- *w_fk* is a constant: the CM effect of one ton of material *k* charged in furnace *f*.

The only non-linearity is the product of charge and blend share. It disappears when the decision
is **tons of each material** rather than the share: `Y_fk = b_fk · F_f(v)`. The ERM billet split
(share × volume) is handled the same way: tons from the supplier and tons from the market.

**Checked numerically on the corrected baseline** (with ERM sourcing at `split:EZDK:0.6`):
- second differences of CM along every sales and blend input are below 4·10⁻⁸ $;
- doubling a line's volume doubles the CM effect of its blend to 1 part in 10¹³.

That is the structure above, to machine precision.

## 2. Decision variables (all ≥ 0)

| Symbol | Meaning | Count |
|---|---|---|
| `L[c,p]`, `X[c,p]` | local and export sales, kt, for each company × product that exists (production matrix) | 7 + 7 |
| `Y[f,k]` | kt of material *k* ∈ {DRI, local scrap, imported scrap} charged in furnace *f* ∈ {EZDK long, EFS long, ESR long, EZDK flat, EFS flat} | 15 |
| `I`, `M` | ERM's billets bought from its internal supplier *s*, and from the market, kt | 2 |

**One internal supplier per run** (Tool 12: "internal billet share per long-line buyer"; any
shortfall goes to market billet, option α). The supplier *s* ∈ {EZDK, EFS, ESR} is chosen by solving
the LP once per supplier and keeping the best. Each solve is exact, so the best of three is the
optimum over all single-supplier plans.

## 3. Objective

**group_cm**: maximise consolidated CM. Intercompany DRI and billet sales are eliminated, so
transfer prices cancel and real costs decide.

**company_cm** (with `company`): maximise that company's CM, including intercompany prices:
- DRI from ERM at ERM's VC + margin;
- billets to ERM at the supplier's offer price.

Both read, per ton:

    CM = Σ_c,p [ (local price − variable cost of the finished ton excl. free charge) · L
               + (export price − export expense − same variable cost) · X ]
         − Σ_f,k (effective cost of material k in furnace f) · Y[f,k]
         + (market billet price − supplier conversion cost) · I        (group view)
         − market billet price · M                                     (part of ERM's cost)

The engine is the model, so **the coefficients are read from the engine itself**, not re-derived
by hand:
- `∂CM/∂v` at the current blends;
- `∂CM/∂b_fk`, divided by `F_f`, gives `w_fk`;
- `∂F_f/∂v` and `∂(ERM billets)/∂v`.

All are central differences of affine functions, so they are exact up to rounding. The LP objective
is then

    CM(v, Y) = CM(v₀, b₀) + a·(v − v₀) + Σ_f,k w_fk · (Y_fk − b₀_fk · F_f(v))

This equals the engine's CM wherever the structure in §1 holds. That is checked on every run by the
engine cross-check (§6), and a mismatch returns an error, not a number.

**Company objective — one coupling that is not linear.** ERM pays its supplier an intercompany
price built from the supplier's own billet cost, so that price moves with the supplier's long-line
blend. When the objective is ERM's CM or the supplier's, (billets bought) × (blend-dependent price)
is a product of two decisions.
- By default, that blend is held at its current value, and the result says so.
- Asking explicitly to free it is refused, with the alternatives: hold the blend, hold the
  sourcing, or use `group_cm`, where intercompany prices cancel.

The engine cross-check found this the first time a company run was tried. It refused the run
(a 0.96 M$ mismatch on ESR's CM) instead of returning a number.

## 4. Constraints

1. **DRI capacity, per plant (t).**
   - EZDK: `Y[EZDK long, DRI] + Y[EZDK flat, DRI] ≤ ceiling`.
   - ERM: `Y[EFS long, DRI] + Y[ESR long, DRI] + Y[EFS flat, DRI] ≤ ceiling`.
2. **Finished capacity (t).** `L[c,p] + X[c,p] ≤ ceiling[c,p]` for each existing combination.
3. **Policy floors.** `Σ_c L[c,p] ≥ φ_p · Σ_c (L + X)[c,p]` for Rebar (0.50), Wire Rod (0.20)
   and HRC (0.20).
4. **Local market ceilings.** `Σ_c L[c,p] ≤ M_p`. Rebar and Wire Rod default to the state. **HRC
   must be given every run**: without it the tool returns `needs_input`.
5. **Furnace balance.** `Σ_k Y[f,k] = F_f(v)`. The free materials fill the charge left after the
   fixed home-scrap and pig-iron shares, so blending_100 holds by construction.
6. **ERM billets.** `I + M = B_ERM(v)`, the billets ERM's rolling needs for its rebar.
7. **Locks.** Anything not in `free_variables` stays as it is now:
   - a locked sales quantity is fixed at its value;
   - a locked blend keeps its shares: `Y[f,k] = b₀_fk · F_f(v)`;
   - locked sourcing keeps the current supplier and share: `I = s₀ · B_ERM(v)`.
7b. **Charge-mix limits** (`state["blend_limits"]`, see [BLEND_LIMITS.md](BLEND_LIMITS.md)):
   - `min% · F ≤ Y[f,k] ≤ max% · F` on every running furnace;
   - group local scrap `Σ_f Y[f, local scrap] ≤` supply (kt).

   Both are linear, applied by default, and can be overridden per run. A held blend outside a
   lowered limit is still feasible by idling that furnace: an idle furnace has no mix to limit.
8. **Additional constraints** (`run_constraints.additional_constraints`):
   `{"variable": <path>, "min": …, "max": …}` on a sales quantity (kt), a blend share (%), or
   `sourcing.ERM_internal_share` (0–1). Blend shares are bounded linearly as
   `Y[f,k] ≥ min% · F_f` and `Y[f,k] ≤ max% · F_f`.

Never optimised, as listed in the spec: prices (raw material, utility, selling, intercompany),
yields, MRMR, consumptions, fixed costs. There is no billet capacity ceiling (Appendix A: billet
capacity is implied by the cascade).

## 5. From the LP answer back to the model

- Sales: `L`, `X` → `sales.<c>.<p>.local_kt` and `.export_kt`.
- Blends: `100 · Y[f,k] / F_f` → `blend_pct` (unchanged on an idle furnace).
- Sourcing: `I / B_ERM` → `split:<s>:<share>`, written as `offer:<s>` at 1 and `market` at 0.

The plan is returned. It is **not applied**: the user chooses to apply it, save it as a scenario,
or neither.

## 6. Self-checks on every run (D.4). Any failure returns an error, never a number

1. **Engine cross-check.** The plan goes through `compute_all`. The engine's CM must equal the
   LP's to machine precision: |Δ| ≤ 10⁻⁹ × scale.
2. **Integrity.** The plan passes every error-level integrity check. Capacity is checked against
   the run's ceilings, and every LP constraint is re-evaluated from the engine's own outputs.
3. **Perturbation.** Each free variable is moved by ±5% on its own:
   - a sales quantity at 0 moves by 5% of its ceiling;
   - the other shares of that blend are rescaled to keep the sum;
   - the internal share is clipped to 0–1.

   Every perturbed plan that still meets all constraints goes through the engine, and none may
   beat the optimum. Infeasible perturbations are counted and reported.

## 7. Infeasibility

The LP is infeasible when the constraints conflict, for example a local HRC market of 0 with a 20%
local floor while HRC exports are held fixed. The tool then finds a **minimal conflicting set** of
constraint groups by deletion filtering: drop one group, re-solve, keep it out if the rest is
still infeasible. It names that set and returns no number. It never relaxes anything on its own.

## 8. Shadow prices

These are the dual values of the capacity, floor and market-ceiling rows at the optimum, in $ of
CM per extra ton (per extra percentage point for floors). They are reported for binding rows only,
e.g. "+$X group CM per extra ton of ERM DRI capacity".

## 9. Checked against the rulebook

| Rulebook | Here |
|---|---|
| §4.4 billet material = Σ blend × price; yield effect = material × (1/yield − 1) | inside `w_fk` and `F_f`, read from the engine that implements it |
| production cascade: DRI = solid charge × DRI blend %; IOP = DRI × MRMR | DRI capacity rows sum `Y[·,DRI]`, which is solid charge × DRI share |
| §4.6–4.7 trade-off matrix; supplier capacity cascade for ERM billets | `I` raises the supplier's furnace charge `F_s` and therefore its DRI need |
| §8.4–8.6 consolidation, intercompany eliminated | `group_cm` is the consolidated CM |
| Appendix A capacity ceilings, policy floors, HRC market asked each run | constraints 1–4 |

## 10. Verification (D.2), as run on the shipped baseline

| Case | Result |
|---|---|
| 1 Identity: everything held | CM equal to the current CM, Δ 0.00 $; no change proposed. Ceilings are raised to current use, because the dummy baseline runs EZDK's DRI at 104.6% and wire rod at 120%. |
| 2 Single-company parity: ERM's billet sourcing | The optimizer buys from EZDK at 457.02 $/t, the trade-off-matrix minimum. An engine sweep of every supplier and share agrees to the cent. On the workbook's own data it lands on Excel's Billet!G44 (429.88 $/t). With EZDK's DRI capped so that only 40% fits, it finds the exact 40% split and beats every point of a fine sweep. |
| 3 Dominant option | Market at $100/t (ESR at $500): ERM buys 100% market, under both objectives. ESR at $100/t (market at $500): ERM buys 100% from ESR. |
| 4 Infeasibility | Local HRC market 0 with a 20% floor and HRC exports held: no number. The conflict named is the HRC floor, the HRC market ceiling, and a held HRC export. |

`optimizer.verify()` runs all four (about 2 s). `tools.optimizer_gate()` runs them once per process
and offers `find_optimal_mix` only if all pass (D.3); otherwise the tool answers
`tool_unavailable` with the failing case.

## 11. Choices to confirm (the data has no limits for these)

- **Charge-mix limits** are now standing data. Several values are assumptions awaiting the plant's
  figures; see [BLEND_LIMITS.md](BLEND_LIMITS.md) for each value's source and the three open
  questions.
- **Exports are unconstrained.** There is no export demand ceiling, so with positive export
  margins the LP fills capacity. Recommendation: export ceilings as additional constraints when
  known.
- **Verification case 4 (D.2).** With HRC exports free, a local HRC market of 0 and a 20% floor is
  feasible: the LP stops HRC entirely. The case is run as the spec intends, with HRC exports held
  at their current level, and the report must name the floor vs ceiling conflict.
- **Verification case 2 (D.2)** asks for an Excel Solver cross-check. Excel cannot run here, so
  the optimizer's ERM sourcing is matched against two independent references:
  1. the workbook's own answer to the same question, the trade-off-matrix minimum it caches;
  2. a brute-force engine sweep over every supplier and internal share.

  Repeating it in Excel Solver on your machine is the remaining confirmation.
