"""
src/demo/bot/profiles.py — User profile definitions for the 4 CDP personas.

Persona mix: 40% Lina (Window Shopper), 25% Minh (Decisive Buyer),
             20% Hoa (Researcher), 15% Quang (Cart Abandoner).

Each profile defines a deterministic sequence of steps with relative timing.
The bot driver maps these steps to CDP event types.
"""

from __future__ import annotations
from typing import TypedDict


class ProfileStep(TypedDict):
    type: str   # 'page_view' | 'product_view' | 'add_to_cart' | 'remove_from_cart'
                # | 'checkout' | 'purchase' | 'search' | 'wishlist_add'
                # | 'cart_abandoned' | 'sleep' | 'newsletter_signup' | 'begin_checkout'
    path: str | None
    title: str | None
    range: tuple[float, float] | None   # for 'sleep': (min_s, max_s)
    # optional payload extras
    query: str | None   # for 'search'
    product_idx: int | None  # index into session's product list (-1 = random)


class Profile(TypedDict):
    name: str
    description: str
    n_products: int           # number of distinct products to browse in session
    events_per_batch: int     # target events before throttling pause
    steps: list[ProfileStep]


PROFILES: dict[str, Profile] = {

    # ── Lina: Window Shopper ─────────────────────────────────────────────────
    # Browses many products, low intent. Goal: build product_view depth signal.
    # Signature: many product_view + scroll_depth, few/no add_to_cart.
    "lina": {
        "name": "Lina (Window Shopper)",
        "description": (
            "Browses many products rapidly, no cart, no purchase. "
            "Goal: deep product_view + scroll_depth signal."
        ),
        "n_products": 12,
        "events_per_batch": 15,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.15, 0.5)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.1, 0.4)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.15, 0.5)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.6)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.1, 0.4)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.15, 0.5)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.7)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.1, 0.3)},
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.2, 0.5)},
        ],
    },

    # ── Minh: Decisive Buyer ────────────────────────────────────────────────
    # Adds 1-2 products, completes checkout fast. Goal: clear purchase signal.
    # Signature: short funnel → begin_checkout → purchase_observed.
    "minh": {
        "name": "Minh (Decisive Buyer)",
        "description": (
            "Adds 1-2 products and completes checkout quickly. "
            "Goal: clear purchase signal for the pipeline."
        ),
        "n_products": 4,
        "events_per_batch": 10,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.3, 0.7)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.15, 0.4)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.4, 1.0)},
            {"type": "page_view", "path": "/cart", "title": "Cart"},
            {"type": "sleep", "range": (0.3, 0.7)},
            {"type": "checkout", "path": None, "title": None},     # → begin_checkout
            {"type": "sleep", "range": (0.5, 1.5)},
            {"type": "purchase", "path": None, "title": None},    # → purchase_observed
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "page_view", "path": "/", "title": "Home"},
        ],
    },

    # ── Hoa: Researcher ─────────────────────────────────────────────────────
    # Uses search, opens product detail, reads specs, compares (no purchase).
    # Goal: high-engagement non-buyer signal.
    # Signature: search events + many product_view + scroll_depth, 0 purchase.
    "hoa": {
        "name": "Hoa (Researcher)",
        "description": (
            "Uses search, reads specs, compares products but never buys. "
            "Goal: high-engagement non-buyer signal."
        ),
        "n_products": 8,
        "events_per_batch": 14,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "search", "path": None, "title": None, "query": "electronics", "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "product_view", "path": None, "title": None, "product_idx": 0},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None, "product_idx": 1},
            {"type": "sleep", "range": (0.2, 0.6)},
            {"type": "search", "path": None, "title": None, "query": "laptop", "product_idx": -1},
            {"type": "sleep", "range": (0.15, 0.4)},
            {"type": "product_view", "path": None, "title": None, "product_idx": 2},
            {"type": "sleep", "range": (0.3, 0.7)},
            {"type": "product_view", "path": None, "title": None, "product_idx": 3},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "wishlist_add", "path": None, "title": None, "product_idx": 2},
            {"type": "sleep", "range": (0.1, 0.3)},
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.2, 0.5)},
        ],
    },

    # ── Quang: Cart Abandoner ────────────────────────────────────────────────
    # Adds many items to cart, drops off at checkout.
    # Goal: cart_abandoned event with timing signal.
    # Signature: many add_to_cart + cart_abandoned, no purchase.
    "quang": {
        "name": "Quang (Cart Abandoner)",
        "description": (
            "Adds many items to cart, browses around, then abandons at checkout. "
            "Goal: cart_abandoned event for re-targeting pipeline."
        ),
        "n_products": 8,
        "events_per_batch": 18,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.3, 0.7)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.15, 0.4)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.4, 1.0)},
            {"type": "page_view", "path": "/cart", "title": "Cart"},
            {"type": "sleep", "range": (0.5, 1.5)},
            # Intentionally abandon — no checkout, no purchase
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.2, 0.6)},
            # cart_abandoned is fired client-side on beforeunload; we emit
            # the marker event here too so it shows in bot-generated batches.
            {"type": "cart_abandoned", "path": None, "title": None},
            {"type": "sleep", "range": (0.1, 0.3)},
        ],
    },

    # ── Legacy profiles (kept for backwards compatibility) ─────────────────
    "visitor": {
        "name": "Visitor (legacy)",
        "description": "Browses catalog, views products — no cart. Alias for Lina.",
        "n_products": 8,
        "events_per_batch": 12,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.5, 1.5)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.8)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.1, 0.5)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.6)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.5, 1.2)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.3, 0.9)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.7)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.5, 1.0)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.1, 0.4)},
        ],
    },

    "cart_abandoner": {
        "name": "Cart Abandoner (legacy)",
        "description": "Browses, adds to cart, abandons — alias for Quang.",
        "n_products": 6,
        "events_per_batch": 14,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.3, 1.0)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.6)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.4, 1.0)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.1, 0.4)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.5, 1.5)},
            {"type": "page_view", "path": "/cart", "title": "Cart"},
            {"type": "sleep", "range": (1.0, 2.0)},
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "cart_abandoned", "path": None, "title": None},
        ],
    },

    "buyer": {
        "name": "Buyer (legacy)",
        "description": "Browses, adds to cart, completes checkout — alias for Minh.",
        "n_products": 5,
        "events_per_batch": 18,
        "steps": [
            {"type": "page_view", "path": "/", "title": "Home"},
            {"type": "sleep", "range": (0.3, 0.8)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.6)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.4, 1.0)},
            {"type": "product_view", "path": None, "title": None, "product_idx": -1},
            {"type": "sleep", "range": (0.2, 0.5)},
            {"type": "add_to_cart", "path": None, "title": None, "product_idx": -1},
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
    if name not in PROFILES:
        raise KeyError(f"Unknown profile: {name}. Available: {list(PROFILES.keys())}")
    return PROFILES[name]


def list_profiles() -> list[str]:
    return list(PROFILES.keys())


def list_persona_profiles() -> list[str]:
    """The 4 primary CDP personas."""
    return ["lina", "minh", "hoa", "quang"]
