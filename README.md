# Ezz Steel Cost Engine

A pure-Python version of the **New Corp Model**. It covers DRI, Billet (EAF→CCP/TSC),
Rebar, Wire Rod, HRC, the trade-off matrix, market share, the production cascade,
fixed-cost allocation, the four P&Ls (USD/LE × monthly/annual) and a consolidated P&L
with intercompany eliminations.

## Two rule sets, one engine

| | **Corrected** (default) | **Legacy** |
|---|---|---|
| What | The model with the workbook's mistakes fixed and no typed-in results | An exact replica of the workbook, quirks included |
| Used for | Live amendments, scenarios, optimization | Reproducing old figures; proving the engine is the same model |
| Proof | 45 corrected-model tests; all 7 integrity checks pass | 2,075 cells = Excel; 8 random LibreOffice recalculations = engine |

What changed and by how much, fix by fix: **[MODEL_FIXES.md](MODEL_FIXES.md)**. Group EBT moves from
−10.87 (workbook) to −14.02 M$/month (corrected), almost all of it from one data fix: ESR's
electricity price.

## Files

| File | Role |
|---|---|
| `cost_engine.py` | The engine. `compute_all(state)` → every view. Pure, deterministic, no I/O. |
| `model_initial_state.json` | **Corrected baseline**: the inputs the model runs on. |
| `model_fixes.py` | Workbook → corrected state, and the fix-by-fix bridge. |
| `excel_io.py` | Reads any version of the workbook into a (legacy) state, reads Excel's results, and checks a file runs the same formulas. |
| `excel_map.py` | The Excel cell for every legacy output (used by the tests). |
| `MODEL_FIXES.md`, `reports/fix_bridge.md` | What was fixed, why, and the effect on the numbers. |
| `tests/` | Corrected-model tests, Excel fidelity, LibreOffice differential test. |

## Usage

```python
import json, cost_engine

state = json.load(open("model_initial_state.json"))       # corrected baseline
state["sales"]["EZDK"]["Rebar"]["local_kt"] = 120          # an amendment
out = cost_engine.compute_all(state)

out["consolidated"]["usd_monthly"]["consolidated"]["ebt"]  # group EBT after eliminations
out["pnl"]["usd_monthly"]["columns"]["ERM/DRI"]           # any P&L column: "<CO>/<product>",
                                                           #   "<CO>/Sub-Total", "Total"
out["sourcing"]                                            # where ERM's billets come from
out["integrity"]                                           # all checks; strict=True raises
```

ERM's billet source: `state["sourcing"]["ERM_rebar_billet"]` = `"min"` (cheapest in the
trade-off matrix, the default), `"market"`, `"offer:EZDK"` / `"offer:EFS"` / `"offer:ESR"`,
or `"vc:<CO>"` (at the supplier's cost). An internal source raises the supplier's production.

Any single fix can be switched off: `compute_all(state, rules={**cost_engine.CORRECTED_RULES, "break_even_on_cm": False})`.

From a workbook (same model, any figures):

```python
import excel_io, model_fixes
legacy = excel_io.extract_state("some_version.xlsx")       # exact workbook behaviour
corrected, log = model_fixes.to_corrected(legacy)          # apply the fixes
excel_io.check_same_model("some_version.xlsx", "tests/fixtures/New_Corp_Model_v8_30-12-19.xlsx")
```

`python model_fixes.py [workbook.xlsx]` regenerates `model_initial_state.json` and the bridge.

## Tests

```
pip install -r requirements.txt
python -m pytest -q tests          # ~1 min; LibreOffice test is skipped if soffice is absent
```

## Relation to the Step 1 brief and rulebook

The brief's architecture holds: pure functions, full precision, currency-tagged views,
sourcing decision in state, integrity checks, `compute_all`. The corrected model now also
does what the rulebook describes and the workbook lacked: the ERM DRI P&L, the consolidated
P&L with explicit eliminations (§8.4–8.6), the supplier capacity cascade for ERM billets
(§4.7), a fully dynamic trade-off matrix (§4.6), and break-even 0 at zero sales (§12.7).
Next step per the brief: `state_manager.py` (baselines, scenarios, live amendments).
