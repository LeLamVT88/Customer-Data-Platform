"""Apply the DDL files in ``sql/`` against the local Iceberg catalog.

Usage:
    .venv\\Scripts\\python.exe src/pipelines/lakehouse/apply_ddl.py
    .venv\\Scripts\\python.exe src/pipelines/lakehouse/apply_ddl.py --file 01_bronze.sql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lakehouse.session import build_session  # noqa: E402

SQL_DIR = Path(__file__).resolve().parent / "sql"


def strip_comments(line: str) -> str:
    """Remove a trailing SQL comment from a line.

    Inline comments matter here: the DDL documents the allowed values of
    ``op`` as ``-- c | u | d | r``. When such a line is joined into a single
    statement, everything after the dashes becomes a comment and the rest of
    the statement is silently dropped.
    """
    marker = line.find("--")
    if marker == -1:
        return line
    return line[:marker].strip()


def split_statements(sql: str) -> list[str]:
    """Split a SQL file into statements, ignoring comment-only lines."""
    statements: list[str] = []
    current: list[str] = []
    for raw_line in sql.splitlines():
        line = strip_comments(raw_line.strip())
        if not line:
            continue
        current.append(line)
        if line.endswith(";"):
            statements.append(" ".join(current).rstrip(";").strip())
            current = []
    if current:
        statements.append(" ".join(current).strip())
    return statements


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the lakehouse DDL.")
    parser.add_argument("--file", default="01_bronze.sql", help="SQL file inside src/pipelines/lakehouse/sql")
    args = parser.parse_args()

    sql_path = SQL_DIR / args.file
    if not sql_path.exists():
        print(f"SQL file not found: {sql_path}", file=sys.stderr)
        return 1

    spark = build_session("lakehouse-apply-ddl")
    statements = split_statements(sql_path.read_text(encoding="utf-8"))
    print(f"Applying {len(statements)} statements from {args.file}")

    for statement in statements:
        spark.sql(statement).collect()
        head = " ".join(statement.split())[:70]
        print(f"  ok  {head}")

    print()
    for namespace in spark.sql("SHOW NAMESPACES IN cdp").collect():
        print(f"namespace {namespace.namespace}")
        for table in spark.sql(f"SHOW TABLES IN cdp.{namespace.namespace}").collect():
            print(f"  table {namespace.namespace}.{table.tableName}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
