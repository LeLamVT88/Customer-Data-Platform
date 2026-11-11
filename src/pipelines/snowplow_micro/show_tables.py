#!/usr/bin/env python3
"""
src/pipelines/snowplow_micro/show_tables.py — Hiển thị dữ liệu Iceberg của nhánh Snowplow Micro cũ.

Chạy sau `ingest.py` để xem thống kê dữ liệu ở từng tầng (không phải bộ nghiệm thu):

    Bronze      — giữ nguyên event của Snowplow (kể cả event lỗi)
    Silver      — chỉ event hợp lệ, đã chuẩn hoá
    Quarantine  — event mà Snowplow Enrich đánh dấu failed
    Gold        — tổng hợp hành vi theo user và phễu theo session

Usage:
    docker compose -f config/docker/compose.local-lakehouse.yml run --rm spark \\
        /workspace/src/pipelines/snowplow_micro/show_tables.py --batch-id demo-local
"""
from __future__ import annotations

import argparse
import json

from pyspark.sql import SparkSession, functions as F


def main() -> None:
    parser = argparse.ArgumentParser(description="Kiem tra du lieu Iceberg cua demo")
    parser.add_argument("--batch-id", default="demo-local")
    args = parser.parse_args()

    spark = SparkSession.builder.appName("cdp-demo-verify").getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    bid = args.batch_id

    print("=" * 70)
    print(f"BRONZE  cdp.bronze.demo_events  (batch_id = {bid})")
    print("=" * 70)
    spark.sql(
        f"SELECT event_type, count(*) AS n, "
        f"sum(CASE WHEN failed THEN 1 ELSE 0 END) AS failed "
        f"FROM cdp.bronze.demo_events WHERE batch_id = '{bid}' "
        f"GROUP BY event_type ORDER BY n DESC"
    ).show(50, truncate=False)

    print("=" * 70)
    print(f"SILVER  cdp.silver.demo_events  (batch_id = {bid})")
    print("=" * 70)
    spark.sql(
        f"SELECT event_type, count(*) AS n, "
        f"count(DISTINCT user_id) AS users, count(DISTINCT session_id) AS sessions "
        f"FROM cdp.silver.demo_events WHERE batch_id = '{bid}' "
        f"GROUP BY event_type ORDER BY n DESC"
    ).show(50, truncate=False)

    print("=" * 70)
    print(f"QUARANTINE  cdp.silver.demo_quarantine  (batch_id = {bid})")
    print("=" * 70)
    spark.sql(
        f"SELECT event_type, quarantine_reason, count(*) AS n "
        f"FROM cdp.silver.demo_quarantine WHERE batch_id = '{bid}' GROUP BY 1, 2"
    ).show(50, truncate=False)

    print("=" * 70)
    print(f"GOLD  cdp.gold.demo_user_behavior  (batch_id = {bid})")
    print("=" * 70)
    spark.sql(
        f"SELECT user_id, event_count, page_views, product_views, searches, "
        f"add_to_cart, begin_checkout, purchases, cart_abandoned "
        f"FROM cdp.gold.demo_user_behavior WHERE batch_id = '{bid}' "
        f"ORDER BY event_count DESC LIMIT 10"
    ).show(20, truncate=False)

    print("=" * 70)
    print(f"GOLD  cdp.gold.demo_session_funnel  (batch_id = {bid})")
    print("=" * 70)
    spark.sql(
        f"SELECT SUM(step_view) AS sessions_viewed, "
        f"SUM(step_cart) AS sessions_cart, "
        f"SUM(step_checkout) AS sessions_checkout, "
        f"SUM(step_purchase) AS sessions_purchased, "
        f"SUM(step_abandoned) AS sessions_abandoned "
        f"FROM cdp.gold.demo_session_funnel WHERE batch_id = '{bid}'"
    ).show(truncate=False)

    print("=" * 70)
    print("Kiem tra chat luong: Silver khong con event failed")
    print("=" * 70)
    leftover = spark.sql(
        f"SELECT count(*) AS n FROM cdp.silver.demo_events "
        f"WHERE batch_id = '{bid}' AND payload IS NULL AND event_type = 'unknown'"
    ).collect()[0]["n"]
    print(json.dumps({"silver_unknown_payload_rows": leftover}))

    spark.stop()


if __name__ == "__main__":
    main()
