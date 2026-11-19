"""Generate a REES46-shaped sample CSV for pipeline verification.

The real dataset is 5.6 GB / 42.4M rows and is not redistributed with the
repository. This generator produces a file with the exact same schema and
value formats so the ingestion job, the DDL and the quality gates can be
exercised end to end.

The output is a *sample*. It is never merged with other batches and must not
be presented as the full month (contract section 4).

Usage:
    .venv\\Scripts\\python.exe src/pipelines/lakehouse/make_sample_rees46.py \\
        --rows 20000 --output data/REES46/sample.csv
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

HEADER = [
    "event_time",
    "event_type",
    "product_id",
    "category_id",
    "category_code",
    "brand",
    "price",
    "user_id",
    "user_session",
]

EVENT_TYPES = ["view", "addtocart", "purchase", "removefromcart"]
CATEGORIES = [
    ("100", "Apparel", "Clo"), ("200", "Accessories", "Acc"),
    ("300", "Electronics", "Ele"), ("400", "Home", "Hom"),
    ("500", "Books", "Boo"),
]
BRANDS = ["Nike", "Adidas", "Samsung", "Sony", "Xiaomi", "Canon", "HP", "Apple"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a REES46-shaped sample CSV.")
    parser.add_argument("--rows", type=int, default=20000)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "data" / "REES46" / "sample.csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    start = datetime(2019, 10, 1, tzinfo=timezone.utc)
    users = [f"{random.getrandbits(48):012x}" for _ in range(max(1, args.rows // 20))]

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        for index in range(args.rows):
            event_time = start + timedelta(seconds=index * 3)
            category_id, category_code, category_name = random.choice(CATEGORIES)
            # A few malformed prices so the price_unparseable quality flag and
            # the null-rate warning are actually exercised.
            price = f"{random.uniform(3, 900):.2f}"
            if index % 997 == 0:
                price = "n/a"
            elif index % 499 == 0:
                price = "-5.00"
            writer.writerow([
                event_time.isoformat().replace("+00:00", ""),
                random.choice(EVENT_TYPES),
                f"p{random.randint(1, 500):05d}",
                category_id,
                category_code,
                random.choice(BRANDS),
                price,
                random.choice(users),
                f"s{random.getrandbits(32):08x}",
            ])

    size = output.stat().st_size
    print(f"Wrote {args.rows:,} rows to {output} ({size / 1024 ** 2:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
