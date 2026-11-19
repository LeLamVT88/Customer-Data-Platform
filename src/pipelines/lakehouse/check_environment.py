"""Smoke test: does the local lakehouse wiring actually work?

Run from the repository root:

    .venv\\Scripts\\python.exe src/pipelines/lakehouse/check_environment.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lakehouse.session import build_session  # noqa: E402


def main() -> int:
    spark = build_session("lakehouse-check")
    print(f"Spark version : {spark.version}")

    # 1. Catalog reachable and empty.
    namespaces = [row.namespace for row in spark.sql("SHOW NAMESPACES IN cdp").collect()]
    print(f"Namespaces    : {namespaces}")

    # 2. Object storage reachable.
    spark.sql("CREATE NAMESPACE IF NOT EXISTS cdp.bronze").collect()
    print("Namespace cdp.bronze created")

    # 3. Write and read a tiny table through Iceberg.
    spark.sql(
        """
        CREATE TABLE IF NOT EXISTS cdp.bronze.smoke_check (
            id BIGINT,
            label STRING
        ) USING iceberg
        TBLPROPERTIES ('format-version' = '2')
        """
    ).collect()

    spark.sql(
        "INSERT INTO cdp.bronze.smoke_check VALUES (1, 'hello'), (2, 'lakehouse')"
    ).collect()

    rows = spark.sql("SELECT * FROM cdp.bronze.smoke_check ORDER BY id").collect()
    print(f"Rows          : {[r.label for r in rows]}")

    # 4. Time travel: the pre-insert snapshot must be empty.
    snapshots = spark.sql("SELECT snapshot_id FROM cdp.bronze.smoke_check.snapshots").collect()
    print(f"Snapshots     : {[s.snapshot_id for s in snapshots]}")
    if len(snapshots) >= 2:
        before = spark.sql(
            f"SELECT COUNT(*) AS n FROM cdp.bronze.smoke_check VERSION AS OF {snapshots[-2].snapshot_id}"
        ).collect()[0].n
        print(f"Rows before   : {before}")

    spark.sql("DROP TABLE cdp.bronze.smoke_check").collect()
    spark.sql("DROP NAMESPACE cdp.bronze").collect()
    print("OK: catalog + storage + Iceberg write/read all work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
