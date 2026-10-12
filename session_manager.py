"""
Step 5 — the conversation as a durable session (system prompt §4 Pattern F, §5, Rule 5).

    sm = SessionManager(store)                 # real Claude; or client=SimulatedClaude()
    opening = sm.connect()                     # resume prompt if there is unsaved work
    reply = sm.ask("Show the consolidated P&L in EGP")
    # … the browser closes; later, possibly in a new process …
    sm = SessionManager(store); sm.connect()   # same conversation, same working state, still EGP

What it keeps, in the same SQLite file as the model states:

* **The conversation** — every message exactly as exchanged, saved after each turn, so a
  reconnect continues the same Claude conversation (full context, append-only).
* **Preferences** — the currency the user last asked for (USD until they ask otherwise).
  Reports that name no currency get it; Rule 5: "that preference holds for the rest of
  the session".
* **The working state** is already saved on every change by the StateStore (Step 2).

A session ends when the working state is promoted to a baseline or discarded (Pattern F,
"end of session"); the next message starts a fresh conversation, with USD again.  Saving a
scenario does not end the session.

There is one conversation per channel ("user" or "orchestrator"); both work on the single
shared working state (§5: one session per user, shared across browser tabs).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import llm_router
from tools import TOOL_SPECS, ToolBox

_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id             TEXT PRIMARY KEY,
    channel        TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    started_at     TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    closed_at      TEXT,
    close_reason   TEXT,
    messages       TEXT NOT NULL DEFAULT '[]',
    preferences    TEXT NOT NULL DEFAULT '{}',
    tool_log       TEXT NOT NULL DEFAULT '[]',
    pending_note   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_conversation ON conversations (channel) WHERE status = 'active';
"""

DEFAULT_PREFERENCES = {"currency": "USD"}
SESSION_ENDING = {"promote_to_baseline", "discard"}


def to_jsonable(obj):
    """Messages → plain JSON.  SDK blocks keep every field they came with (thinking blocks
    must go back unchanged); only empty (None) fields are dropped."""
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    if isinstance(obj, SimpleNamespace):
        return to_jsonable(vars(obj))
    return obj


class _PreferenceToolBox:
    """The session's ToolBox, applying and learning the currency preference."""

    def __init__(self, box: ToolBox, session: "SessionManager"):
        self._box, self._session = box, session

    def __getattr__(self, name):
        return getattr(self._box, name)

    def call(self, name, args=None):
        args = dict(args or {})
        applied = None
        if "currency" in TOOL_SPECS.get(name, {}).get("input_schema", {}).get("properties", {}):
            asked = args.get("currency")
            if asked in ("USD", "EGP"):
                self._session._prefs["currency"] = asked          # the user named one: remember it
            else:
                args["currency"] = applied = self._session._prefs.get("currency", "USD")
        result = self._box.call(name, args)
        if applied and applied != "USD" and result.get("status") == "ok":
            result["currency_from_preference"] = applied
        return result


class SessionManager:
    def __init__(self, store, client=None, *, channel: str = "user", clock=None, **router_kwargs):
        if channel not in ("user", "orchestrator"):
            raise ValueError("channel must be 'user' or 'orchestrator'")
        self.store, self.client, self.channel = store, client, channel
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._router_kwargs = router_kwargs
        self._db, self._lock = store.connection, store.lock
        with self._lock, self._db:
            self._db.executescript(_DDL)
        self._row = None
        self.router = None
        self._prefs: dict = dict(DEFAULT_PREFERENCES)

    # ------------------------------------------------------------------ persistence

    def _now(self) -> str:
        return self._clock().astimezone(dt.timezone.utc).isoformat(timespec="seconds")

    def _active(self):
        return self._db.execute("SELECT * FROM conversations WHERE channel = ? AND status = 'active'",
                                (self.channel,)).fetchone()

    def _new_conversation(self) -> None:
        cid, now = str(uuid.uuid4()), self._now()
        with self._lock, self._db:
            self._db.execute("INSERT INTO conversations (id, channel, status, started_at, last_active_at, "
                             "preferences) VALUES (?, ?, 'active', ?, ?, ?)",
                             (cid, self.channel, now, now, json.dumps(DEFAULT_PREFERENCES)))
        self._load()

    def _load(self) -> None:
        self._row = self._active()
        self._prefs = {**DEFAULT_PREFERENCES, **json.loads(self._row["preferences"])}
        box = _PreferenceToolBox(ToolBox(self.store, mode=self.channel), self)
        self.router = llm_router.Router(box, self.client, messages=json.loads(self._row["messages"]),
                                        **self._router_kwargs)
        if self.client is None:
            self.client = self.router.client

    def _save(self, pending_note=None, tool_calls=()) -> None:
        log = json.loads(self._row["tool_log"]) + [to_jsonable(c) for c in tool_calls]
        with self._lock, self._db:
            self._db.execute("UPDATE conversations SET messages = ?, preferences = ?, tool_log = ?, "
                             "last_active_at = ?, pending_note = ? WHERE id = ?",
                             (json.dumps(to_jsonable(self.router.messages)), json.dumps(self._prefs),
                              json.dumps(log), self._now(), pending_note, self._row["id"]))
        self._row = self._db.execute("SELECT * FROM conversations WHERE id = ?", (self._row["id"],)).fetchone()

    def _close(self, reason: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE conversations SET status = 'closed', closed_at = ?, close_reason = ? "
                             "WHERE id = ?", (self._now(), reason, self._row["id"]))
        self._row, self.router = None, None

    # ------------------------------------------------------------------ public

    def connect(self) -> dict:
        """Open the channel's conversation (new or restored).  With unsaved work in the working
        session, returns Pattern F's resume question for the UI to show first."""
        resumed = self._active() is not None
        if resumed:
            self._load()
        else:
            self._new_conversation()
        header = self.store.runtime_header()
        s = self.store.session_summary()
        opener = None
        if s["status"] == "in_progress":
            when = _fmt_time(s["last_change_at"] or self._row["last_active_at"])
            opener = (f"You have an in-progress session from {when}, based on baseline {s['base_month_label']}. "
                      f"You had updated {_describe_changes(s['net_changes'])}. Would you like to resume, "
                      "save it as a scenario now, or discard it?")
        note = None
        if self.router.messages:                    # continuing an earlier conversation
            note = (f"[Session note] The user reconnected at {_fmt_time(self._now())} after a break "
                    f"(last activity {_fmt_time(self._row['last_active_at'])}). {header} "
                    f"Currency preference: {self._prefs['currency']}.")
        if opener:
            note = (note or "[Session note]") + f' The user was greeted with: "{opener}" Act on their answer.'
        if note:
            self._save(pending_note=note)
        return {"status": "resume_offered" if opener else ("resumed" if resumed else "new"),
                "message": opener, "runtime_header": header, "conversation_id": self._row["id"],
                "preferences": dict(self._prefs), "transcript": self.transcript()}

    def ask(self, text: str) -> llm_router.Reply:
        if self.router is None:                     # first use, or the last session ended
            if self._active() is None:
                self._new_conversation()
            else:
                self._load()
        note = self._row["pending_note"]
        reply = self.router.ask(text, notes=[note] if note else ())
        self._save(tool_calls=reply.tool_calls)
        ended = [c for c in reply.tool_calls if c["name"] == "commit_state" and c["status"] == "ok"
                 and (c.get("input") or {}).get("action") in SESSION_ENDING]
        reply.session_ended = bool(ended)
        if ended:
            self._close(ended[-1]["input"]["action"])
        return reply

    def end(self, reason: str = "closed_by_caller") -> bool:
        """Close the active conversation (e.g. the orchestrator starting an unrelated task).  The
        working state is untouched.  Returns False when there was nothing to close."""
        if self.router is None and self._active() is None:
            return False
        if self.router is None:
            self._load()
        self._close(reason)
        self._prefs = dict(DEFAULT_PREFERENCES)
        return True

    @property
    def preferences(self) -> dict:
        return dict(self._prefs)

    def set_preference(self, key: str, value) -> None:
        """For UI toggles.  Only the currency preference exists today."""
        if key != "currency" or value not in ("USD", "EGP"):
            raise ValueError("supported: currency = 'USD' | 'EGP'")
        if self.router is None:
            self.connect()
        self._prefs[key] = value
        self._save(pending_note=self._row["pending_note"])

    def transcript(self) -> list:
        """The conversation as the user saw it: their messages and the assistant's text, with the
        tools each answer used (tool payloads and session notes left out)."""
        out = []
        for m in (self.router.messages if self.router else []):
            blocks = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            get = lambda b, k: b.get(k) if isinstance(b, dict) else getattr(b, k, None)
            texts = [get(b, "text") for b in blocks if get(b, "type") == "text"
                     and not str(get(b, "text")).startswith("[")]
            tools = [get(b, "name") for b in blocks if get(b, "type") == "tool_use"]
            if m["role"] == "user" and texts:
                out.append({"role": "user", "text": "\n".join(texts)})
            elif m["role"] == "assistant":
                if out and out[-1]["role"] == "assistant":      # one assistant entry per answer
                    out[-1]["tools"] += tools
                    if texts:
                        out[-1]["text"] = "\n".join(texts)
                else:
                    out.append({"role": "assistant", "text": "\n".join(texts), "tools": tools})
        return out

    def history(self, limit: int = 20) -> list:
        """Past conversations on this channel (newest first) — for an audit or a 'recent' list."""
        return [dict(id=r["id"], status=r["status"], started_at=r["started_at"], closed_at=r["closed_at"],
                     close_reason=r["close_reason"], turns=sum(1 for m in json.loads(r["messages"])
                                                               if m["role"] == "user"))
                for r in self._db.execute("SELECT * FROM conversations WHERE channel = ? "
                                          "ORDER BY started_at DESC, rowid DESC LIMIT ?", (self.channel, limit))]


def _fmt_time(iso: str) -> str:
    return dt.datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")


def _describe_changes(net: list) -> str:
    def amount(v):
        return next(iter(v.values())) if isinstance(v, dict) and len(v) == 1 else v
    parts = [f"{c['path']} ({amount(c['baseline'])} → {amount(c['now'])})" for c in net[:4]]
    more = f" and {len(net) - 4} more" if len(net) > 4 else ""
    return ", ".join(parts) + more
