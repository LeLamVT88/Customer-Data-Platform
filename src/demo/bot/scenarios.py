"""
src/demo/bot/scenarios.py — Fixed scenario definitions for funnel testing.

A "scenario" is a deterministic sequence of events with known expected funnel
counts.  The same scenario + seed always produces the same event sequence, so
tests can assert on the expected funnel ratios (view → cart → purchase).

These scenarios are used by:
  • test_ingest.py  — to validate funnel reconstruction from CSV.
  • driver.py       — when --profile is not specified, the default 60/30/10
                      mix is used, which is based on these profiles.
"""

from __future__ import annotations

SCENARIOS: dict[str, dict] = {
    "funnel_baseline": {
        "description": (
            "10 users: 5 visitors, 3 cart-abandoners, 2 buyers. "
            "Expected funnel: all 10 reach product_view, 5 reach add_to_cart, "
            "2 reach purchase_observed."
        ),
        "seed": 0,
        "n_users": 10,
        "profiles": ["visitor"] * 5 + ["cart_abandoner"] * 3 + ["buyer"] * 2,
        "expected": {
            "total_users": 10,
            "product_view": 10,        # every user views at least 1 product
            "add_to_cart": 5,         # only cart_abandoner + buyer add to cart
            "begin_checkout": 2,      # only buyer reaches checkout
            "purchase_observed": 2,   # only buyer completes purchase
        },
    },
    "heavy_buyer": {
        "description": "All 10 users are buyers — 100% conversion funnel.",
        "seed": 1,
        "n_users": 10,
        "profiles": ["buyer"] * 10,
        "expected": {
            "total_users": 10,
            "product_view": 10,
            "add_to_cart": 10,
            "begin_checkout": 10,
            "purchase_observed": 10,
        },
    },
    "all_visitors": {
        "description": "All 10 users are visitors — zero conversion.",
        "seed": 2,
        "n_users": 10,
        "profiles": ["visitor"] * 10,
        "expected": {
            "total_users": 10,
            "product_view": 10,
            "add_to_cart": 0,
            "begin_checkout": 0,
            "purchase_observed": 0,
        },
    },
}


def get_scenario(name: str) -> dict:
    return SCENARIOS[name]


def list_scenarios() -> list[str]:
    return list(SCENARIOS.keys())
