"""
src/demo/bot/profiles.py — User profile definitions.

Mix: 60% visitor, 30% cart_abandoner, 10% buyer.
Each profile defines a sequence of steps (with relative timing) that a
synthetic user follows during a session.

The profile uses deterministic random choices via the seed passed in by driver.py.
"""

from __future__ import annotations

from typing import TypedDict


class ProfileStep(TypedDict):
    type: str          # 'page_view' | 'product_view' | 'add_to_cart' | 'remove_from_cart' | 'checkout' | 'purchase' | 'sleep'
    path: str | None
    title: str | None
    range: tuple[float, float] | None   # for 'sleep': (min_s, max_s)


class Profile(TypedDict):
    name: str
    description: str
    n_products: int           # number of distinct products to browse
    events_per_batch: int     # target events before throttling pause
    steps: list[ProfileStep]


PROFILES: dict[str, Profile] = {
    "visitor": {
        "name": "Visitor",
        "description": "Browses catalog, views products, does not add to cart.",
        "n_products": 8,
        "events_per_batch": 12,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.5, 1.5)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.2, 0.8)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.1, 0.5)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.2, 0.6)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.5, 1.2)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.3, 0.9)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.2, 0.7)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.5, 1.0)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.1, 0.4)},
        ],
    },

    "cart_abandoner": {
        "name": "Cart Abandoner",
        "description": "Browses, adds items to cart, abandons at checkout.",
        "n_products": 6,
        "events_per_batch": 14,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.3, 1.0)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.2, 0.6)},
            {"type": "add_to_cart", "path": None, "title": None},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "add_to_cart", "path": None, "title": None},
            {"type": "sleep", "range": (0.4, 1.0)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.1, 0.4)},
            {"type": "add_to_cart", "path": None, "title": None},
            {"type": "sleep", "range": (0.5, 1.5)},
            {"type": "page_view", "path": "/cart", "title": "Cart"},
            {"type": "sleep", "range": (1.0, 2.0)},
            # Intentionally stops — no checkout/purchase (abandoner)
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.2, 0.5)},
        ],
    },

    "buyer": {
        "name": "Buyer",
        "description": "Browses, adds to cart, completes checkout and purchase.",
        "n_products": 5,
        "events_per_batch": 18,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.2, 0.6)},
            {"type": "add_to_cart", "path": None, "title": None},
            {"type": "sleep", "range": (0.4, 1.0)},
            {"type": "product_view", "path": None, "title": None},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "add_to_cart", "path": None, "title": None},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "page_view", "path": "/cart", "title": "Cart"},
            {"type": "sleep", "range": (0.5, 1.2)},
            {"type": "checkout", "path": None, "title": None},
            {"type": "sleep", "range": (0.8, 2.0)},
            {"type": "purchase", "path": None, "title": None},
            {"type": "sleep", "range": (0.5, 1.5)},
            {"type": "page_view", "path": "/", "title": "Home"},
        ],
    },
}


def build_profile(name: str) -> Profile:
    """Return a profile dict by name. Raises KeyError if unknown."""
    return PROFILES[name]


def list_profiles() -> list[str]:
    return list(PROFILES.keys())
