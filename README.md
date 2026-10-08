# Ezz Steel Cost Engine (Step 1)

A pure-Python replica of the **New Corp Model** workbook. It covers DRI, Billet
(EAF→CCP/TSC), finished products (Rebar, Wire Rod, HRC), the trade-off matrix,
market share, the production cascade, fixed-cost allocation and the four P&L
sheets (USD/LE × monthly/annual).

## Status

**Done-criterion met.** The engine reproduces the workbook cell for cell:

| Check | Result |
|---|---|
| Mapped formula cells vs Excel's cached values (reference workbook) | 2,075 cells, 0 mismatches (relative tolerance 1e-9) |
| Every input perturbed ±15% (and dormant zero inputs switched on), workbook recalculated by LibreOffice, engine compared | 8 random scenarios × 2,075 cells, 0 mismatches |
| Visible summary sheets | every numeric formula cell covered, except page counters and two scratch cells |

`model_verification.md` (hand-built, partly from dummy figures) is retired to `archive/`.
The workbook itself is now the oracle, so any version of the file can be checked.

## Files

| File | Role |
|---|---|
| `cost_engine.py` | The engine. `compute_all(state)` → every view. Pure, deterministic, no I/O. |
| `excel_io.py` | Reads a workbook's inputs into the engine state (`extract_state`), reads Excel's results (`extract_expected`), and checks a file runs the same formulas (`check_same_model`). |
| `excel_map.py` | The home cell of every engine output, used by the tests. |
| `model_initial_state.json` | State extracted from the reference workbook. |
| `MODEL_QUIRKS.md` | **Read this.** Places where the workbook looks wrong or departs from the rulebook. Replicated, awaiting your decision. |
| `tests/` | Fidelity tests, the LibreOffice differential test, behaviour tests. |
| `tests/fixtures/New_Corp_Model_v8_30-12-19.xlsx` | Reference workbook. |
| `archive/` | Superseded verification sheet and the old dummy-figure state. |

## Usage

```python
import excel_io, cost_engine

state = excel_io.extract_state("New_Corp_Model_v8_30-12-19.xlsx")   # or json.load(...)
out = cost_engine.compute_all(state)

out["billet"]["EZDK"]["total_variable_cost"]           # 'Billet'!E30
out["billet"]["tradeoff"]["minimum"]["ERM"]             # 'Billet'!G44
out["pnl"]["usd_monthly"]["columns"]["R"]["ebt"]        # 'P&L $ Monthly'!R43
out["integrity"]                                        # integrity-check results
```

To use another version of the workbook (same model, different figures):

```python
excel_io.check_same_model("other_version.xlsx", "tests/fixtures/New_Corp_Model_v8_30-12-19.xlsx")
# [] → same formulas; the engine applies as-is.  Otherwise: the cells whose formulas differ.
```

`python excel_io.py <workbook.xlsx> <out_dir>` writes the state and expected-values JSON.

## Tests

```
pip install -r requirements.txt
python -m pytest -q tests          # ~40 s; the LibreOffice test is skipped if soffice is absent
```

## How this relates to the Step 1 brief and rulebook

The brief's architecture holds: pure functions, full precision, currency-tagged
views, integrity checks, a sourcing decision in state, and `compute_all`. Where
the rulebook describes behaviour the workbook doesn't have, **the engine follows
the workbook**, and the gap is listed in `MODEL_QUIRKS.md` §B. For example, the
workbook has no consolidated eliminations column and no ERM DRI P&L, and ERM's
billet source is EZDK's VC rather than market. Integrity checks 1, 2, 5 and 7
run at runtime. Checks 3, 4 and 6 hold by construction: the matrix is computed on
demand, every quantity is derived from sales, and the EFS/ESR DRI price is read
from ERM's DRI calculation. Integrity results are reported in
`out["integrity"]`; `compute_all(state, strict=True)` raises on failure. The
reference data currently fails `blending_100` (MODEL_QUIRKS A7).
