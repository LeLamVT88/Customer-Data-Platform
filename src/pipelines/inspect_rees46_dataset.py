#!/usr/bin/env python3
"""Inspect REES46 without loading the CSV into a Python dataframe."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import duckdb


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "data/REES46/2019-Oct.csv"
EXPECTED = [
    "event_time", "event_type", "product_id", "category_id", "category_code",
    "brand", "price", "user_id", "user_session",
]


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Must be greater than zero")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="Export the first N rows for viewing")
    sample.add_argument("--rows", type=positive, default=1000)
    sample.add_argument("--output", type=Path, default=ROOT / "data/REES46/preview.csv")
    profile = commands.add_parser("profile", help="Profile a prefix or the full CSV")
    scope = profile.add_mutually_exclusive_group()
    scope.add_argument("--limit", type=positive, default=100000)
    scope.add_argument("--full", action="store_true")
    profile.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    source = args.source.expanduser().resolve(strict=True)
    output = args.output
    if output is None:
        suffix = "full" if args.full else f"first-{args.limit}"
        output = ROOT / f"data/reports/rees46-{suffix}.json"
    output = output.expanduser().resolve()
    if output == source:
        parser.error("Output cannot overwrite the source CSV")
    if output.exists():
        parser.error(f"Output already exists; choose another --output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = ROOT / ".cache/duckdb"
    temporary.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    try:
        db.execute("SET memory_limit = '512MB'")
        db.execute("SET threads = 2")
        db.execute(f"SET temp_directory = {literal(temporary)}")
        db.execute("SET TimeZone = 'UTC'")
        db.execute(
            "CREATE VIEW source AS SELECT * FROM read_csv("
            f"{literal(source)}, header=true, all_varchar=true, nullstr='', "
            "sample_size=20480, ignore_errors=false)"
        )
        fields = [row[0] for row in db.execute("DESCRIBE source").fetchall()]
        if fields != EXPECTED:
            raise ValueError(f"Unexpected schema: {fields}; expected: {EXPECTED}")
        start = perf_counter()
        if args.command == "sample":
            db.execute(
                f"COPY (SELECT * FROM source LIMIT {args.rows}) "
                f"TO {literal(output)} (HEADER, DELIMITER ',')"
            )
            print(f"Preview written to {output}")
            print("This is a prefix, not a representative or session-complete sample.")
            return
        limit = "" if args.full else f" LIMIT {args.limit}"
        db.execute(f"CREATE VIEW inspected AS SELECT * FROM source{limit}")
        missing = [
            f'count(*) FILTER (WHERE "{field}" IS NULL OR trim("{field}") = \'\') AS missing_{field}'
            for field in fields
        ]
        metrics = [
            "count(*) AS rows",
            "cast(min(try_cast(event_time AS TIMESTAMPTZ)) AS VARCHAR) AS earliest_event_utc",
            "cast(max(try_cast(event_time AS TIMESTAMPTZ)) AS VARCHAR) AS latest_event_utc",
            "count(*) FILTER (WHERE event_time IS NOT NULL AND try_cast(event_time AS TIMESTAMPTZ) IS NULL) AS invalid_timestamp_rows",
            "min(try_cast(price AS DOUBLE)) AS minimum_price",
            "max(try_cast(price AS DOUBLE)) AS maximum_price",
            "count(*) FILTER (WHERE price IS NOT NULL AND (try_cast(price AS DOUBLE) IS NULL OR NOT isfinite(try_cast(price AS DOUBLE)))) AS invalid_price_rows",
            "count(*) FILTER (WHERE try_cast(price AS DOUBLE) < 0) AS negative_price_rows",
            "count(*) FILTER (WHERE try_cast(price AS DOUBLE) = 0) AS zero_price_rows",
            "approx_count_distinct(user_id) AS approximate_users",
            "approx_count_distinct(user_session) AS approximate_sessions",
            "approx_count_distinct(product_id) AS approximate_products",
        ]
        print("Profiling full file..." if args.full else f"Profiling first {args.limit:,} rows...", flush=True)
        cursor = db.execute("SELECT " + ", ".join(metrics + missing) + " FROM inspected")
        summary = dict(zip([column[0] for column in cursor.description], cursor.fetchone()))
        events = db.execute(
            "SELECT event_type, count(*) AS rows FROM inspected GROUP BY event_type ORDER BY rows DESC"
        ).fetchall()
        count = summary["rows"]
        report = {
            "source": str(source),
            "source_bytes": source.stat().st_size,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "duckdb_version": duckdb.__version__,
            "scope": "full_file" if args.full else "first_rows_not_representative",
            "requested_limit": None if args.full else args.limit,
            "fields": fields,
            "summary": summary,
            "event_types": [
                {"event_type": event, "rows": n, "percentage": round(100 * n / count, 4) if count else None}
                for event, n in events
            ],
            "missing_percentages": {
                field: round(100 * summary[f"missing_{field}"] / count, 4) if count else None
                for field in fields
            },
            "elapsed_seconds": round(perf_counter() - start, 3),
            "notes": [
                "Distinct counts are approximate, exclude NULL, and are not acceptance-test ground truth.",
                "Missing means NULL or blank after trimming. No rows are deliberately skipped.",
                "Prices use DOUBLE for exploration only; business calculations require decimal and documented currency.",
                "No duplicate, identity, transaction, or whole-file checksum validation is performed here.",
            ],
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
        output.write_text(encoded, encoding="utf-8")
        print(encoded)
        print(f"Report written to {output}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
