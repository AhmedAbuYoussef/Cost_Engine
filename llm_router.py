"""
Step 4 — Claude reads a question, picks one of the tools, calls it, and answers.

    from llm_router import Router
    router = Router(ToolBox(store))              # real Claude (credentials from the environment)
    router = Router(ToolBox(store), client=SimulatedClaude())   # no API key needed
    reply = router.ask("What is the consolidated EBT this month?")
    reply.text, reply.tool_calls, reply.usage

Design:

* **Claude never calculates** (Rule 1).  Every number in an answer comes from a tool
  result; the engine computes, Claude explains.
* **A manual tool-use loop**, so every call goes through ``ToolBox.call`` with this
  session's permission mode, failures go back to Claude as ``is_error`` tool results it
  can correct, and each call is logged.
* **The conversation is append-only**: Claude's responses are stored exactly as returned
  (thinking blocks included) and never edited, which keeps the prompt cache warm and
  preserved thinking valid.  The runtime header (system prompt §5) rides on the first
  user turn only.
* **Request**: Claude Opus 5.5, effort ``high`` (financial accuracy; its default is
  medium), adaptive thinking (always on for this model), the stable system prompt and
  tool list cached, ``tool_choice`` auto (forced tool use is not available on this
  model), and server-side refusal fallback (``fallbacks: "default"``).

Run ``python llm_router.py --simulate`` for a terminal session without an API key.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass, field

import state_schema as schema

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, "ezz_steel_bot_system_prompt_v2.md")

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 16000
MAX_TOOL_ROUNDS = 12
FALLBACK_BETA = "server-side-fallback-2026-07-01"


# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #

def _path_catalogue(state: dict) -> str:
    """Section → keys, with example paths: enough for Claude to name inputs exactly and to
    use read_state for anything deeper."""
    lines = []
    for k, v in state.items():
        if k in schema.READ_ONLY_ROOTS:
            continue
        if not isinstance(v, dict) or not v:
            lines.append(f"- `{k}`")
            continue
        leaves = list(schema.leaves(v, f"{k}."))
        keys = ", ".join(f"`{x}`" for x in v.keys())
        examples = ", ".join(f"`{p}`" for p in leaves[:2])
        lines.append(f"- `{k}` → {keys} ({len(leaves)} inputs; e.g. {examples})")
    return "\n".join(lines)


def build_system_prompt(mode: str, state: dict) -> str:
    """Sections 1–5 of the system prompt file (the runtime part — the revision notes and
    the build-time appendices stay out) plus notes on how this implementation behaves."""
    with open(PROMPT_FILE, encoding="utf-8") as f:
        text = f.read()
    head = text[:text.index("## Revision notes")].rstrip()
    body = text[text.index("## 1. Identity & Mission"):text.index("## Appendix A")].rstrip().rstrip("-").rstrip()
    addendum = f"""
## 6. Implementation notes (authoritative where they differ from the sections above)

- **Caller mode for this conversation: {mode}.** {"You are serving the direct user." if mode == "user" else
  "You are serving the Fantomaas orchestrator: structured JSON answers, no conversational overhead, and no baseline commits."}
- **Tools.** The tool definitions attached to this conversation are authoritative for names and
  arguments. `find_optimal_mix` is not available yet: it ships at a later build step, after its four
  verification cases pass. If asked to optimise, say so and offer sensitivity runs or scenario
  comparisons instead. There is no undo tool. To revert an input, set it back to the old value that the
  earlier `update_input` result returned.
- **Tool results are JSON.** Reports return tables (`title`, `columns`, `rows` with `label`, `unit`,
  `kind` and `values`, plus `footnotes` and `source`). Present them as markdown tables. Keep every
  footnote that matters and always end with the source line. Round only for display:
  - money in millions to 2 decimals;
  - per-ton values to 2 decimals in USD and 0 decimals in LE;
  - quantities (kt) to 1 decimal;
  - percentages (`kind: pct`) to 0 decimals, or 1 decimal when below 10;
  - consumptions to 1 decimal.
  Never compute a number that a tool did not return.
- **`status: "needs_input"`** means a value must come from the user (e.g. the HRC local market size).
  Ask for it, then call the tool again with it. Never store it.
- **Amendments.** `update_input` returns old and new values, the impact on key figures, warnings
  (capacity) and, when it happens, `sourcing_change` (ERM's cheapest billet supplier switched, moving
  billet production between companies). Always tell the user about warnings and sourcing changes.
  Inputs that must change together (a blend and its balancing scrap share) go in one call as `changes`.
- **Integrity.** Error-level checks block writes and reports, and the tools return them as
  `integrity_check_failed`. Capacity overruns are warnings: report them and do not stop.
- **Currency arguments** are `"USD"` or `"EGP"`. Money in the state is USD unless the key says `le`, or
  the value is written `{{"le": x}}`.
- **State paths** (dotted; use `read_state` on a section to see its exact keys):
{_path_catalogue(state)}
"""
    return f"{head}\n\n{body}\n{addendum}"


def tool_definitions(toolbox) -> list:
    """API tool list from the ToolBox's visible tools, in a fixed order (cache-stable)."""
    return [{"name": s["name"], "description": s["description"], "input_schema": s["input_schema"]}
            for s in toolbox.visible_tools()]


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #

def _round_floats(obj, sig: int = 6):
    """Tool results go to Claude with 6 significant digits — plenty for 2-decimal display,
    and far fewer tokens than full float precision."""
    if isinstance(obj, float):
        if obj == 0 or not math.isfinite(obj):
            return obj
        return round(obj, sig - 1 - int(math.floor(math.log10(abs(obj)))))
    if isinstance(obj, dict):
        return {k: _round_floats(v, sig) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, sig) for v in obj]
    return obj


def _get(block, key, default=None):
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


@dataclass
class Reply:
    text: str
    stop_reason: str
    tool_calls: list = field(default_factory=list)
    rounds: int = 0
    usage: dict = field(default_factory=dict)


class Router:
    def __init__(self, toolbox, client=None, *, model: str = MODEL, effort: str = EFFORT,
                 max_tool_rounds: int = MAX_TOOL_ROUNDS, use_fallbacks: bool = True):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()      # credentials from the environment / `ant auth login`
        self.toolbox, self.client = toolbox, client
        self.model, self.effort, self.max_tool_rounds = model, effort, max_tool_rounds
        self.use_fallbacks = use_fallbacks
        self.system = build_system_prompt(toolbox.mode, toolbox.store.get_state("working"))
        self.tools = tool_definitions(toolbox)
        self.messages: list = []
        self.tool_log: list = []

    def _request(self) -> dict:
        req = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            "tools": self.tools,
            "messages": self.messages,
            "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},     # also caches the growing conversation
        }
        if self.use_fallbacks:
            req["betas"] = [FALLBACK_BETA]
            req["fallbacks"] = "default"
        return req

    def _run_tool(self, block) -> dict:
        name, args = _get(block, "name"), _get(block, "input") or {}
        t0 = time.perf_counter()
        result = self.toolbox.call(name, args)
        entry = {"name": name, "input": args, "status": result.get("status"),
                 "error_code": result.get("error_code"), "ms": round((time.perf_counter() - t0) * 1000, 1)}
        self.tool_log.append(entry)
        return {"type": "tool_result", "tool_use_id": _get(block, "id"),
                "content": json.dumps(_round_floats(result), ensure_ascii=False, separators=(",", ":")),
                **({"is_error": True} if result.get("status") == "error" else {})}, entry

    def ask(self, text: str) -> Reply:
        """One user turn: Claude may call tools several times before answering."""
        content = [{"type": "text", "text": text}]
        if not self.messages:                       # runtime header, first turn only
            content.insert(0, {"type": "text", "text": f"[Runtime header] {self.toolbox.store.runtime_header()}"})
        self.messages.append({"role": "user", "content": content})
        calls, usage = [], {}
        for rounds in range(1, self.max_tool_rounds + 1):
            if self.use_fallbacks:
                response = self.client.beta.messages.create(**self._request())
            else:
                response = self.client.messages.create(**self._request())
            _add_usage(usage, _get(response, "usage"))
            blocks = list(_get(response, "content") or [])
            self.messages.append({"role": "assistant", "content": blocks})   # exactly as returned
            stop = _get(response, "stop_reason")
            if stop == "tool_use":
                results = []
                for b in blocks:
                    if _get(b, "type") == "tool_use":
                        r, entry = self._run_tool(b)
                        results.append(r)
                        calls.append(entry)
                self.messages.append({"role": "user", "content": results})   # all results, one turn
                continue
            if stop == "pause_turn":
                continue
            text_out = "\n".join(_get(b, "text") for b in blocks if _get(b, "type") == "text").strip()
            if stop == "refusal":
                details = _get(response, "stop_details")
                cat = _get(details, "category") if details else None
                text_out = text_out or ("I can't help with that request" + (f" ({cat})." if cat else "."))
            elif stop == "max_tokens":
                text_out += "\n\n(The answer was cut off at the length limit — ask me to continue.)"
            return Reply(text_out, stop, calls, rounds, usage)
        return Reply(f"I stopped after {self.max_tool_rounds} rounds of tool calls without a final answer. "
                     "Please narrow the question.", "tool_round_limit", calls, self.max_tool_rounds, usage)


def _add_usage(total: dict, usage) -> None:
    if usage is None:
        return
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        v = _get(usage, k)
        if isinstance(v, int):
            total[k] = total.get(k, 0) + v


# --------------------------------------------------------------------------- #
# Bare terminal loop (Step 4 done-criterion)
# --------------------------------------------------------------------------- #

def main(argv=None):
    from state_manager import StateStore
    from tools import ToolBox
    p = argparse.ArgumentParser(description="Ezz Steel Pricing Model Assistant — terminal session")
    p.add_argument("--db", default="ezz_model.db")
    p.add_argument("--mode", choices=["user", "orchestrator"], default="user")
    p.add_argument("--simulate", action="store_true", help="use the simulated Claude (no API key needed)")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--effort", default=EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    a = p.parse_args(argv)
    store = StateStore(a.db)
    client = None
    if a.simulate:
        from llm_sim import SimulatedClaude
        client = SimulatedClaude()
    router = Router(ToolBox(store, mode=a.mode), client, model=a.model, effort=a.effort,
                    use_fallbacks=not a.simulate)
    print(store.runtime_header())
    print("Ask a question (empty line to quit).")
    while True:
        try:
            q = input("\n> ").strip()
        except EOFError:
            break
        if not q:
            break
        r = router.ask(q)
        print("\n" + r.text)
        if r.tool_calls:
            print("\n[tools: " + ", ".join(f"{c['name']}→{c['status']}" for c in r.tool_calls) + "]")


if __name__ == "__main__":
    main()
