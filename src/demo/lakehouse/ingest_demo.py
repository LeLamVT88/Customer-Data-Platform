#!/usr/bin/env python3
"""
src/demo/lakehouse/ingest_demo.py — Nạp event từ Snowplow vào Iceberg (Lakehouse).

Snowplow đã thay toàn bộ tầng ingest thủ công. Luồng dữ liệu hiện tại:

    Web (Browser Tracker) ─┐
                           ├─▶ Snowplow Collector → Enrich → PostgreSQL
    Bot (TP2) ────────────┘                              │
                                                        ▼
                                    Spark (JDBC) → Iceberg Bronze/Silver/Gold
                                                        │
                                                        ▼
                                                 Demo API → Dashboard

Job này đọc trực tiếp bảng ``events`` (storage backend của Snowplow) qua JDBC.
Trong bảng đó, enriched event được lưu dưới dạng jsonb ở cột ``event_json``:

    event_json -> 'unstruct_event_com_cdp_demo_<event>_1'   : payload của event
    event_json -> 'contexts_com_cdp_demo_session_1'         : entity com.cdp.demo/session
    event_json -> 'contexts_com_cdp_demo_product_1'         : entity com.cdp.demo/product
    event_json -> 'page_url' / 'useragent' / 'collector_tstamp' / ...

Job ghi:

    cdp.bronze.demo_events        — enriched event nguyên bản
    cdp.silver.demo_events        — event hợp lệ, đã chuẩn hoá
    cdp.silver.demo_quarantine    — event lỗi (bad stream)
    cdp.gold.demo_user_behavior   — tổng hợp hành vi theo user
    cdp.gold.demo_session_funnel  — phễu hành vi theo session

Chạy bằng spark-submit (Spark phải nối được tới PostgreSQL của Snowplow):

    docker compose -f config/docker/compose.snowplow.yml up -d
    docker compose -f config/docker/compose.local-lakehouse.yml up -d --wait catalog storage
    docker compose -f config/docker/compose.local-lakehouse.yml run --rm spark \\
        /workspace/src/demo/lakehouse/ingest_demo.py --batch-id demo-local
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (
    ArrayType, DoubleType, IntegerType, StringType, StructField, StructType,
)

# Cho phép import helper của pipelines (write_batch, ensure_bucket).
_PIPELINES = Path(__file__).resolve().parents[2] / "pipelines" / "lakehouse"
sys.path.insert(0, str(_PIPELINES))

from common import ensure_bucket, write_batch  # noqa: E402

SQL_ROOT = Path(__file__).parent / "sql"

TABLES = {
    "bronze": "cdp.bronze.demo_events",
    "silver": "cdp.silver.demo_events",
    "quarantine": "cdp.silver.demo_quarantine",
    "user_behavior": "cdp.gold.demo_user_behavior",
    "session_funnel": "cdp.gold.demo_session_funnel",
}

# Event type hợp lệ — khớp config/snowplow/tools/build_schemas.py.
VALID_EVENT_TYPES = [
    "page_view", "product_view", "add_to_cart", "remove_from_cart",
    "begin_checkout", "purchase_observed", "element_click",
    "scroll_depth", "search", "error",
    "cart_abandoned", "apply_filter", "wishlist_add", "wishlist_remove",
    "newsletter_signup",
]

# ── Snowplow connection (JVM-side) ───────────────────────────────────────────

SNOWPLOW_JDBC_URL = "jdbc:postgresql://snowplow-postgres:5432/snowplow"
SNOWPLOW_JDBC_USER = "snowplow"
SNOWPLOW_JDBC_PASSWORD = "cdp-local-snowplow"

VENDOR_PREFIX = "com_cdp_demo"


# ── JSON schema cho payload / contexts ───────────────────────────────────────

ITEM_SCHEMA = StructType([
    StructField("product_id", StringType()),
    StructField("quantity", IntegerType()),
    StructField("price", StringType()),
    StructField("currency", StringType()),
])

PAYLOAD_SCHEMA = StructType([
    StructField("product_id", StringType()),
    StructField("category_id", StringType()),
    StructField("quantity", IntegerType()),
    StructField("price", StringType()),
    StructField("currency", StringType()),
    StructField("total_price", StringType()),
    StructField("query", StringType()),
    StructField("results_count", IntegerType()),
    StructField("depth_percent", DoubleType()),
    StructField("path", StringType()),
    StructField("title", StringType()),
    StructField("filter_type", StringType()),
    StructField("message", StringType()),
    StructField("email", StringType()),
    StructField("cart_id", StringType()),
    StructField("items", ArrayType(ITEM_SCHEMA)),
])

SESSION_SCHEMA = StructType([StructField("session_id", StringType())])

PRODUCT_SCHEMA = StructType([
    StructField("product_id", StringType()),
    StructField("category_id", StringType()),
    StructField("brand", StringType()),
    StructField("price", StringType()),
    StructField("currency", StringType()),
])


# ── Snowplow JSON helpers ────────────────────────────────────────────────────

def _payload_path(event_type: str) -> str:
    return f"$.unstruct_event_{VENDOR_PREFIX}_{event_type}_1"


def _session_path() -> str:
    return f"$.contexts_{VENDOR_PREFIX}_session_1"


def _product_path() -> str:
    return f"$.contexts_{VENDOR_PREFIX}_product_1"


def _payload_json(event_type_col: str = "event_name") -> "object":
    """
    Rút payload của từng event.

    Snowplow lưu mỗi loại self-describing event ở một cột phẳng riêng trong
    ``event_json`` (``unstruct_event_com_cdp_demo_<event>_1``), nên ta dựng
    CASE để lấy đúng cột theo tên event của từng dòng.
    """
    col = F.col(event_type_col)
    result = F.lit(None).cast("string")
    for event_type in reversed(VALID_EVENT_TYPES):
        result = F.when(
            col == event_type,
            F.get_json_object(F.col("event_json"), _payload_path(event_type)),
        ).otherwise(result)
    return result


def _session_array() -> "object":
    """Entity com.cdp.demo/session dạng array (đã parse từ jsonb)."""
    return F.from_json(
        F.get_json_object(F.col("event_json"), _session_path()),
        ArrayType(SESSION_SCHEMA),
    )


def _product_array() -> "object":
    """Entity com.cdp.demo/product dạng array (đã parse từ jsonb)."""
    return F.from_json(
        F.get_json_object(F.col("event_json"), _product_path()),
        ArrayType(PRODUCT_SCHEMA),
    )


def _session_id() -> "object":
    return _session_array()[0]["session_id"]


def _contexts_json() -> "object":
    """Gộp entity của app thành một chuỗi JSON để lưu ở Bronze/Quarantine."""
    return F.to_json(
        F.struct(
            _session_array().alias("session"),
            _product_array().alias("product"),
        )
    )


# ── Spark transformations ────────────────────────────────────────────────────

def read_snowplow_events(spark, since: datetime, app_id: str | None):
    """Đọc enriched event từ bảng ``events`` của Snowplow qua JDBC."""
    frame = (
        spark.read.format("jdbc")
        .option("url", SNOWPLOW_JDBC_URL)
        .option("dbtable", "events")
        .option("user", SNOWPLOW_JDBC_USER)
        .option("password", SNOWPLOW_JDBC_PASSWORD)
        .option("fetchsize", 10000)
        .load()
    )
    if app_id:
        frame = frame.filter(F.col("app_id") == app_id)
    # `timestamp` trong storage backend là timestamp without time zone (UTC).
    return frame.filter(F.col("timestamp") >= F.lit(since))


def build_bronze(spark, raw, batch_id: str):
    """Bronze: giữ nguyên enriched event, chỉ đổi tên cột cho thuận tiện."""
    return raw.select(
        F.col("event_id").cast("string").alias("event_id"),
        F.col("timestamp").cast("timestamp").alias("event_time"),
        F.coalesce(F.col("event_name"), F.lit("unknown")).cast("string").alias("event_type"),
        F.to_date(F.col("timestamp")).alias("event_date"),
        F.col("user_id").cast("string").alias("user_id"),
        _session_id().cast("string").alias("session_id"),
        F.lit("com.cdp.demo").alias("namespace"),
        F.col("app_id").cast("string").alias("app_id"),
        F.get_json_object(F.col("event_json"), "$.page_url").cast("string").alias("url"),
        F.get_json_object(F.col("event_json"), "$.page_referrer").cast("string").alias("referrer"),
        F.get_json_object(F.col("event_json"), "$.useragent").cast("string").alias("user_agent"),
        F.col("platform").cast("string").alias("platform"),
        F.col("name_tracker").cast("string").alias("name_tracker"),
        F.col("v_tracker").cast("string").alias("v_tracker"),
        F.get_json_object(F.col("event_json"), "$.collector_tstamp")
            .cast("timestamp").alias("collector_tstamp"),
        F.get_json_object(F.col("event_json"), "$.derived_tstamp")
            .cast("timestamp").alias("derived_tstamp"),
        F.get_json_object(F.col("event_json"), "$.dvce_sent_tstamp")
            .cast("timestamp").alias("device_sent_tstamp"),
        _payload_json().alias("payload"),
        _contexts_json().alias("contexts"),
        F.col("failed").cast("boolean").alias("failed"),
        F.lit(batch_id).alias("batch_id"),
    )


def build_silver(spark, bronze):
    """Silver: loại event lỗi, chuẩn hoá field, gắn quality_flags."""
    is_known_type = F.array_contains(F.lit(VALID_EVENT_TYPES), F.col("event_type"))
    missing_session = (F.col("session_id").isNull()) | (F.trim(F.col("session_id")) == "")
    missing_user = (F.col("user_id").isNull()) | (F.trim(F.col("user_id")) == "")
    invalid_time = F.col("event_time").isNull()

    flags = F.array_remove(
        F.array(
            F.when(~is_known_type, F.lit("unknown_event_type")).otherwise(F.lit(None)),
            F.when(missing_session, F.lit("missing_session")).otherwise(F.lit(None)),
            F.when(missing_user, F.lit("missing_user_id")).otherwise(F.lit(None)),
            F.when(invalid_time, F.lit("invalid_event_time")).otherwise(F.lit(None)),
        ),
        None,
    )

    payload = F.from_json(F.col("payload"), PAYLOAD_SCHEMA)
    product = F.from_json(F.col("contexts"), StructType([
        StructField("session", ArrayType(SESSION_SCHEMA)),
        StructField("product", ArrayType(PRODUCT_SCHEMA)),
    ]))

    product_id = F.coalesce(
        payload.getField("product_id"),
        product.getField("product")[0].getField("product_id"),
    )
    category_id = F.coalesce(
        payload.getField("category_id"),
        product.getField("product")[0].getField("category_id"),
    )
    currency = F.coalesce(
        payload.getField("currency"),
        product.getField("product")[0].getField("currency"),
    )
    quantity = F.when(
        F.col("event_type") == "add_to_cart", payload.getField("quantity")
    ).otherwise(F.lit(None).cast("int"))
    total_price = F.when(
        F.col("event_type").isin("begin_checkout", "purchase_observed", "cart_abandoned"),
        payload.getField("total_price").cast("decimal(18,2)"),
    ).otherwise(F.lit(None).cast("decimal(18,2)"))

    return bronze.filter(~F.col("failed")).select(
        F.col("event_id"),
        F.col("event_time"),
        F.col("event_type"),
        F.col("event_date"),
        F.coalesce(F.col("user_id"), F.lit("anonymous")).alias("user_id"),
        F.coalesce(F.col("session_id"), F.lit("unknown")).alias("session_id"),
        F.col("namespace"),
        F.col("app_id"),
        F.lit("snowplow").alias("source"),
        F.col("url"),
        F.col("referrer"),
        F.col("user_agent"),
        F.col("platform"),
        F.col("name_tracker"),
        F.col("v_tracker"),
        product_id.cast("string").alias("product_id"),
        category_id.cast("string").alias("category_id"),
        quantity.cast("int").alias("quantity"),
        total_price.alias("total_price"),
        currency.cast("string").alias("currency"),
        F.col("payload"),
        flags.alias("quality_flags"),
        F.col("collector_tstamp"),
        F.current_timestamp().alias("ingestion_time"),
        F.col("batch_id"),
    )


def build_quarantine(spark, raw, batch_id: str):
    """Quarantine: event mà Snowplow Enrich đánh dấu failed (bad stream)."""
    failure_context = F.get_json_object(
        F.col("event_json"),
        "$.contexts_com_snowplowanalytics_snowplow_failure_1",
    )
    return raw.filter(F.col("failed")).select(
        F.col("event_id").cast("string").alias("event_id"),
        F.col("timestamp").cast("timestamp").alias("event_time"),
        F.coalesce(F.col("event_name"), F.lit("unknown")).cast("string").alias("event_type"),
        F.to_date(F.col("timestamp")).alias("event_date"),
        F.col("user_id").cast("string").alias("user_id"),
        _session_id().cast("string").alias("session_id"),
        F.lit("com.cdp.demo").alias("namespace"),
        F.col("app_id").cast("string").alias("app_id"),
        F.lit("snowplow").alias("source"),
        F.get_json_object(F.col("event_json"), "$.page_url").cast("string").alias("url"),
        F.get_json_object(F.col("event_json"), "$.useragent").cast("string").alias("user_agent"),
        F.col("platform").cast("string").alias("platform"),
        _payload_json().alias("payload"),
        _contexts_json().alias("contexts"),
        F.array(F.lit("enrichment_failed")).alias("quality_flags"),
        F.lit("snowplow_enrichment_failed").alias("quarantine_reason"),
        failure_context.alias("failure_detail"),
        F.get_json_object(F.col("event_json"), "$.collector_tstamp")
            .cast("timestamp").alias("collector_tstamp"),
        F.current_timestamp().alias("ingestion_time"),
        F.lit(batch_id).alias("batch_id"),
    )


def build_user_behavior(spark, silver):
    """Gold: tổng hợp hành vi theo user + ngày."""
    return silver.groupBy(
        F.col("batch_id"), F.col("event_date"), F.col("user_id")
    ).agg(
        F.countDistinct("session_id").alias("session_count"),
        F.count(F.lit(1)).alias("event_count"),
        F.sum(F.when(F.col("event_type") == "page_view", 1).otherwise(0)).alias("page_views"),
        F.sum(F.when(F.col("event_type") == "product_view", 1).otherwise(0)).alias("product_views"),
        F.sum(F.when(F.col("event_type") == "search", 1).otherwise(0)).alias("searches"),
        F.sum(F.when(F.col("event_type") == "add_to_cart", 1).otherwise(0)).alias("add_to_cart"),
        F.sum(F.when(F.col("event_type") == "remove_from_cart", 1).otherwise(0)).alias("remove_from_cart"),
        F.sum(F.when(F.col("event_type") == "begin_checkout", 1).otherwise(0)).alias("begin_checkout"),
        F.sum(F.when(F.col("event_type") == "purchase_observed", 1).otherwise(0)).alias("purchases"),
        F.sum(F.when(F.col("event_type") == "cart_abandoned", 1).otherwise(0)).alias("cart_abandoned"),
        F.sum(F.when(F.col("event_type") == "wishlist_add", 1).otherwise(0)).alias("wishlist_add"),
        F.min("event_time").alias("first_event_at"),
        F.max("event_time").alias("last_event_at"),
    )


def build_session_funnel(spark, silver):
    """Gold: phễu hành vi theo session (mỗi bước sau bước trước)."""
    base = silver.select(
        F.col("batch_id"),
        F.col("event_date"),
        F.col("user_id"),
        F.col("session_id"),
        F.col("event_type"),
        F.col("event_time"),
    )
    sessions = base.groupBy(
        F.col("batch_id"), F.col("event_date"), F.col("user_id"), F.col("session_id")
    ).agg(
        F.min(F.when(F.col("event_type") == "product_view", F.col("event_time"))).alias("first_view_at"),
        F.min(F.when(F.col("event_type") == "add_to_cart", F.col("event_time"))).alias("first_cart_at"),
        F.min(F.when(F.col("event_type") == "begin_checkout", F.col("event_time"))).alias("first_checkout_at"),
        F.min(F.when(F.col("event_type") == "purchase_observed", F.col("event_time"))).alias("first_purchase_at"),
        F.min(F.when(F.col("event_type") == "cart_abandoned", F.col("event_time"))).alias("first_abandoned_at"),
    )
    return sessions.withColumn(
        "step_view", F.when(F.col("first_view_at").isNotNull(), F.lit(1)).otherwise(F.lit(0))
    ).withColumn(
        "step_cart",
        F.when(
            F.col("first_view_at").isNotNull()
            & F.col("first_cart_at").isNotNull()
            & (F.col("first_cart_at") > F.col("first_view_at")),
            F.lit(1),
        ).otherwise(F.lit(0)),
    ).withColumn(
        "step_checkout",
        F.when(
            F.col("first_cart_at").isNotNull()
            & F.col("first_checkout_at").isNotNull()
            & (F.col("first_checkout_at") > F.col("first_cart_at")),
            F.lit(1),
        ).otherwise(F.lit(0)),
    ).withColumn(
        "step_purchase",
        F.when(
            F.col("first_checkout_at").isNotNull()
            & F.col("first_purchase_at").isNotNull()
            & (F.col("first_purchase_at") > F.col("first_checkout_at")),
            F.lit(1),
        ).otherwise(F.lit(0)),
    ).withColumn(
        "step_abandoned",
        F.when(F.col("first_abandoned_at").isNotNull(), F.lit(1)).otherwise(F.lit(0)),
    ).select(
        F.col("batch_id"),
        F.col("event_date"),
        F.col("user_id"),
        F.col("session_id"),
        F.col("step_view"),
        F.col("step_cart"),
        F.col("step_checkout"),
        F.col("step_purchase"),
        F.col("step_abandoned"),
        F.col("first_view_at"),
        F.col("first_cart_at"),
        F.col("first_checkout_at"),
        F.col("first_purchase_at"),
        F.col("first_abandoned_at"),
    )


# ── DDL ──────────────────────────────────────────────────────────────────────

def create_tables(spark) -> None:
    """Tạo bảng Iceberg từ các file DDL trong sql/ (nếu chưa tồn tại)."""
    for namespace in ("bronze", "silver", "gold"):
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS cdp.{namespace}")
    for ddl in ("01_bronze.sql", "02_silver.sql", "03_gold.sql"):
        text = (SQL_ROOT / ddl).read_text(encoding="utf-8")
        for statement in [s.strip() for s in text.split(";")]:
            if statement and not statement.startswith("--"):
                spark.sql(statement)


# ── Main ─────────────────────────────────────────────────────────────────────

def run(spark, batch_id: str, since_hours: int, app_id: str | None) -> dict:
    started = perf_counter()
    print("Step 1/5: doc enriched event tu Snowplow PostgreSQL", flush=True)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    raw = read_snowplow_events(spark, since, app_id).cache()
    raw_count = raw.count()
    if raw_count == 0:
        raw.unpersist()
        raise SystemExit(
            f"Khong co event nao trong {since_hours} gio gan nhat. "
            "Hay chay bot hoac duyet web demo truoc."
        )
    print(f"  Doc {raw_count} enriched event", flush=True)

    ensure_bucket(spark)
    create_tables(spark)

    print("Step 2/5: ghi Bronze", flush=True)
    bronze = build_bronze(spark, raw, batch_id)
    write_batch(spark, bronze, TABLES["bronze"], batch_id)

    print("Step 3/5: tinh Silver + Quarantine", flush=True)
    stored_bronze = spark.table(TABLES["bronze"]).filter(F.col("batch_id") == batch_id)
    silver = build_silver(spark, stored_bronze)
    quarantine = build_quarantine(spark, raw, batch_id)
    write_batch(spark, silver, TABLES["silver"], batch_id)
    write_batch(spark, quarantine, TABLES["quarantine"], batch_id)

    print("Step 4/5: tinh Gold", flush=True)
    stored_silver = spark.table(TABLES["silver"]).filter(F.col("batch_id") == batch_id)
    write_batch(spark, build_user_behavior(spark, stored_silver), TABLES["user_behavior"], batch_id)
    write_batch(spark, build_session_funnel(spark, stored_silver), TABLES["session_funnel"], batch_id)

    print("Step 5/5: tong hop ket qua", flush=True)
    counts = {
        "bronze_rows": spark.table(TABLES["bronze"]).filter(F.col("batch_id") == batch_id).count(),
        "silver_rows": spark.table(TABLES["silver"]).filter(F.col("batch_id") == batch_id).count(),
        "quarantine_rows": spark.table(TABLES["quarantine"]).filter(F.col("batch_id") == batch_id).count(),
        "user_behavior_rows": spark.table(TABLES["user_behavior"]).filter(F.col("batch_id") == batch_id).count(),
        "session_funnel_rows": spark.table(TABLES["session_funnel"]).filter(F.col("batch_id") == batch_id).count(),
    }
    raw.unpersist()

    result = {
        "batch_id": batch_id,
        "source": "snowplow-postgres",
        "since_hours": since_hours,
        "counts": counts,
        "elapsed_s": round(perf_counter() - started, 2),
    }
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Nap event tu Snowplow vao Iceberg")
    parser.add_argument("--batch-id", default="demo-local",
                        help="Dinh danh batch (moi lan chay = 1 batch)")
    parser.add_argument("--since-hours", type=int, default=24,
                        help="Cua so thoi gian lay event (gio)")
    parser.add_argument("--app-id", default="cdp-demo",
                        help="Chi lay event cua app_id nay; de rong = tat ca")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", args.batch_id):
        raise SystemExit("batch-id khong hop le")

    spark = SparkSession.builder.appName("cdp-demo-snowplow-lakehouse").getOrCreate()
    try:
        run(spark, args.batch_id, args.since_hours, args.app_id or None)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
