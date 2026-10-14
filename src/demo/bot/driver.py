"""
src/demo/bot/driver.py — Synthetic user bot driver.

Usage
-----
    python -m src.demo.bot.driver              # default: 200 users, 5000 events/min
    python -m src.demo.bot.driver --users 5    # smoke test
    python -m src.demo.bot.driver --users 50 --rate 10000 --seed 42

The driver POSTs events to the Demo API at http://127.0.0.1:8000/api/events.
Each worker corresponds to one synthetic user (session-level events).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx

# __file__ = src/demo/bot/driver.py
# parents[0] = src/demo/bot/
# parents[1] = src/demo/
# parents[2] = src/
# parents[3] = repo root
_REPO = Path(__file__).resolve().parents[3]
# Add src/ on path so "from src.demo.bot.profiles import ..." works
sys.path.insert(0, str(_REPO / "src"))
ROOT = _REPO   # repo root: config/ and data/ are here

from src.demo.bot.profiles import build_profile
from src.demo.bot.scenarios import SCENARIOS

API_BASE = os.getenv("CDP_DEMO_API", "http://127.0.0.1:8000")
DEFAULT_USERS = 200
DEFAULT_RATE = 5000          # target events per minute
REQUEST_TIMEOUT = 30         # seconds per POST


# ── Helpers ───────────────────────────────────────────────────────────────────

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: str) -> str:
    import hashlib
    return hashlib.sha256(data.encode()).hexdigest()


def load_catalog() -> list[dict]:
    """Load catalog once per process; each worker gets a random sample."""
    path = ROOT / "config" / "demo" / "catalog.products.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pick_products(catalog: list[dict], n: int, rng: random.Random) -> list[dict]:
    return rng.sample(catalog, min(n, len(catalog)))


# ── Event builder ─────────────────────────────────────────────────────────────

def make_event(
    event_type: str,
    session_id: str,
    user_id: str,
    url: str,
    viewport: str,
    payload: dict,
    source: str = "bot-demo",
) -> dict:
    return {
        "event_type": event_type,
        "event_time": utc_now(),
        "session_id": session_id,
        "user_id": user_id,
        "namespace": "cdp.demo.events",
        "source": source,
        "url": url,
        "referrer": "",
        "user_agent": "CDP-DemoBot/1.0",
        "viewport": viewport,
        "payload": payload,
    }


# ── Worker ────────────────────────────────────────────────────────────────────

def run_worker(
    worker_id: int,
    profile_name: str,
    catalog: list[dict],
    user_seed: int,
    target_rate: int,
    global_seed: int,
    total_workers: int,
) -> dict:
    """
    One synthetic user session.
    Returns stats dict.
    """
    rng = random.Random(user_seed)
    profile = build_profile(profile_name)

    session_id = str(uuid.uuid4())
    user_id = f"bot_uid_{worker_id:06d}"
    url_base = "http://localhost:8080"
    viewport = "1920x1080"

    # Pick products for this session
    n_products = profile.get("n_products", 10)
    products = pick_products(catalog, n_products, rng)
    cart = []

    events_emitted = 0
    errors = 0
    batches_sent = 0

    # Rate-limiting: sleep between batches
    events_per_batch = profile.get("events_per_batch", 10)
    min_interval = (60.0 / target_rate) * events_per_batch * total_workers

    session_start = time.monotonic()

    def emit(event_type: str, payload: dict) -> dict:
        return make_event(event_type, session_id, user_id, url_base, viewport, payload)

    def _send(batch: list[dict]):
        nonlocal errors, batches_sent
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.post(f"{API_BASE}/api/events", json=batch)
                if resp.status_code != 200:
                    errors += 1
                else:
                    batches_sent += 1
        except Exception:
            errors += 1

    for step in profile.get("steps", []):
        step_type = step["type"]

        if step_type == "page_view":
            ev = emit("page_view", {"path": step.get("path", "/"), "title": step.get("title", "Demo")})
            _send([ev])
            events_emitted += 1

        elif step_type == "product_view":
            product_idx = step.get("product_idx", -1)
            if product_idx == -1:
                product = rng.choice(products)
            else:
                product = products[product_idx % len(products)]
            ev = emit("product_view", {
                "product_id": product["product_id"],
                "category_id": product["category_id"],
                "price": product["price"],
                "currency": product.get("currency", "USD"),
            })
            _send([ev])
            events_emitted += 1

        elif step_type == "add_to_cart":
            product = rng.choice(products)
            qty = rng.randint(1, 3)
            cart.append({"product_id": product["product_id"], "quantity": qty})
            ev = emit("add_to_cart", {
                "product_id": product["product_id"],
                "quantity": qty,
                "price": product["price"],
                "currency": product.get("currency", "USD"),
            })
            _send([ev])
            events_emitted += 1

        elif step_type == "remove_from_cart":
            if cart:
                item = cart.pop()
                product = next((p for p in products if p["product_id"] == item["product_id"]), products[0])
                ev = emit("remove_from_cart", {
                    "product_id": item["product_id"],
                    "quantity": item["quantity"],
                    "price": product["price"],
                    "currency": product.get("currency", "USD"),
                })
                _send([ev])
                events_emitted += 1

        elif step_type == "checkout":
            if not cart:
                continue
            cart_id = str(uuid.uuid4())
            total = sum(
                float(next((p for p in products if p["product_id"] == i["product_id"]), products[0])["price"]) * i["quantity"]
                for i in cart
            )
            ev = emit("begin_checkout", {
                "cart_id": cart_id,
                "items": cart.copy(),
                "total_price": str(round(total, 2)),
                "currency": "USD",
            })
            _send([ev])
            events_emitted += 1

        elif step_type == "purchase":
            if not cart:
                cart = [{"product_id": products[0]["product_id"], "quantity": 1}]
            cart_id = str(uuid.uuid4())
            total = sum(
                float(next((p for p in products if p["product_id"] == i["product_id"]), products[0])["price"]) * i["quantity"]
                for i in cart
            )
            ev = emit("purchase_observed", {
                "cart_id": cart_id,
                "items": cart.copy(),
                "total_price": str(round(total, 2)),
                "currency": "USD",
            })
            _send([ev])
            events_emitted += 1

        elif step_type == "search":
            query = step.get("query") or rng.choice(["electronics", "laptop", "phone", "shoes", "book"])
            ev = emit("search", {
                "query": query,
                "results_count": rng.randint(5, 50),
                "type": "catalog_search",
            })
            _send([ev])
            events_emitted += 1

        elif step_type == "wishlist_add":
            product = rng.choice(products)
            ev = emit("wishlist_add", {
                "product_id": product["product_id"],
                "price": product["price"],
                "currency": product.get("currency", "USD"),
            })
            _send([ev])
            events_emitted += 1

        elif step_type == "cart_abandoned":
            if cart:
                ev = emit("cart_abandoned", {
                    "items": [dict(i) for i in cart],
                    "total_price": str(round(sum(
                        float(next((p for p in products if p["product_id"] == i["product_id"]), products[0])["price"]) * i["quantity"]
                        for i in cart
                    ), 2)),
                    "currency": "USD",
                })
                _send([ev])
                events_emitted += 1

        elif step_type == "sleep":
            # Sleep a random amount within the range
            lo, hi = step.get("range", (0.1, 1.0))
            time.sleep(rng.uniform(lo, hi))

        # Throttle
        if min_interval > 0:
            time.sleep(min_interval)

    elapsed = time.monotonic() - session_start
    return {
        "worker_id": worker_id,
        "profile": profile_name,
        "user_id": user_id,
        "events_emitted": events_emitted,
        "errors": errors,
        "elapsed_s": round(elapsed, 2),
    }


# ── Deterministic profile assignment ─────────────────────────────────────────

def assign_profiles(n_users: int, seed: int) -> list[str]:
    """
    Assign profile names to n_users using a deterministic weighted shuffle.
    Default mix: 40% lina, 25% minh, 20% hoa, 15% quang (the 4 CDP personas).
    Falls back to legacy mix for backwards compatibility.
    """
    rng = random.Random(seed)
    weights = [
        ("lina", 40),
        ("minh", 25),
        ("hoa", 20),
        ("quang", 15),
    ]
    pool: list[str] = []
    for name, weight in weights:
        pool.extend([name] * weight)
    return [rng.choice(pool) for _ in range(n_users)]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CDP Demo Bot Driver")
    parser.add_argument("--users", type=int, default=DEFAULT_USERS,
                        help="Number of synthetic users (default 200)")
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE,
                        help="Target events per minute (default 5000)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Global seed for reproducibility (default 42)")
    parser.add_argument("--profile", default=None,
                        help="Force all users to a specific profile (visitor|cart_abandoner|buyer)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Thread pool size (default: min(users, 50))")
    args = parser.parse_args()

    n_users = max(1, args.users)
    target_rate = max(1, args.rate)
    seed = args.seed
    workers_count = args.workers or min(n_users, 50)

    print(f"CDP Demo Bot — {n_users} users, target {target_rate} events/min, seed={seed}")
    print(f"API: {API_BASE}")
    print(f"Workers: {workers_count}")

    catalog = load_catalog()
    print(f"Catalog: {len(catalog)} products loaded")

    profiles = [args.profile] * n_users if args.profile else assign_profiles(n_users, seed)

    # Compute per-user seeds from global seed (deterministic)
    def user_seed(uid: int) -> int:
        return (seed * 31 + uid) & 0xFFFF_FFFF

    start_time = time.monotonic()
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers_count) as pool:
        futures = {
            pool.submit(
                run_worker,
                i,
                profiles[i],
                catalog,
                user_seed(i),
                target_rate,
                seed,
                n_users,
            ): i
            for i in range(n_users)
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
                if len(results) % 20 == 0 or len(results) == n_users:
                    print(f"  Completed {len(results)}/{n_users} workers…")
            except Exception as exc:
                print(f"  Worker error: {exc}")

    elapsed = time.monotonic() - start_time
    total_events = sum(r["events_emitted"] for r in results)
    total_errors = sum(r["errors"] for r in results)

    print(f"\n=== Summary ===")
    print(f"  Users:        {n_users}")
    print(f"  Total events: {total_events}")
    print(f"  Errors:       {total_errors}")
    print(f"  Elapsed:      {elapsed:.1f}s")
    print(f"  Rate (actual): {total_events / max(elapsed/60, 0.1):.0f} events/min")
    print(f"\nPer-profile counts:")
    for profile_name in ("lina", "minh", "hoa", "quang"):
        cnt = sum(1 for r in results if r["profile"] == profile_name)
        evts = sum(r["events_emitted"] for r in results if r["profile"] == profile_name)
        if cnt > 0:
            print(f"  {profile_name}: {cnt} users, {evts} events")

    # Persist run metadata
    meta = {
        "n_users": n_users,
        "target_rate": target_rate,
        "seed": seed,
        "elapsed_s": round(elapsed, 2),
        "total_events": total_events,
        "total_errors": total_errors,
        "actual_rate": round(total_events / max(elapsed / 60, 0.1)),
        "worker_results": [
            {"worker_id": r["worker_id"], "profile": r["profile"],
             "events": r["events_emitted"], "errors": r["errors"]}
            for r in results
        ],
    }
    meta_path = ROOT / "data" / "demo-events" / f"bot-run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"\nRun metadata: {meta_path}")


if __name__ == "__main__":
    main()
