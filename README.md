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
| `tools.py` | **Step 3.** The assistant's tools (the 14 specified + undo), with their argument schemas (`TOOL_SPECS`). |
| `refresh_template.py` | The seven-sheet monthly refresh template (Appendix D), and the XLSX / CSV parsers. |
| `llm_router.py` | **Step 4.** Claude picks and calls the tools, then answers. Includes a terminal session. |
| `llm_sim.py` | A simulated Claude (same API surface) for running and testing without an API key. |
| `session_manager.py` | **Step 5.** The conversation as a durable session: saved turns, currency preference, resume. |
| `app.py` | **Step 6.** The web interface (Gradio): chat, charts, comparisons, the resume question. |
| `ui_render.py` | The display layer: number formatting, SVG charts, flow diagram, heatmap, colour-coded comparisons. |
| `orchestrator_api.py` | **Step 7.** The Fantomaas entry point: JSON in, JSON out, baseline commits refused. |
| `optimizer.py` | **Step 8.** `find_optimal_mix`: the LP, its self-checks, the four verification cases and the ship-gate. |
| `OPTIMIZER_LP.md` | The LP formulation (Appendix D.1), why it is exact for this model, and the verification results. |
| `BLEND_LIMITS.md` | The charge-mix limits per furnace: values, sources, effect, open questions. |
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

## Step 3 — the tools (`tools.py`)

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
| 1b | `undo_last_change` | reverts the last amendment (repeatable), with its impact. Added at your request beyond the specified 14 |
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

## Step 4 — Claude on top of the tools (`llm_router.py`)

```bash
python llm_router.py --simulate           # terminal session, no API key (simulated Claude)
python llm_router.py                      # real Claude: needs ANTHROPIC_API_KEY or `ant auth login`
python llm_router.py --mode orchestrator  # Fantomaas permissions
```

```python
from llm_router import Router
router = Router(ToolBox(store))                     # or Router(ToolBox(store), client=SimulatedClaude())
reply = router.ask("What is the consolidated EBT this month?")
reply.text          # the answer (markdown tables, source line)
reply.tool_calls    # [{name, input, status, error_code, ms}]
reply.usage         # tokens, including cache reads
```

- **Claude never calculates.** Every number comes from a tool result. Claude picks the tool,
  reads the result, and explains it.
- **The system prompt is the runtime part of `ezz_steel_bot_system_prompt_v2.md`** (sections 1–5;
  the revision notes and build appendices are left out), plus implementation notes generated from
  the code: caller mode, real state paths, display rounding, how to treat warnings, supplier
  switches and `needs_input`. The runtime header rides on the first turn.
- **Request:** Claude Opus 5.5 at effort `high` (financial accuracy; this model's default is
  `medium`), adaptive thinking, cached system prompt and tools, automatic `tool_choice`, and
  server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`).
  Pass `use_fallbacks=False` to turn the fallback off.
- **A manual tool-use loop.** Each call goes through the ToolBox with the session's permission
  mode. Several calls in one turn return their results together. Errors go back to Claude marked
  `is_error`, so it can correct itself. The history is append-only (Claude's responses are stored
  exactly as returned), and the number of tool rounds is capped.
- **Testing.** Loop mechanics are tested with a scripted client, and answers end to end with the
  simulated Claude. `tests/test_llm_live.py` runs real Claude once credentials are configured.

## Step 5 — sessions (`session_manager.py`)

```python
from session_manager import SessionManager
session = SessionManager(store)          # or SessionManager(store, SimulatedClaude(), use_fallbacks=False)
opening = session.connect()
opening["message"]      # "You have an in-progress session from …, based on baseline 2026-04. You had
                        #  updated …. Would you like to resume, save it as a scenario now, or discard it?"
opening["transcript"]   # the conversation so far, for the UI to redraw
reply = session.ask("Show the consolidated P&L")
```

- **Close the browser (or the process) at any point.** The working inputs (saved on every change),
  the conversation (saved after every turn) and the currency preference are all in the SQLite
  file. `connect()` picks up where you stopped, in the same Claude conversation with its full context.
- **Resume (Pattern F).** With unsaved changes, the assistant opens with the spec's question
  (resume / save as scenario / discard). Claude gets a one-off note on the next turn saying the
  user reconnected, when, and what they were asked. The history stays append-only.
- **Currency preference (Rule 5).** Asking for EGP (or USD) in any report makes it the session's
  currency. Later reports that name no currency use it, and say so. It resets to USD when a new
  session starts.
- **A session ends** when the working state is promoted to a baseline or discarded. The next
  message starts a fresh conversation. Saving a scenario does not end it. Closed conversations are
  kept (`session.history()`).
- **Channels.** The direct user and the orchestrator each have their own conversation over the
  single shared working state (§5: one session per user, shared across tabs).
- `python llm_router.py [--simulate]` runs a terminal session on top of this, so closing and
  reopening the terminal resumes the same way.

## Step 6 — the web interface (`app.py`)

```
pip install -r requirements.txt
python app.py --simulate        # try it without an API key (keyword rules stand in for Claude)
python app.py                   # with Claude: ANTHROPIC_API_KEY set, or `ant auth login`
```

Then open http://127.0.0.1:7860. Options: `--db` (default `ezz_model.db`), `--port`, `--host`,
`--share` (a temporary public link), `--model`, `--effort`.

- **Chat.** Ask in plain language. Every answer shows the tools it used: one collapsible line each,
  with the arguments, and errors flagged. Claude writes the tables. Under the answer, the page draws
  what markdown cannot, always from that turn's tool results, never re-computed:
  - **Charts**: stacked cost bars with totals on top, EBT bars, sales volumes, fixed costs,
    sensitivity lines with the zero crossing marked. Hover any bar or point for its value.
  - **Production flow**: IOP → DRI → melt shop → billets/slabs → products, with link width
    proportional to tonnage and one colour per company.
  - **Trade-off heatmap**: the cheapest source per buyer marked ✓.
  - **Comparisons** (`compare_states`): ▲/▼ with green = better and red = worse (EBT up is good,
    cost up is bad). Volumes and inputs are shown neutral.
- **Numbers** follow the Rendering Rules:
  - money in M with 2 decimals, negatives in parentheses;
  - per-ton values to 2 decimals in USD, 0 in LE;
  - kt to 1 decimal;
  - percentages to 0 decimals (1 below 10%).
- **Open or reload the page.** The conversation is redrawn. With unsaved changes, the assistant
  asks Pattern F's question, with one-click answers: *Resume*, *Save it as a scenario*, *Discard it*.
- **Side panel.**
  - The baseline, the number of scenarios, and each unsaved change (input: baseline → now).
  - The **currency** used when a question names none. It also follows what you last asked for.
  - **Undo last change** and **Compare with baseline**. Both go through the assistant, so the
    conversation records them.
  - The saved scenarios.
- Light and dark mode (follows the system; `?__theme=dark` forces it).

## Step 7 — the orchestrator API (`orchestrator_api.py`)

The entry point for Fantomaas. Whoever comes in through it is the orchestrator: no field, header or
argument can make a request count as the direct user.

```
python orchestrator_api.py --serve [--port 8765] [--token …]    # HTTP; interactive docs at /docs
python orchestrator_api.py --stdin                               # one JSON request per line → one JSON reply per line
```

```python
from orchestrator_api import OrchestratorAPI
api = OrchestratorAPI(StateStore("ezz_model.db"))               # or (store, SimulatedClaude(), use_fallbacks=False)
api.handle({"tool": "update_input", "args": {"path": "sales.EZDK.Rebar.local_kt", "value": 120}})
api.handle({"calls": [{"tool": "update_input", "args": {…}}, {"tool": "get_pnl", "args": {"scope": "consolidated"}}]})
api.handle({"instruction": "Raise EZDK rebar sales to 120 kt and report group EBT"})   # through Claude
```

| Request | What happens |
|---|---|
| `{"tool", "args"}` | One tool, called directly. No language model involved, so the result is deterministic. |
| `{"calls": [...]}` | Several tools in order, stopping at the first error. Not a transaction: earlier writes stay. |
| `{"instruction", "new_conversation"?}` | Claude in orchestrator mode (no confirmations, JSON answers) has its own conversation on the shared working state. |

Every reply has the §4 shape. The figures in `result` always come from the tool results, never from
Claude's text (Rule 1).

```json
{"status": "ok | error | needs_input", "tool_called": "update_input", "result": {…}, "error": null,
 "integrity_checks": "passed | failed: <checks> | not_run", "warnings": [{"check", "detail"}], "request_id": …}
```

- **Permission model B.** These are refused with `permission_denied` before anything runs:
  - `commit_state` with `promote_to_baseline`;
  - every action of `manage_baseline_refresh`.

  The ToolBox (orchestrator mode) and the StateStore (actor `orchestrator`) refuse them again. The
  orchestrator *can* update the working state, run every report and analysis, undo, and save or
  discard scenarios.
- **Warnings** include capacity overruns and ERM switching billet supplier. They never block.
- **HTTP endpoints:**
  - `GET /v1/health`, `GET /v1/tools` (what may be called, with schemas, and what is refused),
    `GET /v1/state`;
  - `POST /v1/tools/{name}` (body = the arguments), `POST /v1/requests` (any of the three
    request types).
- **HTTP status codes:**
  - 200 for every processed request, including tool errors (read `status`);
  - 403 for `permission_denied`;
  - 400 for a malformed request;
  - 401 for a missing or wrong token.

  With `--token` / `FANTOMAAS_API_TOKEN`, every request needs `Authorization: Bearer <token>`.
  Serving beyond localhost without a token is refused.
- **Shared working state.** The orchestrator's amendments show up in the user's session. The change
  log records them with actor `orchestrator`, and the user's next visit offers to resume them.

## Step 8 — the optimizer (`optimizer.py`, `find_optimal_mix`)

"What's the best mix?" Maximise group CM, or one company's CM, by choosing:
- local and export sales per company and product;
- ERM's billet sourcing (one internal supplier and its share, with the rest from the market);
- each furnace's blend of DRI, local scrap and imported scrap.

It works within:
- the DRI and finished-product capacity ceilings;
- the 50/20/20 local-share floors;
- the local markets (**the HRC market is asked every run**);
- any extra bounds you give.

Prices, yields, MRMR, consumptions and fixed costs are never changed. The formulation is in
**[OPTIMIZER_LP.md](OPTIMIZER_LP.md)**.

```python
import optimizer
r = optimizer.optimize(state, objective="group_cm",
                       run_constraints={"local_market_ceilings": {"HRC": 120},
                                        "additional_constraints": [
                                            {"variable": "billet.companies.EZDK.blend_pct.dri", "min": 70, "max": 85}]})
r["formulation"]; r["plan"]; r["cm"]; r["by_company"]; r["binding_constraints"]; r["self_checks"]
store.update_inputs(r["changes"])        # only if the user chooses to apply it
```

- **Exact, not approximate.** Per-ton costs in the model don't depend on volume, so CM is linear
  in volumes and in tons of each charge material. The LP's coefficients are read from the engine
  itself, so the LP is the engine. Partial ERM sourcing (`split:<CO>:<share>`) is now an engine
  input.
- **Every run checks itself (D.4).** The answer is an error, never a number, if any check fails:
  1. the engine recomputes the plan's CM, which must match to machine precision (typically
     within 0.00001 $ on 65 M$);
  2. the plan must pass every integrity check and every run constraint, measured on the engine's
     outputs;
  3. no feasible ±5% move of any single free variable may beat it.
- **Answers:**
  - the plan;
  - CM now vs at the optimum, and by company;
  - stage volumes;
  - binding constraints with **shadow prices**, e.g. "+$37.58 CM per extra ton of EZDK DRI
    capacity" (checked against a re-solve);
  - the self-check results.

  If no plan fits, it names a **minimal conflicting set of constraints** and returns no number.
- **Ship-gate (D.3).** The four verification cases of D.2 run once per process (about 2 s). The
  tool is offered to Claude and Fantomaas only if all four pass. Results are in OPTIMIZER_LP.md §10.
- **Nothing is applied.** The plan comes with `changes`; Claude asks whether to apply it, save it
  as a scenario, or neither. `changes` reach Claude at full precision: rounding would mean
  applying a different, unverified plan.
- **On the page**, the result is a colour-coded table (CM up is green ▲) under the plain-English
  formulation.
- **Charge-mix limits** are standing model data: `blend_limits` holds min/max DRI, local and
  imported scrap per furnace, and the group's local scrap supply. The optimizer applies them by
  default, and the engine warns (`blend_within_limits`) when a stored blend leaves them. Values,
  sources and the open questions for the plant are in **[BLEND_LIMITS.md](BLEND_LIMITS.md)**. On
  the dummy baseline they take the optimum from 65.62 down to 51.97 M$/month. The data has no
  export demand ceilings, so give those through `additional_constraints`.

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
Next step per the brief: Step 9, polish.
