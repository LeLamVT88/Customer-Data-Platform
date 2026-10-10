"""Independent DuckDB Gold oracle, exported to Parquet for distributed comparison.

No user/session-level result is collected into Python memory. DuckDB can spill
aggregations to disk; Spark checks key uniqueness and compares every column.
"""
import tempfile
from pathlib import Path
import duckdb
from pyspark.sql import functions as F
from common import assert_same_rows

REFERENCE_SQL = {
    "daily_events": """
        SELECT batch_id, source_namespace, cast(event_at AS DATE) AS event_date,
               event_name, count(*) AS event_count, count(DISTINCT source_user_id) AS user_count
        FROM events GROUP BY 1, 2, 3, 4
    """,
    "user_behavior": """
        SELECT batch_id, source_namespace, source_user_id,
               cast(min(event_at) AS TIMESTAMP) AS first_seen_at,
               cast(max(event_at) AS TIMESTAMP) AS last_seen_at, count(*) AS event_count,
               count(DISTINCT CASE WHEN trim(source_session_id) <> '' THEN source_session_id END) AS session_count,
               count(*) FILTER (WHERE event_name='product_view') AS view_count,
               count(*) FILTER (WHERE event_name='add_to_cart') AS cart_count,
               count(*) FILTER (WHERE event_name='purchase_observed') AS purchase_event_count
        FROM events GROUP BY 1, 2, 3
    """,
    # Different implementation: correlated subqueries instead of the Spark joins.
    "session_funnel": """
        WITH views AS (
            SELECT batch_id, source_namespace, source_user_id, source_session_id,
                   min(event_at) FILTER (WHERE event_name='product_view') AS first_view_at
            FROM events WHERE source_session_id IS NOT NULL AND trim(source_session_id) <> ''
            GROUP BY 1, 2, 3, 4
        ), carts AS (
            SELECT v.*, (
                SELECT min(e.event_at) FROM events e
                WHERE e.batch_id=v.batch_id AND e.source_namespace=v.source_namespace
                  AND e.source_user_id=v.source_user_id AND e.source_session_id=v.source_session_id
                  AND e.event_name='add_to_cart' AND e.event_at > v.first_view_at
            ) AS first_cart_after_view_at FROM views v
        ), purchases AS (
            SELECT c.*, (
                SELECT min(e.event_at) FROM events e
                WHERE e.batch_id=c.batch_id AND e.source_namespace=c.source_namespace
                  AND e.source_user_id=c.source_user_id AND e.source_session_id=c.source_session_id
                  AND e.event_name='purchase_observed' AND e.event_at > c.first_cart_after_view_at
            ) AS first_purchase_after_cart_at FROM carts c
        )
        SELECT batch_id, source_namespace, source_user_id, source_session_id,
               cast(first_view_at AS TIMESTAMP) AS first_view_at,
               cast(first_cart_after_view_at AS TIMESTAMP) AS first_cart_after_view_at,
               cast(first_purchase_after_cart_at AS TIMESTAMP) AS first_purchase_after_cart_at,
               first_view_at IS NOT NULL AS has_view,
               first_cart_after_view_at IS NOT NULL AS has_cart_after_view,
               first_purchase_after_cart_at IS NOT NULL AS has_purchase_after_cart
        FROM purchases
    """,
}


def verify_gold(spark, batch, batch_id, tables):
    with tempfile.TemporaryDirectory(dir=str(batch.parent)) as temporary:
        root = Path(temporary)
        db = duckdb.connect()
        try:
            db.execute("SET TimeZone='UTC'")
            db.execute("SET memory_limit='512MB'")
            db.execute("SET threads=2")
            # Bound memory use and allow spill during full-file aggregations.
            spill_path = str(root / "spill").replace("'", "''")
            db.execute(f"SET temp_directory='{spill_path}'")
            db.read_parquet(str(batch / "silver.parquet")).create_view("events")
            for name, sql in REFERENCE_SQL.items():
                destination = root / f"{name}.parquet"
                escaped_path = str(destination).replace("'", "''")
                db.execute(f"COPY ({sql}) TO '{escaped_path}' (FORMAT PARQUET)")
                actual = spark.table(tables[name]).filter(F.col("batch_id") == batch_id)
                expected = spark.read.parquet(str(destination))
                assert_same_rows(actual, expected, f"Gold {name} vs independent DuckDB")
        finally:
            db.close()
