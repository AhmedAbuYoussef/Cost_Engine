"""
The state schema: what a valid model state looks like, dotted-path access, and the
structured errors every tool returns (system prompt §3).

The schema is the corrected baseline's own shape (``model_initial_state.json``): a
valid state has exactly the same sections and keys, a number wherever the baseline
has a number, and values inside the ranges below.  Paths that name a production step
a company does not have (ESR HRC, EFS DRI…) are reported as
``structural_non_existence``, not as a typo.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(HERE, "model_initial_state.json")

COMPANIES = ("EZDK", "EFS", "ERM", "ESR")
PRODUCTS = ("Rebar", "Wire Rod", "HRC")

# Who produces what (system prompt §5).
PRODUCTION_MATRIX = {
    "DRI": {"EZDK", "ERM"},
    "Billet": {"EZDK", "EFS", "ESR"},
    "Rebar": {"EZDK", "EFS", "ERM", "ESR"},
    "Wire Rod": {"EZDK"},
    "HRC": {"EZDK", "EFS"},
}
STAGE_LABEL = {"DRI": "DRI", "Billet": "billet", "Rebar": "rebar", "Wire Rod": "wire rod", "HRC": "HRC"}

READ_ONLY_ROOTS = ("meta", "month_label", "rules_profile")
FREE_FORM = ("meta", "billet.tradeoff_overrides")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SOURCING_RE = re.compile(r"^(market|min|(vc|offer):(EZDK|EFS|ESR))$")

ERROR_CODES = (
    "missing_required_arg", "invalid_path", "structural_non_existence",
    "integrity_check_failed", "capacity_exceeded", "infeasible_optimization",
    "baseline_not_found", "scenario_not_found", "state_not_found", "baseline_exists",
    "permission_denied", "schema_validation_error", "nothing_to_undo",
)


class ModelError(Exception):
    """A refusal in the system prompt's error format."""

    def __init__(self, code: str, message: str, field: str | None = None, expected=None):
        assert code in ERROR_CODES, code
        super().__init__(message)
        self.code, self.message, self.field, self.expected = code, message, field, expected

    def to_dict(self) -> dict:
        d = {"status": "error", "error_code": self.code, "error_message": self.message}
        if self.field is not None:
            d["field"] = self.field
        if self.expected is not None:
            d["expected"] = self.expected
        return d


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def split(path: str) -> list:
    if not isinstance(path, str) or not path or path.startswith(".") or path.endswith(".") or ".." in path:
        raise ModelError("invalid_path", f"malformed path {path!r}", field=str(path))
    return path.split(".")


def get(state: dict, path: str):
    if path == "*":
        return copy.deepcopy(state)
    node = state
    for i, seg in enumerate(split(path)):
        if not isinstance(node, dict) or seg not in node:
            raise missing_path_error(path)
        node = node[seg]
    return copy.deepcopy(node)


def exists(state: dict, path: str) -> bool:
    node = state
    for seg in path.split("."):
        if not isinstance(node, dict) or seg not in node:
            return False
        node = node[seg]
    return True


def set_value(state: dict, path: str, value) -> None:
    segs = split(path)
    node = state
    for seg in segs[:-1]:
        node = node[seg]
    node[segs[-1]] = copy.deepcopy(value)


def is_leaf(v) -> bool:
    """Numbers, strings, None — and the small amount dicts {'le': x} / {'usd': x}."""
    return not isinstance(v, dict) or _is_money(v)


def _is_money(v) -> bool:
    return isinstance(v, dict) and len(v) == 1 and next(iter(v)) in ("le", "usd")


def leaves(state: dict, prefix: str = "") -> dict:
    """{dotted path: leaf value} for every input in the state."""
    out = {}
    for k, v in state.items():
        p = f"{prefix}{k}"
        if is_leaf(v) or (isinstance(v, dict) and not v):
            out[p] = v
        else:
            out.update(leaves(v, p + "."))
    return out


# --------------------------------------------------------------------------- #
# Structural non-existence
# --------------------------------------------------------------------------- #

_SHEET_PRODUCT = {"Rebar": "Rebar", "Rolling": "Rebar", "Wire": "Wire Rod", "Flat": "HRC"}


def _company_and_stage(segs: list):
    """Best reading of which (company, production step) a path talks about."""
    s0 = segs[0]
    g = lambda i: segs[i] if len(segs) > i else None
    if s0 == "dri":
        return g(1), "DRI"
    if s0 == "billet" and g(1) == "companies":
        return g(2), "Billet"
    if s0 == "flat":
        return g(1), "HRC"
    if s0 in ("sales",) or (s0 == "pnl" and g(1) == "export_expense_usd_t"):
        co, prod = (g(1), g(2)) if s0 == "sales" else (g(2), g(3))
        return co, prod if prod in PRODUCTION_MATRIX else None
    if s0 == "finishing_yield_pct":
        return g(2), g(1) if g(1) in PRODUCTION_MATRIX else None
    if s0 == "detail" and g(1):
        parts = g(1).split(" ", 1)
        return parts[0], _SHEET_PRODUCT.get(parts[1] if len(parts) > 1 else "")
    if s0 == "capacity_ceilings":
        if g(1) == "dri":
            return g(2), "DRI"
        if g(1) == "finished":
            return g(2), g(3) if g(3) in PRODUCTION_MATRIX else None
    return None, None


def missing_path_error(path: str) -> ModelError:
    segs = path.split(".")
    co, stage = _company_and_stage(segs)
    if co in COMPANIES and stage and co not in PRODUCTION_MATRIX[stage]:
        who = [c for c in COMPANIES if c in PRODUCTION_MATRIX[stage]]
        why = {"DRI": " — it receives DRI from ERM" if co in ("EFS", "ESR") else "",
               "Billet": " — ERM has no furnace and buys its billets" if co == "ERM" else ""}.get(stage, "")
        return ModelError("structural_non_existence",
                          f"{co} does not produce {STAGE_LABEL[stage]}{why}. "
                          f"Only {' and '.join(who) if len(who) < 3 else ', '.join(who)} do.",
                          field=path)
    return ModelError("invalid_path", f"no input at {path!r}", field=path)


def check_writable(path: str) -> None:
    if split(path)[0] in READ_ONLY_ROOTS:
        raise ModelError("invalid_path", f"{path!r} is managed by the system and cannot be edited",
                         field=path)


# --------------------------------------------------------------------------- #
# Scope fan-out (update_input scope = all_companies / all_products)
# --------------------------------------------------------------------------- #

_SHEET_WORD = {"Rebar": "Rebar", "Wire Rod": "Wire", "HRC": "Flat"}


def _substitute(segs: list, names: tuple, words: dict) -> list:
    """Every variant of ``segs`` with the first company/product token swapped for each of
    ``names``.  A token is a whole segment ("EZDK") or a word inside one ("EZDK Rebar");
    ``words`` maps sheet words ("Flat") to the product they stand for ("HRC")."""
    for i, seg in enumerate(segs):
        if seg in names:
            return [segs[:i] + [n] + segs[i + 1:] for n in names]
        parts = seg.split(" ")
        for j, w in enumerate(parts):
            if words.get(w, w) in names:
                # inside a sheet name ("EZDK Rebar") products go by their sheet word ("Flat")
                swap = (lambda n: _SHEET_WORD.get(n, n)) if words and len(parts) > 1 else (lambda n: n)
                return [segs[:i] + [" ".join(parts[:j] + [swap(n)] + parts[j + 1:])] + segs[i + 1:]
                        for n in names]
    return []


def expand_scope(state: dict, path: str, scope: str) -> list:
    if scope in (None, "single"):
        return [path]
    segs = split(path)
    if scope == "all_companies":
        variants = _substitute(segs, COMPANIES, {})
    elif scope == "all_products":
        variants = _substitute(segs, PRODUCTS, {"Wire": "Wire Rod", "Flat": "HRC"})
    else:
        raise ModelError("schema_validation_error", f"unknown scope {scope!r}", field="scope",
                         expected=["single", "all_companies", "all_products"])
    if not variants:
        raise ModelError("invalid_path", f"scope {scope} needs a "
                         f"{'company' if scope == 'all_companies' else 'product'} in the path",
                         field=path)
    targets = [".".join(v) for v in variants]
    found = [t for t in dict.fromkeys(targets) if exists(state, t)]
    return found


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def load_template() -> dict:
    with open(TEMPLATE_PATH) as f:
        return json.load(f)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _range_problem(path: str, v: float):
    key = path.rsplit(".", 1)[-1]
    if "byproduct_pct" in key:
        return None if -1 <= v <= 0 else "a byproduct share between -1 and 0"
    if v < 0:
        return "a value ≥ 0"
    if key.endswith("_yield_pct") or path.startswith("finishing_yield_pct."):
        return None if 0 < v <= 100 else "a yield in % (0–100]"
    if ".blend_pct." in path or ".distribution_pct." in path:
        frac = path.startswith("detail.")
        top = 1 if frac else 100
        return None if v <= top else f"a share ≤ {top}"
    if ".feed_share." in path or path.startswith("policy_floors."):
        return None if v <= 1 else "a share between 0 and 1"
    if key == "mrmr":
        return None if v >= 1 else "MRMR ≥ 1"
    if key in ("fx_egp_per_usd", "tradeoff_ratio"):
        return None if v > 0 else "a value > 0"
    return None


def _validate(value, tmpl, path: str, problems: list):
    if len(problems) >= 20:
        return
    if path in FREE_FORM:
        return
    if isinstance(tmpl, dict) and not _is_money(tmpl):
        if path == "billet.tradeoff_overrides":
            return
        if not isinstance(value, dict) or _is_money(value):
            problems.append((path, "a section (object)", value))
            return
        for k in tmpl.keys() - value.keys():
            problems.append((f"{path}.{k}" if path else k, "present (missing)", None))
        for k in value.keys() - tmpl.keys():
            problems.append((f"{path}.{k}" if path else k, "no such input", value[k]))
        for k in tmpl.keys() & value.keys():
            _validate(value[k], tmpl[k], f"{path}.{k}" if path else k, problems)
        return
    if isinstance(tmpl, str):
        rules = {"sourcing.ERM_rebar_billet": (SOURCING_RE, "market | min | vc:<CO> | offer:<CO>"),
                 "rules_profile": (re.compile(r"^corrected$"), "corrected"),
                 "month_label": (MONTH_RE, "YYYY-MM")}
        rx, want = rules.get(path, (None, "text"))
        if not isinstance(value, str) or (rx and not rx.match(value)):
            problems.append((path, want, value))
        return
    # numeric leaf (template: number, money dict, or null)
    if tmpl is None and value is None:
        return
    amount = value
    if _is_money(value):
        if not _is_money(tmpl):
            problems.append((path, "a plain number", value))
            return
        amount = next(iter(value.values()))
    if not _num(amount):
        problems.append((path, "a finite number", value))
        return
    why = _range_problem(path, amount)
    if why:
        problems.append((path, why, value))


def validate(state: dict, template: dict | None = None) -> None:
    """Raise schema_validation_error listing what is wrong (first problem as ``field``)."""
    template = template if template is not None else load_template()
    problems: list = []
    _validate(state, template, "", problems)
    if problems:
        p, want, got = problems[0]
        more = f" (+{len(problems) - 1} more: " + "; ".join(x[0] for x in problems[1:6]) + ")" \
            if len(problems) > 1 else ""
        raise ModelError("schema_validation_error",
                         f"{p}: expected {want}, got {got!r}{more}", field=p, expected=want)
