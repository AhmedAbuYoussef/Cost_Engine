"""
Step 2 — persistent model states in SQLite: monthly baselines, named scenarios, and the
live working session (system prompt §3, §5, Appendix B decisions 3, 8, 9, 21, 22).

* **Baselines** (``baseline_YYYY-MM``) are the committed months.  Only a human user can
  write one — by promoting the working session or by a refresh — and an existing month is
  replaced only with ``overwrite_if_exists``.  The orchestrator gets ``permission_denied``.
* **Scenarios** (UUIDs) are frozen copies of the working session, anchored to the baseline
  the session was born from (``parent_baseline_id``).  Kept 12 months.
* **The working session** (``"working"``) is the only state ``update_inputs`` writes to.
  Every change is saved at once with a change log, so a closed browser loses nothing and
  any change can be undone.

Every write is validated against the state schema and the engine's integrity checks
before it is stored; a write that would break a check is refused whole (nothing is
stored).  Capacity overruns are warnings, never refusals.

    store = StateStore("ezz_model.db")          # first open: loads model_initial_state.json
    store.update_input("sales.EZDK.Rebar.local_kt", 120)
    store.commit_state("save_as_scenario", name="rebar push")
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import sqlite3
import threading
import uuid

import cost_engine as ce
import state_schema as schema
from state_schema import ModelError

SCHEMA_VERSION = 1
RETENTION_MONTHS = 12
ACTORS = ("user", "orchestrator", "system")

_DDL = """
CREATE TABLE IF NOT EXISTS states (
    id                 TEXT PRIMARY KEY,
    kind               TEXT NOT NULL CHECK (kind IN ('baseline', 'scenario', 'working')),
    name               TEXT,
    month_label        TEXT,
    parent_baseline_id TEXT,
    description        TEXT,
    tags               TEXT NOT NULL DEFAULT '[]',
    changed_inputs     TEXT NOT NULL DEFAULT '[]',
    requested_outputs  TEXT NOT NULL DEFAULT '[]',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    created_by         TEXT NOT NULL,
    body               TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_baseline_per_month ON states (month_label) WHERE kind = 'baseline';
CREATE TABLE IF NOT EXISTS changes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    batch    INTEGER NOT NULL,
    at       TEXT NOT NULL,
    actor    TEXT NOT NULL,
    path     TEXT NOT NULL,
    old      TEXT NOT NULL,
    new      TEXT NOT NULL,
    note     TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    actor  TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _months_back(t: dt.datetime, months: int) -> dt.datetime:
    y, m = divmod(t.month - 1 - months, 12)
    year, month = t.year + y, m + 1
    for day in (t.day, 30, 29, 28):
        try:
            return t.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    raise AssertionError("unreachable")


def baseline_id(month_label: str) -> str:
    return f"baseline_{month_label}"


def _require_user(actor: str, action: str) -> None:
    if actor not in ACTORS:
        raise ModelError("schema_validation_error", f"unknown actor {actor!r}", field="actor",
                         expected=list(ACTORS[:2]))
    if actor != "user":
        raise ModelError("permission_denied",
                         f"{action} writes a baseline and needs a human user; "
                         f"the {actor} may update the working session and save scenarios only")


def _check_month(month_label) -> None:
    if not month_label:
        raise ModelError("missing_required_arg", "month_label is required (YYYY-MM)", field="month_label")
    if not schema.MONTH_RE.match(str(month_label)):
        raise ModelError("schema_validation_error", f"month_label {month_label!r} is not YYYY-MM",
                         field="month_label", expected="YYYY-MM")


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _amount(v):
    """Comparable number for a leaf ({'le': x} → x)."""
    if isinstance(v, dict) and len(v) == 1:
        return next(iter(v.values()))
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def diff_inputs(a: dict, b: dict, threshold_pct: float = 0.0) -> list:
    """Inputs that differ between two states: [{path, a, b, delta, pct}], biggest % first."""
    la, lb = schema.leaves(a), schema.leaves(b)
    out = []
    for path in sorted(la.keys() | lb.keys()):
        if path.split(".")[0] in schema.READ_ONLY_ROOTS:     # meta, month_label, rules_profile
            continue
        va, vb = la.get(path), lb.get(path)
        if _same(va, vb):
            continue
        na, nb = _amount(va), _amount(vb)
        delta = None if na is None or nb is None else nb - na
        pct = None if delta is None or na == 0 else delta / abs(na) * 100
        if threshold_pct and pct is not None and abs(pct) < threshold_pct:
            continue
        out.append({"path": path, "a": va, "b": vb, "delta": delta, "pct": pct})
    out.sort(key=lambda r: -abs(r["pct"]) if r["pct"] is not None else float("-inf"))
    return out


def diff_figures(fa: dict, fb: dict, threshold_pct: float = 0.0) -> list:
    out = []
    for k in fa.keys() | fb.keys():
        a, b = fa.get(k), fb.get(k)
        if a is None or b is None:
            if a is not b:
                out.append({"figure": k, "a": a, "b": b, "delta": None, "pct": None})
            continue
        d = b - a
        if abs(d) <= 1e-9 * max(1.0, abs(a)):
            continue
        pct = None if a == 0 else d / abs(a) * 100
        if threshold_pct and pct is not None and abs(pct) < threshold_pct:
            continue
        out.append({"figure": k, "a": a, "b": b, "delta": d, "pct": pct})
    # group lines first, then the largest absolute moves
    out.sort(key=lambda r: (not r["figure"].startswith("Group"), -abs(r["delta"] or 0)))
    return out


class StateStore:
    """All model states, persisted in one SQLite file.  Thread-safe for a single process."""

    def __init__(self, db_path: str = "ezz_model.db", *, initial_state: dict | None = None,
                 clock=None):
        self._clock = clock or _utcnow
        self._lock = threading.RLock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        with self._db:
            self._db.executescript(_DDL)
            self._db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        self._template = schema.load_template()
        if self._latest_baseline() is None:
            state = initial_state if initial_state is not None else copy.deepcopy(self._template)
            self._write_baseline(state, state.get("month_label"), actor="system", overwrite=False,
                                 action="bootstrap")
        if self._row("working") is None:
            self._reset_working(self._latest_baseline())
        self.prune_scenarios()

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------------ rows

    def _now(self) -> str:
        return self._clock().astimezone(dt.timezone.utc).isoformat(timespec="seconds")

    def _row(self, state_id: str):
        return self._db.execute("SELECT * FROM states WHERE id = ?", (state_id,)).fetchone()

    def _latest_baseline(self):
        return self._db.execute("SELECT * FROM states WHERE kind = 'baseline' "
                                "ORDER BY month_label DESC LIMIT 1").fetchone()

    def _audit(self, actor, action, target, detail=None) -> None:
        self._db.execute("INSERT INTO audit (at, actor, action, target, detail) VALUES (?,?,?,?,?)",
                         (self._now(), actor, action, target,
                          None if detail is None else json.dumps(detail, default=str)))

    def _get_row(self, state_id: str):
        row = self._row(state_id)
        if row is None:
            code = ("baseline_not_found" if str(state_id).startswith("baseline_")
                    else "scenario_not_found")
            raise ModelError(code, f"no state {state_id!r}", field="state_id")
        return row

    # ------------------------------------------------------------------ checks

    def _validated(self, state: dict) -> dict:
        """Schema + integrity errors; returns the engine outputs."""
        schema.validate(state, self._template)
        out = ce.compute_all(state)
        failed = ce.failed_errors(out)
        if failed:
            raise ModelError("integrity_check_failed",
                             "; ".join(f"{c['check']}: {c['detail']}" for c in failed),
                             field=failed[0]["check"])
        return out

    # ------------------------------------------------------------------ reads

    def get_state(self, state_id: str = "working") -> dict:
        with self._lock:
            return json.loads(self._get_row(state_id)["body"])

    def read(self, path: str = "*", state_id: str = "working"):
        if not path:
            raise ModelError("missing_required_arg", "path is required ('*' for everything)", field="path")
        return schema.get(self.get_state(state_id), path)

    def compute(self, state_id: str = "working") -> dict:
        """Engine outputs for a stored state (each state computed on its own — Rule 7)."""
        return ce.compute_all(self.get_state(state_id))

    def _meta(self, row) -> dict:
        d = {"id": row["id"], "type": row["kind"], "name": row["name"],
             "month_label": row["month_label"], "created_at": row["created_at"],
             "updated_at": row["updated_at"], "created_by": row["created_by"],
             "tags": json.loads(row["tags"])}
        if row["kind"] == "scenario":
            d.update(parent_baseline_id=row["parent_baseline_id"], description=row["description"],
                     changed_inputs=json.loads(row["changed_inputs"]),
                     requested_outputs=json.loads(row["requested_outputs"]))
        if row["kind"] == "working":
            d["base_baseline_id"] = row["parent_baseline_id"]
        return d

    def list_states(self, type: str = "all", filter_by: dict | None = None) -> list:
        kinds = {"baselines": ("baseline",), "scenarios": ("scenario",),
                 "all": ("baseline", "scenario")}.get(type)
        if kinds is None:
            raise ModelError("schema_validation_error", f"unknown type {type!r}", field="type",
                             expected=["baselines", "scenarios", "all"])
        f = filter_by or {}
        unknown = set(f) - {"date_from", "date_to", "changed_inputs", "requested_outputs", "tags",
                            "month_label"}
        if unknown:
            raise ModelError("schema_validation_error", f"unknown filter(s) {sorted(unknown)}",
                             field="filter_by")
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM states WHERE kind IN ({','.join('?' * len(kinds))}) "
                "ORDER BY created_at DESC, id", kinds).fetchall()
            months = {r["id"]: r["month_label"] for r in self._db.execute(
                "SELECT id, month_label FROM states WHERE kind = 'baseline'")}
        out = []
        for r in rows:
            m = self._meta(r)
            day = m["created_at"][:10]
            if f.get("date_from") and day < f["date_from"]:
                continue
            if f.get("date_to") and day > f["date_to"]:
                continue
            if f.get("tags") and not set(f["tags"]) & set(m["tags"]):
                continue
            month = m["month_label"] or months.get(m.get("parent_baseline_id"))
            if f.get("month_label") and month != f["month_label"]:
                continue
            if f.get("changed_inputs") and not any(p.startswith(q) for p in m.get("changed_inputs", [])
                                                   for q in f["changed_inputs"]):
                continue
            if f.get("requested_outputs") and not set(f["requested_outputs"]) & set(m.get("requested_outputs", [])):
                continue
            out.append(m)
        return out

    # ------------------------------------------------------------------ working session

    def _reset_working(self, baseline_row) -> None:
        now = self._now()
        with self._db:
            self._db.execute("DELETE FROM changes")
            self._db.execute(
                "INSERT INTO states (id, kind, parent_baseline_id, created_at, updated_at, created_by, body) "
                "VALUES ('working', 'working', ?, ?, ?, 'system', ?) "
                "ON CONFLICT(id) DO UPDATE SET parent_baseline_id = excluded.parent_baseline_id, "
                "updated_at = excluded.updated_at, body = excluded.body",
                (baseline_row["id"], now, now, baseline_row["body"]))

    def update_input(self, path: str, value, scope: str = "single", *, actor: str = "user",
                     note: str | None = None) -> dict:
        """Tool 1 — change one input (or fan it out with ``scope``) in the working session."""
        return self.update_inputs([{"path": path, "value": value, "scope": scope}], actor=actor, note=note)

    def update_inputs(self, changes: list, *, actor: str = "user", note: str | None = None) -> dict:
        """Several changes applied together: all are stored, or none (e.g. a blend change
        and its balancing scrap change)."""
        if actor not in ACTORS[:2]:
            raise ModelError("schema_validation_error", f"unknown actor {actor!r}", field="actor")
        if not changes:
            raise ModelError("missing_required_arg", "no changes given", field="changes")
        with self._lock:
            row = self._get_row("working")
            before = json.loads(row["body"])
            after = copy.deepcopy(before)
            applied = []
            for ch in changes:
                if "path" not in ch or "value" not in ch:
                    raise ModelError("missing_required_arg", "each change needs a path and a value",
                                     field="path" if "path" not in ch else "value")
                path = ch["path"]
                schema.check_writable(path)
                if not schema.exists(after, path):
                    raise schema.missing_path_error(path)
                for target in schema.expand_scope(after, path, ch.get("scope", "single")):
                    old = schema.get(after, target)
                    if _same(old, ch["value"]):
                        continue
                    schema.set_value(after, target, ch["value"])
                    applied.append({"path": target, "old": old, "new": copy.deepcopy(ch["value"])})
            if not applied:
                return {"status": "ok", "state_id": "working", "changes": [], "impact": [],
                        "warnings": [], "message": "nothing changed — the values were already set"}
            out_before = ce.compute_all(before)
            schema.validate(after, self._template)
            out_after = ce.compute_all(after)
            already = {c["check"] for c in ce.failed_errors(out_before)}
            broken = [c for c in ce.failed_errors(out_after) if c["check"] not in already]
            if broken:
                raise ModelError("integrity_check_failed",
                                 "change refused, nothing stored — " +
                                 "; ".join(f"{c['check']}: {c['detail']}" for c in broken),
                                 field=broken[0]["check"])
            now = self._now()
            with self._db:
                batch = (self._db.execute("SELECT COALESCE(MAX(batch), 0) FROM changes").fetchone()[0]) + 1
                self._db.executemany(
                    "INSERT INTO changes (batch, at, actor, path, old, new, note) VALUES (?,?,?,?,?,?,?)",
                    [(batch, now, actor, a["path"], json.dumps(a["old"]), json.dumps(a["new"]), note)
                     for a in applied])
                self._db.execute("UPDATE states SET body = ?, updated_at = ? WHERE id = 'working'",
                                 (json.dumps(after), now))
            fb, fa = ce.key_figures(out_before), ce.key_figures(out_after)
            return {"status": "ok", "state_id": "working", "changes": applied,
                    "impact": diff_figures(fb, fa)[:25],
                    "warnings": [c for c in out_after["integrity"]
                                 if not c["passed"] and c["severity"] == "warning"]}

    def undo(self, *, actor: str = "user") -> dict:
        """Revert the last change batch of the working session."""
        with self._lock:
            last = self._db.execute("SELECT MAX(batch) FROM changes").fetchone()[0]
            if last is None:
                raise ModelError("nothing_to_undo", "the working session has no changes to undo")
            rows = self._db.execute("SELECT * FROM changes WHERE batch = ? ORDER BY id DESC",
                                    (last,)).fetchall()
            state = self.get_state("working")
            for r in rows:
                schema.set_value(state, r["path"], json.loads(r["old"]))
            schema.validate(state, self._template)
            with self._db:
                self._db.execute("DELETE FROM changes WHERE batch = ?", (last,))
                self._db.execute("UPDATE states SET body = ?, updated_at = ? WHERE id = 'working'",
                                 (json.dumps(state), self._now()))
                self._audit(actor, "undo", "working", [r["path"] for r in rows])
            return {"status": "ok", "reverted": [{"path": r["path"], "restored": json.loads(r["old"])}
                                                 for r in rows]}

    def session_summary(self) -> dict:
        """What the working session holds — the basis of the resume prompt (Pattern F)."""
        with self._lock:
            row = self._get_row("working")
            base_row = self._row(row["parent_baseline_id"])
            batches = self._db.execute("SELECT COUNT(DISTINCT batch), MAX(at) FROM changes").fetchone()
            log = [dict(r) for r in self._db.execute(
                "SELECT batch, at, actor, path, old, new, note FROM changes ORDER BY id")]
        net = diff_inputs(json.loads(base_row["body"]), json.loads(row["body"])) if base_row else []
        return {"base_baseline_id": row["parent_baseline_id"],
                "base_month_label": base_row["month_label"] if base_row else None,
                "status": "in_progress" if net else "untouched",
                "net_changes": [{"path": n["path"], "baseline": n["a"], "now": n["b"]} for n in net],
                "change_batches": batches[0], "last_change_at": batches[1], "change_log": log}

    def runtime_header(self) -> str:
        """The one-line state summary injected at session start (system prompt §5)."""
        s = self.session_summary()
        scen = self.list_states("scenarios")
        names = ", ".join(x["name"] for x in scen) or "none"
        work = ("untouched" if s["status"] == "untouched"
                else f"in progress with {len(s['net_changes'])} changes")
        return (f"Current state: baseline {s['base_month_label']} loaded, {len(scen)} scenarios "
                f"saved ({names}), working session {work}.")

    def open_working_from(self, state_id: str, *, discard_changes: bool = False,
                          actor: str = "user") -> dict:
        """Start the working session from a stored baseline or scenario."""
        with self._lock:
            src = self._get_row(state_id)
            if src["kind"] == "working":
                raise ModelError("invalid_path", "the working session is already open", field="state_id")
            s = self.session_summary()
            if s["status"] == "in_progress" and not discard_changes:
                raise ModelError("missing_required_arg",
                                 f"the working session has {len(s['net_changes'])} unsaved changes — "
                                 "save them as a scenario, or pass discard_changes=true",
                                 field="discard_changes")
            base = src["id"] if src["kind"] == "baseline" else src["parent_baseline_id"]
            now = self._now()
            with self._db:
                self._db.execute("DELETE FROM changes")
                self._db.execute("UPDATE states SET body = ?, parent_baseline_id = ?, updated_at = ? "
                                 "WHERE id = 'working'", (src["body"], base, now))
                self._audit(actor, "open_working_from", state_id)
            return {"status": "ok", "state_id": "working", "loaded_from": state_id,
                    "base_baseline_id": base}

    # ------------------------------------------------------------------ commits

    def commit_state(self, action: str, *, actor: str = "user", month_label: str | None = None,
                     overwrite_if_exists: bool = False, name: str | None = None,
                     description: str | None = None, tags: list | None = None,
                     requested_outputs: list | None = None) -> dict:
        """Tool 14 — promote_to_baseline | save_as_scenario | discard."""
        if action == "promote_to_baseline":
            _require_user(actor, "promote_to_baseline")
            _check_month(month_label)
            with self._lock:
                state = self.get_state("working")
                res = self._write_baseline(state, month_label, actor=actor,
                                           overwrite=overwrite_if_exists, action="promote_to_baseline")
                self._reset_working(self._row(res["baseline_id"]))
                return res
        if action == "save_as_scenario":
            if not name:
                raise ModelError("missing_required_arg", "a scenario needs a name", field="name")
            with self._lock:
                row = self._get_row("working")
                state = json.loads(row["body"])
                self._validated(state)
                base = self._row(row["parent_baseline_id"])
                changed = [d["path"] for d in diff_inputs(json.loads(base["body"]), state)] if base else []
                sid = str(uuid.uuid4())
                now = self._now()
                with self._db:
                    self._db.execute(
                        "INSERT INTO states (id, kind, name, month_label, parent_baseline_id, description, "
                        "tags, changed_inputs, requested_outputs, created_at, updated_at, created_by, body) "
                        "VALUES (?, 'scenario', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (sid, name, row["parent_baseline_id"], description, json.dumps(tags or []),
                         json.dumps(changed), json.dumps(requested_outputs or []), now, now, actor,
                         row["body"]))
                    self._audit(actor, "save_as_scenario", sid, {"name": name})
                self.prune_scenarios()
                return {"status": "ok", "scenario_id": sid, "name": name,
                        "parent_baseline_id": row["parent_baseline_id"], "changed_inputs": changed}
        if action == "discard":
            with self._lock:
                latest = self._latest_baseline()
                self._reset_working(latest)
                with self._db:
                    self._audit(actor, "discard", "working")
                return {"status": "ok", "state_id": "working", "base_baseline_id": latest["id"]}
        raise ModelError("schema_validation_error", f"unknown action {action!r}", field="action",
                         expected=["promote_to_baseline", "save_as_scenario", "discard"])

    def _write_baseline(self, state: dict, month_label: str, *, actor: str, overwrite: bool,
                        action: str) -> dict:
        _check_month(month_label)
        state = copy.deepcopy(state)
        state["month_label"] = month_label
        out = self._validated(state)
        bid = baseline_id(month_label)
        previous = self._db.execute(
            "SELECT * FROM states WHERE kind = 'baseline' AND month_label < ? "
            "ORDER BY month_label DESC LIMIT 1", (month_label,)).fetchone()
        existing = self._row(bid)
        if existing is not None and not overwrite:
            raise ModelError("baseline_exists",
                             f"a baseline for {month_label} already exists — choose another month "
                             "or confirm overwrite_if_exists", field="month_label")
        now = self._now()
        with self._db:
            self._db.execute(
                "INSERT INTO states (id, kind, name, month_label, created_at, updated_at, created_by, body) "
                "VALUES (?, 'baseline', ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at, "
                "created_by = excluded.created_by, body = excluded.body",
                (bid, f"Baseline {month_label}", month_label, now, now, actor, json.dumps(state)))
            self._audit(actor, action, bid, {"overwrote": existing is not None})
        res = {"status": "ok", "baseline_id": bid, "overwrote": existing is not None,
               "integrity": out["integrity"], "previous_baseline_id": previous["id"] if previous else None}
        if previous is not None:
            prev = json.loads(previous["body"])
            res["diff_vs_previous"] = {
                "inputs": diff_inputs(prev, state),
                "outputs": diff_figures(ce.key_figures(ce.compute_all(prev)), ce.key_figures(out))}
        return res

    def refresh_baseline(self, payload: dict, month_label: str, *, actor: str = "user",
                         overwrite_if_exists: bool = False) -> dict:
        """Tool 13 (commit) — store a complete state snapshot as a month's baseline.  Atomic:
        a payload that fails the schema or an integrity check stores nothing."""
        _require_user(actor, "refresh_baseline")
        if not isinstance(payload, dict):
            raise ModelError("missing_required_arg", "payload must be a complete state", field="payload")
        with self._lock:
            return self._write_baseline(payload, month_label, actor=actor,
                                        overwrite=overwrite_if_exists, action="refresh_baseline")

    def import_workbook(self, path: str, month_label: str, *, actor: str = "user",
                        overwrite_if_exists: bool = False, reference_workbook: str | None = None) -> dict:
        """A month's baseline straight from a version of the Excel model: the workbook is
        checked to run the reference formulas, read, corrected (model_fixes), then stored."""
        import excel_io
        import model_fixes
        _require_user(actor, "import_workbook")
        ref = reference_workbook or model_fixes.REFERENCE_WORKBOOK
        diffs = excel_io.check_same_model(path, ref)
        if diffs:
            raise ModelError("schema_validation_error",
                             f"the workbook's formulas differ from the reference model in "
                             f"{len(diffs)} cells, e.g. {diffs[0]} — review before importing",
                             field="workbook", expected="the reference model's formulas")
        corrected, log = model_fixes.to_corrected(excel_io.extract_state(path))
        res = self.refresh_baseline(corrected, month_label, actor=actor,
                                    overwrite_if_exists=overwrite_if_exists)
        res["fixes_applied"] = [{"fix": fid, "title": title, "notes": notes} for fid, title, notes in log]
        return res

    # ------------------------------------------------------------------ scenarios

    def delete_scenario(self, scenario_id: str, *, actor: str = "user") -> dict:
        with self._lock:
            row = self._get_row(scenario_id)
            if row["kind"] != "scenario":
                raise ModelError("scenario_not_found", f"{scenario_id!r} is not a scenario",
                                 field="state_id")
            with self._db:
                self._db.execute("DELETE FROM states WHERE id = ?", (scenario_id,))
                self._audit(actor, "delete_scenario", scenario_id, {"name": row["name"]})
            return {"status": "ok", "deleted": scenario_id}

    def prune_scenarios(self) -> list:
        """Retention (decision 9): scenarios older than 12 months are removed."""
        cutoff = _months_back(self._clock(), RETENTION_MONTHS).astimezone(dt.timezone.utc)
        cutoff_s = cutoff.isoformat(timespec="seconds")
        with self._lock:
            old = [r["id"] for r in self._db.execute(
                "SELECT id FROM states WHERE kind = 'scenario' AND created_at < ?", (cutoff_s,))]
            if old:
                with self._db:
                    self._db.executemany("DELETE FROM states WHERE id = ?", [(i,) for i in old])
                    self._audit("system", "retention_prune", None, old)
            return old

    # ------------------------------------------------------------------ comparison

    def diff(self, state_a: str, state_b: str = "working", *, threshold_pct: float = 0.0,
             include_outputs: bool = True) -> dict:
        """Compare two stored states: inputs that differ, and the key figures each one
        produces (computed separately)."""
        a, b = self.get_state(state_a), self.get_state(state_b)
        res = {"a": state_a, "b": state_b, "inputs": diff_inputs(a, b, threshold_pct)}
        if include_outputs:
            fa, fb = ce.key_figures(ce.compute_all(a)), ce.key_figures(ce.compute_all(b))
            res["outputs"] = diff_figures(fa, fb, threshold_pct)
            res["group_ebt"] = {"a": fa["Group EBT M$"], "b": fb["Group EBT M$"],
                                "delta": fb["Group EBT M$"] - fa["Group EBT M$"]}
        res["summary"] = {"inputs_changed": len(res["inputs"]),
                          "outputs_changed": len(res.get("outputs", []))}
        return res

    def audit_log(self, limit: int = 50) -> list:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]
