"""
config/snowplow/tools/probe_tp2.py — Kiểm tra payload TP2 của bot vào Snowplow.

Gửi một event mẫu theo đúng format Browser Tracker rồi báo cáo event có
được lưu vào PostgreSQL hay không (failed = true/false).

    python config/snowplow/tools/probe_tp2.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from src.demo.snowplow.tp2 import (  # noqa: E402
    SnowplowCollector,
    build_event,
    build_payload,
)

COLLECTOR = "http://127.0.0.1:9090"


def main() -> None:
    event = build_event(
        "product_view",
        {"product_id": "P0010001", "price": "129.99", "currency": "USD"},
        user_id="probe-user-2",
        session_id="sess-probe-2",
        product={
            "product_id": "P0010001",
            "category_id": "electronics.smartphone",
            "brand": "Apple",
            "price": "999.99",
            "currency": "USD",
        },
    )
    print("Payload:")
    print(json.dumps(build_payload([event]), indent=2, ensure_ascii=False))
    print()

    with SnowplowCollector(COLLECTOR) as collector:
        ok = collector.send([event])
    print(f"HTTP accepted: {ok}")
    print("Waiting for Enrich...")
    time.sleep(4)
    print("Check the events table next.")


if __name__ == "__main__":
    main()
