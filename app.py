"""
Step 6 — the web interface (Gradio).

    python app.py --simulate          # no API key needed: the simulated Claude
    python app.py                     # real Claude (ANTHROPIC_API_KEY or `ant auth login`)

One page:

* **Chat** — the conversation with the assistant.  Each answer shows the tools it used
  (collapsible, with the arguments), Claude's tables, and under it the charts, colour-coded
  comparisons and the trade-off heatmap drawn from that turn's tool results.
* **On open** — the stored conversation is restored; with unsaved changes the Pattern F
  question appears with one-click answers (resume / save as a scenario / discard).
* **Side panel** — the model's state (baseline, scenarios, working-session changes), the
  currency preference, quick actions (undo, compare with baseline), saved scenarios.

The page is a view over the SessionManager (Step 5): closing the browser loses nothing.
One session per user, shared across tabs (§5), so turns are serialised.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import threading

import gradio as gr

import ui_render
from session_manager import SessionManager
from state_manager import StateStore

TITLE = "Ezz Steel Pricing Model Assistant"

EXAMPLES = [
    "Show the consolidated P&L with a chart",
    "Show the DRI cost for all companies with a chart",
    "Show the billet trade-off matrix",
    "Show the production flow diagram",
    "set sales.EZDK.Rebar.local_kt to 120",
    "Compare the working session with baseline 2026-04",
    "Run a sensitivity of dri.ERM.iop_landed_usd_t on ebt for ERM with a chart",
    "Show the fixed cost report in EGP with a chart",
    "Find the optimal mix, the HRC market is 120",
]

RESUME_OPTIONS = ["Resume where I left off", "Save it as a scenario", "Discard it"]

CSS = """
.gradio-container{max-width:1320px !important}
#status-panel{font-size:13px}
#status-panel ul{margin:2px 0 6px 0;padding-left:18px}
#chat table{font-variant-numeric:tabular-nums;font-size:13px;display:block;overflow-x:auto;max-width:100%}
#chat td,#chat th{white-space:nowrap;padding:4px 10px}
#chat td:first-child{white-space:normal;min-width:160px}
footer{display:none !important}
"""


class App:
    """The UI's state and handlers, independent of the Gradio layout (so tests can drive it)."""

    def __init__(self, store: StateStore, client=None, *, channel: str = "user", simulated: bool = False,
                 **router_kwargs):
        self.store, self.simulated = store, simulated
        self.session = SessionManager(store, client, channel=channel, **router_kwargs)
        self._lock = threading.Lock()
        self._opener: str | None = None
        self._opener_at = 0
        self._closed: list = []            # a conversation that just ended stays on screen until reload

    # ------------------------------------------------------------------ rendering

    def _messages(self) -> list:
        return self.session.router.messages if self.session.router else []

    def history(self) -> list[gr.ChatMessage]:
        entries = ui_render.conversation(self._messages())
        chat = list(self._closed)
        for i, e in enumerate(entries):
            if self._opener and i == self._opener_at:
                chat.append(self._opener_message())
            chat.extend(to_chat(e))
        if self._opener and self._opener_at >= len(entries):
            chat.append(self._opener_message())
        return chat

    def _opener_message(self) -> gr.ChatMessage:
        return gr.ChatMessage(role="assistant", content=self._opener,
                              options=[{"value": o} for o in RESUME_OPTIONS])

    def status_markdown(self) -> str:
        s = self.store.session_summary()
        lines = []
        if self.simulated:
            lines.append("**Simulated assistant** — keyword rules stand in for Claude (no API key in use).\n")
        lines.append(f"**Baseline:** {s['base_month_label']}  ")
        n = len(self.store.list_states("scenarios"))
        lines.append(f"**Saved scenarios:** {n}  ")
        if s["status"] == "in_progress":
            lines.append(f"**Working session:** {len(s['net_changes'])} unsaved change(s)")
            for c in s["net_changes"][:8]:
                lines.append(f"- `{c['path']}`: {_short(c['baseline'])} → {_short(c['now'])}")
            if len(s["net_changes"]) > 8:
                lines.append(f"- … and {len(s['net_changes']) - 8} more")
        else:
            lines.append("**Working session:** same as the baseline")
        return "\n".join(lines)

    def scenarios(self) -> list[list]:
        rows = sorted(self.store.list_states("scenarios"), key=lambda r: r["created_at"], reverse=True)
        return [[r["name"], r["created_at"][:16].replace("T", " "), r["id"][:8]] for r in rows[:50]]

    def snapshot(self):
        return self.history(), self.status_markdown(), self.session.preferences["currency"], self.scenarios()

    # ------------------------------------------------------------------ handlers

    def on_load(self):
        with self._lock:
            c = self.session.connect()
            self._closed = []
            self._opener = c["message"]
            self._opener_at = len(ui_render.conversation(self._messages()))
            return self.snapshot()

    def on_user_message(self, text: str, chat: list):
        """Echo the user's message at once, with a working indicator, while the answer runs."""
        text = (text or "").strip()
        if not text:
            return gr.update(), chat
        chat = list(chat or []) + [gr.ChatMessage(role="user", content=text),
                                   gr.ChatMessage(role="assistant", content="",
                                                  metadata={"title": "Working on it…", "status": "pending"})]
        return "", chat

    def respond(self, chat: list):
        text = next((m["content"] if isinstance(m, dict) else m.content for m in reversed(chat or [])
                     if (m["role"] if isinstance(m, dict) else m.role) == "user"), None)
        if isinstance(text, list):         # Gradio may hand back structured content
            text = " ".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in text)
        if not text:
            return self.snapshot()
        return self.ask(text)

    def ask(self, text: str):
        with self._lock:
            before = self.history()
            try:
                reply = self.session.ask(text)
            except Exception as exc:            # network, credentials, rate limits: say so, keep the session
                chat = before + [gr.ChatMessage(role="user", content=text),
                                 gr.ChatMessage(role="assistant",
                                                content=f"I couldn't reach the assistant: {html.escape(str(exc))}. "
                                                        "Nothing was changed; please try again.")]
                return chat, self.status_markdown(), self.session.preferences["currency"], self.scenarios()
            self._opener = None
            if getattr(reply, "session_ended", False):
                # keep the closed conversation visible: rebuild it from what we showed plus this turn
                ended = before + [gr.ChatMessage(role="user", content=text),
                                  gr.ChatMessage(role="assistant", content=reply.text),
                                  gr.ChatMessage(role="assistant", content="Session closed. Your next message "
                                                 "starts a fresh conversation (currency back to USD).",
                                                 metadata={"title": "ℹ Session closed"})]
                self._closed = ended
            return self.snapshot()

    def on_option(self, evt: gr.SelectData):
        return evt.value

    def on_currency(self, currency: str):
        with self._lock:
            if currency != self.session.preferences["currency"]:
                self.session.set_preference("currency", currency)
            return self.status_markdown()


def _short(v) -> str:
    """A value for the status panel and tool summaries (markdown escapes it)."""
    if isinstance(v, dict) and len(v) == 1:
        v = next(iter(v.values()))
    if isinstance(v, float):
        return f"{v:,.4g}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def to_chat(entry: dict) -> list[gr.ChatMessage]:
    """One ui_render.conversation entry → chat messages."""
    if entry["role"] == "user":
        return [gr.ChatMessage(role="user", content=entry["text"])]
    if entry["role"] == "tool":
        args = ", ".join(f"{k}={_short(v)}" for k, v in entry["input"].items()) or "no arguments"
        body = (entry["preamble"] + "\n\n" if entry["preamble"] else "") + f"`{entry['name']}({args})`"
        if entry["status"] == "error":
            title = f"⚠ {entry['label']} — {entry['error_code']}"
            body += f"\n\n{entry.get('error_message') or ''}"
        elif entry["status"] == "needs_input":
            title = f"❓ {entry['label']} — needs a figure"
        else:
            title = f"🔧 {entry['label']}"
        return [gr.ChatMessage(role="assistant", content=body, metadata={"title": title, "status": "done"})]
    out = [gr.ChatMessage(role="assistant", content=entry["text"] or "(no text)")]
    for a in entry["artifacts"]:
        out.append(gr.ChatMessage(role="assistant", content=gr.HTML(a["html"])))
    return out


def build(app: App) -> gr.Blocks:
    with gr.Blocks(title=TITLE) as demo:
        gr.Markdown(f"## {TITLE}\nAsk about costs, P&L, sales, production and sourcing; change inputs and "
                    "see the impact; save, compare and promote scenarios. Figures come from the cost engine, "
                    "never from memory.")
        with gr.Row(equal_height=False):
            with gr.Column(scale=3):
                chat = gr.Chatbot(elem_id="chat", height=680, layout="panel", show_label=False,
                                  render_markdown=True, group_consecutive_messages=True,
                                  latex_delimiters=[], buttons=["copy"],
                                  placeholder="Ask a question, or pick an example below.")
                with gr.Row():
                    box = gr.Textbox(placeholder="e.g. Show the consolidated P&L in EGP", show_label=False,
                                     scale=8, autofocus=True, submit_btn=True)
                gr.Examples(EXAMPLES, inputs=box, label="Try")
            with gr.Column(scale=1, min_width=300):
                status = gr.Markdown(elem_id="status-panel")
                currency = gr.Radio(["USD", "EGP"], label="Currency for reports", value="USD",
                                    info="Applies when a question names no currency.")
                with gr.Row():
                    undo = gr.Button("↶ Undo last change", size="sm")
                    compare = gr.Button("Compare with baseline", size="sm")
                scen = gr.Dataframe(headers=["Scenario", "Saved (UTC)", "Id"], label="Saved scenarios",
                                    interactive=False, wrap=True, max_height=260)

        outputs = [chat, status, currency, scen]
        demo.load(app.on_load, None, outputs)
        (box.submit(app.on_user_message, [box, chat], [box, chat], queue=False)
            .then(app.respond, chat, outputs, concurrency_limit=1))

        def quick(text):
            return lambda c: app.on_user_message(text, c)
        for btn, text in ((undo, "Undo my last change"),
                          (compare, "Compare the working session with the baseline")):
            (btn.click(quick(text), chat, [box, chat], queue=False)
                .then(app.respond, chat, outputs, concurrency_limit=1))
        (chat.option_select(app.on_option, None, box)
            .then(app.on_user_message, [box, chat], [box, chat], queue=False)
            .then(app.respond, chat, outputs, concurrency_limit=1))
        currency.input(app.on_currency, currency, status)
    return demo


def main(argv=None):
    p = argparse.ArgumentParser(description=f"{TITLE} — web interface")
    p.add_argument("--db", default="ezz_model.db")
    p.add_argument("--simulate", action="store_true", help="use the simulated Claude (no API key needed)")
    p.add_argument("--mode", choices=["user", "orchestrator"], default="user")
    p.add_argument("--model", default=None)
    p.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--host", default=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("GRADIO_SERVER_PORT", 7860)))
    p.add_argument("--share", action="store_true", help="create a temporary public Gradio link")
    a = p.parse_args(argv)
    client, kwargs = None, {}
    if a.simulate:
        from llm_sim import SimulatedClaude
        client, kwargs["use_fallbacks"] = SimulatedClaude(), False
    if a.model:
        kwargs["model"] = a.model
    if a.effort:
        kwargs["effort"] = a.effort
    app = App(StateStore(a.db), client, channel=a.mode, simulated=a.simulate, **kwargs)
    build(app).queue().launch(server_name=a.host, server_port=a.port, share=a.share, css=CSS,
                              theme=gr.themes.Soft(font=[gr.themes.Font(f) for f in ("system-ui", "Segoe UI", "Roboto", "sans-serif")]))


if __name__ == "__main__":
    main()
