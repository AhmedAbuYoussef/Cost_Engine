"""State loader for the Ezz Steel cost engine.

Loads `model_initial_state.json`, seeds the `sourcing_decision` field that the
engine requires (per Step 1 brief §11 final bullet), and runs schema-level
structural validation. The engine itself is strict about field access — it
raises on missing fields rather than defaulting silently. This module is the
single place where defaulting and validation happen.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


PRODUCTION_MATRIX: dict[str, frozenset[str]] = {
    "EZDK": frozenset({"Rebar", "Wire Rod", "HRC"}),
    "EFS":  frozenset({"Rebar", "HRC"}),
    "ERM":  frozenset({"Rebar"}),
    "ESR":  frozenset({"Rebar"}),
}

DEFAULT_SOURCING: dict[tuple[str, str], str] = {
    ("EZDK", "Rebar"):    "own",
    ("EZDK", "Wire Rod"): "own",
    ("EZDK", "HRC"):      "own",
    ("EFS",  "Rebar"):    "own",
    ("EFS",  "HRC"):      "own",
    ("ERM",  "Rebar"):    "market",
    ("ESR",  "Rebar"):    "own",
}

LEGAL_SOURCING_VALUES = frozenset({"own", "market", "internal_minimum"})


class StateValidationError(Exception):
    pass


def load_state(path: str | Path = "model_initial_state.json") -> dict[str, Any]:
    """Load JSON state, seed sourcing_decision defaults, run schema validation.

    Per Step 1 brief §11 final bullet, the JSON file does not yet carry the
    `sourcing_decision` field. Seeding happens here, not in the engine, so
    production code and tests load through the same path.
    """
    raw = json.loads(Path(path).read_text())
    state = copy.deepcopy(raw)
    _seed_sourcing_decisions(state)
    _validate(state)
    return state


def _seed_sourcing_decisions(state: dict) -> None:
    fp = state.setdefault("finished_products", {})
    for (company, product), default in DEFAULT_SOURCING.items():
        product_block = fp.setdefault(product, {})
        company_block = product_block.setdefault(company, {})
        if "sourcing_decision" not in company_block:
            company_block["sourcing_decision"] = default
        elif company_block["sourcing_decision"] not in LEGAL_SOURCING_VALUES:
            raise StateValidationError(
                f"Illegal sourcing_decision '{company_block['sourcing_decision']}' "
                f"for {company} {product}; allowed: {sorted(LEGAL_SOURCING_VALUES)}"
            )


def _validate(state: dict) -> None:
    for key in ("global", "entities", "dri", "billet", "finished_products",
                "sales", "fixed_costs", "market_shares", "intercompany"):
        if key not in state:
            raise StateValidationError(f"missing top-level key '{key}'")

    fx = state["global"].get("fx_rate_egp_usd")
    if not isinstance(fx, (int, float)) or fx <= 0:
        raise StateValidationError(f"invalid fx_rate_egp_usd: {fx!r}")

    for producer in state["entities"]["dri_producers"]:
        if producer not in state["dri"]:
            raise StateValidationError(f"DRI producer '{producer}' has no dri block")

    for producer in state["entities"]["billet_producers"]:
        if producer not in state["billet"]:
            raise StateValidationError(f"billet producer '{producer}' has no billet block")

    if "market" not in state["billet"]:
        raise StateValidationError("billet.market block missing")

    for company, products in PRODUCTION_MATRIX.items():
        for product in products:
            if product not in state["finished_products"]:
                raise StateValidationError(f"finished_products.{product} missing")
            if company not in state["finished_products"][product]:
                raise StateValidationError(
                    f"finished_products.{product}.{company} missing "
                    f"(required by production matrix)"
                )

    for company in state["entities"]["companies"]:
        if company not in state["fixed_costs"]:
            raise StateValidationError(f"fixed_costs.{company} missing")
        dist = state["fixed_costs"][company].get("distribution_pct", {})
        for product_key in ("DRI", "Rebar", "Wire Rod", "HRC"):
            if product_key not in dist:
                raise StateValidationError(
                    f"fixed_costs.{company}.distribution_pct.{product_key} missing"
                )


def production_matrix_has(company: str, product: str) -> bool:
    return product in PRODUCTION_MATRIX.get(company, frozenset())


def assert_in_production_matrix(company: str, product: str) -> None:
    if not production_matrix_has(company, product):
        raise StateValidationError(
            f"{company} does not produce {product} per the production matrix"
        )
