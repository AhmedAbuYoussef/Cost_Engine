# Model fixes — from the workbook to the corrected model

The engine runs the model under two rule sets:

- **Corrected** (default): every fix below applied, and no typed-in results. Every
  number is an input or a formula.
- **Legacy**: an exact replica of `New_Corp_Model_v8_30-12-19.xlsx`. It is proven cell
  for cell against Excel and LibreOffice. Use it to reproduce old figures, and as the
  starting point of the bridge.

`python model_fixes.py` turns the workbook into the corrected baseline
(`model_initial_state.json`) and writes the **fix-by-fix bridge**
(`reports/fix_bridge.md`). The bridge shows how much each fix moves each company's
EBT. Each fix is a named rule in `cost_engine.RULES` and can be switched off on its own.

## Bridge (monthly, USD M — reference workbook)

| Fix | What | Group EBT | Group CM | Group revenue | EZDK EBT | EFS EBT | ERM EBT | ESR EBT |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| — | Workbook as is (legacy) | -10.870 | 38.570 | 235.275 | -1.913 | -0.834 | -4.178 | -3.945 |
| A1 | Export expenses: $/t × volume | · | · | · | · | · | · | · |
| A2/A3/B6 | Exports produced, priced, ×12 consistently | · | · | · | · | · | · | · |
| A4 | ERM DRI volume includes EFS flat | · | · | · | · | · | · | · |
| A5 | HRC market share | · | · | · | · | · | · | · |
| A6 | ESR electricity price decimal | -3.250 | -3.250 | · | · | · | · | -3.250 |
| A7 | Blends sum to 100% | -0.022 | -0.022 | · | -0.013 | -0.006 | -0.002 | · |
| B3 | DRI selling price from input | · | · | · | · | · | · | · |
| B5 | Own inputs per line | · | · | · | · | · | · | · |
| C | Summaries = detail | · | · | · | · | · | · | · |
| B1 | ERM billet: cheapest source + supplier cascade | · | · | · | +0.553 | · | -0.553 | · |
| B2 | ERM DRI P&L + eliminations | +0.119 | +0.289 | · | · | · | +0.119 | · |
| B4 | Break-even on CM | · | · | · | · | · | · | · |
| **=** | **Corrected model** | **-14.023** | **35.587** | **235.275** | **-1.374** | **-0.840** | **-4.614** | **-7.195** |

`·` = no change on today's data. Most fixes don't move today's figures, but they
change how the model *responds* to amendments. For example, with A1 export expenses
now grow with export volume; before, they stayed fixed whatever was exported.

## The fixes

| # | Workbook did | Corrected model does |
|---|---|---|
| A1 | Subtracted export expenses as a lump sum: 0.2 / 0.8 / 0.15 M$, labelled "$/t". | Each figure was exactly **$20/t × the export volume**, so the model now stores **$20/t** and charges $/t × export tons. Same result today; it now scales with volume. |
| A2 | EFS rebar exports cost money but earned no revenue (hardcoded 0). | Every export is priced. |
| A3 | Rebar exports were sold but not produced. | Production = local + export for every product. |
| B6 | Annual/LE P&Ls held typed copies of rates and an inconsistent ×12. | All four P&Ls come from one calculation: annual = 12 × monthly and LE = USD × FX, exactly (tested). |
| A4 | ERM's DRI volume left out the 14.8 kt it supplies to EFS's flat line. | Included. ERM DRI fixed cost 4,014 → 3,427 LE/t. |
| A5 | HRC group sales summed the wrong cells (#DIV/0!). | EZDK + EFS HRC local sales (52.5 kt). The share appears once you enter the HRC market size. |
| A6 | ESR electricity 0.007 $/kWh (others 0.07). | **0.07 $/kWh.** This is the one fix that moves EBT materially: ESR −3.25 M$/month. |
| A7 | Blends summed to 99.977–99.998%. | Imported scrap (the balancing material) takes the gap: EZDK 15.977→16%, EFS 5.978→6%. |
| B1 | ERM bought billets at EZDK's cost, and a typed 429.88 sat in the trade-off matrix. | The matrix is fully computed. ERM buys from the **cheapest source** in the matrix (EZDK, 457.02 $/t), and the supplier's billet, DRI, scrap and IOP volumes rise by ERM's billets (rulebook §4.7). The supplier books the sale. ERM can be switched to `market`, `offer:EFS`, `offer:ESR`, `vc:EZDK`… |
| B2 | ERM carried all its fixed cost on Rebar, plus a typed "DRI gain" of 0.17 M$; ERM's DRI sales were in no P&L. | ERM has a **DRI column**: 101.5 kt sold to EFS/ESR at VC + margin, CM 0.289 M$. Fixed costs are split 70/30 per the distribution %. A **consolidated P&L** eliminates intercompany sales from revenue and COGS. |
| B3 | The DRI gross margin used a frozen link to another workbook. | Uses the DRI selling-price input (same value today). |
| B4 | Break-even = (fixed + dep) ÷ (price − VC), ignoring export expenses. | (fixed + dep) ÷ CM per ton. A **cash break-even** (fixed only) is added. Break-even is blank when each ton loses money. |
| B5 | Silent cross-links: ESR's scrap prices were EZDK's; both flat lines used EZDK's billet electricity; ERM's rolling scrap was credited at the billet *purchase price*. | Each line has its own inputs (same values today). The ERM scrap link meant a change in an intercompany price changed *group* profit, which is now impossible (tested). |
| C | Summary sheets omitted some detail lines (billet VC 438.8998 vs 438.9012). | Summaries are derived from the detailed build-up and match it exactly (integrity check). |

## Integrity checks (all pass on the corrected baseline)

`fixed_distribution_100`, `blending_100` (now including home scrap and pig iron),
`no_hardcoded_results` (fails if anyone types a value into the trade-off matrix),
`currency_tagged`, `break_even_zero`, `intercompany_reconciles` (ERM's DRI revenue
= what EFS+ESR pay for it; the supplier's billet revenue = what ERM pays), and
`summary_matches_detail`. The workbook itself fails two of them: blends and
typed-in results.

## Please confirm — my judgement calls

1. **ESR electricity 0.07 $/kWh** (A6). If ESR really has a special tariff, put it back in `model_initial_state.json`. This one decision is worth 3.25 M$/month.
2. **ERM's rolling scrap value: 7,112 LE/t.** Frozen at today's value, which is the billet price. EZDK values the same kind of scrap at 5,133 LE/t. If 5,133 is right, ERM's scrap credit shrinks and its EBT falls by 0.044 M$/month.
3. **ERM billet sourcing = cheapest internal/market offer.** Today that is EZDK at cost × 1.041. Another rule is one setting away.
4. **Export expenses = $20/t.** Inferred from 0.2 M$ / 10 kt, 0.8 / 40 and 0.15 / 7.5, which all give exactly 20. (The detail sheets mention $11/t in an unused cell.)
5. **Capacity (warning, from the workbook's own capacity cells ÷ 12).**
   - With ERM buying its billets from EZDK, EZDK needs **261.6 kt/month of DRI against 250 kt** (104.6%). This is the upstream check rulebook §4.7 asks for: either part of ERM's billets come from EFS or the market, or the ceiling is wrong.
   - EZDK wire rod runs at 50 kt against a 41.7 kt "capacity". That cell on the Wire sheet looks copy-pasted from ERM's (same label, same 16.08% utilisation), so it is probably not the real wire capacity.

## Not modelled

The detail sheets' own fixed-cost/COGS blocks (e.g. `EZDK Rebar` rows 206–235). The P&L
takes fixed costs from the `Fixed Cost` sheet, so these blocks never reached a result.
Sheet1/2/4/5/6, BS and P&L Sc2 are side analyses outside the model chain.

## Where the engine differs from Excel even in legacy mode

- **Zero sales:** per-ton costs are kept, and break-even = 0 (Excel: #DIV/0!).
- **Other divisions by zero** return `None`.
