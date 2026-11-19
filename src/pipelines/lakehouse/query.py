"""Query the lakehouse from the command line.

Usage:
    .venv\\Scripts\\python.exe src/pipelines/lakehouse/query.py "SELECT COUNT(*) FROM cdp.bronze.rees46_events"
    .venv\\Scripts\\python.exe src/pipelines/lakehouse/query.py --file scripts.sql
    .venv\\Scripts\\python.exe src/pipelines/lakehouse/query.py --tables
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lakehouse.session import build_session  # noqa: E402


def show(spark, statement: str) -> None:
    print(f"\n>>> {statement.strip()}")
    rows = spark.sql(statement).collect()
    if not rows:
        print("(no rows)")
        return
    columns = rows[0].asDict().keys()
    widths = {c: max(len(str(c)), *(len(str(r[c])) for r in rows)) for c in columns}
    header = " | ".join(str(c).ljust(widths[c]) for c in columns)
    print(header)
    print("-+-".join("-" * widths[c] for c in columns))
    for row in rows:
        print(" | ".join(str(row[c]).ljust(widths[c]) for c in columns))
    print(f"({len(rows)} rows)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Query the local Iceberg lakehouse.")
    parser.add_argument("sql", nargs="?", help="SQL statement to run")
    parser.add_argument("--file", type=Path, help="SQL file to run")
    parser.add_argument("--tables", action="store_true", help="List namespaces and tables")
    args = parser.parse_args()

    if not args.sql and not args.file and not args.tables:
        parser.error("provide a SQL statement, --file or --tables")

    spark = build_session("lakehouse-query")

    if args.tables:
        for namespace in spark.sql("SHOW NAMESPACES IN cdp").collect():
            print(f"\n{namespace.namespace}")
            for table in spark.sql(f"SHOW TABLES IN cdp.{namespace.namespace}").collect():
                detail = spark.sql(f"DESCRIBE TABLE cdp.{namespace.namespace}.{table.tableName}").collect()
                partition = next((d for d in detail if d.data_type == "partition"), None)
                print(f"  {table.tableName:<24} {partition.col_name if partition else '(unpartitioned)'}")

    if args.file:
        show(spark, args.file.read_text(encoding="utf-8"))

    if args.sql:
        show(spark, args.sql)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
