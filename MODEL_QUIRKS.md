# Model quirks — things the workbook does that you should confirm

The engine reproduces `New_Corp_Model_v8_30-12-19.xlsx` **exactly, quirks included**.
That is deliberate: it is the only way the tests can prove the engine is the same
model as the workbook. Fixing a quirk is a one-line change in `cost_engine.py`, but it
should be your decision, made one item at a time, because each fix moves the numbers away from Excel.

Figures below are from the reference workbook (monthly, USD).

## A. Likely errors — decision needed

| # | What the workbook does | Where | Impact on the reference figures | Suggested fix |
|---|---|---|---|---|
| A1 | **Export expenses labelled "$/t" are subtracted from contribution margin as if they were M$.** CM = Revenue − COGS − 0.2, not − 0.2 × qty. | `P&L $ Monthly`!E23:P23 (row 21) | Wire Rod: 0.200 M$ deducted vs 0.002 M$ if $/t × 10 kt. HRC EZDK 0.800 vs 0.032; HRC EFS 0.150 vs 0.001. **Group EBT understated by 1.115 M$/month.** | Either the inputs are really M$/month (fix the label) or CM should use qty × rate ÷ 1000. |
| A2 | **EFS rebar exports earn no revenue.** Export qty (`Market Share`!E20) is added to quantity and COGS, but export value/price are hardcoded 0. | `P&L $ Monthly`!J13, J14 | None today (EFS rebar export is blank). Any EFS rebar export entered would carry cost but no revenue. | Link J13/J14 like K13/K14. |
| A3 | **Rebar exports are not produced.** EZDK/EFS rebar production uses local sales only, but the P&L sells local + export. | `EZDK Rebar`!E10, `EFS Rebar`!E10 | None today (rebar exports blank). | Production = local + export (as Wire and HRC already do). |
| A4 | **ERM's DRI volume omits the DRI it supplies to EFS's flat line.** ERM production = EFS rebar DRI + ESR DRI. `Production Requirments` counts EFS flat DRI for ERM's IOP. | `DRI Cost`!G16 | 86,694 t used vs 101,539 t; ERM DRI fixed cost **4,014 LE/t vs 3,427 LE/t**. | Add `'EFS Flat'!E26`. |
| A5 | **Market share: HRC group sales sum the wrong cells** (the market-size cells), giving 0 and #DIV/0! for the HRC company percentages. | `Market Share`!G11 | HRC shares cannot be shown. | `=SUM(G6:G7)`. |
| A6 | **ESR electricity price is 0.007 $/kWh**, ten times lower than every other line (0.07). | `Billet`!G11 | ESR EAF electricity cost 4.29 $/t instead of ~42.9 $/t. | Probably a typo; confirm. |
| A7 | **Blending ratios don't sum to 100%**: EZDK long 99.977%, EFS long 99.978%, EFS flat 99.978%. | `Billet`!E13:F15, `Flat`!F13:F15 | ~0.02% of solid charge is unaccounted. The engine flags this (integrity check `blending_100`). | Correct the inputs. |

## B. Design choices to confirm

| # | What the workbook does | Where | Note |
|---|---|---|---|
| B1 | **ERM buys billet at EZDK's billet VC (438.90), with no trade-off ratio.** The matrix shows a hardcoded 429.88 for EZDK→ERM (formula would give 456.93); that value is the ERM column minimum but ERM does not use it. | `Rebar`!G12, `Billet`!G39 | The rulebook/brief default for ERM was *market*. The engine reads the workbook's choice (`state["sourcing"]["ERM_rebar_billet"] = "vc:EZDK"`) and supports `"market"`, `"min"`, `"offer:<CO>"`, `"vc:<CO>"`. ERM EBT: −4.18 (EZDK VC) / −3.91 (min) / −6.46 (market) M$. |
| B2 | **ERM's P&L carries the whole company's fixed cost on Rebar**, plus a hardcoded "Intercompany Gains — DRI" of 0.17 M$/month. The 70/30 DRI/Rebar distribution is computed but used nowhere; ERM's DRI sales never appear in any P&L, so there is no eliminations column. | `P&L $ Monthly`!N28, N31:N33, N40 | The rulebook's consolidated P&L with an eliminations column does not exist in the workbook. |
| B3 | **The DRI selling price input is not used.** Gross margin uses a link to an external workbook (`[1]Production Q. & Sales (2)`), frozen at 6,465.41 LE/t. | `DRI Cost`!E86/G86 vs E13/G13 | The engine reads the cached external value and records its source in the state. |
| B4 | **Break-even includes depreciation** and uses (avg price − VC), not CM/t: BE = (Total Fixed + Dep) ÷ (Avg Price − VC/t). | `P&L $ Monthly` row 48 | Differs from rulebook §8.2. |
| B5 | **Cross-links that are not per-company inputs**: ESR scrap prices = EZDK's; both flat sheets use EZDK's billet electricity price (the `Flat` sheet's own electricity row is unused); rolling sheets (ERM, Wire) use a hardcoded 0.07 $/kWh; ESR EAF electricity = `Billet`!G20 + 15.73 kWh. | `Billet`!G9:G10; `EZDK/EFS Flat`!E62; `ERM Rolling`/`EZDK Wire`!E45; `ESR Rebar`!E39 | Changing EZDK's scrap/electricity also moves ESR's/EFS-flat's costs. |
| B6 | **Copies instead of links in the LE and Annual P&Ls.** The export-expense rates (0.2, 0.8, 0.15) and the 0.17 DRI gain are retyped as constants. EZDK rebar export is ×12 in `P&L $ Annual` but not in `P&L LE Annual`; EFS rebar export is never ×12. | `P&L LE Monthly`, `P&L $ Annual`, `P&L LE Annual` rows 8, 21, 28 | Editing `P&L $ Monthly` does not flow to the other three. The engine derives all four from one set of inputs (identical today). |

## C. Minor / cosmetic (replicated, no action needed)

- `Billet`/`Flat` "Other Conversion Cost" omits stage-2 nitrogen and argon: billet VC 438.8998 (summary) vs 438.9012 (detail sheet, which is what the P&L uses).
- `Rebar`!F16 (EFS) leaves out the work-roll line, while EZDK's includes it (EFS work roll is 0 today).
- The detail sheets' own fixed-cost/COGS blocks (e.g. `EZDK Rebar` rows 206–235; the flat sheets' are hardcoded) are not connected to the P&L, which uses `Fixed Cost`. The engine does not reproduce them.
- `Billet`!E36 "Landed Cost" factor (1.0174) is not used anywhere.

## D. Where the engine deliberately differs from Excel

- **Zero sales.** Excel shows #DIV/0! across a product's whole cost build-up. The engine returns the
  per-ton costs (they don't depend on volume), zero volumes, and **break-even = 0** (rulebook check 7).
- **Division by zero elsewhere** (e.g. average price with no sales) is returned as `None`, where Excel shows #DIV/0!.
