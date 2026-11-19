"""Ingest a REES46 monthly CSV into ``cdp.bronze.rees46_events``.

The CSV is 5.6 GB / 42.4M rows, so it is never loaded into a Python
dataframe. DuckDB streams it with a 512 MB memory limit and writes Parquet
files into a temporary directory; Spark then reads that Parquet and writes it
into Iceberg.

The write is idempotent: ``overwrite(batch_id == ...)`` replaces only the rows
of the batch being ingested, so re-running the job never duplicates data and
never touches another batch.

Usage:
    .venv\\Scripts\\python.exe src/pipelines/lakehouse/ingest_rees46.py \\
        --source data/REES46/2019-Oct.csv --batch-id rees46-2019-10-v1
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lakehouse.session import build_session  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = REPO_ROOT / "data" / "REES46" / "2019-Oct.csv"
DEFAULT_TABLE = "cdp.bronze.rees46_events"

# REES46 columns, in source order.
REES46_COLUMNS = [
    "event_time",
    "event_type",
    "product_id",
    "category_id",
    "category_code",
    "brand",
    "price",
    "user_id",
    "user_session",
]


def file_checksum(path: Path, chunk_size: int = 1 << 20) -> str:
    """Return the sha256 of the source file, used as the dedup fingerprint."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_with_duckdb(source: Path, workdir: Path) -> tuple[Path, int]:
    """Convert the CSV into Parquet with DuckDB and report the row count.

    Returns the staging directory and the number of rows written.
    """
    import duckdb

    staging = workdir / "staging"
    staging.mkdir(parents=True, exist_ok=True)

    db = duckdb.connect()
    try:
        db.execute("SET memory_limit = '512MB'")
        db.execute("SET threads = 2")
        db.execute(f"SET temp_directory = '{str(workdir / 'duckdb-temp').replace(chr(92), '/')}'")
        db.execute("SET TimeZone = 'UTC'")
        db.execute(
            "CREATE VIEW source AS SELECT * FROM read_csv("
            f"'{str(source).replace(chr(92), '/')}', header=true, all_varchar=true, "
            "nullstr='', sample_size=20480, ignore_errors=false)"
        )
        columns = [row[0] for row in db.execute("DESCRIBE source").fetchall()]
        if columns != REES46_COLUMNS:
            raise ValueError(f"Unexpected schema: {columns}; expected: {REES46_COLUMNS}")

        db.execute(
            "COPY (SELECT * FROM source) TO "
            f"'{str(staging / 'rees46').replace(chr(92), '/')}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        rows = db.execute("SELECT COUNT(*) FROM source").fetchone()[0]
    finally:
        db.close()

    return staging, int(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a REES46 CSV into the Bronze layer.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--keep-staging", action="store_true")
    args = parser.parse_args()

    source = args.source.expanduser().resolve(strict=True)
    batch_id = args.batch_id or f"rees46-{source.stem.lower()}-v1"

    print(f"Source   : {source} ({source.stat().st_size / 1024 ** 3:.2f} GB)")
    print(f"Batch    : {batch_id}")
    print(f"Table    : {args.table}")

    checksum = file_checksum(source)
    print(f"Checksum : sha256:{checksum[:16]}...")

    workdir = Path(tempfile.mkdtemp(prefix="cdp-rees46-"))
    try:
        print("Staging the CSV to Parquet with DuckDB ...")
        staging, expected_rows = stage_with_duckdb(source, workdir)
        print(f"Staged rows: {expected_rows:,}")

        spark = build_session("ingest-rees46")
        from pyspark.sql import functions as F
        from pyspark.sql.types import DateType, StringType, TimestampType

        raw = (
            spark.read.parquet(str(staging))
            .withColumn("source_file", F.lit(source.as_posix()))
            .withColumn("source_file_checksum", F.lit(checksum))
            .withColumn("source_system", F.lit("rees46"))
            .withColumn("batch_id", F.lit(batch_id))
            .withColumn("ingested_at", F.lit(datetime.now(timezone.utc)).cast(TimestampType()))
            # A stable, restartable row number inside the source file.
            .withColumn("source_row_number", F.monotonically_increasing_id() + 1)
            .withColumn("price_raw", F.col("price"))
            # try_cast, not cast: a malformed price must become NULL (the
            # price_unparseable quality flag), not abort the whole batch.
            .withColumn("price", F.expr("try_cast(price as decimal(18,2))"))
            # REES46 carries no currency information; the column stays NULL on
            # purpose so downstream joins never invent a currency.
            .withColumn("currency", F.lit(None).cast(StringType()))
            .withColumn("event_time", F.col("event_time").cast(TimestampType()))
            .withColumn("event_date", F.to_date("event_time").cast(DateType()))
        )

        null_dates = raw.filter(F.col("event_date").isNull()).count()
        if null_dates:
            print(f"Rows without a usable event_date: {null_dates:,}")

        written = (
            raw.writeTo(args.table)
            .overwrite(F.col("batch_id") == F.lit(batch_id))
        )
        del written

        total = spark.sql(f"SELECT COUNT(*) AS n FROM {args.table}").collect()[0].n
        batch_rows = spark.sql(
            f"SELECT COUNT(*) AS n FROM {args.table} WHERE batch_id = '{batch_id}'"
        ).collect()[0].n

        print(f"Rows in table          : {total:,}")
        print(f"Rows for this batch    : {batch_rows:,}")
        print(f"Rows read from the CSV : {expected_rows:,}")
        if batch_rows != expected_rows:
            print(f"MISMATCH: expected {expected_rows}, wrote {batch_rows}", file=sys.stderr)
            return 1
        print("OK: the batch row count matches the source")
        return 0
    finally:
        if args.keep_staging:
            print(f"Staging kept at {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
