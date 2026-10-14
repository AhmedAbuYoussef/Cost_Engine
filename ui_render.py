"""
Step 6 — display layer for the web UI (system prompt §4 "Rendering Rules", rulebook §9.2).

Pure functions, no Gradio import, so everything here is unit-testable:

* ``fmt``            — one number at display precision (accounting negatives in parentheses).
* ``chart_svg``      — a tool's chart spec (stacked_bar | bar | line) → self-contained SVG,
                       with a hover tooltip on every mark.
* ``compare_html``   — ``compare_states`` output → HTML with colour-coded deltas (▲/▼ + sign,
                       never colour alone).
* ``tradeoff_html``  — the billet trade-off matrix as a heatmap, cheapest source per buyer marked.
* ``conversation``   — the stored Claude conversation → chat entries for the UI: the user's
                       messages, the tools each answer used, the answer, and the artifacts
                       (charts, comparisons) drawn from the tool results of that turn.

Claude writes the tables itself (markdown, in its answer); the UI adds what markdown cannot
show: charts, coloured comparisons and the heatmap.  The numbers drawn are the tool results,
never re-derived.
"""

from __future__ import annotations

import html
import json
import math

# Reference palette (dataviz skill, references/palette.md): categorical slots in fixed order,
# status colours reserved for good/bad deltas, a single-hue sequential ramp for the heatmap.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SERIES_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767")
GOOD, BAD = "#0ca30c", "#d03b3b"
SEQ = ("#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf")

_FINANCIAL = {"money", "per_t", "price"}


# --------------------------------------------------------------------------- #
# Numbers
# --------------------------------------------------------------------------- #

def fmt(v, kind: str = "money", unit: str = "") -> str:
    """Display precision (router addendum): money 2 dp; per-ton 2 dp in USD, 0 dp in LE;
    kt and consumptions 1 dp; percentages 0 dp (1 dp below 10).  Financial negatives in
    parentheses (Rendering Rules)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, float) and not math.isfinite(v):
        return "n/a"
    if kind == "pct":
        return f"{v:,.1f}%" if abs(v) < 10 else f"{v:,.0f}%"
    if kind in ("qty", "consumption"):
        return f"{v:,.1f}"
    if kind == "ratio":
        return f"{v:,.4f}"
    dp = 0 if kind in ("per_t", "price") and unit.startswith("LE") else 2
    s = f"{abs(v):,.{dp}f}"
    if kind in _FINANCIAL and round(v, dp) < 0:
        return f"({s})"
    return s if v >= 0 or round(v, dp) == 0 else f"-{s}"


def _kind_of_figure(figure: str) -> tuple[str, str]:
    """(kind, unit) from a compare_states figure name such as 'Group EBT M$' or 'Capacity DRI EZDK %'."""
    unit = figure.rsplit(" ", 1)[-1]
    return {"M$": ("money", unit), "%": ("pct", ""), "kt": ("qty", unit), "$/t": ("per_t", unit),
            "LE/t": ("per_t", unit)}.get(unit, ("money", ""))


_HIGHER_IS_BETTER = ("revenue", "ebt", "ebtd", "cm", "margin", "profit")
_LOWER_IS_BETTER = ("cost", "cogs", "expense", "break-even", "breakeven", "fixed")


def delta_direction(figure: str) -> int:
    """+1 when an increase is good news, -1 when it is bad news, 0 when neither (volumes, inputs)."""
    words = figure.lower().replace("/", " ").split()
    if any(w in words for w in _LOWER_IS_BETTER) or "cost" in figure.lower():
        return -1
    if any(w in words for w in _HIGHER_IS_BETTER):
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Charts (SVG)
# --------------------------------------------------------------------------- #

_VIZ_CSS = """<style>
.viz-root{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e6e5e1;--axis:#b9b8b2;
%s
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--surface);
border-radius:8px;padding:12px 12px 4px;margin:4px 0;max-width:720px}
.dark .viz-root{--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2f2f2d;--axis:#5c5b57;
%s}
.viz-root h4{margin:0 0 2px;font-size:14px;font-weight:600;color:var(--ink)}
.viz-root .viz-sub{margin:0 0 6px;font-size:12px;color:var(--ink2)}
.viz-root .viz-legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--ink2);margin-bottom:4px}
.viz-root .viz-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.viz-root svg{display:block;width:100%%;height:auto;overflow:visible}
.viz-root svg text{fill:var(--ink2);font-size:11px}
.viz-root svg .viz-total{fill:var(--ink);font-weight:600}
.viz-root svg .viz-hit{fill:transparent}
.viz-root svg .viz-mark:hover,.viz-root svg g:hover>.viz-mark{opacity:.82}
</style>""" % ("".join(f"--s{i + 1}:{c};" for i, c in enumerate(SERIES)),
               "".join(f"--s{i + 1}:{c};" for i, c in enumerate(SERIES_DARK)))


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi == lo:
        hi, lo = (hi + 1, lo - 1) if hi == 0 else (hi * 1.1, lo * 0.9 if lo > 0 else lo * 1.1)
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 1e-9:
        ticks.append(round(t, 10))
        t += step
    if ticks[-1] < hi:
        ticks.append(ticks[-1] + step)
    return ticks


def _axis(t: float, ticks: list, kind: str = "") -> str:
    """Tick label with only the decimals the tick step needs; financial negatives in parentheses."""
    step = abs(ticks[1] - ticks[0]) if len(ticks) > 1 else 1
    dp = next(d for d in range(4) if abs(round(step, d) - step) < 1e-9 or d == 3)
    s = f"{abs(t):,.{dp}f}"
    if t < 0 and round(t, dp) != 0:
        return f"({s})" if kind in _FINANCIAL else f"-{s}"
    return s


def _bar_path(x, y0, w, y1, r=4.0) -> str:
    """A bar from baseline y0 to data end y1, rounded only at the data end."""
    r = min(r, w / 2, abs(y1 - y0))
    if y1 <= y0:        # grows up
        return (f"M{x:.1f},{y0:.1f}V{y1 + r:.1f}Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f}"
                f"H{x + w - r:.1f}Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 + r:.1f}V{y0:.1f}Z")
    return (f"M{x:.1f},{y0:.1f}V{y1 - r:.1f}Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f}"
            f"H{x + w - r:.1f}Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 - r:.1f}V{y0:.1f}Z")


def _frame(title: str, subtitle: str, legend: list[str], svg: str) -> str:
    leg = ""
    if len(legend) >= 2:
        leg = '<div class="viz-legend">' + "".join(
            f'<span><i style="background:var(--s{i + 1})"></i>{html.escape(n)}</span>'
            for i, n in enumerate(legend)) + "</div>"
    return (f'{_VIZ_CSS}<div class="viz-root"><h4>{html.escape(title)}</h4>'
            f'<p class="viz-sub">{html.escape(subtitle)}</p>{leg}{svg}</div>')


def chart_svg(spec: dict, source: str = "") -> str:
    """Render a tool's chart spec.  ``source`` (e.g. 'Source: working state') goes in the subtitle,
    so the chart names its scope and source (Rendering Rules)."""
    kind, unit = spec.get("kind", "money"), spec.get("unit", "")
    sub = " · ".join(x for x in (unit and f"Unit: {unit}", source) if x)
    if spec["type"] == "line":
        return _frame(spec["title"], sub, [], _line_svg(spec, kind, unit))
    series = spec["series"][:8]                       # a 9th series is never a generated hue
    legend = [s["name"] for s in series] if spec["type"] == "stacked_bar" else []
    return _frame(spec["title"], sub, legend, _bars_svg(spec, series, kind, unit))


def _bars_svg(spec, series, kind, unit) -> str:
    cats = spec["categories"]
    stacked = spec["type"] == "stacked_bar"
    W, H, L, R, T, B = 640, 300, 56, 110 if stacked and len(series) <= 4 else 16, 22, 30
    vals = [[(s["values"][i] or 0) for s in series] for i in range(len(cats))]
    if stacked:
        tops = [sum(v for v in col if v > 0) for col in vals]
        bots = [sum(v for v in col if v < 0) for col in vals]
    else:
        tops = [max(0, col[0]) for col in vals]
        bots = [min(0, col[0]) for col in vals]
    ticks = _nice_ticks(min(0, *bots), max(0, *tops))
    lo, hi = ticks[0], ticks[-1]
    y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    band = (W - L - R) / max(1, len(cats))
    bw = min(56, band * 0.56)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(spec["title"])}">']
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" '
                   f'stroke="var({"--axis" if t == 0 else "--grid"})" stroke-width="1"/>'
                   f'<text x="{L - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{_axis(t, ticks, kind)}</text>')
    for i, c in enumerate(cats):
        x = L + band * i + (band - bw) / 2
        out.append(f'<text x="{x + bw / 2:.1f}" y="{H - B + 16}" text-anchor="middle">{html.escape(str(c))}</text>')
        if stacked:
            pos = neg = 0.0
            # the outermost positive / negative segment carries the rounded data end
            last_pos = max((k for k, v in enumerate(vals[i]) if v > 0), default=None)
            last_neg = max((k for k, v in enumerate(vals[i]) if v < 0), default=None)
            for k, v in enumerate(vals[i]):
                if v == 0:
                    continue
                base = pos if v > 0 else neg
                y0, y1 = y(base), y(base + v)
                gap = 2 if base != 0 else 0                     # 2px surface gap between segments
                y0 = y0 - gap if v > 0 else y0 + gap
                tip = f'{series[k]["name"]} — {cats[i]}: {fmt(v, kind, unit)} {unit}'
                if abs(y1 - y0) >= 0.5:                         # too thin to draw: still stacked
                    d = (_bar_path(x, y0, bw, y1) if k in (last_pos, last_neg)
                         else f"M{x:.1f},{y0:.1f}V{y1:.1f}H{x + bw:.1f}V{y0:.1f}Z")
                    out.append(f'<path class="viz-mark" d="{d}" fill="var(--s{k + 1})">'
                               f'<title>{html.escape(tip)}</title></path>')
                if v > 0:
                    pos += v
                else:
                    neg += v
            if spec.get("total_labels", True):
                total = sum(vals[i])
                ty = y(max(pos, 0)) - 6
                out.append(f'<text class="viz-total" x="{x + bw / 2:.1f}" y="{ty:.1f}" text-anchor="middle">'
                           f'{fmt(total, kind, unit)}</text>')
            # direct labels (≤ 4 series) beside the last bar
            if i == len(cats) - 1 and len(series) <= 4:
                acc = 0.0
                for k, v in enumerate(vals[i]):
                    if v > 0 and (y(acc) - y(acc + v)) >= 13:
                        out.append(f'<text x="{x + bw + 8:.1f}" y="{(y(acc) + y(acc + v)) / 2 + 4:.1f}">'
                                   f'{html.escape(series[k]["name"])}</text>')
                    acc += max(v, 0)
        else:
            v = vals[i][0]
            y0, y1 = y(0), y(v)
            tip = f"{cats[i]}: {fmt(v, kind, unit)} {unit}"
            out.append(f'<g><rect class="viz-hit" x="{x - 4:.1f}" y="{T}" width="{bw + 8:.1f}" height="{H - T - B}"/>'
                       f'<path class="viz-mark" d="{_bar_path(x, y0, bw, y1)}" fill="var(--s1)"/>'
                       f'<title>{html.escape(tip)}</title></g>')
            ly = y1 - 6 if v >= 0 else y1 + 14
            out.append(f'<text class="viz-total" x="{x + bw / 2:.1f}" y="{ly:.1f}" text-anchor="middle">'
                       f'{fmt(v, kind, unit)}</text>')
    out.append("</svg>")
    return "".join(out)


def _line_svg(spec, kind, unit) -> str:
    pts = [(x, y_) for x, y_ in zip(spec["x"], spec["y"]) if y_ is not None]
    if not pts:
        return "<p>No computable points.</p>"
    W, H, L, R, T, B = 640, 280, 64, 20, 16, 42
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    yt = _nice_ticks(min(0, *ys) if min(ys) < 0 < max(ys) or min(ys) <= 0 else min(ys), max(ys))
    xt = _nice_ticks(min(xs), max(xs), 6)
    sx = lambda v: L + (v - xt[0]) / (xt[-1] - xt[0]) * (W - L - R)
    sy = lambda v: T + (yt[-1] - v) / (yt[-1] - yt[0]) * (H - T - B)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(spec["title"])}">']
    for t in yt:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" '
                   f'stroke="var({"--axis" if t == 0 else "--grid"})"/>'
                   f'<text x="{L - 6}" y="{sy(t) + 4:.1f}" text-anchor="end">{_axis(t, yt, kind)}</text>')
    for t in xt:
        out.append(f'<text x="{sx(t):.1f}" y="{H - B + 16}" text-anchor="middle">{_axis(t, xt)}</text>')
    out.append(f'<text x="{(L + W - R) / 2:.1f}" y="{H - 6}" text-anchor="middle">'
               f'{html.escape(spec.get("x_label", ""))}</text>')
    for m in spec.get("markers", []):
        out.append(f'<line x1="{sx(m):.1f}" x2="{sx(m):.1f}" y1="{T}" y2="{H - B}" stroke="var(--ink2)" '
                   f'stroke-dasharray="3 3"/><text x="{sx(m) + 4:.1f}" y="{T + 10}">zero at {fmt(m, "money")}</text>')
    d = "M" + "L".join(f"{sx(x):.1f},{sy(y_):.1f}" for x, y_ in pts)
    out.append(f'<path d="{d}" fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round"/>')
    for x, y_ in pts:
        out.append(f'<g><circle class="viz-hit" cx="{sx(x):.1f}" cy="{sy(y_):.1f}" r="11"/>'
                   f'<circle class="viz-mark" cx="{sx(x):.1f}" cy="{sy(y_):.1f}" r="4.5" fill="var(--s1)" '
                   f'stroke="var(--surface)" stroke-width="2"/>'
                   f'<title>{html.escape(fmt(x, "money") + " → " + fmt(y_, kind, unit) + " " + unit)}</title></g>')
    out.append("</svg>")
    return "".join(out)


_COMPANIES = ("EZDK", "EFS", "ERM", "ESR")
_LAYER = {"IOP": 0, "DRI": 1, "EAF": 2, "CAST": 3, "MARKET": 3, "FIN": 4}
_LAYER_TITLE = ("Iron ore pellets", "DRI", "Melt shop (EAF)", "Billets / slabs", "Finished products")


def flow_svg(flow: dict, source: str = "") -> str:
    """The production flow (get_production_report, view=flow_diagram) as a layered diagram:
    stages left to right, link width ∝ kt, each company in its own colour.  Scrap charged to
    a furnace is shown on the furnace rather than as a separate box."""
    nodes = {n["id"]: dict(n) for n in flow["nodes"] if not n["id"].startswith("SCRAP")}
    scrap = {e["to"]: e["kt"] for e in flow["edges"] if e["from"].startswith("SCRAP")}
    edges = [e for e in flow["edges"] if e["from"] in nodes and e["to"] in nodes]
    for n in nodes.values():
        n["layer"] = _LAYER.get(n["id"].split("_")[0], 2)
        n["co"] = next((c for c in _COMPANIES if c in n["id"].split("_")), None)
    succ = {}
    for e in edges:
        succ.setdefault(e["from"], []).append(e["to"])
    W, NW, NH, T = 980, 150, 44, 34
    by_layer = [[n for n in nodes.values() if n["layer"] == k] for k in range(5)]
    gap = 14
    # finished products evenly spaced; upstream nodes centred on what they feed, then de-overlapped
    for n_i, n in enumerate(by_layer[4]):
        n["y"] = T + n_i * (NH + gap)
    for k in (3, 2, 1, 0):
        for n in by_layer[k]:
            ys = [nodes[t]["y"] for t in succ.get(n["id"], []) if "y" in nodes[t]]
            n["y"] = sum(ys) / len(ys) if ys else T
        by_layer[k].sort(key=lambda n: n["y"])
        for a, b in zip(by_layer[k], by_layer[k][1:]):
            b["y"] = max(b["y"], a["y"] + NH + gap)
    H = max([n["y"] for n in nodes.values()] + [T]) + NH + 16
    colx = lambda k: 8 + k * (W - NW - 16) / 4
    peak = max([e["kt"] for e in edges] + [1])
    out = [f'<svg viewBox="0 0 {W} {H:.0f}" role="img" aria-label="Production flow">']
    for k, t in enumerate(_LAYER_TITLE):
        out.append(f'<text x="{colx(k) + NW / 2:.1f}" y="14" text-anchor="middle" '
                   f'style="font-weight:600">{t}</text>')
    for e in edges:
        a, b = nodes[e["from"]], nodes[e["to"]]
        x1, y1 = colx(a["layer"]) + NW, a["y"] + NH / 2
        x2, y2 = colx(b["layer"]), b["y"] + NH / 2
        mx = (x1 + x2) / 2
        w = 1.5 + 10 * e["kt"] / peak
        col = f"var(--s{_COMPANIES.index(b['co']) + 1})" if b["co"] else "var(--ink2)"
        out.append(f'<path class="viz-mark" d="M{x1:.1f},{y1:.1f}C{mx:.1f},{y1:.1f} {mx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" '
                   f'fill="none" stroke="{col}" stroke-opacity=".45" stroke-width="{w:.1f}">'
                   f'<title>{html.escape(a["label"])} → {html.escape(b["label"])}: {e["kt"]:,.1f} kt</title></path>')
    for n in nodes.values():
        x, y = colx(n["layer"]), n["y"]
        col = f"var(--s{_COMPANIES.index(n['co']) + 1})" if n["co"] else "var(--ink2)"
        sub = f'{n["kt"]:,.1f} kt' + (f' · incl. {scrap[n["id"]]:,.1f} scrap' if n["id"] in scrap else "")
        tip = f'{n["label"]}: {sub}'
        out.append(f'<g><rect x="{x:.1f}" y="{y:.1f}" width="{NW}" height="{NH}" rx="6" fill="var(--surface)" '
                   f'stroke="var(--grid)"/><rect x="{x:.1f}" y="{y:.1f}" width="4" height="{NH}" rx="2" fill="{col}"/>'
                   f'<text x="{x + 12:.1f}" y="{y + 18:.1f}" class="viz-total">{html.escape(n["label"])}</text>'
                   f'<text x="{x + 12:.1f}" y="{y + 34:.1f}">{html.escape(sub)}</text>'
                   f'<title>{html.escape(tip)}</title></g>')
    out.append("</svg>")
    present = [c for c in _COMPANIES if any(n["co"] == c for n in nodes.values())]
    legend = "".join(f'<span><i style="background:var(--s{_COMPANIES.index(c) + 1})"></i>{c}</span>' for c in present)
    return (f'{_VIZ_CSS}<div class="viz-root" style="max-width:1000px"><h4>Production flow — kt per month</h4>'
            f'<p class="viz-sub">{html.escape(source or "")} · link width ∝ tonnage</p>'
            f'<div class="viz-legend">{legend}</div>{"".join(out)}</div>')


# --------------------------------------------------------------------------- #
# Comparison (compare_states) — HTML with colour-coded deltas
# --------------------------------------------------------------------------- #

_TABLE_CSS = """<style>
.cmp{--ink:#0b0b0b;--ink2:#52514e;--rule:#e6e5e1;--good:#006300;--bad:#b02a2a;
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px;color:var(--ink);max-width:760px}
.dark .cmp{--ink:#f0efec;--ink2:#c3c2b7;--rule:#2f2f2d;--good:#3fc23f;--bad:#ef7a7a}
.cmp h4{margin:6px 0 4px;font-size:14px}
.cmp table{border-collapse:collapse;width:100%;margin-bottom:8px}
.cmp th{font-weight:600;color:var(--ink2);text-align:right;border-bottom:1px solid var(--rule);padding:4px 8px}
.cmp th:first-child,.cmp td:first-child{text-align:left}
.cmp td{padding:3px 8px;text-align:right;border-bottom:1px solid var(--rule);font-variant-numeric:tabular-nums}
.cmp .up-good,.cmp .down-good{color:var(--good);font-weight:600}
.cmp .up-bad,.cmp .down-bad{color:var(--bad);font-weight:600}
.cmp .note{color:var(--ink2);font-style:italic;margin:2px 0}
.cmp .hm td{color:#0b0b0b}.cmp .hm td.dark-cell{color:#fff}
.cmp .best{font-weight:700}
.cmp .sr{position:absolute;left:-9999px}
</style>"""


def _delta_cell(delta, figure, kind, unit, pct=None) -> str:
    if delta is None or not isinstance(delta, (int, float)):
        return "<td>—</td><td></td>"
    sign = 1 if delta > 0 else -1 if delta < 0 else 0
    good = delta_direction(figure) * sign
    cls = "" if sign == 0 or good == 0 else ("up" if sign > 0 else "down") + ("-good" if good > 0 else "-bad")
    arrow = "▲" if sign > 0 else "▼" if sign < 0 else "■"
    num = ("+" if delta > 0 else "−" if delta < 0 else "") + fmt(abs(delta), kind, unit)
    verdict = {1: " better", -1: " worse"}.get(good, "")
    pct_s = "" if pct is None else f"{'+' if pct > 0 else '−' if pct < 0 else ''}{abs(pct):,.1f}%"
    hidden = f'<span class="sr">{verdict}</span>' if verdict else ""
    return (f'<td class="{cls}" title="{verdict.strip()}">{arrow} {num}{hidden}</td>'
            f'<td class="{cls}">{pct_s}</td>')


def compare_html(result: dict, max_rows: int = 40) -> str:
    a, b = result["a"]["source"].replace("Source: ", ""), result["b"]["source"].replace("Source: ", "")
    out = [_TABLE_CSS, '<div class="cmp">', f"<h4>Comparison — {html.escape(a)} → {html.escape(b)}</h4>"]
    if "group_ebt" in result:
        g = result["group_ebt"]
        out.append('<table><tr><th>Group EBT (M$)</th><th>' + html.escape(a) + '</th><th>' + html.escape(b) +
                   '</th><th>Change</th><th>%</th></tr><tr><td><b>Group EBT</b></td>'
                   f'<td>{fmt(g["a"])}</td><td>{fmt(g["b"])}</td>'
                   + _delta_cell(g["delta"], "Group EBT", "money", "M$") + "</tr></table>")
    if result.get("inputs"):
        out.append(f'<h4>Inputs changed ({len(result["inputs"])})</h4><table><tr><th>Input</th><th>{html.escape(a)}'
                   f'</th><th>{html.escape(b)}</th><th>Change</th><th>%</th></tr>')
        for d in result["inputs"][:max_rows]:
            fa, fb = (_plain(d["a"]), _plain(d["b"]))
            out.append(f'<tr><td><code>{html.escape(d["path"])}</code></td><td>{fa}</td><td>{fb}</td>'
                       + _delta_cell(d.get("delta"), d["path"], "money", "", d.get("pct")) + "</tr>")
        out.append("</table>")
    if result.get("outputs"):
        outs = result["outputs"]
        out.append(f'<h4>Results that moved ({len(outs)})</h4><table><tr><th>Figure</th><th>{html.escape(a)}</th>'
                   f'<th>{html.escape(b)}</th><th>Change</th><th>%</th></tr>')
        for d in outs[:max_rows]:
            kind, unit = _kind_of_figure(d["figure"])
            out.append(f'<tr><td>{html.escape(d["figure"])}</td><td>{fmt(d["a"], kind, unit)}</td>'
                       f'<td>{fmt(d["b"], kind, unit)}</td>'
                       + _delta_cell(d.get("delta"), d["figure"], kind, unit, d.get("pct")) + "</tr>")
        out.append("</table>")
        if len(outs) > max_rows:
            out.append(f'<p class="note">{len(outs) - max_rows} smaller changes not shown.</p>')
    if result.get("sourcing_change"):
        out.append(f'<p class="note">⚠ {html.escape(result["sourcing_change"]["message"])}</p>')
    out.append('<p class="note">▲/▼ green = better, red = worse; volumes and inputs are not judged.</p></div>')
    return "".join(out)


def _plain(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:,.4g}" if abs(v) < 1 else f"{v:,.2f}".rstrip("0").rstrip(".")
    return html.escape(json.dumps(v) if not isinstance(v, str) else v)


# --------------------------------------------------------------------------- #
# Trade-off heatmap
# --------------------------------------------------------------------------- #

def tradeoff_html(table: dict) -> str:
    """The billet trade-off matrix: rows = sources, columns = buyers; sequential blue by price
    (darker = dearer), the cheapest source per buyer in bold with a ✓."""
    cols = table["columns"]
    rows = [r for r in table["rows"] if r.get("source") and r["kind"] == "price"]
    vals = [v for r in rows for v in r["values"].values() if isinstance(v, (int, float))]
    lo, hi = (min(vals), max(vals)) if vals else (0, 1)
    unit = rows[0]["unit"] if rows else ""
    out = [_TABLE_CSS, '<div class="cmp">',
           f'<h4>{html.escape(table["title"])} — buyers across, sources down ({html.escape(unit)})</h4>',
           '<table class="hm"><tr><th>Source ↓ / Buyer →</th>' + "".join(f"<th>{html.escape(c)}</th>" for c in cols)
           + "</tr>"]
    for r in rows:
        out.append(f"<tr><td>{html.escape(r['label'])}</td>")
        for c in cols:
            v = r["values"].get(c)
            if not isinstance(v, (int, float)):
                out.append("<td></td>")
                continue
            step = 0 if hi == lo else round((v - lo) / (hi - lo) * (len(SEQ) - 1))
            best = c in r.get("cheapest_for", [])
            cls = ("dark-cell " if step >= 6 else "") + ("best" if best else "")
            out.append(f'<td class="{cls}" style="background:{SEQ[step]}" title="{html.escape(r["label"])} → '
                       f'{html.escape(c)}: {fmt(v, "price", unit)} {html.escape(unit)}">'
                       f'{"✓ " if best else ""}{fmt(v, "price", unit)}</td>')
        out.append("</tr>")
    out.append("</table>")
    for f in table.get("footnotes", []):
        out.append(f'<p class="note">{html.escape(f)}</p>')
    out.append(f'<p class="note">{html.escape(table["source"])} · ✓ = cheapest source for that buyer; '
               "darker = dearer.</p></div>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# Conversation → chat entries
# --------------------------------------------------------------------------- #

def _g(block, key, default=None):
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [_g(b, "text") for b in content if _g(b, "type") == "text"]


def optimizer_html(result: dict) -> str:
    """find_optimal_mix → the plan, CM now vs optimum, per company, binding constraints with
    shadow prices and the self-checks — CM deltas colour-coded (▲ green better, ▼ red worse)."""
    e = html.escape
    cm = result["cm"]
    head = ("group" if result["objective"] == "group_cm" else f"{result['company']}'s") + " contribution margin"
    out = [_TABLE_CSS, '<div class="cmp">', f"<h4>Optimal plan — {e(head)} (M$ per month)</h4>",
           "<table><tr><th>CM</th><th>Now</th><th>Optimum</th><th>Change</th><th>%</th></tr><tr><td><b>"
           f"{e(head.capitalize())}</b></td><td>{fmt(cm['current'])}</td><td>{fmt(cm['optimal'])}</td>"
           + _delta_cell(cm["delta"], "CM", "money", "M$",
                         None if not cm["current"] else 100 * cm["delta"] / abs(cm["current"])) + "</tr></table>"]
    sales = [r for r in result["plan"]["sales"] if abs(r["delta_kt"]) > 1e-9]
    if sales:
        out.append("<h4>Sales (kt per month)</h4><table><tr><th>Line</th><th>Now</th><th>Optimum</th>"
                   "<th>Change</th><th>%</th></tr>")
        for r in sales:
            _, co, prod, k = r["path"].split(".")
            label = f"{co} {prod} {'local' if k.startswith('local') else 'export'}"
            out.append(f"<tr><td>{e(label)}</td><td>{fmt(r['current_kt'], 'qty')}</td>"
                       f"<td>{fmt(r['optimal_kt'], 'qty')}</td>"
                       + _delta_cell(r["delta_kt"], label, "qty", "kt") + "</tr>")
        out.append("</table>")
    src = result["plan"]["billet_sourcing"]
    def _src(sup, share):
        return "market" if sup == "market" or share == 0 else (
            f"{sup} {share:.0%}" + (" + market" if share < 1 else ""))
    out.append(f"<h4>ERM billet sourcing</h4><p>{e(_src(src['current_supplier'], src['current_share']))} → "
               f"<b>{e(_src(src['supplier'], src['internal_share']))}</b> "
               f"({fmt(src['internal_kt'], 'qty')} kt internal, {fmt(src['market_kt'], 'qty')} kt market)</p>")
    blends = [r for r in result["plan"]["blending"] if abs(r["delta_pct"]) > 1e-9]
    if blends:
        out.append("<h4>Furnace blends (% of charge)</h4><table><tr><th>Furnace · material</th><th>Now</th>"
                   "<th>Optimum</th><th>Change</th><th></th></tr>")
        for r in blends:
            label = f"{r['furnace']} · {r['material'].replace('_', ' ')}"
            out.append(f"<tr><td>{e(label)}</td><td>{r['current_pct']:.1f}%</td><td>{r['optimal_pct']:.1f}%</td>"
                       + _delta_cell(r["delta_pct"], label, "consumption", "") + "</tr>")
        out.append("</table>")
    out.append("<h4>CM by company (M$)</h4><table><tr><th>Company</th><th>Now</th><th>Optimum</th>"
               "<th>Change</th><th>%</th></tr>")
    for r in result["by_company"]["rows"]:
        pct = None if not r["current"] else 100 * r["delta"] / abs(r["current"])
        out.append(f"<tr><td>{e(r['company'])}</td><td>{fmt(r['current'])}</td><td>{fmt(r['optimal'])}</td>"
                   + _delta_cell(r["delta"], f"{r['company']} CM", "money", "M$", pct) + "</tr>")
    out.append("</table>")
    if result["binding_constraints"]:
        out.append("<h4>Binding constraints — what one more unit is worth</h4><table><tr><th>Constraint</th>"
                   "<th>Shadow price</th></tr>")
        for b in result["binding_constraints"]:
            out.append(f"<tr><td>{e(b['description'])}</td><td>{e(b['text'].split(' (')[0])}</td></tr>")
        out.append("</table>")
    sc = result.get("self_checks") or {}
    if sc:
        c, p = sc["engine_cross_check"], sc["perturbation"]
        out.append('<p class="note">Self-checks: ✓ engine cross-check (Δ '
                   f'{abs(c["difference_usd"]):.2g} $) · ✓ integrity and every run constraint · ✓ perturbation '
                   f'({p["feasible"]} feasible ±5% moves of {p["tested"]}, none better)</p>')
    for n in result.get("notes", []):
        out.append(f'<p class="note">Note: {e(n)}</p>')
    viol = result.get("current_plan_violations") or []
    if viol:
        out.append(f'<p class="note">The current plan breaks: {e("; ".join(viol))}.</p>')
    out.append(f'<p class="note">{e(result.get("source", ""))} · not applied to the working state.</p></div>')
    return "".join(out)


def artifacts(tool: str, result: dict) -> list[dict]:
    """HTML pieces the UI shows under an answer, for one tool result."""
    if result.get("status") != "ok":
        return []
    out = []
    if tool == "compare_states":
        out.append({"kind": "compare", "html": compare_html(result)})
    if tool == "find_optimal_mix":
        out.append({"kind": "optimizer", "html": optimizer_html(result)})
    tables = [result["table"]] if "table" in result else result.get("tables", [])
    for t in tables:
        if t.get("chart"):
            out.append({"kind": "chart", "html": chart_svg(t["chart"], t.get("source", ""))})
        if tool == "get_tradeoff_matrix":
            out.append({"kind": "heatmap", "html": tradeoff_html(t)})
    if result.get("chart"):
        out.append({"kind": "chart", "html": chart_svg(result["chart"], result.get("source", ""))})
    if result.get("flow_diagram"):
        src = (result.get("tables") or [{}])[0].get("source", "")
        out.append({"kind": "flow", "html": flow_svg(result["flow_diagram"], src)})
    return out


_TOOL_LABEL = {
    "read_state": "Read model inputs", "list_states": "Listed saved states", "get_cost_sheet": "Cost sheet",
    "get_pnl": "P&L", "get_sales_report": "Sales report", "get_fixed_cost_report": "Fixed-cost report",
    "get_production_report": "Production report", "get_tradeoff_matrix": "Billet trade-off matrix",
    "update_input": "Updated the working session", "undo_last_change": "Undid the last change",
    "run_sensitivity": "Sensitivity run", "compare_states": "Compared states",
    "commit_state": "Session action", "manage_baseline_refresh": "Baseline refresh",
    "find_optimal_mix": "Optimizer",
}


def conversation(messages: list) -> list[dict]:
    """Stored messages → UI entries, in order:

        {"role": "user", "text": ...}
        {"role": "tool", "name", "label", "input", "status", "error_code", "preamble"}
        {"role": "assistant", "text": ..., "artifacts": [...]}

    Runtime headers and session notes (texts starting with "[") and thinking are not shown."""
    out: list[dict] = []
    pending: dict[str, dict] = {}            # tool_use_id → its tool entry
    turn_artifacts: list = []
    for m in messages:
        content = m["content"]
        if m["role"] == "user":
            if isinstance(content, list) and any(_g(b, "type") == "tool_result" for b in content):
                for b in content:
                    if _g(b, "type") != "tool_result":
                        continue
                    entry = pending.pop(_g(b, "tool_use_id"), None)
                    try:
                        result = json.loads(_g(b, "content")) if isinstance(_g(b, "content"), str) else {}
                    except ValueError:
                        result = {}
                    if entry is not None:
                        entry["status"] = result.get("status")
                        entry["error_code"] = result.get("error_code")
                        entry["error_message"] = result.get("error_message")
                        turn_artifacts.extend(artifacts(entry["name"], result))
                continue
            texts = [t for t in _texts(content) if t and not t.startswith("[")]
            if texts:
                out.append({"role": "user", "text": "\n".join(texts)})
                turn_artifacts = []
            continue
        texts = [t for t in _texts(content) if t]
        uses = [b for b in content if _g(b, "type") == "tool_use"] if isinstance(content, list) else []
        if uses:
            for i, u in enumerate(uses):
                entry = {"role": "tool", "name": _g(u, "name"), "label": _TOOL_LABEL.get(_g(u, "name"), _g(u, "name")),
                         "input": _g(u, "input") or {}, "status": None, "error_code": None,
                         "preamble": "\n".join(texts) if i == 0 else ""}
                pending[_g(u, "id")] = entry
                out.append(entry)
        else:
            out.append({"role": "assistant", "text": "\n".join(texts), "artifacts": turn_artifacts})
            turn_artifacts = []
    return out
