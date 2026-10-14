"""
Step 7 — the Fantomaas orchestrator entry point (system prompt §1 "Two callers", Rule 2,
§4 "Orchestrator Mode Behavior", Appendix B decision 21: permission model B).

Structured JSON in, structured JSON out.  The caller is the orchestrator because it came in
through this module: there is no argument, header or field that turns a request into a
direct-user request.

Three ways in, all answering with the same envelope:

    api = OrchestratorAPI(StateStore("ezz_model.db"))
    api.handle({"tool": "get_pnl", "args": {"scope": "consolidated"}})        # one tool, no LLM
    api.handle({"calls": [{"tool": "update_input", "args": {...}},           # several, in order,
                          {"tool": "compare_states", "args": {...}}]})        #   stop at the first error
    api.handle({"instruction": "Raise EZDK rebar sales to 120 kt and give me group EBT"})  # via Claude

    python orchestrator_api.py --serve [--port 8765] [--token …]   # HTTP (FastAPI), docs at /docs
    python orchestrator_api.py --stdin                             # one JSON request per line

The envelope (§4):

    {"status": "ok" | "error" | "needs_input",
     "tool_called": "<tool name>" | null,
     "result": {…} | null,                       # the tool's own result (numbers at full precision)
     "error": {"error_code", "error_message", "field"?, "expected"?} | null,
     "integrity_checks": "passed" | "failed: <which>" | "not_run",
     "warnings": [{"check", "detail"}, …],       # capacity overruns, ERM supplier switches
     "request_id": …}                            # echoed when given

Permission model B — refused with ``permission_denied``, before anything runs:
``commit_state`` with ``promote_to_baseline`` and every action of ``manage_baseline_refresh``.
The same refusals are enforced again by the ToolBox (orchestrator mode) and by the StateStore
(actor "orchestrator"), so no single layer is the only guard.

The orchestrator shares the one working state with the direct user (§5): its amendments show
up in the user's session, logged with actor "orchestrator".
"""

# (no `from __future__ import annotations`: FastAPI must resolve the `Request` annotation at runtime)
import argparse
import hmac
import ipaddress
import json
import math
import os
import sys
import threading

from cost_engine import CHECK_SEVERITY
from session_manager import SessionManager
from state_schema import ModelError
from tools import TOOL_SPECS, ToolBox

STATUSES = ("ok", "error", "needs_input")

REFUSED = {
    "commit_state": {"promote_to_baseline"},     # this action only
    "manage_baseline_refresh": None,             # every action
}

_REQUEST_KEYS = {
    "tool": {"tool", "args", "request_id"},
    "calls": {"calls", "request_id"},
    "instruction": {"instruction", "new_conversation", "request_id"},
}


def refusal(tool: str, args: dict | None) -> dict | None:
    """The permission_denied error for an operation model B keeps from the orchestrator, else None."""
    if tool not in REFUSED:
        return None
    actions = REFUSED[tool]
    action = (args or {}).get("action")
    if actions is not None and action not in actions:
        return None
    what = f"{tool}({action})" if action else tool
    why = ("promotes the working state to a baseline" if tool == "commit_state"
           else "is part of the monthly baseline refresh")
    return ModelError("permission_denied",
                      f"{what} {why}, which only a direct user may do (Rule 2, permission model B). The "
                      "orchestrator may update the working state, run reports and analyses, and save or "
                      "discard scenarios.").to_dict()


def _finite(obj):
    """JSON-safe: NaN and ±inf become null (strict JSON has no such numbers)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


def _warnings(result: dict) -> list:
    out = [{"check": w.get("check", "warning"), "detail": w.get("detail", str(w))}
           for w in result.get("warnings", []) if isinstance(w, dict)]
    sc = result.get("sourcing_change")
    if sc:
        out.append({"check": "sourcing_change", "detail": sc.get("message", json.dumps(sc))})
    return out


def _integrity(result: dict) -> str:
    if result.get("status") == "ok" or result.get("status") == "needs_input":
        return "passed"                 # every tool refuses output from a state failing an error-level check
    if result.get("error_code") == "integrity_check_failed":
        msg = result.get("error_message", "")
        names = [c for c in CHECK_SEVERITY if c in msg] or [result.get("field") or "unknown"]
        return "failed: " + ", ".join(names)
    return "not_run"                    # refused before the engine ran (bad arguments, permissions, …)


def envelope(tool: str | None, result: dict, request_id=None) -> dict:
    """A tool result in the orchestrator response shape."""
    status = result.get("status") if result.get("status") in STATUSES else "ok"
    body = {k: v for k, v in result.items() if k != "status"}
    env = {"status": status, "tool_called": tool,
           "result": None if status == "error" else body,
           "error": body if status == "error" else None,
           "integrity_checks": _integrity(result),
           "warnings": _warnings(result) if status != "error" else []}
    if request_id is not None:
        env["request_id"] = request_id
    return _finite(env)


def _request_error(message: str, field: str | None = None, expected=None, request_id=None) -> dict:
    return envelope(None, ModelError("schema_validation_error", message, field=field,
                                     expected=expected).to_dict(), request_id)


class OrchestratorAPI:
    """Fantomaas' side of the assistant.  Thread-safe: requests are served one at a time (one
    SQLite file, one working state — §5)."""

    def __init__(self, store, client=None, *, template_dir: str = "refresh_templates", **router_kwargs):
        self.store = store
        self.box = ToolBox(store, mode="orchestrator", template_dir=template_dir)
        self._client, self._router_kwargs = client, router_kwargs
        self._session: SessionManager | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ discovery

    def describe(self) -> dict:
        """What the orchestrator may call, with argument schemas, and what it may not."""
        tools = [{"name": s["name"], "description": s["description"], "input_schema": s["input_schema"]}
                 for s in self.box.visible_tools()]
        return {"status": "ok", "caller": "orchestrator", "tools": tools,
                "refused": [{"tool": "commit_state", "action": "promote_to_baseline"},
                            {"tool": "manage_baseline_refresh", "action": "*"}],
                "unavailable": sorted({s["name"] for s in TOOL_SPECS.values() if s["available"]}
                                      - {t["name"] for t in tools} - {r for r in REFUSED})}

    def state(self) -> dict:
        with self._lock:
            s = self.store.session_summary()
            return _finite({"status": "ok", "runtime_header": self.store.runtime_header(),
                            "working_session": {k: s[k] for k in ("status", "base_baseline_id", "base_month_label",
                                                                   "net_changes", "change_batches",
                                                                   "last_change_at")},
                            "states": self.store.list_states("all")})

    # ------------------------------------------------------------------ calls

    def call_tool(self, tool, args=None, request_id=None) -> dict:
        if not isinstance(tool, str) or not tool:
            return _request_error("'tool' must be a tool name", "tool", sorted(TOOL_SPECS), request_id)
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return _request_error("'args' must be a JSON object", "args", request_id=request_id)
        denied = refusal(tool, args)
        if denied:
            return envelope(tool, denied, request_id)
        with self._lock:
            return envelope(tool, self.box.call(tool, args), request_id)

    def call_many(self, calls, request_id=None) -> dict:
        """Several tools in order; stops at the first error (later calls would act on a state the
        caller did not expect).  Not a transaction: earlier successful writes stay."""
        if not isinstance(calls, list) or not calls:
            return _request_error("'calls' must be a non-empty list of {tool, args}", "calls", request_id=request_id)
        out, status = [], "ok"
        with self._lock:
            for i, c in enumerate(calls):
                if not isinstance(c, dict) or set(c) - {"tool", "args"}:
                    out.append(_request_error("each call is {\"tool\": name, \"args\": {…}}", f"calls[{i}]"))
                else:
                    out.append(self.call_tool(c.get("tool"), c.get("args")))
                if out[-1]["status"] != "ok":
                    status = out[-1]["status"]
                    break
        env = {"status": status, "results": out, "completed": sum(1 for r in out if r["status"] == "ok"),
               "requested": len(calls)}
        if request_id is not None:
            env["request_id"] = request_id
        return env

    def instruct(self, instruction, new_conversation: bool = False, request_id=None) -> dict:
        """A natural-language instruction, carried out by Claude in orchestrator mode.  The
        envelope's figures come from the tool results, never from Claude's text (Rule 1)."""
        if not isinstance(instruction, str) or not instruction.strip():
            return _request_error("'instruction' must be non-empty text", "instruction", request_id=request_id)
        with self._lock:
            if self._session is None:
                self._session = SessionManager(self.store, self._client, channel="orchestrator",
                                               **self._router_kwargs)
                self._session.connect()
            if new_conversation:
                self._session.end("new_conversation")
            try:
                reply = self._session.ask(instruction.strip())
            except Exception as exc:                 # the model is unreachable: say so, change nothing more
                return _finite({"status": "error", "tool_called": None, "result": None,
                                "error": {"error_code": "tool_unavailable",
                                          "error_message": f"the assistant could not be reached: {exc}"},
                                "integrity_checks": "not_run", "warnings": [], "tool_calls": [],
                                **({"request_id": request_id} if request_id is not None else {})})
        answer = _parse_json(reply.text)
        calls = [{"tool": c["name"], "args": c["input"], "status": c["status"], "error_code": c["error_code"]}
                 for c in reply.tool_calls]
        if reply.results:
            env = envelope(reply.tool_calls[-1]["name"], reply.results[-1], request_id)
            env["warnings"] = [w for r in reply.results if r.get("status") != "error" for w in _warnings(r)]
            failed = [_integrity(r) for r in reply.results if _integrity(r).startswith("failed")]
            if failed:
                env["integrity_checks"] = failed[-1]
        else:                                       # Claude asked for clarification or declined
            status = answer.get("status") if isinstance(answer, dict) and answer.get("status") in STATUSES \
                else "needs_input"
            env = {"status": status, "tool_called": None, "result": None,
                   "error": answer.get("error") if isinstance(answer, dict) and status == "error" else None,
                   "integrity_checks": "not_run", "warnings": []}
            if request_id is not None:
                env["request_id"] = request_id
        env.update({"tool_calls": calls, "message": reply.text,
                    "conversation_ended": bool(getattr(reply, "session_ended", False))})
        return _finite(env)

    # ------------------------------------------------------------------ one entry point

    def handle(self, request) -> dict:
        """Any request → the envelope.  Exactly one of 'tool', 'calls' or 'instruction'."""
        if isinstance(request, (str, bytes)):
            try:
                request = json.loads(request)
            except ValueError as exc:
                return _request_error(f"the request is not valid JSON: {exc}")
        if not isinstance(request, dict):
            return _request_error("the request must be a JSON object")
        rid = request.get("request_id")
        kinds = [k for k in _REQUEST_KEYS if k in request]
        if len(kinds) != 1:
            return _request_error("give exactly one of 'tool', 'calls' or 'instruction'", "request",
                                  sorted(_REQUEST_KEYS), rid)
        extra = set(request) - _REQUEST_KEYS[kinds[0]]
        if extra:
            return _request_error(f"unknown field(s) {sorted(extra)}; the caller is always the orchestrator",
                                  sorted(extra)[0], sorted(_REQUEST_KEYS[kinds[0]]), rid)
        if kinds[0] == "tool":
            return self.call_tool(request["tool"], request.get("args"), rid)
        if kinds[0] == "calls":
            return self.call_many(request["calls"], rid)
        return self.instruct(request["instruction"], bool(request.get("new_conversation", False)), rid)


def _parse_json(text: str):
    """Claude's answer as JSON when it wrote JSON (optionally in a ```json fence), else None."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

HTTP_STATUS = {"permission_denied": 403}


def create_app(api: OrchestratorAPI, token: str | None = None):
    """FastAPI app.  With a token, every request needs ``Authorization: Bearer <token>``.

    HTTP 200 carries every processed request, including tool errors (read ``status``); 403 a
    permission_denied envelope; 400 a malformed request; 401 a missing or wrong token."""
    from fastapi import Body, FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="Ezz Steel Pricing Model — orchestrator API", version="1.0",
                  description="Fantomaas entry point. Structured JSON in, structured JSON out. "
                              "Baseline commits are refused (permission model B).")

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if token:
            given = request.headers.get("authorization", "")
            if not hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
                return JSONResponse({"status": "error", "error": {
                    "error_code": "permission_denied", "error_message": "missing or invalid bearer token"}},
                    status_code=401)
        return await call_next(request)

    def respond(env: dict) -> JSONResponse:
        code = 200
        err = env.get("error") or {}
        if env.get("status") == "error" and err.get("error_code") in HTTP_STATUS:
            code = HTTP_STATUS[err["error_code"]]
        elif env.get("status") == "error" and env.get("tool_called") is None and \
                err.get("error_code") == "schema_validation_error" and "tool_calls" not in env:
            code = 400
        return JSONResponse(env, status_code=code)

    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/tools")
    def tools():
        return api.describe()

    @app.get("/v1/state")
    def state():
        return api.state()

    @app.post("/v1/tools/{name}")
    def tool(name: str, args: dict = Body(default_factory=dict)):
        return respond(api.call_tool(name, args))

    @app.post("/v1/requests")
    async def request(req: Request):
        try:
            body = await req.json()
        except ValueError:
            return respond(_request_error("the request body is not valid JSON"))
        return respond(api.handle(body))

    return app


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def main(argv=None):
    from state_manager import StateStore
    p = argparse.ArgumentParser(description="Ezz Steel Pricing Model — Fantomaas orchestrator entry point")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="HTTP server (FastAPI; docs at /docs)")
    mode.add_argument("--stdin", action="store_true", help="read one JSON request per line, write one JSON reply per line")
    p.add_argument("--db", default="ezz_model.db")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--token", default=os.environ.get("FANTOMAAS_API_TOKEN"),
                   help="bearer token required on every HTTP request (default: $FANTOMAAS_API_TOKEN)")
    p.add_argument("--simulate", action="store_true", help="simulated Claude for 'instruction' requests")
    a = p.parse_args(argv)
    client, kwargs = None, {}
    if a.simulate:
        from llm_sim import SimulatedClaude
        client, kwargs["use_fallbacks"] = SimulatedClaude(), False
    api = OrchestratorAPI(StateStore(a.db), client, **kwargs)
    if a.stdin:
        for line in sys.stdin:
            if line.strip():
                print(json.dumps(api.handle(line), ensure_ascii=False), flush=True)
        return
    if not a.token and not _is_loopback(a.host):
        p.error("serving beyond this machine needs a token (--token or FANTOMAAS_API_TOKEN)")
    import uvicorn
    uvicorn.run(create_app(api, a.token), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
