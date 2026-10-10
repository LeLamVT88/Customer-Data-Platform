#!/usr/bin/env python3
"""Export one batch's Gold tables to CSV for inspection in the IDE."""
import argparse
import csv
import re
from pathlib import Path
from pyspark.sql import SparkSession, functions as F
from run_rees46 import TABLES, ROOT


def export(spark, batch_id, output_root):
    if not re.fullmatch(r"[a-f0-9]{64}", batch_id):
        raise ValueError("Invalid batch ID")
    destination = output_root / batch_id
    destination.mkdir(parents=True, exist_ok=True)
    ordering = {
        "daily_events": ["event_date", "event_name"],
        "user_behavior": [F.desc("event_count"), "source_user_id"],
        "session_funnel": ["source_user_id", "source_session_id"],
    }
    for name, columns in ordering.items():
        frame = spark.table(TABLES[name]).filter(F.col("batch_id") == batch_id).orderBy(*columns)
        path = destination / f"{name}.csv"
        pending = path.with_suffix(".csv.pending")
        try:
            count = 0
            with pending.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(frame.columns)
                # Stream partitions rather than collecting all users/sessions into Python.
                for row in frame.toLocalIterator():
                    writer.writerow(row)
                    count += 1
            pending.replace(path)
            print(f"Exported {count} rows: {path}")
        finally:
            pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/reports/gold")
    args = parser.parse_args()
    spark = SparkSession.builder.appName("cdp-export-gold").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    try:
        export(spark, args.batch_id, args.output_root)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
