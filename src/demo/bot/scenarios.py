"""
src/demo/bot/scenarios.py — Fixed scenario definitions for funnel testing and persona demos.

A "scenario" is a deterministic sequence of users (with profiles) and expected funnel
counts.  The same scenario + seed always produces the same event sequence, so tests
can assert on expected funnel ratios.

The 4 CDP personas:
  lina   — Window Shopper: many product_views, no cart
  minh   — Decisive Buyer: full funnel → purchase
  hoa    — Researcher: search + product_view, no purchase
  quang  — Cart Abandoner: many add_to_cart + cart_abandoned

These scenarios are used by:
  • test_ingest.py       — to validate funnel reconstruction from CSV.
  • driver.py --profile  — when --profile is specified to force a persona.
"""

from __future__ import annotations

SCENARIOS: dict[str, dict] = {
    # ── Mixed persona scenario (primary demo) ────────────────────────────────
    "persona_mix": {
        "description": (
            "20 users: 8 Lina (Window Shopper), 5 Minh (Buyer), 4 Hoa (Researcher), "
            "3 Quang (Cart Abandoner). Expected: Lina → high product_view, Minh → purchase, "
            "Hoa → search + product_view no purchase, Quang → cart_abandoned."
        ),
        "seed": 0,
        "n_users": 20,
        "profiles": (
            ["lina"] * 8 +
            ["minh"] * 5 +
            ["hoa"] * 4 +
            ["quang"] * 3
        ),
        "expected": {
            "total_users": 20,
            "product_view": 20,         # every user views at least 1 product
            "add_to_cart": 8,           # Minh(5) + Quang(3); Lina has 0
            "begin_checkout": 5,        # only Minh reaches checkout
            "purchase_observed": 5,     # only Minh completes purchase
            "cart_abandoned": 3,       # only Quang
            "search": 4,               # only Hoa
            "wishlist_add": 4,         # only Hoa
        },
    },

    # ── All Lina (Window Shopper) ────────────────────────────────────────────
    "all_lina": {
        "description": (
            "10 Lina users — 0% conversion. All product_view, 0 add_to_cart."
        ),
        "seed": 10,
        "n_users": 10,
        "profiles": ["lina"] * 10,
        "expected": {
            "total_users": 10,
            "product_view": 10,
            "add_to_cart": 0,
            "begin_checkout": 0,
            "purchase_observed": 0,
            "cart_abandoned": 0,
        },
    },

    # ── All Minh (Decisive Buyer) ────────────────────────────────────────────
    "all_minh": {
        "description": (
            "10 Minh users — 100% conversion funnel. All complete purchase."
        ),
        "seed": 20,
        "n_users": 10,
        "profiles": ["minh"] * 10,
        "expected": {
            "total_users": 10,
            "product_view": 10,
            "add_to_cart": 10,
            "begin_checkout": 10,
            "purchase_observed": 10,
            "cart_abandoned": 0,
        },
    },

    # ── All Hoa (Researcher) ─────────────────────────────────────────────────
    "all_hoa": {
        "description": (
            "10 Hoa users — 0% purchase. All search + product_view, no checkout."
        ),
        "seed": 30,
        "n_users": 10,
        "profiles": ["hoa"] * 10,
        "expected": {
            "total_users": 10,
            "product_view": 10,
            "add_to_cart": 0,
            "begin_checkout": 0,
            "purchase_observed": 0,
            "search": 10,
            "wishlist_add": 10,
        },
    },

    # ── All Quang (Cart Abandoner) ────────────────────────────────────────────
    "all_quang": {
        "description": (
            "10 Quang users — 100% abandonment. All add_to_cart + cart_abandoned, 0 purchase."
        ),
        "seed": 40,
        "n_users": 10,
        "profiles": ["quang"] * 10,
        "expected": {
            "total_users": 10,
            "product_view": 10,
            "add_to_cart": 10,
            "begin_checkout": 0,
            "purchase_observed": 0,
            "cart_abandoned": 10,
        },
    },

    # ── Legacy scenarios (backwards compatibility) ────────────────────────────
    "funnel_baseline": {
        "description": (
            "10 users: 5 visitors, 3 cart-abandoners, 2 buyers. "
            "Legacy alias for Lina/Minh/Quang."
        ),
        "seed": 0,
        "n_users": 10,
        "profiles": ["lina"] * 5 + ["quang"] * 3 + ["minh"] * 2,
        "expected": {
            "total_users": 10,
            "product_view": 10,
            "add_to_cart": 5,         # Minh(2) + Quang(3)
            "begin_checkout": 2,     # only Minh
            "purchase_observed": 2,
            "cart_abandoned": 3,    # only Quang
        },
    },

    "heavy_buyer": {
        "description": "All 10 users are buyers — 100% conversion funnel.",
        "seed": 1,
        "n_users": 10,
        "profiles": ["minh"] * 10,
        "expected": {
            "total_users": 10,
            "product_view": 10,
            "add_to_cart": 10,
            "begin_checkout": 10,
            "purchase_observed": 10,
        },
    },

    "all_visitors": {
        "description": "All 10 users are visitors — zero conversion. Alias for all_lina.",
        "seed": 2,
        "n_users": 10,
        "profiles": ["lina"] * 10,
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
