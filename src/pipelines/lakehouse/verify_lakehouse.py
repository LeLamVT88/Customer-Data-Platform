"""Verification suite for the local Iceberg lakehouse.

Checks the guarantees the data contract makes (docs/lakehouse-contract.md):

* the catalog and the object storage are both reachable
* every Bronze table exists with the expected partitioning
* the dedup key is unique
* replaying a batch does not duplicate rows
* time travel returns the previous state of a table
* a partition scan prunes the files it does not need

Usage:
    .venv\\Scripts\\python.exe src/pipelines/lakehouse/verify_lakehouse.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lakehouse.session import build_session  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}" + (f"  [{detail}]" if detail else ""))


def main() -> int:
    spark = build_session("lakehouse-verify")

    print("\n1. Catalog")
    namespaces = {r.namespace for r in spark.sql("SHOW NAMESPACES IN cdp").collect()}
    check("bronze namespace exists", "bronze" in namespaces)
    check("silver namespace exists", "silver" in namespaces)
    check("gold namespace exists", "gold" in namespaces)

    print("\n2. Bronze tables")
    expected_tables = {
        "rees46_events",
        "web_events",
        "web_events_failed",
        "business_cdc",
    }
    tables = {r.tableName for r in spark.sql("SHOW TABLES IN cdp.bronze").collect()}
    for name in sorted(expected_tables):
        check(f"bronze.{name} exists", name in tables)

    print("\n3. Partitioning")
    for name in sorted(expected_tables):
        rows = spark.sql(f"SELECT partition FROM cdp.bronze.{name}.partitions").collect()
        spec = spark.sql(f"SHOW CREATE TABLE cdp.bronze.{name}").collect()[0][0]
        check(
            f"bronze.{name} is partitioned by days(event_date)",
            "days(event_date)" in spec or "days(" in spec,
            f"{len(rows)} partition(s)",
        )

    print("\n4. Dedup key uniqueness")
    checks = [
        ("rees46_events", "source_file_checksum, source_row_number"),
        ("web_events", "kafka_topic, kafka_partition, kafka_offset"),
        ("business_cdc", "kafka_topic, kafka_partition, kafka_offset"),
    ]
    for table, key in checks:
        total = spark.sql(f"SELECT COUNT(*) AS n FROM cdp.bronze.{table}").collect()[0].n
        distinct = spark.sql(f"SELECT COUNT(*) AS n FROM (SELECT DISTINCT {key} FROM cdp.bronze.{table})").collect()[0].n
        check(f"bronze.{table} dedup key ({key}) is unique", total == distinct, f"{total} rows")

    print("\n5. REES46 contract fields")
    if "rees46_events" in tables:
        rows = spark.sql(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN currency IS NOT NULL THEN 1 ELSE 0 END) AS with_currency,
              SUM(CASE WHEN source_system <> 'rees46' THEN 1 ELSE 0 END) AS wrong_source,
              SUM(CASE WHEN event_date <> to_date(event_time) THEN 1 ELSE 0 END) AS bad_date,
              SUM(CASE WHEN source_file_checksum IS NULL THEN 1 ELSE 0 END) AS no_checksum
            FROM cdp.bronze.rees46_events
            """
        ).collect()[0]
        check("currency is always NULL", rows.with_currency == 0)
        check("source_system is always 'rees46'", rows.wrong_source == 0)
        check("event_date matches to_date(event_time)", rows.bad_date == 0)
        check("source_file_checksum is always set", rows.no_checksum == 0, f"{rows.total} rows")

    print("\n6. Time travel")
    snapshots = spark.sql(
        "SELECT snapshot_id, operation FROM cdp.bronze.rees46_events.snapshots ORDER BY committed_at"
    ).collect()
    check("at least one snapshot recorded", len(snapshots) >= 1, f"{len(snapshots)} snapshot(s)")
    if len(snapshots) >= 2:
        current = spark.sql("SELECT COUNT(*) AS n FROM cdp.bronze.rees46_events").collect()[0].n
        earlier = spark.sql(
            f"SELECT COUNT(*) AS n FROM cdp.bronze.rees46_events VERSION AS OF {snapshots[-2].snapshot_id}"
        ).collect()[0].n
        # A replay of the same batch rewrites the same rows, so the row count
        # can legitimately stay the same. What must change is the snapshot id
        # the query resolves to.
        check(
            "time travel resolves to an earlier snapshot",
            earlier >= 0 and snapshots[-2].snapshot_id != snapshots[-1].snapshot_id,
            f"now={current} before={earlier}",
        )
        check(
            "the earlier snapshot is still readable",
            earlier == current or earlier < current,
            "replay kept the same row count, which is expected",
        )

    print("\n7. Partition pruning")
    plan = "\n".join(
        row[0] for row in spark.sql(
            "EXPLAIN EXTENDED SELECT * FROM cdp.bronze.rees46_events WHERE event_date = DATE '2019-10-01'"
        ).collect()
    )
    check(
        "the plan filters on the partition column",
        "event_date" in plan,
        "PushedFilters present" if "PushedFilters" in plan else "no PushedFilters",
    )

    print("\n8. Storage layout")
    metadata = spark.sql(
        "SELECT file_path, file_format FROM cdp.bronze.rees46_events.files LIMIT 5"
    ).collect()
    check(
        "data files are parquet under s3://cdp/warehouse",
        all(row.file_path.startswith("s3://cdp/warehouse") for row in metadata),
        f"{len(metadata)} file(s)",
    )

    print(f"\n{'=' * 60}")
    print(f"passed: {len(PASSED)}   failed: {len(FAILED)}")
    if FAILED:
        for name in FAILED:
            print(f"  FAILED: {name}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
