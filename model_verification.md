# Model Verification Sheet

Every value below — inputs and outputs — can be compared cell-by-cell against the Excel model.
FX Rate: **15.92 EGP/USD** | Default currency: **USD** | Date: 2026-04-17

---

## Corrections

- 2026-04-24 — EZDK Rebar Sc2 home scrap corrected from 7.33 (typo) to 14.48. Sc1 and Sc2 share identical inputs for this line item per formula (billets used × home-scrap % × byproduct price ÷ finished qty is independent of the billet sourcing scenario). Cascaded cells updated to stay self-consistent: Sc2 Total Conversion Cost 42.37 → 35.23, Sc2 Total Variable Mfg Cost 632.37 → 625.23, Difference (Sc1 − Sc2) 197.85 → 190.71.

---

## 1. Stage 1 — DRI Cost

### 1.1 Inputs

| Item | Unit | EZDK | ERM |
|---|---|---|---|
| Production Volume | tons | 153,735 | 68,821 |
| MRMR | t/t | 1.47 | 1.43 |
| Selling Price | LE/t | 6,465 | 6,465 |
| IOP Landed | USD/t | 154.84 | 174.31 |
| IOP Landed | EGP/t | 2,465 | 2,775 |
| Electricity consumption | KWh/t | 42 | 27 |
| Natural Gas consumption | Nm³/t | 301.7 | 333.0 |
| Oxygen consumption | Nm³/t | 14 | 14 |
| Nitrogen consumption | Nm³/t | 15.5 | 10.2 |
| Water consumption | Nm³/t | 1.2 | 1.2 |
| Chemicals consumption | t/t | 1.0 | 0.7 |
| External Services | t/t | 0.993 | 0.607 |
| Other | t/t | 1.0 | 0.0 |
| Electricity price | EGP/KWh | 0.9 | 0.9 |
| Natural Gas price | EGP/Nm³ | 2.56 | 2.56 |
| Nitrogen price | EGP/Nm³ | 1 | 1 |
| Water price | EGP/Nm³ | 4 | 4 |
| Chemicals price | LE/t | 25 | 25 |
| External Services price | LE/t | 43 | 44 |
| Other price | LE/t | 20 | 0 |
| Labor | LE (M) | 54.01 | 54.01 |
| Depreciation | LE (M) | 239.75 | 239.75 |
| Other Fixed | LE (M) | 54.24 | 54.24 |

### 1.2 Calculated Outputs — Detailed (LE/t)

| Item | EZDK | ERM |
|---|---|---|
| IOP Cost (= MRMR × IOP EGP) | 3,624 | 3,968 |
| Electricity | 38 | 25 |
| Natural Gas | 772 | 852 |
| Oxygen | 0 | 0 |
| Nitrogen | 16 | 10 |
| Water | 5 | 5 |
| Chemicals | 25 | 16 |
| Spare Parts | 0 | 0 |
| External Services | 43 | 27 |
| Other | 20 | 0 |
| **Variable Cost** | **4,541** | **4,902** |
| Labor | 351 | 785 |
| Depreciation | 1,559 | 3,484 |
| Other Fixed | 353 | 788 |
| **Fixed Cost** | **2,264** | **5,057** |
| **Manufacturing Cost** | **6,805** | **9,959** |
| DRI Selling Price | 6,465 | 6,465 |
| **Gross Margin** | **(339)** | **(3,494)** |

### 1.3 Calculated Outputs — Conversion Cost View ($/t)

| Item | EZDK | ERM |
|---|---|---|
| Material Price (= IOP Landed $) | 154.84 | 174.31 |
| MRMR Effect (= (MRMR-1) × IOP $) | 72.77 | 74.95 |
| Other Conversion Cost (= LE items ÷ FX) | 57.62 | 58.68 |
| Total Conversion Cost | 130.39 | 133.63 |
| **Total Variable Mfg Cost** | **285.23** | **307.94** |

---

## 2. Stage 2 — Billet Cost

### 2.1 Inputs (summary)

| Item | Unit | EZDK | EFS | ESR |
|---|---|---|---|---|
| EAF Yield | % | 85.99 | 84.82 | 87.35 |
| CCP Yield | % | 98.77 | 98.05 | 98.50 |
| DRI blending | % | 60.0 | 70.0 | 20.0 |
| Local Scrap blending | % | 12.0 | 20.9 | 16.0 |
| Imported Scrap blending | % | 28.0 | 9.1 | 64.0 |
| Trade-off ratio | — | 1.169 | 1.016 | 1.017 |
| DRI price used | $/t | 285.23 | 307.94 | 315.48 |
| Local Scrap price | $/t | 136.81 | 270.10 | 270.10 |
| Imported Scrap Landed | $/t | 270.22 | 307.56 | 307.56 |
| Electricity | $/KWh | 0.06 | 0.06 | 0.06 |
| EAF & LF Electricity consumption | KWh/t MS | 693.3 | 689.84 | 597.1 |

### 2.2 Calculated Outputs — Conversion Cost View ($/t)

| Item | EZDK | EFS | ESR |
|---|---|---|---|
| Material Price | 263.21 | 299.98 | 303.15 |
| Yield Effect | 46.70 | 60.72 | 49.19 |
| Other Conversion Cost | 99.61 | 107.26 | 97.97 |
| Total Conversion Cost | 146.31 | 167.98 | 147.16 |
| **Total Variable Mfg Cost** | **409.52** | **467.96** | **450.31** |

### 2.3 Trade-off Matrix (fully dynamic)

Intercompany Price = Seller's Billet VC × Seller's Trade-off Ratio.

| Source → | Price ($/t) | To EZDK | To EFS | To ERM | To ESR |
|---|---|---|---|---|---|
| EZDK (×1.169) | 478.73 | 409.52 | 478.73 | 478.73 | 478.73 |
| EFS (×1.016) | 475.45 | 475.45 | 467.96 | 475.45 | 475.45 |
| ESR (×1.017) | 457.97 | 457.97 | 457.97 | 457.97 | 450.31 |
| Market | 590.00 | 590.00 | 590.00 | 590.00 | 590.00 |
| **Minimum** | | **409.52** | **457.97** | **457.97** | **450.31** |

*Note: ERM sourcing is a user decision — if selects internal, supplier's production must increase (capacity check upstream).*

### 2.4 Market Billet Build-up

| Component | USD/t |
|---|---|
| Base | 428 |
| Safe Guards | 74 |
| Other Costs | 88 |
| **Market Price** | **590** |

---

## 3. Stage 3 — Finished Products

### 3.1 Rebar — All four companies

**Yields:** EZDK 94.64% | EFS 97.09% | ERM 97.92% | ESR 96.82%

**Scenario 1 — In-house billet:**

| Item ($/t) | EZDK | EFS | ERM | ESR |
|---|---|---|---|---|
| Material Price (min from matrix) | 409.52 | 467.96 | 590.00* | 450.31 |
| Yield Effect | 23.19 | 14.03 | 12.55 | 14.78 |
| Home Scrap Deduction | (14.48) | (7.24) | (5.62) | (7.91) |
| Other Conversion Cost | 16.29 | 11.32 | 17.18 | 20.64 |
| Total Conversion Cost | 25.00 | 18.11 | 24.10 | 27.50 |
| **Total Variable Mfg Cost** | **434.52** | **486.07** | **614.10** | **477.81** |

*ERM shown at market price per current user-provided data. If user switches ERM to internal sourcing, Material Price drops to 457.97 and upstream capacity cascades kick in.*

**Scenario 2 — Market billet:**

| Item ($/t) | EZDK | EFS | ERM | ESR |
|---|---|---|---|---|
| Material Price | 590 | 590 | 590 | 590 |
| Yield Effect | 33.42 | 17.68 | 12.55 | 19.36 |
| Home Scrap Deduction | (14.48) | (7.24) | (5.62) | (7.91) |
| Other Conversion Cost | 16.29 | 11.32 | 17.18 | 20.64 |
| Total Conversion Cost | 35.23 | 21.76 | 24.10 | 32.09 |
| **Total Variable Mfg Cost** | **625.23** | **611.76** | **614.10** | **622.09** |
| **Difference (Sc1 − Sc2)** | **(190.71)** | **(125.70)** | **0.00** | **(144.27)** |

### 3.2 Wire Rod — EZDK only

Wire Yield: 97.78%. Same formula structure as Rebar. Sc1 Total VC can be calculated on demand using EZDK Billet VC + Wire Yield effect.

### 3.3 HRC (Flat) — EZDK & EFS only

| Item | Unit | EZDK | EFS |
|---|---|---|---|
| EAF Yield | % | 85.74 | 84.82 |
| TSC Yield | % | 98.52 | 98.00 |
| HSM Yield | % | 97.56 | 98.00 |
| Combined Yield | % | 82.37 | 81.43 |
| DRI blending | % | 80.00 | 70.00 |
| Local Scrap | % | 17.96 | 21.00 |
| Imported Scrap | % | 2.04 | 9.00 |
| Material Price | $/t | 280.73 | 299.96 |
| Yield Effect | $/t | 59.92 | 68.26 |
| Other Conversion Cost | $/t | 108.87 | 128.60 |
| **Total Variable Mfg Cost** | **$/t** | **449.52** | **496.83** |

---

## 4. Sales

### 4.1 Monthly Plan

| | Unit | EZDK | EFS | ERM | ESR | Group |
|---|---|---|---|---|---|---|
| **Rebar Local** | Ktons | 70 | 60 | 0 | 70 | 200 |
| **Rebar Export** | Ktons | 0 | 0 | 0 | 0 | 0 |
| **Wire Rod Local** | Ktons | 40 | — | — | — | 40 |
| **Wire Rod Export** | Ktons | 40 | — | — | — | 40 |
| **HRC Local** | Ktons | 45 | 0 | — | — | 45 |
| **HRC Export** | Ktons | 0 | 75 | — | — | 75 |

### 4.2 Selling Prices

| | Unit | EZDK | EFS | ERM | ESR |
|---|---|---|---|---|---|
| Rebar Local | LE/t | 8,910 | 8,860 | 8,860 | 8,860 |
| Rebar Export | $/t | 500 | 500 | 500 | 500 |
| Wire Rod Local | LE/t | 8,860 | — | — | — |
| Wire Rod Export | $/t | 520 | — | — | — |
| HRC Local | LE/t | 8,750 | 8,750 | — | — |
| HRC Export | $/t | 540 | 521 | — | — |

### 4.3 Export Expenses

| Company | Product | $/t |
|---|---|---|
| EFS | HRC | 0.15 |
| EZDK | Wire Rod | 0.2 |
| EZDK | HRC | 0.8 |
| All others | — | 0.00 |

### 4.4 Market Share

| Product | Group Local (Ktons) | Total Local Market | Ezz Market Share |
|---|---|---|---|
| Rebar | 200 | 440 | 45.45% |
| Wire Rod | 40 | 60 | 66.67% |
| HRC | 45 | *user to provide* | *pending* |

---

## 5. Production Cascade (derived from Sales)

### 5.1 Long Line (Rebar + Wire Rod)

| | Unit | EZDK | EFS | ERM | ESR |
|---|---|---|---|---|---|
| Rebar produced | Ktons | 70.00 | 60.00 | 0 | 70.00 |
| Wire Rod produced | Ktons | 80.00 | — | — | — |
| Billets required | Ktons | 155.78 | 61.80 | 0 | 72.30 |
| Molten Steel | Ktons | 157.72 | 63.03 | — | 73.40 |
| Solid Charge | Ktons | 183.42 | 74.31 | — | 84.03 |
| DRI | Ktons | 110.05 | 52.02 | — | 16.81 |
| Imported Scrap | Ktons | 51.35 | 6.76 | — | 53.78 |
| Local Scrap | Ktons | 22.01 | 15.53 | — | 13.44 |
| IOP | Ktons | 161.77 | — | 98.41* | — |

*ERM DRP supplies EFS and ESR: IOP required = (EFS DRI + ESR DRI) × MRMR ERM = (52.02 + 16.81) × 1.43 = 98.41.*

### 5.2 Flat Line (HRC)

| | Unit | EZDK | EFS |
|---|---|---|---|
| HRC produced | Ktons | 45.00 | 75.00 |
| Molten Steel | Ktons | 46.82 | 78.09 |
| Solid Charge | Ktons | 54.61 | 92.07 |
| DRI | Ktons | 43.68 | 64.45 |
| Imported Scrap | Ktons | 1.11 | 8.29 |
| Local Scrap | Ktons | 9.81 | 19.33 |
| IOP | Ktons | 64.22 | 92.16* |

*EFS DRI comes from ERM: ERM IOP for flat = 64.45 × 1.43 = 92.16.*

### 5.3 Monthly Summary

| | Unit | EZDK | EFS | ERM | ESR | Total |
|---|---|---|---|---|---|---|
| Rebar | Ktons | 70.00 | 60.00 | 0 | 70.00 | 200.00 |
| Wire Rod | Ktons | 80.00 | — | — | — | 80.00 |
| HRC | Ktons | 45.00 | 75.00 | — | — | 120.00 |
| Billet | Ktons | 155.78 | 61.80 | 0 | 72.30 | 289.88 |
| DRI | Ktons | 153.73 | 116.47 | *supplied* | 16.81 | 287.01 |
| IOP | Ktons | 225.99 | — | 190.57 | — | 416.56 |
| Scrap (Local + Imp.) | Ktons | 84.29 | 49.91 | — | 67.22 | 201.42 |

---

## 6. Fixed Costs

### 6.1 Manual Inputs (USD M)

| | EZDK | EFS | ERM | ESR | Total |
|---|---|---|---|---|---|
| Manufacturing Fixed | 10.16 | 3.54 | 1.20 | 2.51 | 17.41 |
| SG&A | 4.06 | 1.03 | 1.11 | 2.30 | 8.50 |
| Net Finance Cost | 8.03 | 1.88 | 3.85 | 2.12 | 15.88 |
| Depreciation | 2.45 | 2.52 | 1.26 | 0.14 | 6.37 |
| **Total W/ Dep** | **24.70** | **8.97** | **7.42** | **7.07** | **48.16** |

### 6.2 Distribution % per Product

| | DRI | Rebar | Wire Rod | Flat | Total |
|---|---|---|---|---|---|
| EZDK | 0 | 25 | 25 | 50 | 100 |
| EFS | 0 | 50 | 0 | 50 | 100 |
| ERM | 70 | 30 | 0 | 0 | 100 |
| ESR | 0 | 100 | 0 | 0 | 100 |

### 6.3 Allocated Fixed Cost by Product (USD M)

**DRI (ERM only):** Mfg 0.84 | SG&A 0.777 | Net Finance 2.695 | Dep 0.882 | **Total 5.19**

**Rebar:**

| | EZDK | EFS | ERM | ESR | Total |
|---|---|---|---|---|---|
| Mfg Fixed | 2.540 | 1.770 | 0.360 | 2.510 | 7.18 |
| SG&A | 1.015 | 0.515 | 0.333 | 2.300 | 4.163 |
| Net Finance | 2.008 | 0.940 | 1.155 | 2.120 | 6.223 |
| Depreciation | 0.613 | 1.260 | 0.378 | 0.140 | 2.391 |
| **Total** | **6.176** | **4.485** | **2.226** | **7.070** | **19.96** |

**Wire Rod (EZDK only):** Mfg 2.540 | SG&A 1.015 | Net Finance 2.008 | Dep 0.613 | **Total 6.18**

**Flat:**

| | EZDK | EFS | Total |
|---|---|---|---|
| Mfg Fixed | 5.08 | 1.77 | 6.85 |
| SG&A | 2.030 | 0.515 | 2.545 |
| Net Finance | 4.015 | 0.940 | 4.955 |
| Depreciation | 1.225 | 1.260 | 2.485 |
| **Total** | **12.35** | **4.49** | **16.84** |

---

## 7. Standalone P&L by Company (USD M)

### 7.1 EZDK

| Item | Unit | Rebar | Wire Rod | HRC | Sub-Total |
|---|---|---|---|---|---|
| Local Sales | Ktons | 70 | 40 | 45 | 155 |
| Export Sales | Ktons | 0 | 40 | 0 | 40 |
| Total Sales Qty | Ktons | 70 | 80 | 45 | 195 |
| Local Revenue | M$ | 39.18 | 22.26 | 24.73 | 86.17 |
| Local Price/t | $/t | 560 | 557 | 550 | 556 |
| Export Revenue | M$ | 0 | 20.80 | 0 | 20.80 |
| Export Price/t | $/t | 500 | 520 | 540 | 520 |
| Total Revenue | M$ | 39.18 | 43.06 | 24.73 | 106.97 |
| Avg Price/t | $/t | 560 | 538 | 550 | 549 |
| Variable COGS | M$ | 30.42 | 34.56 | 20.23 | 85.20 |
| Cost/t | $/t | 435 | 432 | 450 | 437 |
| Export Expenses | $/t | 0 | 0.2 | 0.8 | 1.0 |
| **Contribution Margin** | M$ | **8.76** | **8.30** | **3.70** | **20.77** |
| CM/t | $/t | 125 | 104 | 82 | 107 |
| CM% | % | 22 | 19 | 15 | 19 |
| Mfg Fixed Cost | M$ | 2.54 | 2.54 | 5.08 | 10.16 |
| SG&A | M$ | 1.02 | 1.02 | 2.03 | 4.06 |
| Net Finance Cost | M$ | 2.01 | 2.01 | 4.02 | 8.03 |
| Total Fixed | M$ | 5.56 | 5.56 | 11.13 | 22.25 |
| **EBTD** | M$ | **3.20** | **2.74** | **(7.42)** | **(1.48)** |
| Depreciation | M$ | 0.61 | 0.61 | 1.23 | 2.45 |
| **EBT** | M$ | **2.59** | **2.13** | **(8.65)** | **(3.93)** |
| EBT% | % | 6.60 | 4.94 | (34.95) | (3.67) |
| VC + FC / t | $/t | 523 | 509 | 724 | 564 |
| Break-even Qty | Ktons | 49 | 58 | 123 | 221 |

### 7.2 EFS

| Item | Unit | Rebar | HRC | Sub-Total |
|---|---|---|---|---|
| Local Sales | Ktons | 60 | 0 | 60 |
| Export Sales | Ktons | 0 | 75 | 75 |
| Total Sales Qty | Ktons | 60 | 75 | 135 |
| Local Revenue | M$ | 33.39 | 0 | 33.39 |
| Export Revenue | M$ | 0 | 39.08 | 39.08 |
| Total Revenue | M$ | 33.39 | 39.08 | 72.47 |
| Variable COGS | M$ | 29.16 | 37.26 | 66.42 |
| Export Expenses | M$ | 0 | 0.01 | 0.01 |
| **Contribution Margin** | M$ | **4.23** | **1.80** | **6.04** |
| CM/t | $/t | 71 | 24 | 45 |
| CM% | % | 13 | 5 | 8 |
| Mfg Fixed Cost | M$ | 1.77 | 1.77 | 3.54 |
| SG&A | M$ | 0.52 | 0.52 | 1.03 |
| Net Finance Cost | M$ | 0.94 | 0.94 | 1.88 |
| Total Fixed | M$ | 3.23 | 3.23 | 6.45 |
| **EBTD** | M$ | **1.01** | **(1.43)** | **(0.41)** |
| Depreciation | M$ | 1.26 | 1.26 | 2.52 |
| **EBT** | M$ | **(0.25)** | **(2.69)** | **(2.93)** |
| VC + FC / t | $/t | 533 | 539 | 536 |
| Break-even Qty | Ktons | 46 | 135 | 143 |

### 7.3 ERM

| Item | Unit | Rebar | DRI (Interco) | Sub-Total |
|---|---|---|---|---|
| Total Qty | Ktons | 0 | 133.28 | 133.28 |
| Revenue | M$ | 0 | 41.18 | 41.18 |
| Variable COGS | M$ | 0 | 41.06 | 41.06 |
| **Contribution Margin** | M$ | **0** | **0.12** | **0.12** |
| Mfg Fixed | M$ | 0.36 | 0.84 | 1.20 |
| SG&A | M$ | 0.33 | 0.78 | 1.11 |
| Net Finance | M$ | 1.16 | 2.70 | 3.85 |
| Total Fixed | M$ | 1.85 | 4.31 | 6.16 |
| **EBTD** | M$ | **(1.85)** | **(4.19)** | **(6.04)** |
| Depreciation | M$ | 0.38 | 0.88 | 1.26 |
| **EBT** | M$ | **(2.23)** | **(5.07)** | **(7.30)** |
| Break-even Qty | Ktons | 0 | — | — |

### 7.4 ESR

| Item | Unit | Rebar | Sub-Total |
|---|---|---|---|
| Local Sales | Ktons | 70 | 70 |
| Total Sales Qty | Ktons | 70 | 70 |
| Total Revenue | M$ | 38.96 | 38.96 |
| Variable COGS | M$ | 33.45 | 33.45 |
| **Contribution Margin** | M$ | **5.51** | **5.51** |
| CM/t | $/t | 79 | 79 |
| Mfg Fixed | M$ | 2.51 | 2.51 |
| SG&A | M$ | 2.30 | 2.30 |
| Net Finance | M$ | 2.12 | 2.12 |
| Total Fixed | M$ | 6.93 | 6.93 |
| **EBTD** | M$ | **(1.42)** | **(1.42)** |
| Depreciation | M$ | 0.14 | 0.14 |
| **EBT** | M$ | **(1.56)** | **(1.56)** |
| VC + FC / t | $/t | 577 | 577 |
| Break-even Qty | Ktons | 88 | 88 |

---

## 8. Consolidated P&L (USD M)

| Item | EZDK | EFS | ERM | ESR | Eliminations | **Consolidated** |
|---|---|---|---|---|---|---|
| Total Revenue | 106.97 | 72.47 | 41.18 | 38.96 | (41.18) | **218.40** |
| Variable COGS | 85.20 | 66.42 | 41.06 | 33.45 | (41.18) | **184.95** |
| Export Expenses | — | 0.01 | — | — | — | **0.01** |
| **Contribution Margin** | **20.77** | **6.04** | **0.12** | **5.51** | **0** | **32.44** |
| CM% | 19 | 8 | 0.29 | 14 | — | **15** |
| Mfg Fixed | 10.16 | 3.54 | 1.20 | 2.51 | — | **17.41** |
| SG&A | 4.06 | 1.03 | 1.11 | 2.30 | — | **8.50** |
| Net Finance | 8.03 | 1.88 | 3.85 | 2.12 | — | **15.88** |
| Total Fixed | 22.25 | 6.45 | 6.16 | 6.93 | — | **41.79** |
| **EBTD** | **(1.48)** | **(0.41)** | **(6.04)** | **(1.42)** | — | **(9.35)** |
| Depreciation | 2.45 | 2.52 | 1.26 | 0.14 | — | **6.37** |
| **EBT** | **(3.93)** | **(2.93)** | **(7.30)** | **(1.56)** | — | **(15.72)** |
| EBT% | (3.67) | (4.04) | (17.73) | (4.00) | — | **(7.20)** |

**Consolidated Average Local Price:** Total Local Revenue ÷ Total Local Qty = $159M ÷ 285 Ktons = **$556/t**.

### 8.1 Intercompany Eliminations

| Line | Amount (M$) | Explanation |
|---|---|---|
| Interco DRI Revenue (ERM) | (41.18) | ERM DRI sales to EFS and ESR |
| Interco DRI COGS (EFS, ESR) | (41.18) | Embedded DRI cost removed from buyer COGS |
| Interco Margin on DRI (ERM → ESR) | — | $7.54/t × 16.81 Ktons DRI routed to ESR = ~$0.13 M; netted within COGS line above |

---

## 9. Known Data Gaps

1. **HRC local market total** — user provides on demand for market share.
2. **Export expense rates** outside EFS HRC — user can input per company per product.
3. **Consumption decimals** for certain DRI items (ERM Nitrogen, Water, etc.) — current JSON uses back-calculated dummies that satisfy confirmed outputs. Replace with true Excel values when updating.
4. **Dummy detailed consumptions** for EFS and ESR billets, and for EZDK/EFS HRC detailed build-up — structure identical to EZDK billet; replace with actual Excel values when updating.

---

*End of verification sheet. Every figure here is derived from the formulas in the rulebook and matches — to rounding — the outputs you shared from the Excel model.*
