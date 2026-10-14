# Fix-by-fix bridge: workbook → corrected model

Monthly, USD M. The first row shows the workbook's figures. Each later row shows the change from applying that one fix on top of the ones above it. Group figures are after intercompany eliminations. `·` = no change.

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

| Other measure | Workbook | Corrected |
|---|---:|---:|
| ERM billet $/t | 438.90 | 457.02 |
| ERM DRI fixed LE/t | 4014.09 | 3427.25 |
| checks passed | 3.00 | 7.00 |

## What each fix changed in the data

- **A1 Export expenses: $/t × volume:** EZDK Wire Rod: 0.2 M$/month on 10 kt → 20.00 $/t; EZDK HRC: 0.8 M$/month on 40 kt → 20.00 $/t; EFS HRC: 0.15 M$/month on 7.5 kt → 20.00 $/t
- **A2/A3/B6 Exports produced, priced, ×12 consistently:** rebar exports now produced and priced: none in this data
- **A4 ERM DRI volume includes EFS flat:** ERM DRI volume = EFS long + EFS flat + ESR DRI
- **A5 HRC market share:** HRC group sales computed; HRC share needs the total market size
- **A6 ESR electricity price decimal:** ESR electricity 0.007 → 0.07 $/kWh
- **A7 Blends sum to 100%:** EZDK long: imported scrap 15.977% → 16% (blend was 99.977%); EFS long: imported scrap 5.978% → 6% (blend was 99.978%); EZDK flat: imported scrap 3% → 3.002% (blend was 99.998%); EFS flat: imported scrap 5.978% → 6% (blend was 99.978%)
- **B3 DRI selling price from input:** selling prices were already inputs (same values)
- **B5 Own inputs per line:** ESR local_scrap_usd_t was linked to EZDK; now its own input (300); ESR imported_scrap_usd_t was linked to EZDK; now its own input (300); flat lines now use their own electricity price ('Flat' sheet); ERM Rolling scrap credit was linked to the billet price; now its own input (7,112 LE/t) — review: EZDK Wire values rolling scrap at 5,133 LE/t
- **C Summaries = detail:** billet / HRC / rebar summaries now equal the detail sheets
- **B1 ERM billet: cheapest source + supplier cascade:** removed typed matrix cell EZDK→ERM = 429.88; ERM billet source vc:EZDK → min (cheapest offer in the trade-off matrix)
- **B2 ERM DRI P&L + eliminations:** removed typed DRI intercompany gain 0.17 M$/month; ERM DRI column computed
- **B4 Break-even on CM:** break-even uses CM per ton (after export expenses)
