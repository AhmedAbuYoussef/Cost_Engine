"""
Step 8 — ``find_optimal_mix`` (system prompt Tool 12; Appendix D.1–D.4).  The formulation, and
why a linear program is exact for this model, is in OPTIMIZER_LP.md.

    result = optimize(state, objective="group_cm", run_constraints={"local_market_ceilings": {"HRC": 120}})

How it stays honest:

* **Coefficients come from the engine.**  Every relationship the LP needs (CM per ton sold,
  CM per ton of each charge material, furnace charge per ton sold, ERM billets per ton of
  rebar) is read off ``cost_engine.compute_all`` by exact finite differences, never re-derived
  by hand.  The LP therefore *is* the engine, linearised where the engine is linear.
* **Three self-checks on every run (D.4)**, any failure → an error, never a number:
  the engine's CM of the proposed plan equals the LP's to machine precision; the plan passes
  every integrity check and every run constraint, re-measured on the engine's own outputs;
  no feasible ±5% move of a single free variable beats it.
* **Infeasible → a named conflict** (a minimal set of constraint groups), no number, nothing
  relaxed.
* **The plan is not applied.**  ``changes`` is ready for ``update_input`` if the user agrees.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy.optimize import linprog

import cost_engine as ce
import state_schema as schema
from state_schema import ModelError

MATERIALS = ("dri", "local_scrap", "imported_scrap")
_DETAIL_KEY = {"dri": "dri", "local_scrap": "local", "imported_scrap": "imported"}
SUPPLIERS = ce.BILLET_PRODUCERS
FURNACES = {          # name → (blend path, detail sheet, company)
    "EZDK long": ("billet.companies.EZDK.blend_pct", "EZDK Rebar", "EZDK"),
    "EFS long": ("billet.companies.EFS.blend_pct", "EFS Rebar", "EFS"),
    "ESR long": ("billet.companies.ESR.blend_pct", "ESR Rebar", "ESR"),
    "EZDK flat": ("flat.EZDK.blend_pct", "EZDK Flat", "EZDK"),
    "EFS flat": ("flat.EFS.blend_pct", "EFS Flat", "EFS"),
}
GROUPS = ("local_sales", "export_sales", "billet_sourcing", "blending")
SHARE_PATH = "sourcing.ERM_internal_share"
PERTURBATION = 0.05
REL_TOL = 1e-9            # engine cross-check: |LP − engine| ≤ REL_TOL · max(1, |CM|)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _sales_paths(state):
    return [f"sales.{c}.{p}.{k}" for c in ce.COMPANIES for p in state["sales"].get(c, {})
            for k in ("local_kt", "export_kt")]


def _node(state, path):
    """The live dict at ``path`` (``schema.get`` returns a copy, which must not be edited)."""
    node = state
    for seg in schema.split(path):
        node = node[seg]
    return node


def _objective_value(outputs, objective, company):
    con = outputs["consolidated"]["usd_monthly"]
    cm = con["consolidated"]["contribution_margin"] if objective == "group_cm" else \
        con["companies"][company]["contribution_margin"]
    return cm * 1e6                                     # $ per month


def _dri_plants(rules):
    erm = ["EFS long", "ESR long"] + (["EFS flat"] if rules["erm_dri_full_volume"] else [])
    return {"EZDK": ["EZDK long", "EZDK flat"], "ERM": erm}


def _fmt_t(x):
    return f"{x:,.0f} t"


class _Row:
    """One linear row:  coef · x  (<= | ==)  rhs, tagged with the group it belongs to."""

    def __init__(self, coef, op, rhs, group, label, kind="other", meta=None):
        self.coef, self.op, self.rhs, self.group, self.label = coef, op, rhs, group, label
        self.kind, self.meta = kind, meta or {}


# --------------------------------------------------------------------------- #
# Run set-up: constraints and free variables
# --------------------------------------------------------------------------- #

def _number(v, field, allow_none=False):
    """A run-constraint value: a finite number ≥ 0 (or None where 'no limit' is allowed)."""
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise ModelError("schema_validation_error", f"{field} must be a number ≥ 0, got {v!r}", field=field,
                         expected="a number ≥ 0")
    return float(v)


def _run_settings(state, run_constraints):
    rc = dict(run_constraints or {})
    keys = ["capacity_ceilings", "policy_floors", "local_market_ceilings", "blend_limits", "additional_constraints"]
    unknown = set(rc) - set(keys)
    if unknown:
        raise ModelError("schema_validation_error", f"unknown run_constraints {sorted(unknown)}",
                         field="run_constraints", expected=keys)
    caps = copy.deepcopy(state["capacity_ceilings"])
    over = rc.get("capacity_ceilings") or {}
    for co, v in (over.get("dri") or {}).items():
        if co not in caps["dri"]:
            raise schema.missing_path_error(f"capacity_ceilings.dri.{co}")
        caps["dri"][co] = _number(v, f"capacity_ceilings.dri.{co}")
    for co, prods in (over.get("finished") or {}).items():
        for prod, v in prods.items():
            if prod not in caps["finished"].get(co, {}):
                raise schema.missing_path_error(f"capacity_ceilings.finished.{co}.{prod}")
            caps["finished"][co][prod] = _number(v, f"capacity_ceilings.finished.{co}.{prod}")
    floors = dict(state["policy_floors"]["local_share_min"])
    for prod, v in ((rc.get("policy_floors") or {}).get("local_share_min") or {}).items():
        if prod not in floors:
            raise ModelError("invalid_path", f"no policy floor for {prod!r}", field=prod, expected=sorted(floors))
        v = _number(v, f"policy_floors.local_share_min.{prod}")
        if v > 1:
            raise ModelError("schema_validation_error", f"policy floor for {prod} must be within 0..1",
                             field=f"policy_floors.local_share_min.{prod}")
        floors[prod] = v
    markets = {p: state["total_local_market_kt"].get(p) for p in ("Rebar", "Wire Rod", "HRC")}
    for prod, v in (rc.get("local_market_ceilings") or {}).items():
        if prod not in markets:
            raise ModelError("invalid_path", f"no local market for {prod!r}", field=prod, expected=sorted(markets))
        markets[prod] = _number(v, f"local_market_ceilings.{prod}", allow_none=True)
    if (rc.get("local_market_ceilings") or {}).get("HRC") is None:
        return None                                    # HRC must be given fresh every run
    blend = _blend_limits(state, rc.get("blend_limits"))
    extra = rc.get("additional_constraints") or []
    if not isinstance(extra, list):
        raise ModelError("schema_validation_error", "additional_constraints must be a list",
                         field="run_constraints.additional_constraints")
    return {"capacity": caps, "floors": floors, "markets": markets, "blend": blend, "extra": extra}


def _blend_limits(state, override):
    """The state's standing charge-mix limits, with this run's overrides merged in.  An override
    has the same shape: {"furnaces": {<furnace>: {<material>: {"min_pct", "max_pct"}}},
    "local_scrap_supply_kt": kt | None (None = no supply cap this run)}."""
    lim = copy.deepcopy(state.get("blend_limits") or {"furnaces": {}, "local_scrap_supply_kt": None})
    over = override or {}
    if not isinstance(over, dict) or set(over) - {"furnaces", "local_scrap_supply_kt"}:
        raise ModelError("schema_validation_error", "blend_limits is {furnaces: {…}, local_scrap_supply_kt}",
                         field="run_constraints.blend_limits")
    for f, mats in (over.get("furnaces") or {}).items():
        if f not in FURNACES:
            raise ModelError("invalid_path", f"no furnace {f!r}", field=f, expected=list(FURNACES))
        for k, b in mats.items():
            if k not in MATERIALS or not isinstance(b, dict) or set(b) - {"min_pct", "max_pct"}:
                raise ModelError("invalid_path", f"blend limit {f}.{k} must be {{min_pct, max_pct}} for "
                                 f"one of {list(MATERIALS)}", field=f"{f}.{k}")
            cur = lim["furnaces"].setdefault(f, {}).setdefault(k, {"min_pct": 0.0, "max_pct": 100.0})
            cur.update({x: _number(v, f"blend_limits.furnaces.{f}.{k}.{x}") for x, v in b.items()})
    if "local_scrap_supply_kt" in over:
        v = over["local_scrap_supply_kt"]
        lim["local_scrap_supply_kt"] = _number(v, "blend_limits.local_scrap_supply_kt", allow_none=True)
    for f, mats in lim["furnaces"].items():
        for k, b in mats.items():
            if not 0 <= b["min_pct"] <= b["max_pct"] <= 100:
                raise ModelError("schema_validation_error", f"blend limit {f} {k}: need 0 ≤ min ≤ max ≤ 100, "
                                 f"got {b['min_pct']}–{b['max_pct']}", field=f"blend_limits.furnaces.{f}.{k}")
    return lim


def _free_set(state, free_variables):
    """→ (free sales paths, free furnaces, sourcing free?)"""
    sales = _sales_paths(state)
    if free_variables is None:
        free_variables = list(GROUPS)
    if not isinstance(free_variables, list):
        raise ModelError("schema_validation_error", "free_variables must be a list", field="free_variables")
    fs, ff, src = set(), set(), False
    for v in free_variables:
        if v == "local_sales":
            fs |= {p for p in sales if p.endswith("local_kt")}
        elif v == "export_sales":
            fs |= {p for p in sales if p.endswith("export_kt")}
        elif v == "billet_sourcing" or v in ("sourcing.ERM_rebar_billet", SHARE_PATH):
            src = True
        elif v == "blending":
            ff |= set(FURNACES)
        elif v in sales:
            fs.add(v)
        elif v in FURNACES:
            ff.add(v)
        elif any(v == FURNACES[f][0] for f in FURNACES):
            ff.add(next(f for f in FURNACES if FURNACES[f][0] == v))
        else:
            raise ModelError("invalid_path", f"{v!r} is not something the optimizer can choose",
                             field="free_variables",
                             expected=list(GROUPS) + ["sales.<CO>.<product>.local_kt|export_kt",
                                                      "<blend path>", "sourcing.ERM_rebar_billet"])
    return [p for p in sales if p in fs], [f for f in FURNACES if f in ff], src


def _decouple(free, objective, company, candidates, current, explicit):
    """With a company objective, ERM pays its supplier an intercompany price built from the
    supplier's own billet cost, i.e. from the supplier's long-line blend.  (Billets bought) ×
    (blend-dependent price) is not linear, so that blend cannot be free in the same run.  The
    default free set holds it (and says so); an explicit request to free it is refused."""
    sales, furnaces, src = free
    if objective != "company_cm":
        return free, []
    buying = candidates if src else ([current["supplier"]] if current["supplier"] and current["share"] > 0 else [])
    coupled = [f"{s} long" for s in buying if company in ("ERM", s) and f"{s} long" in furnaces]
    if not coupled:
        return free, []
    if explicit:
        raise ModelError("schema_validation_error",
                         f"with company_cm for {company}, ERM's intercompany billet price follows "
                         f"{', '.join(coupled)} blending, which makes the problem non-linear. Hold that blend "
                         "(leave it out of free_variables), hold the billet sourcing, or use group_cm "
                         "(where intercompany prices cancel).", field="free_variables",
                         expected=[f for f in furnaces if f not in coupled])
    kept = [f for f in furnaces if f not in coupled]
    note = (f"{', '.join(coupled)} blending is held at its current value: with {company}'s CM as the objective, "
            "the intercompany billet price ERM pays follows that blend, which would make the problem non-linear.")
    return (sales, kept, src), [note]


# --------------------------------------------------------------------------- #
# Coefficients, read from the engine
# --------------------------------------------------------------------------- #

class _Linearisation:
    """Engine-derived affine pieces around a reference point R (all sales ≥ 1 kt, market
    sourcing, current blends).  Exact because the engine is affine in each of them (§1)."""

    def __init__(self, state, objective, company):
        self.state, self.objective, self.company = state, objective, company
        self.rules = ce.rules_for(state)
        self.sales = _sales_paths(state)
        R = copy.deepcopy(state)
        for p in self.sales:
            schema.set_value(R, p, max(float(schema.get(state, p)), 1.0))
        R["sourcing"]["ERM_rebar_billet"] = "market"
        self.R = R
        o = ce.compute_all(R)
        self.cm_R = _objective_value(o, objective, company)
        self.sc_R = self._sc(o)
        self.B_R = o["sourcing"]["billets_t"]
        self.q_R = np.array([float(schema.get(R, p)) for p in self.sales])
        self.b_R = {f: {k: float(schema.get(R, FURNACES[f][0])[k]) for k in MATERIALS} for f in FURNACES}
        h = 1.0                                               # kt; exact for affine functions
        self.a = np.zeros(len(self.sales))                    # $/kt sold, at fixed blends, I fixed
        self.sigma = {f: np.zeros(len(self.sales)) for f in FURNACES}   # charge t per kt sold
        self.beta = np.zeros(len(self.sales))                 # ERM billets t per kt sold
        for i, p in enumerate(self.sales):
            S = copy.deepcopy(R)
            schema.set_value(S, p, self.q_R[i] + h)
            os_ = ce.compute_all(S)
            self.a[i] = (_objective_value(os_, objective, company) - self.cm_R) / h
            sc = self._sc(os_)
            for f in FURNACES:
                self.sigma[f][i] = (sc[f] - self.sc_R[f]) / h
            self.beta[i] = (os_["sourcing"]["billets_t"] - self.B_R) / h
        self.w = {f: {} for f in FURNACES}                    # $ per kt of material k charged in f
        for f, (bpath, _, _) in FURNACES.items():
            for k in MATERIALS:
                S = copy.deepcopy(R)
                _node(S, bpath)[k] = self.b_R[f][k] + 1.0       # +1 percentage point
                d = _objective_value(ce.compute_all(S), objective, company) - self.cm_R
                self.w[f][k] = d * 100 * 1000 / self.sc_R[f]
        self.psi = {f: sum(self.b_R[f].values()) / 100 for f in FURNACES}
        self.by_supplier = {}

    @staticmethod
    def _sc(outputs):
        return {f: outputs["detail"][sheet]["s1.solid_charge_t"] for f, (_, sheet, _) in FURNACES.items()}

    def supplier(self, s):
        """CM and furnace charge per kt of ERM billets moved from the market to supplier s."""
        if s not in self.by_supplier:
            S = copy.deepcopy(self.R)
            S["sourcing"]["ERM_rebar_billet"] = f"offer:{s}"
            o = ce.compute_all(S)
            Bk = self.B_R / 1000
            sc = self._sc(o)
            self.by_supplier[s] = {"a_I": (_objective_value(o, self.objective, self.company) - self.cm_R) / Bk,
                                   "sigma_I": {f: (sc[f] - self.sc_R[f]) / Bk for f in FURNACES}}
        return self.by_supplier[s]


# --------------------------------------------------------------------------- #
# The LP for one internal supplier
# --------------------------------------------------------------------------- #

class _Model:
    def __init__(self, lin: _Linearisation, settings, free, supplier, current):
        self.lin, self.settings, self.supplier = lin, settings, supplier
        free_sales, free_furnaces, src_free = free
        self.free_sales, self.free_furnaces, self.src_free = free_sales, free_furnaces, src_free
        n_q = len(lin.sales)
        self.iq = {p: i for i, p in enumerate(lin.sales)}
        self.iY = {}
        idx = n_q
        for f in FURNACES:
            for k in MATERIALS:
                self.iY[(f, k)] = idx
                idx += 1
        self.iI, self.iM = idx, idx + 1
        self.n = idx + 2
        sup = lin.supplier(supplier)
        self.sup = sup

        # affine expressions as (coef vector, constant)
        def zero():
            return np.zeros(self.n)

        def sc_expr(f):                                   # furnace charge, t
            c = zero()
            c[:n_q] = lin.sigma[f]
            c[self.iI] = sup["sigma_I"][f]
            return c, lin.sc_R[f] - lin.sigma[f] @ lin.q_R
        self.sc_expr = {f: sc_expr(f) for f in FURNACES}
        cB = zero()
        cB[:n_q] = lin.beta
        self.B_expr = (cB, lin.B_R - lin.beta @ lin.q_R)   # ERM billets, t

        # objective  CM = CM_R + a·(q − q_R) + a_I·I + Σ w_fk (Y_fk − b_R,fk/100 · SC_f/1000)
        c = zero()
        c[:n_q] = lin.a
        c[self.iI] = sup["a_I"]
        const = lin.cm_R - lin.a @ lin.q_R
        for f in FURNACES:
            sc_c, sc_k = self.sc_expr[f]
            for k in MATERIALS:
                w = lin.w[f][k]
                c[self.iY[(f, k)]] += w
                c -= w * lin.b_R[f][k] / 100 * sc_c / 1000
                const -= w * lin.b_R[f][k] / 100 * sc_k / 1000
        self.c, self.c0 = c, const

        rows: list[_Row] = []
        caps, floors, markets = settings["capacity"], settings["floors"], settings["markets"]
        # furnace balance (structural)
        for f in FURNACES:
            sc_c, sc_k = self.sc_expr[f]
            coef = -lin.psi[f] * sc_c / 1000
            for k in MATERIALS:
                coef[self.iY[(f, k)]] += 1.0
            rows.append(_Row(coef, "==", lin.psi[f] * sc_k / 1000, "structure", f"{f} charge balance"))
        # ERM billets (structural): I + M = B(q)
        coef = -self.B_expr[0] / 1000
        coef[self.iI] += 1
        coef[self.iM] += 1
        rows.append(_Row(coef, "==", self.B_expr[1] / 1000, "structure", "ERM billet balance"))
        # 1 DRI capacity
        for plant, furnaces in _dri_plants(lin.rules).items():
            coef = zero()
            for f in furnaces:
                coef[self.iY[(f, "dri")]] = 1.0
            cap = caps["dri"][plant]
            rows.append(_Row(coef, "<=", cap / 1000, f"DRI capacity {plant}",
                             f"{plant} DRI ≤ {_fmt_t(cap)}", "capacity", {"per": "t"}))
        # 2 finished capacity
        for co, prods in caps["finished"].items():
            for prod, cap in prods.items():
                coef = zero()
                for k in ("local_kt", "export_kt"):
                    coef[self.iq[f"sales.{co}.{prod}.{k}"]] = 1.0
                rows.append(_Row(coef, "<=", cap / 1000, f"{prod} capacity {co}",
                                 f"{co} {prod} production ≤ {_fmt_t(cap)}", "capacity", {"per": "t"}))
        # 3 policy floors:  φ Σ(L+X) − ΣL ≤ 0
        for prod, phi in floors.items():
            coef = zero()
            tot = 0
            for co in ce.COMPANIES:
                if prod in lin.state["sales"].get(co, {}):
                    coef[self.iq[f"sales.{co}.{prod}.local_kt"]] += phi - 1
                    coef[self.iq[f"sales.{co}.{prod}.export_kt"]] += phi
                    tot += 1
            if tot:
                rows.append(_Row(coef, "<=", 0.0, f"policy floor {prod}",
                                 f"{prod}: local sales ≥ {phi:.0%} of group {prod} production", "floor",
                                 {"product": prod}))
        # 4 local market ceilings
        for prod, m in markets.items():
            if m is None:
                continue
            coef = zero()
            for co in ce.COMPANIES:
                if prod in lin.state["sales"].get(co, {}):
                    coef[self.iq[f"sales.{co}.{prod}.local_kt"]] = 1.0
            rows.append(_Row(coef, "<=", m, f"local market ceiling {prod}",
                             f"{prod}: group local sales ≤ {m:,.1f} kt (local market)", "market", {"per": "t"}))
        # 5b charge-mix limits (% of the furnace's solid charge) and the group's local scrap supply
        bl = settings["blend"]
        for f, mats in bl["furnaces"].items():
            sc_c, sc_k = self.sc_expr[f]
            for k, b in mats.items():
                for side, pct in (("min", b["min_pct"]), ("max", b["max_pct"])):
                    if (side == "min" and pct <= 0) or (side == "max" and pct >= 100):
                        continue                              # no limit on that side
                    sgn = -1 if side == "min" else 1          # min: −(Y − m·SC) ≤ 0
                    coef = -sgn * (pct / 100) * sc_c / 1000
                    coef[self.iY[(f, k)]] += sgn
                    label = f"{f} {k.replace('_', ' ')} {'≥' if side == 'min' else '≤'} {pct:g}% of charge"
                    rows.append(_Row(coef, "<=", sgn * (pct / 100) * sc_k / 1000,
                                     f"blend limit: {label}", label, "blend", {"furnace": f, "side": side}))
        if bl.get("local_scrap_supply_kt") is not None:
            coef = zero()
            for f in FURNACES:
                coef[self.iY[(f, "local_scrap")]] = 1.0
            sup = bl["local_scrap_supply_kt"]
            rows.append(_Row(coef, "<=", sup, "local scrap supply",
                             f"group local scrap ≤ {sup:,.1f} kt (what the market can supply)", "capacity"))
        # 7 locks
        for p in lin.sales:
            if p not in free_sales:
                coef = zero()
                coef[self.iq[p]] = 1.0
                v = float(schema.get(lin.state, p))
                rows.append(_Row(coef, "==", v, f"held fixed: {p}", f"{p} = {v:,.3f} kt (not free)", "lock"))
        for f in FURNACES:
            if f not in free_furnaces:
                sc_c, sc_k = self.sc_expr[f]
                for k in MATERIALS:
                    b = current["blends"][f][k] / 100
                    coef = -b * sc_c / 1000
                    coef[self.iY[(f, k)]] += 1.0
                    rows.append(_Row(coef, "==", b * sc_k / 1000, f"held fixed: {f} blend",
                                     f"{f} blend kept at {current['blends'][f][k]:.2f}% {k}", "lock"))
        if not src_free:
            share = current["share"] if current["supplier"] == supplier else 0.0
            coef = -share * self.B_expr[0] / 1000
            coef[self.iI] += 1.0
            rows.append(_Row(coef, "==", share * self.B_expr[1] / 1000, "held fixed: ERM billet sourcing",
                             f"ERM internal billet share kept at {share:.0%}", "lock"))
        # 8 additional constraints
        for i, ac in enumerate(settings["extra"]):
            rows += self._extra_rows(i, ac)
        self.rows = rows

    def _extra_rows(self, i, ac):
        if not isinstance(ac, dict) or "variable" not in ac or not ({"min", "max"} & set(ac)):
            raise ModelError("schema_validation_error",
                             'each additional constraint is {"variable": <path>, "min": x, "max": y}',
                             field=f"additional_constraints[{i}]")
        var, out = ac["variable"], []
        for side in ("min", "max"):
            if ac.get(side) is None:
                continue
            v = ac[side]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ModelError("schema_validation_error", f"additional_constraints[{i}].{side} must be a number",
                                 field=f"additional_constraints[{i}].{side}")
            v = float(v)
            op_sign = -1 if side == "min" else 1                  # min: −expr ≤ −v
            label = f"{var} {'≥' if side == 'min' else '≤'} {v:g}"
            group = f"additional: {label}"
            if var in self.iq:
                coef = np.zeros(self.n)
                coef[self.iq[var]] = op_sign
                out.append(_Row(coef, "<=", op_sign * v, group, label, "extra"))
            elif var == SHARE_PATH:
                cB, kB = self.B_expr
                coef = -op_sign * v * cB / 1000
                coef[self.iI] += op_sign
                out.append(_Row(coef, "<=", op_sign * v * kB / 1000, group, label, "extra"))
            else:
                hit = [(f, k) for f, (bp, _, _) in FURNACES.items() for k in MATERIALS if var == f"{bp}.{k}"]
                if not hit:
                    raise ModelError("invalid_path", f"cannot constrain {var!r}", field=var,
                                     expected=["sales.<CO>.<product>.local_kt|export_kt",
                                               "<blend path>.<material>", SHARE_PATH])
                f, k = hit[0]
                sc_c, sc_k = self.sc_expr[f]
                coef = -op_sign * (v / 100) * sc_c / 1000
                coef[self.iY[(f, k)]] += op_sign
                out.append(_Row(coef, "<=", op_sign * (v / 100) * sc_k / 1000, group, label, "extra"))
        return out

    def solve(self, rows=None):
        rows = self.rows if rows is None else rows
        ub = [r for r in rows if r.op == "<="]
        eq = [r for r in rows if r.op == "=="]
        res = linprog(-self.c,
                      A_ub=np.array([r.coef for r in ub]) if ub else None,
                      b_ub=np.array([r.rhs for r in ub]) if ub else None,
                      A_eq=np.array([r.coef for r in eq]) if eq else None,
                      b_eq=np.array([r.rhs for r in eq]) if eq else None,
                      bounds=[(0, None)] * self.n, method="highs")
        return res, ub, eq

    def feasible(self, rows):
        res, _, _ = self.solve(rows)
        return res.status == 0 or res.status == 3     # 3 = unbounded, still feasible


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def _current(state):
    o = ce.compute_all(state)
    src = o["sourcing"]
    return {"outputs": o, "supplier": None if src["supplier"] == "market" else src["supplier"],
            "share": src["internal_share"],
            "blends": {f: {k: float(schema.get(state, FURNACES[f][0])[k]) for k in MATERIALS} for f in FURNACES}}


def optimize(state, objective="group_cm", company=None, free_variables=None, run_constraints=None,
             source="Source: working state", check=True):
    if objective not in ("group_cm", "company_cm"):
        raise ModelError("schema_validation_error", "objective is group_cm or company_cm", field="objective",
                         expected=["group_cm", "company_cm"])
    if objective == "company_cm" and company not in ce.COMPANIES:
        raise ModelError("missing_required_arg", "company_cm needs 'company'", field="company",
                         expected=list(ce.COMPANIES))
    settings = _run_settings(state, run_constraints)
    free = _free_set(state, free_variables)            # bad arguments are reported before asking for more
    if settings is None:
        return {"status": "needs_input", "field": "run_constraints.local_market_ceilings.HRC",
                "message": "The optimizer needs this month's total local HRC market (kt). The state does "
                           "not store it; it is asked at every run."}
    current = _current(state)
    if free[2]:
        candidates = list(SUPPLIERS)
    else:
        candidates = [current["supplier"] or SUPPLIERS[0]]
    free, notes = _decouple(free, objective, company, candidates, current, explicit=free_variables is not None)
    lin = _Linearisation(state, objective, company)

    solved = []
    for s in candidates:
        m = _Model(lin, settings, free, s, current)
        res, ub, eq = m.solve()
        if res.status == 3:
            raise ModelError("infeasible_optimization", "the problem is unbounded: some volume has no ceiling")
        if res.status == 0:
            solved.append((m, res, ub, eq))
    if not solved:
        m = _Model(lin, settings, free, candidates[0], current)
        conflict = _conflict(m)
        raise ModelError("infeasible_optimization",
                         "no plan satisfies all the constraints together. Conflict: "
                         + "; ".join(c["constraint"] for c in conflict)
                         + ". Nothing was relaxed; change one of these to get a plan.",
                         conflict=conflict, formulation=formulation_text(m))
    best = max(solved, key=lambda t: (-t[1].fun, t[0].supplier == current["supplier"]))
    m, res, ub, eq = best
    x = res.x
    plan_state, plan = _plan(m, x, state, current)
    lp_cm = float(m.c @ x + m.c0)
    result = {
        "status": "ok", "objective": objective, "company": company, "source": source,
        "formulation": formulation_text(m) + "".join(f"\nNote: {n}" for n in notes),
        "notes": notes,
        "plan": plan["summary"],
        "changes": plan["changes"],
    }
    out_opt = ce.compute_all(plan_state)
    engine_cm = _objective_value(out_opt, objective, company)
    cur_cm = _objective_value(current["outputs"], objective, company)
    result["cm"] = {"unit": "M$", "current": cur_cm / 1e6, "optimal": engine_cm / 1e6,
                    "delta": (engine_cm - cur_cm) / 1e6}
    result["by_company"] = _by_company(current["outputs"], out_opt)
    result["volumes"] = _volumes(current["outputs"], out_opt)
    result["binding_constraints"] = _binding(m, res, ub, x)
    result["current_plan_violations"] = _violations(m, state, current["outputs"])
    if check:
        result["self_checks"] = _self_checks(m, plan_state, out_opt, lp_cm, engine_cm, objective, company,
                                             state, plan["engine_vars"])
    return result


# --------------------------------------------------------------------------- #
# Plan, reporting
# --------------------------------------------------------------------------- #

def _plan(m: _Model, x, state, current):
    lin = m.lin
    P = copy.deepcopy(state)
    changes, sales_rows = [], []
    for p in lin.sales:
        v = max(0.0, float(x[m.iq[p]]))
        if abs(v) < 1e-9:
            v = 0.0
        old = float(schema.get(state, p))
        schema.set_value(P, p, v)
        sales_rows.append({"path": p, "current_kt": old, "optimal_kt": v, "delta_kt": v - old})
        if abs(v - old) > 1e-9:
            changes.append({"path": p, "value": v})
    blend_rows = []
    for f, (bp, _, _) in FURNACES.items():
        sc_c, sc_k = m.sc_expr[f]
        sc = float(sc_c @ x + sc_k)
        new = dict(current["blends"][f])
        if sc > 1e-6 and f in m.free_furnaces:
            for k in MATERIALS:
                new[k] = 100 * max(0.0, float(x[m.iY[(f, k)]])) / (sc / 1000)
            # keep the free total exact (the fixed home scrap / pig iron shares are untouched)
            total = 100 * lin.psi[f]
            drift = total - sum(new.values())
            kmax = max(new, key=new.get)
            new[kmax] += drift
        bl = _node(P, bp)
        for k in MATERIALS:
            old = current["blends"][f][k]
            bl[k] = new[k]
            blend_rows.append({"furnace": f, "material": k, "path": f"{bp}.{k}", "current_pct": old,
                               "optimal_pct": new[k], "delta_pct": new[k] - old})
            if abs(new[k] - old) > 1e-9:
                changes.append({"path": f"{bp}.{k}", "value": new[k]})
    cB, kB = m.B_expr
    B = float(cB @ x + kB) / 1000
    I = max(0.0, float(x[m.iI]))
    share = 0.0 if B <= 1e-12 else min(1.0, I / B)
    if share <= 1e-12:
        src, share = "market", 0.0
    elif share >= 1 - 1e-12:
        src, share = f"offer:{m.supplier}", 1.0
    else:
        src = f"split:{m.supplier}:{share:.12f}"
    # "min" already resolving to the same supplier and share needs no change — but only while the
    # blends stay put ("min" is re-resolved from the suppliers' costs).  "vc:<CO>" prices at cost,
    # not at the offer the LP valued, so it is replaced.
    blends_moved = any(c["path"].startswith(("billet.", "flat.")) for c in changes)
    cur_src = state["sourcing"]["ERM_rebar_billet"]
    same = cur_src == src or (cur_src == "min" and not blends_moved
                              and (current["supplier"] or "market") == (m.supplier if share > 0 else "market")
                              and abs(current["share"] - share) <= 1e-12)
    P["sourcing"]["ERM_rebar_billet"] = state["sourcing"]["ERM_rebar_billet"] if same else src
    if not same and src != state["sourcing"]["ERM_rebar_billet"]:
        changes.append({"path": "sourcing.ERM_rebar_billet", "value": src})
    sourcing = {"supplier": m.supplier if share > 0 else "market", "internal_share": share,
                "internal_kt": share * B, "market_kt": (1 - share) * B, "billets_kt": B, "source": src,
                "current_source": state["sourcing"]["ERM_rebar_billet"],
                "current_supplier": current["supplier"] or "market", "current_share": current["share"]}
    engine_vars = {"sales": [p for p in lin.sales if p in m.free_sales],
                   "furnaces": list(m.free_furnaces), "sourcing": m.src_free}
    return P, {"summary": {"sales": sales_rows, "blending": blend_rows, "billet_sourcing": sourcing},
               "changes": changes, "engine_vars": engine_vars}


def _by_company(cur, opt):
    a = cur["consolidated"]["usd_monthly"]
    b = opt["consolidated"]["usd_monthly"]
    rows = []
    for co in ce.COMPANIES:
        x, y = a["companies"][co]["contribution_margin"], b["companies"][co]["contribution_margin"]
        rows.append({"company": co, "current": x, "optimal": y, "delta": y - x})
    x, y = a["consolidated"]["contribution_margin"], b["consolidated"]["contribution_margin"]
    rows.append({"company": "Group (consolidated)", "current": x, "optimal": y, "delta": y - x})
    return {"unit": "M$", "rows": rows}


def _volumes(cur, opt):
    a, b = cur["production"]["summary_total"], opt["production"]["summary_total"]
    return {"unit": "kt", "rows": [{"stage": k, "current": a[k], "optimal": b[k], "delta": b[k] - a[k]}
                                   for k in ("rebar", "wire_rod", "hrc", "billet", "dri", "iop", "scrap")]}


def _binding(m: _Model, res, ub, x):
    out = []
    marg = res.ineqlin.marginals if ub else []
    for r, mu in zip(ub, marg):
        slack = r.rhs - float(r.coef @ x)
        if abs(slack) > 1e-7 or abs(mu) < 1e-9 or r.kind not in ("capacity", "floor", "market", "blend", "extra"):
            continue
        shadow = -mu                                   # linprog minimises −CM
        entry = {"constraint": r.group, "description": r.label}
        if r.kind in ("capacity", "market"):
            entry.update({"shadow_price": shadow / 1000, "unit": "$ CM per extra ton per month",
                          "text": f"+${shadow / 1000:,.2f} CM per extra ton ({r.label})"})
        elif r.kind == "blend":
            sc_c, sc_k = m.sc_expr[r.meta["furnace"]]
            per_pp = shadow * float(sc_c @ x + sc_k) / 1000 * 0.01
            if abs(per_pp) < 0.5:                        # binding in name only
                continue
            entry.update({"shadow_price": per_pp, "unit": "$ CM per percentage point more room, at the margin",
                          "text": f"+${per_pp:,.0f} CM per pp more room, at the margin ({r.label})"})
        elif r.kind == "floor":
            prod = r.meta["product"]
            total = sum(float(x[m.iq[f"sales.{co}.{prod}.{k}"]]) for co in ce.COMPANIES
                        if prod in m.lin.state["sales"].get(co, {}) for k in ("local_kt", "export_kt"))
            per_pp = -shadow * total * 0.01
            entry.update({"shadow_price": per_pp, "unit": "$ CM per +1 percentage point of the floor",
                          "text": f"{'+' if per_pp >= 0 else '−'}${abs(per_pp):,.0f} CM per +1 pp of the {prod} floor"})
        else:
            entry.update({"shadow_price": shadow, "unit": "$ CM per unit of the bound", "text": r.label})
        out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# Constraints measured on the engine's outputs (self-check 2, perturbation, current plan)
# --------------------------------------------------------------------------- #

def _violations(m: _Model, state, outputs, locks=False, tol=1e-6):
    s = m.settings
    v = []
    for item, d in outputs["capacity"]["items"].items():
        if item.startswith("DRI "):
            cap = s["capacity"]["dri"][item[4:]]
        else:
            prod, co = item.rsplit(" ", 1)
            cap = s["capacity"]["finished"][co][prod]
        if d["required_t"] > cap * (1 + tol) + tol:
            v.append(f"{item}: {d['required_t']:,.0f} t > {cap:,.0f} t")
    for prod, phi in s["floors"].items():
        loc = sum(state["sales"][c][prod]["local_kt"] for c in ce.COMPANIES if prod in state["sales"].get(c, {}))
        tot = loc + sum(state["sales"][c][prod]["export_kt"] for c in ce.COMPANIES
                        if prod in state["sales"].get(c, {}))
        if loc < phi * tot - tol * max(1, tot):
            v.append(f"{prod} local share {loc / tot:.1%} < floor {phi:.0%}")
        mk = s["markets"].get(prod)
        if mk is not None and loc > mk * (1 + tol) + tol:
            v.append(f"{prod} local sales {loc:,.1f} kt > local market {mk:,.1f} kt")
    for p in _sales_paths(state):
        if schema.get(state, p) < -tol:
            v.append(f"{p} is negative")
    src = outputs["sourcing"]
    for ac in s["extra"]:
        var = ac["variable"]
        val = src["internal_share"] if var == SHARE_PATH else schema.get(state, var)
        if ac.get("min") is not None and val < float(ac["min"]) - tol * max(1, abs(float(ac["min"]))):
            v.append(f"{var} = {val:g} < {ac['min']}")
        if ac.get("max") is not None and val > float(ac["max"]) + tol * max(1, abs(float(ac["max"]))):
            v.append(f"{var} = {val:g} > {ac['max']}")
    for f, (bp, _, _) in FURNACES.items():
        if any(x < -tol for x in schema.get(state, bp).values()):
            v.append(f"{f} has a negative blend share")
    bl = s["blend"]
    for f, mats in bl["furnaces"].items():
        if outputs["detail"][FURNACES[f][1]]["s1.solid_charge_t"] <= 1e-6:
            continue                                   # an idle furnace has no charge mix to limit
        shares = schema.get(state, FURNACES[f][0])
        for k, b in mats.items():
            if not b["min_pct"] - 1e-7 <= shares[k] <= b["max_pct"] + 1e-7:
                v.append(f"{f} {k} {shares[k]:.4f}% outside {b['min_pct']:g}–{b['max_pct']:g}%")
    if bl.get("local_scrap_supply_kt") is not None:
        used = sum(outputs["detail"][sheet]["s1.t.local"] for _, sheet, _ in FURNACES.values()) / 1000
        if used > bl["local_scrap_supply_kt"] * (1 + tol) + tol:
            v.append(f"local scrap {used:,.2f} kt > supply {bl['local_scrap_supply_kt']:,.1f} kt")
    return v


def _self_checks(m, plan_state, out_opt, lp_cm, engine_cm, objective, company, state, engine_vars):
    scale = max(1.0, abs(engine_cm))
    diff = engine_cm - lp_cm
    cross = {"passed": abs(diff) <= REL_TOL * scale, "lp_cm_usd": lp_cm, "engine_cm_usd": engine_cm,
             "difference_usd": diff, "tolerance_usd": REL_TOL * scale}
    if not cross["passed"]:
        raise ModelError("infeasible_optimization",
                         f"self-check failed: the engine's CM of the proposed plan ({engine_cm:,.2f} $) differs "
                         f"from the optimizer's ({lp_cm:,.2f} $) by {diff:,.6f} $. No plan is returned.",
                         self_check="engine_cross_check")
    failed = ce.failed_errors(out_opt)
    viol = _violations(m, plan_state, out_opt)
    integ = {"passed": not failed and not viol,
             "checks": [c["check"] for c in out_opt["integrity"] if c["severity"] == "error"],
             "run_constraints": "all met" if not viol else viol}
    if not integ["passed"]:
        why = "; ".join([f"{c['check']}: {c['detail']}" for c in failed] + viol)
        raise ModelError("integrity_check_failed", f"self-check failed: the proposed plan breaks: {why}. "
                         "No plan is returned.", self_check="integrity")
    pert = _perturbation(m, plan_state, engine_cm, objective, company, engine_vars)
    if not pert["passed"]:
        raise ModelError("infeasible_optimization",
                         f"self-check failed: moving {pert['better_move']} raises CM by "
                         f"{pert['best_gain_usd']:,.2f} $, so the plan is not optimal. No plan is returned.",
                         self_check="perturbation")
    return {"engine_cross_check": cross, "integrity": integ, "perturbation": pert, "all_passed": True}


def _perturbation(m, plan_state, cm_opt, objective, company, engine_vars):
    tol = REL_TOL * max(1.0, abs(cm_opt)) + 1e-6
    moves = []
    for p in engine_vars["sales"]:
        v = float(schema.get(plan_state, p))
        co, prod = p.split(".")[1:3]
        cap = m.settings["capacity"]["finished"].get(co, {}).get(prod, 0) / 1000
        d = PERTURBATION * v if v > 1e-9 else PERTURBATION * cap
        for sgn in (1, -1):
            if v + sgn * d >= 0 and d > 0:
                moves.append((f"{p} {'+' if sgn > 0 else '−'}5%", ("sales", p, v + sgn * d)))
    for f in engine_vars["furnaces"]:
        bp = FURNACES[f][0]
        bl = schema.get(plan_state, bp)
        total = sum(bl[k] for k in MATERIALS)
        for k in MATERIALS:
            v = bl[k]
            d = PERTURBATION * v if v > 1e-9 else PERTURBATION * total
            for sgn in (1, -1):
                nv = min(total, max(0.0, v + sgn * d))
                if abs(nv - v) > 1e-12:
                    moves.append((f"{bp}.{k} {'+' if sgn > 0 else '−'}5%", ("blend", bp, k, nv, total)))
    if engine_vars["sourcing"]:
        out = ce.compute_all(plan_state)["sourcing"]
        share, sup = out["internal_share"], out["supplier"]
        if sup != "market":
            for sgn in (1, -1):
                ns = min(1.0, max(0.0, share * (1 + sgn * PERTURBATION)))
                if abs(ns - share) > 1e-12:
                    moves.append((f"ERM internal share {'+' if sgn > 0 else '−'}5%", ("share", sup, ns)))
        for s in SUPPLIERS:
            if s != sup:
                moves.append((f"ERM buys 5% from {s}", ("share", s, PERTURBATION)))
    tested = feasible = 0
    best_gain, best_move = -math.inf, None
    for name, mv in moves:
        S = copy.deepcopy(plan_state)
        if mv[0] == "sales":
            schema.set_value(S, mv[1], mv[2])
        elif mv[0] == "blend":
            _, bp, k, nv, total = mv
            bl = _node(S, bp)
            others = [j for j in MATERIALS if j != k]
            rest = sum(bl[j] for j in others)
            for j in others:
                bl[j] = (bl[j] / rest * (total - nv)) if rest > 0 else (total - nv) / len(others)
            bl[k] = nv
        else:
            _, s, ns = mv
            S["sourcing"]["ERM_rebar_billet"] = f"split:{s}:{ns:.12f}"
        tested += 1
        o = ce.compute_all(S)
        if ce.failed_errors(o) or _violations(m, S, o):
            continue
        feasible += 1
        gain = _objective_value(o, objective, company) - cm_opt
        if gain > best_gain:
            best_gain, best_move = gain, name
    return {"passed": not (best_gain > tol), "tested": tested, "feasible": feasible,
            "best_gain_usd": 0.0 if best_gain == -math.inf else best_gain,
            "better_move": best_move if best_gain > tol else None, "tolerance_usd": tol}


# --------------------------------------------------------------------------- #
# Infeasibility: a minimal conflicting set of constraint groups (deletion filter)
# --------------------------------------------------------------------------- #

def _conflict(m: _Model):
    groups = []
    for r in m.rows:
        if r.group != "structure" and r.group not in groups:
            groups.append(r.group)
    keep = list(groups)
    for g in groups:
        trial = [x for x in keep if x != g]
        rows = [r for r in m.rows if r.group == "structure" or r.group in trial]
        if not m.feasible(rows):
            keep = trial
    labels = {}
    for r in m.rows:
        labels.setdefault(r.group, r.label)
    return [{"constraint": g, "detail": labels[g]} for g in keep]


# --------------------------------------------------------------------------- #
# The formulation in plain English (Pattern E step 3)
# --------------------------------------------------------------------------- #

def formulation_text(m: _Model) -> str:
    lin, s = m.lin, m.settings
    what = ("group contribution margin (consolidated: intercompany sales eliminated)"
            if lin.objective == "group_cm" else f"{lin.company}'s contribution margin (at intercompany prices)")
    free = []
    if m.free_sales:
        free.append(f"{len(m.free_sales)} sales quantities")
    if m.free_furnaces:
        free.append("blending on " + ", ".join(m.free_furnaces))
    if m.src_free:
        free.append("ERM's internal billet share (supplier and share; the rest bought at market)")
    lines = [f"Maximize {what}: Σ over companies and products of (local qty × local price + export qty × "
             "(export price − export expense) − variable cost per ton × production), with the variable cost "
             "built from the charge tons of DRI, local scrap and imported scrap in each furnace.",
             "Free: " + ("; ".join(free) if free else "nothing (every variable held at its current value)") + ".",
             "Held fixed: all prices, yields, MRMR, consumptions and fixed costs" +
             ("" if len(m.free_sales) == len(lin.sales) else "; sales quantities not listed as free") + ".",
             "Subject to:"]
    for plant, furnaces in _dri_plants(lin.rules).items():
        lines.append(f"- {plant} DRI required (DRI charged in {', '.join(furnaces)}) ≤ "
                     f"{_fmt_t(s['capacity']['dri'][plant])}/month")
    for co, prods in s["capacity"]["finished"].items():
        for prod, cap in prods.items():
            lines.append(f"- {co} {prod}: local + export ≤ {_fmt_t(cap)}/month")
    lines.append("- Per furnace: DRI + local scrap + imported scrap = the charge left after the fixed home "
                 "scrap and pig iron shares (blending sums to 100%)")
    lines.append("- ERM billets: internal + market = billets needed for ERM's rebar; 0 ≤ internal share ≤ 1")
    bl = s["blend"]
    for f, mats in bl["furnaces"].items():
        parts = [f"{k.replace('_', ' ')} {b['min_pct']:g}–{b['max_pct']:g}%" for k, b in mats.items()
                 if b["min_pct"] > 0 or b["max_pct"] < 100]
        if parts:
            lines.append(f"- {f} charge mix: " + ", ".join(parts))
    if bl.get("local_scrap_supply_kt") is not None:
        lines.append(f"- Group local scrap ≤ {bl['local_scrap_supply_kt']:,.1f} kt/month (market supply)")
    for prod, phi in s["floors"].items():
        lines.append(f"- {prod}: Σ local sales ≥ {phi:.2f} × Σ {prod} production")
    for prod, mk in s["markets"].items():
        if mk is not None:
            lines.append(f"- {prod}: Σ local sales ≤ {mk:,.1f} kt (local market)")
    for ac in s["extra"]:
        rng = " and ".join(x for x in (f"≥ {ac['min']}" if ac.get("min") is not None else "",
                                        f"≤ {ac['max']}" if ac.get("max") is not None else "") if x)
        lines.append(f"- {ac['variable']} {rng}")
    lines.append("- All quantities ≥ 0")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Appendix D.2 — the four verification cases;  D.3 — the ship-gate
# --------------------------------------------------------------------------- #

def _baseline():
    import json
    import os
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_initial_state.json")) as f:
        return json.load(f)


def _ceilings_covering(state, outputs):
    """Capacity ceilings raised to at least what the state uses now (the dummy baseline runs
    EZDK's DRI and wire rod over capacity, which would make 'hold everything' infeasible)."""
    caps = copy.deepcopy(state["capacity_ceilings"])
    for item, d in outputs["capacity"]["items"].items():
        if item.startswith("DRI "):
            caps["dri"][item[4:]] = max(caps["dri"][item[4:]], d["required_t"] * 1.0001)
        else:
            prod, co = item.rsplit(" ", 1)
            caps["finished"][co][prod] = max(caps["finished"][co][prod], d["required_t"] * 1.0001)
    return caps


def _case_identity(base):
    out = ce.compute_all(base)
    rc = {"local_market_ceilings": {"HRC": 120.0}, "capacity_ceilings": _ceilings_covering(base, out)}
    r = optimize(base, free_variables=[], run_constraints=rc)
    cur = _objective_value(out, "group_cm", None)
    got = r["cm"]["optimal"] * 1e6
    ok = abs(got - cur) <= REL_TOL * max(1, abs(cur)) and r["changes"] == []
    return ok, f"every variable held: CM {got:,.2f} $ vs current {cur:,.2f} $ (Δ {got - cur:.2e} $); " \
               f"{len(r['changes'])} change(s) proposed"


def _case_parity(base):
    """ERM's billet sourcing on its own.  The workbook answers this question with the minimum of
    the trade-off matrix (which the engine reproduces cell for cell); an engine sweep over every
    supplier and internal share is the second, independent reference."""
    big = {"dri": {"EZDK": 1e6, "ERM": 1e6}}
    rc = {"local_market_ceilings": {"HRC": 120.0},
          "capacity_ceilings": {**_ceilings_covering(base, ce.compute_all(base)), **big}}
    r = optimize(base, objective="company_cm", company="ERM", free_variables=["billet_sourcing"], run_constraints=rc)
    out = ce.compute_all(base)
    t = out["billet"]["tradeoff"]
    want_src, want_price = t["cheapest_source"]["ERM"], t["minimum"]["ERM"]
    plan = copy.deepcopy(base)
    for c in r["changes"]:
        schema.set_value(plan, c["path"], c["value"])
    got = ce.compute_all(plan)["sourcing"]
    ok1 = got["supplier"] == want_src and abs(got["price_usd_t"] - want_price) < 1e-9
    best = -math.inf
    for s in SUPPLIERS:
        for i in range(0, 21):
            S = copy.deepcopy(base)
            S["sourcing"]["ERM_rebar_billet"] = f"split:{s}:{i / 20:.2f}"
            best = max(best, _objective_value(ce.compute_all(S), "company_cm", "ERM"))
    lp = r["cm"]["optimal"] * 1e6
    ok2 = abs(lp - best) <= REL_TOL * max(1, abs(best))
    # capacity binding: only 40% of ERM's billets fit in EZDK's DRI, and ERM's DRI plant (behind
    # EFS and ESR) is full → the answer is a split, checked by a 0.001-step sweep of every supplier
    need = out["capacity"]["items"]["DRI EZDK"]["required_t"]
    market = ce.compute_all({**base, "sourcing": {"ERM_rebar_billet": "market"}})
    own = market["capacity"]["items"]["DRI EZDK"]["required_t"]
    cap = own + 0.4 * (need - own)
    erm_cap = market["capacity"]["items"]["DRI ERM"]["required_t"] * (1 + 1e-9)
    caps2 = {**_ceilings_covering(base, out), "dri": {"EZDK": cap, "ERM": erm_cap}}
    r2 = optimize(base, free_variables=["billet_sourcing"],
                  run_constraints={"local_market_ceilings": {"HRC": 120.0}, "capacity_ceilings": caps2})
    share = r2["plan"]["billet_sourcing"]["internal_share"]
    best2, step = -math.inf, 0.001
    for s in SUPPLIERS:                      # fine where the answer is, coarse elsewhere
        for i in (range(0, 1001) if s == "EZDK" else range(0, 1001, 50)):
            S = copy.deepcopy(base)
            S["sourcing"]["ERM_rebar_billet"] = f"split:{s}:{i * step:.3f}"
            o = ce.compute_all(S)
            items = o["capacity"]["items"]
            if items["DRI EZDK"]["required_t"] <= cap and items["DRI ERM"]["required_t"] <= erm_cap:
                best2 = max(best2, _objective_value(o, "group_cm", None))
    lp2 = r2["cm"]["optimal"] * 1e6
    gap_bound = step * got["billets_t"] * 1000          # one grid step × billets × $1000/t, generous
    ok3 = r2["plan"]["billet_sourcing"]["supplier"] == "EZDK" and 0.3 < share < 0.5 and \
        best2 <= lp2 + REL_TOL * abs(lp2) and lp2 - best2 <= gap_bound
    return ok1 and ok2 and ok3, (
        f"ERM alone: optimizer buys from {got['supplier']} at {got['price_usd_t']:,.2f} $/t = trade-off minimum "
        f"{want_src} {want_price:,.2f} $/t; engine sweep best {best:,.2f} $ vs optimizer {lp:,.2f} $. "
        f"With EZDK DRI capped at {cap:,.0f} t and ERM's DRI full: optimizer buys {share:.4f} from "
        f"{r2['plan']['billet_sourcing']['supplier']}, CM {lp2:,.2f} $ ≥ best of a sweep over every supplier "
        f"(0.001 steps for EZDK) {best2:,.2f} $")


def _case_dominant(base):
    out = ce.compute_all(base)
    caps = {**_ceilings_covering(base, out), "dri": {"EZDK": 1e6, "ERM": 1e6}}
    rc = {"local_market_ceilings": {"HRC": 120.0}, "capacity_ceilings": caps}
    msgs, ok = [], True
    vc = {s: out["billet"][s]["total_variable_cost"] for s in SUPPLIERS}
    # (a) market billets at $100/t, ESR's offer at $500/t → every buyer (ERM) takes the market
    a = copy.deepcopy(base)
    m = a["billet"]["market_usd_t"]
    m["base"] = 100.0 - m["safe_guards"] - m["other_costs"]
    a["billet"]["companies"]["ESR"]["tradeoff_ratio"] = 500.0 / vc["ESR"]
    for objective, company in (("group_cm", None), ("company_cm", "ERM")):
        r = optimize(a, objective=objective, company=company, free_variables=["billet_sourcing"], run_constraints=rc)
        src = r["plan"]["billet_sourcing"]
        ok &= src["supplier"] == "market" and src["internal_share"] == 0.0
        msgs.append(f"market at $100 ({objective}): ERM takes {src['supplier']} {1 - src['internal_share']:.0%} market")
    # (b) ESR's offer at $100/t, market at $500/t → ERM buys everything from ESR
    b = copy.deepcopy(base)
    m = b["billet"]["market_usd_t"]
    m["base"] = 500.0 - m["safe_guards"] - m["other_costs"]
    b["billet"]["companies"]["ESR"]["tradeoff_ratio"] = 100.0 / vc["ESR"]
    r = optimize(b, objective="company_cm", company="ERM", free_variables=["billet_sourcing"], run_constraints=rc)
    src = r["plan"]["billet_sourcing"]
    ok &= src["supplier"] == "ESR" and src["internal_share"] == 1.0
    msgs.append(f"ESR at $100 vs market $500 (ERM's CM): ERM takes {src['supplier']} at {src['internal_share']:.0%}")
    return ok, "; ".join(msgs)


def _case_infeasible(base):
    sales = _sales_paths(base)
    free = ["local_sales", "billet_sourcing", "blending"] + \
        [p for p in sales if p.endswith("export_kt") and ".HRC." not in p]     # HRC exports held
    rc = {"local_market_ceilings": {"HRC": 0.0}, "policy_floors": {"local_share_min": {"HRC": 0.20}}}
    try:
        r = optimize(base, free_variables=free, run_constraints=rc)
    except ModelError as e:
        names = [c["constraint"] for c in e.details.get("conflict", [])]
        ok = e.code == "infeasible_optimization" and "policy floor HRC" in names \
            and "local market ceiling HRC" in names
        return ok, f"infeasible, conflict named: {', '.join(names)}"
    return False, f"returned a number ({r['cm']['optimal']:,.2f} M$) instead of an infeasibility report"


CASES = (("identity", _case_identity), ("single_company_parity", _case_parity),
         ("dominant_option", _case_dominant), ("infeasibility", _case_infeasible))


def verify(base=None) -> dict:
    """Run the four D.2 cases (on the shipped corrected baseline unless given a state)."""
    base = base or _baseline()
    results = []
    for name, fn in CASES:
        try:
            ok, detail = fn(copy.deepcopy(base))
        except Exception as exc:                      # a crash is a failure, with its reason
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append({"case": name, "passed": bool(ok), "detail": detail})
    return {"passed": all(r["passed"] for r in results), "cases": results}


_GATE: dict | None = None


def ship_gate() -> dict:
    """D.3: the optimizer is offered only if all four cases pass.  Run once per process."""
    global _GATE
    if _GATE is None:
        _GATE = verify()
    return _GATE
