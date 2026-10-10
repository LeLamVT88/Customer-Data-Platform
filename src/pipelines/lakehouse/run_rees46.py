#!/usr/bin/env python3
"""Verified local batch -> Iceberg Bronze -> recomputed Silver -> Gold.

Run with spark-submit through src/tools/run_local_lakehouse.sh.
The DuckDB prototype is an independent Silver/quarantine reference.
"""

import argparse
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from pyspark import StorageLevel
from pyspark.sql import SparkSession, functions as F
from common import assert_same_rows, ensure_bucket, write_batch

SQL_ROOT = Path(__file__).parent / "sql"
ROOT = Path(__file__).resolve().parents[3]
TABLES = {
    "bronze": "cdp.bronze.rees46_events",
    "silver": "cdp.silver.rees46_events",
    "quarantine": "cdp.silver.rees46_quarantine",
    "daily_events": "cdp.gold.rees46_daily_events",
    "user_behavior": "cdp.gold.rees46_user_behavior",
    "session_funnel": "cdp.gold.rees46_session_funnel",
}


def verify_batch(batch):
    """Reject changed local artifacts before any Iceberg write."""
    manifest = json.loads((batch / "manifest.json").read_text())
    batch_id = manifest["batch_id"]
    if not re.fullmatch(r"[a-f0-9]{64}", batch_id):
        raise ValueError("Invalid batch ID")
    if manifest["specification"]["source_namespace"] != "rees46.marketplace":
        raise ValueError("Expected a REES46 batch")
    required = {"bronze.parquet", "silver.parquet", "quarantine.parquet", "selected-users.json"}
    if set(manifest["output_sha256"]) != required:
        raise ValueError("Unexpected manifest output files")
    for name, expected in manifest["output_sha256"].items():
        digest = hashlib.sha256()
        with (batch / name).open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"Changed local output: {name}")
    return manifest


def query(spark, name):
    return spark.sql((SQL_ROOT / f"{name}.sql").read_text())


def read_batch(spark, table, batch_id):
    return spark.table(table).filter(F.col("batch_id") == batch_id)


def run(spark, batch, report_root):
    started = perf_counter()
    print("Step 1/5: verify local batch and initialize storage", flush=True)
    manifest = verify_batch(batch)
    batch_id = manifest["batch_id"]
    if manifest["specification"]["selection"] == "all_source_records":
        # Keep full-month shuffle partitions small enough for four concurrent tasks.
        spark.conf.set("spark.sql.shuffle.partitions", "128")
        spark.conf.set("spark.sql.adaptive.coalescePartitions.enabled", "false")
    ensure_bucket(spark)
    for namespace in ("bronze", "silver", "gold"):
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS cdp.{namespace}")

    # Bronze imports the original parsed payload + source identity, not Silver.
    print("Step 2/5: write and reconcile Iceberg Bronze", flush=True)
    bronze_input = spark.read.parquet(str(batch / "bronze.parquet"))
    if bronze_input.filter((F.col("batch_id") != batch_id) | F.col("batch_id").isNull()).limit(1).count():
        raise ValueError("Bronze rows have an unexpected batch ID")
    if bronze_input.select("event_id").distinct().count() != bronze_input.count():
        raise ValueError("Bronze event IDs are not unique")
    write_batch(spark, bronze_input, TABLES["bronze"], batch_id)
    bronze = read_batch(spark, TABLES["bronze"], batch_id)
    assert_same_rows(bronze, bronze_input, "persisted Bronze")
    bronze.createOrReplaceTempView("source_bronze")

    # Spark applies the REES46 rules again; DuckDB output is only the oracle.
    print("Step 3/5: compute and reconcile Silver/quarantine", flush=True)
    # Wide raw payloads in checked are retained for quarantine. Use disk-backed
    # caching for large batches to avoid competing with join/aggregate heap.
    cache_level = StorageLevel.DISK_ONLY if manifest["counts"]["bronze_rows"] > 1000000 else StorageLevel.MEMORY_AND_DISK
    checked = query(spark, "checked").persist(cache_level)
    try:
        checked.createOrReplaceTempView("checked_events")
        silver = query(spark, "silver")
        quarantine = checked.filter(F.size("error_reasons") > 0)
        silver_reference = spark.read.parquet(str(batch / "silver.parquet"))
        quarantine_reference = spark.read.parquet(str(batch / "quarantine.parquet"))
        assert_same_rows(silver, silver_reference, "Spark Silver vs DuckDB")
        # Quarantine has extra parsed columns; compare original identity/reasons/flags.
        columns = ["event_id", "source_row_number", "raw_payload", "error_reasons", "quality_flags"]
        assert_same_rows(quarantine.select(columns), quarantine_reference.select(columns), "quarantine")
        counts = {"bronze_rows": bronze.count(), "silver_rows": silver.count(),
                  "quarantine_rows": quarantine.count()}
        if counts != manifest["counts"] or counts["bronze_rows"] != counts["silver_rows"] + counts["quarantine_rows"]:
            raise AssertionError("Batch row reconciliation failed")
        write_batch(spark, silver, TABLES["silver"], batch_id)
        write_batch(spark, quarantine, TABLES["quarantine"], batch_id)
        assert_same_rows(read_batch(spark, TABLES["silver"], batch_id), silver_reference, "persisted Silver")
        assert_same_rows(read_batch(spark, TABLES["quarantine"], batch_id).select(columns),
                         quarantine_reference.select(columns), "persisted quarantine")
    finally:
        checked.unpersist()

    print("Step 4/5: compute and write Gold", flush=True)
    stored_silver = read_batch(spark, TABLES["silver"], batch_id)
    stored_silver.createOrReplaceTempView("source_silver")
    for name in ("daily_events", "user_behavior", "session_funnel"):
        gold = query(spark, name)
        write_batch(spark, gold, TABLES[name], batch_id)
        assert_same_rows(read_batch(spark, TABLES[name], batch_id), gold, f"persisted {name}")

    # An independent DuckDB aggregation checks Gold keys and values.
    print("Step 5/5: independent Gold reconciliation and report", flush=True)
    from reference import verify_gold
    verify_gold(spark, batch, batch_id, TABLES)
    funnel = read_batch(spark, TABLES["session_funnel"], batch_id)
    funnel_counts = funnel.agg(
        F.count("*").alias("sessions_total"),
        F.count(F.when(F.col("has_view"), 1)).alias("sessions_with_view"),
        F.count(F.when(F.col("has_cart_after_view"), 1)).alias("sessions_with_cart_after_view"),
        F.count(F.when(F.col("has_purchase_after_cart"), 1)).alias("sessions_with_purchase_after_cart"),
    ).first().asDict()
    funnel_counts["excluded_missing_session_events"] = stored_silver.filter(
        F.col("source_session_id").isNull() | (F.trim("source_session_id") == "")).count()
    # Only a single aggregate row is collected; data files are read from Iceberg metadata.
    storage = {}
    for name, table in TABLES.items():
        files = spark.table(f"{table}.files").filter(F.col("partition.batch_id") == batch_id)
        storage[name] = files.agg(F.count("*").alias("file_count"),
                                  F.coalesce(F.sum("file_size_in_bytes"), F.lit(0)).alias("data_bytes")).first().asDict()
    report = {
        "run_id": uuid.uuid4().hex, "batch_id": batch_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed", "counts": counts,
        "funnel": funnel_counts, "iceberg_data_files": storage,
        "input_bytes": sum((batch / name).stat().st_size for name in manifest["output_sha256"]),
        "runtime": {"spark_version": spark.version, "master": spark.sparkContext.master,
                    "driver_memory": spark.sparkContext.getConf().get("spark.driver.memory"),
                    "shuffle_partitions": spark.conf.get("spark.sql.shuffle.partitions")},
        "tables": {name: {"name": table, "batch_rows": read_batch(spark, table, batch_id).count()}
                   for name, table in TABLES.items()},
        "checks": ["input checksums", "Bronze exact rows", "Silver values vs DuckDB",
                   "quarantine reasons", "Gold values vs DuckDB", "row reconciliation"],
    }
    report["elapsed_seconds"] = round(perf_counter() - started, 3)
    report_root.mkdir(parents=True, exist_ok=True)
    path = report_root / f"{batch_id}-{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"Report: {path}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, default=ROOT / "data/reports/lakehouse")
    args = parser.parse_args()
    spark = SparkSession.builder.appName("cdp-rees46-batch").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    try:
        run(spark, args.batch.resolve(strict=True), args.report_root)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
