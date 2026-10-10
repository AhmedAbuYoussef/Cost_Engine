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
| `state_manager.py` | **Step 2.** Baselines, scenarios and the live working session in SQLite. |
| `state_schema.py` | What a valid state is; dotted paths; the structured errors every tool returns. |
| `tools.py` | **Step 3.** The assistant's 14 tools, with their argument schemas (`TOOL_SPECS`). |
| `refresh_template.py` | The seven-sheet monthly refresh template (Appendix D), and the XLSX / CSV parsers. |
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

## Step 2 — states, amendments, scenarios (`state_manager.py`)

```python
from state_manager import StateStore
store = StateStore("ezz_model.db")      # first open stores model_initial_state.json as baseline_2026-04

r = store.update_input("sales.EZDK.Rebar.local_kt", 120)   # live amendment (working session only)
r["changes"]      # [{path, old, new}]
r["impact"]       # what moved: Group EBT +2.10 M$, EZDK revenue +11.48 M$, …
r["warnings"]     # e.g. DRI EZDK over capacity

store.update_input("sales.EZDK.Rebar.local_price_le_t", 9500, scope="all_companies")
store.update_inputs([...])               # several changes, stored together or not at all
store.undo()                              # revert the last change
store.commit_state("save_as_scenario", name="rebar push", tags=["chairman"])
store.diff("baseline_2026-04", "<scenario id>", threshold_pct=1)   # inputs + key figures
store.commit_state("promote_to_baseline", month_label="2026-05")  # human user only
store.import_workbook("New_Corp_Model_vX.xlsx", month_label="2026-05")  # a month straight from Excel
store.runtime_header()   # "Current state: baseline 2026-04 loaded, 1 scenarios saved (rebar push), …"
```

- **Working session**: the only state amendments write to. It is saved on every change
  together with a change log, so closing the browser loses nothing, and every change can be undone.
- **Baselines**: one per month, written only by a human user (promote, refresh, workbook
  import). The orchestrator gets `permission_denied`. An existing month is replaced only
  with `overwrite_if_exists`.
- **Scenarios**: frozen copies of the session with their `parent_baseline_id`, the inputs
  they changed, and tags. Kept 12 months, then pruned.
- **Every write is checked.** It must fit the schema (right sections, numbers in range,
  no step a company doesn't have) and must not break any integrity check. Otherwise
  nothing is stored, and an error comes back in the system-prompt format
  (`invalid_path`, `structural_non_existence`, `schema_validation_error`,
  `integrity_check_failed`, …). Capacity overruns are warnings.

## Step 3 — the 14 tools (`tools.py`)

```python
from tools import ToolBox
box = ToolBox(store)                         # mode="orchestrator" for Fantomaas
box.call("get_pnl", {"scope": "consolidated", "currency": "EGP", "period": "annual"})
box.call("get_cost_sheet", {"stage": "billet", "company": "all", "view": "detailed"})
box.call("run_sensitivity", {"input_path": "sales.ESR.Rebar.local_price_le_t",
         "variation": {"type": "range", "from": 8000, "to": 11000, "steps": 7},
         "output_metric": "ebt", "company": "ESR"})          # → EBT turns positive at 10,965 LE/t
box.call("manage_baseline_refresh", {"action": "generate_template"})   # seven-sheet XLSX
box.call("manage_baseline_refresh", {"action": "commit", "source": "xlsx", "file_path": "filled.xlsx"})
```

| # | Tool | What it returns |
|---|---|---|
| 1 | `update_input` | old → new, impact on key figures, affected reports, an ERM supplier switch if one happens |
| 2 | `read_state` | any slice of any stored state |
| 3 | `list_states` | baselines / scenarios, filterable |
| 4 | `get_cost_sheet` | DRI, billet, or finished-product cost sheet: detailed, conversion summary, inputs side by side |
| 5 | `get_pnl` | standalone (products + intercompany + sub-total) or consolidated with eliminations; monthly or annual; USD or EGP |
| 6 | `get_sales_report` | volumes, mix, prices, market share (HRC market size asked at each run, never stored) |
| 7 | `get_fixed_cost_report` | amounts, per ton, allocation |
| 8 | `get_production_report` | cascade, summary with capacity use, flow diagram (nodes, edges and Mermaid), full plan |
| 9 | `get_tradeoff_matrix` | every source × buyer, cheapest per buyer, ERM's current source |
| 10 | `run_sensitivity` | input × output table with zero crossings; failing points flagged, not dropped |
| 11 | `compare_states` | input diffs and output deltas, focus and threshold filters |
| 12 | `find_optimal_mix` | registered but **hidden until Step 8**: it ships only after its four verification cases pass (Appendix D.3) |
| 13 | `manage_baseline_refresh` | template generation; commit from XLSX, CSV or a full state (direct user only) |
| 14 | `commit_state` | promote (direct user only), save as scenario, discard |

- **Tables are data:** columns, rows with unit and kind, footnotes, and optional chart data.
  Numbers are kept at full precision; the display layer rounds them (Step 6).
- **Every number comes from the engine** (tested). Reports refuse a state that fails an
  error-level integrity check, and refuse steps a company doesn't have, explaining why.
  A "company: all" report shows only the producers, with a footnote naming the others.
- **Refresh template.** Every input appears exactly once across the seven sheets, as
  Last month / This month / % change, with sum-to-100 check cells. A blank cell means
  "unchanged", so a filled template always commits a complete month.

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
Next step per the brief: Step 4, `llm_router.py` (Claude picks and calls the tools from natural language).
