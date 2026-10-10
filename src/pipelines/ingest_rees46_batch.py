#!/usr/bin/env python3
"""Reproducible REES46 user sample -> local Bronze/Silver/quarantine Parquet."""

import argparse
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import duckdb

ROOT = Path(__file__).resolve().parents[2]
VERSION = "rees46-local-1.0.0"
FIELDS = ["event_time", "event_type", "product_id", "category_id", "category_code",
          "brand", "price", "user_id", "user_session"]


def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be positive")
    return number


def ingest(source, output_root, users=100):
    """users=None selects all records, including missing-user rows for quarantine."""
    started = perf_counter()
    source = Path(source).expanduser().resolve(strict=True)
    output_root = Path(output_root).expanduser().resolve()
    print("Computing source SHA-256...", flush=True)
    file_hash = sha256(source)
    specification = {"source_sha256": file_hash, "users_requested": users,
                     "selection": ("all_source_records" if users is None else
                                   "first_distinct_nonblank_users_in_source_order"),
                     "adapter_version": VERSION, "source_namespace": "rees46.marketplace"}
    batch_id = hashlib.sha256(json.dumps(specification, sort_keys=True).encode()).hexdigest()
    destination = output_root / batch_id
    if destination.exists():
        manifest = json.loads((destination / "manifest.json").read_text())
        if manifest["specification"] != specification:
            raise ValueError("Existing batch specification mismatch")
        for name, expected in manifest["output_sha256"].items():
            if sha256(destination / name) != expected:
                raise ValueError(f"Existing output changed or corrupted: {name}")
        print(f"Already ingested; verified existing outputs, no new rows: {destination}")
        return destination, False

    output_root.mkdir(parents=True, exist_ok=True)
    staging = output_root / f".pending-{uuid.uuid4().hex}"
    staging.mkdir()
    cache = ROOT / ".cache/duckdb"
    cache.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    try:
        # Full-month uniqueness checks need more hash-table memory than samples.
        # Keep source order preservation: event IDs depend on CSV ordinality.
        memory_limit = "2GB" if users is None else "512MB"
        db.execute(f"SET memory_limit={sql_string(memory_limit)}")
        db.execute("SET threads=2")
        db.execute("SET TimeZone='UTC'")
        db.execute(f"SET temp_directory={sql_string(cache)}")
        db.execute(
            f"CREATE VIEW input AS SELECT * FROM read_csv({sql_string(source)}, "
            "header=true, all_varchar=true, nullstr='', ignore_errors=false) WITH ORDINALITY"
        )
        columns = [row[0] for row in db.execute("DESCRIBE input").fetchall()]
        if columns != FIELDS + ["ordinality"]:
            raise ValueError(f"Unexpected columns: {columns}")
        if users is None:
            print("Collecting all source records, including missing user IDs...", flush=True)
            chosen = []  # Full-file mode has no selected-user list to collect.
            source_relation = "input i"
        else:
            print(f"Selecting {users} users and collecting all their source rows...", flush=True)
            db.execute(
                "CREATE TABLE selected_users AS SELECT user_id, min(ordinality) AS first_source_row "
                "FROM input WHERE user_id IS NOT NULL AND trim(user_id) <> '' GROUP BY user_id "
                f"ORDER BY first_source_row LIMIT {int(users)}"
            )
            chosen = [row[0] for row in db.execute(
                "SELECT user_id FROM selected_users ORDER BY first_source_row").fetchall()]
            if not chosen:
                raise ValueError("No nonblank user IDs found")
            source_relation = "input i JOIN selected_users u ON i.user_id=u.user_id"
        ingested_at = datetime.now(timezone.utc).isoformat()
        raw_struct = ", ".join(f"{field} := i.{field}" for field in FIELDS)
        db.execute(
            "CREATE TABLE bronze AS SELECT i.*, ordinality AS source_row_number, "
            f"sha256({sql_string('rees46.marketplace:' + file_hash + ':')} || cast(ordinality AS VARCHAR)) AS event_id, "
            f"{sql_string(file_hash)} AS source_sha256, {sql_string(batch_id)} AS batch_id, "
            "'rees46.marketplace' AS source_namespace, "
            f"cast({sql_string(ingested_at)} AS TIMESTAMPTZ) AS ingested_at, "
            f"cast(to_json(struct_pack({raw_struct})) AS VARCHAR) AS raw_payload "
            f"FROM {source_relation}"
        )
        db.execute("ALTER TABLE bronze DROP COLUMN ordinality")
        db.execute("""
            CREATE VIEW checked AS
            SELECT *, try_cast(event_time AS TIMESTAMPTZ) AS event_at,
                try_cast(price AS DECIMAL(18,2)) AS price_decimal,
                CASE event_type WHEN 'view' THEN 'product_view'
                    WHEN 'cart' THEN 'add_to_cart'
                    WHEN 'purchase' THEN 'purchase_observed' END AS event_name,
                list_filter([
                    CASE WHEN try_cast(event_time AS TIMESTAMPTZ) IS NULL THEN 'invalid_event_time' END,
                    CASE WHEN event_type IS NULL OR event_type NOT IN ('view','cart','purchase') THEN 'unsupported_event_type' END,
                    CASE WHEN product_id IS NULL OR trim(product_id)='' THEN 'missing_product_id' END,
                    CASE WHEN user_id IS NULL OR trim(user_id)='' THEN 'missing_source_user_id' END,
                    CASE WHEN price IS NULL OR NOT regexp_full_match(price, '-?[0-9]+(\\.[0-9]{1,2})?')
                        OR try_cast(price AS DECIMAL(18,2)) IS NULL THEN 'invalid_price' END,
                    CASE WHEN try_cast(price AS DECIMAL(18,2)) < 0 THEN 'negative_price' END
                ], reason -> reason IS NOT NULL) AS error_reasons,
                list_filter([
                    CASE WHEN category_code IS NULL OR trim(category_code)='' THEN 'missing_category_code' END,
                    CASE WHEN brand IS NULL OR trim(brand)='' THEN 'missing_brand' END,
                    CASE WHEN user_session IS NULL OR trim(user_session)='' THEN 'missing_session' END,
                    CASE WHEN try_cast(price AS DECIMAL(18,2))=0 THEN 'zero_price' END
                ], flag -> flag IS NOT NULL) AS quality_flags
            FROM bronze
        """)
        db.execute("""
            CREATE VIEW silver AS SELECT event_id, batch_id, source_namespace,
                source_sha256, source_row_number, ingested_at, event_at,
                event_name, event_type AS source_event_type, '1-0-0' AS contract_version,
                user_id AS source_user_id, user_session AS source_session_id,
                cast(NULL AS VARCHAR) AS verified_customer_id,
                product_id, category_id, category_code, brand, price_decimal AS price,
                cast(NULL AS VARCHAR) AS currency, quality_flags
            FROM checked WHERE len(error_reasons)=0
        """)
        counts = {
            "bronze_rows": db.execute("SELECT count(*) FROM bronze").fetchone()[0],
            "silver_rows": db.execute("SELECT count(*) FROM silver").fetchone()[0],
            "quarantine_rows": db.execute("SELECT count(*) FROM checked WHERE len(error_reasons)>0").fetchone()[0],
        }
        if counts["bronze_rows"] != counts["silver_rows"] + counts["quarantine_rows"]:
            raise AssertionError("Row reconciliation failed")
        print("Reconciling counts and unique event IDs...", flush=True)
        unique = db.execute("SELECT count(DISTINCT event_id) FROM bronze").fetchone()[0]
        if unique != counts["bronze_rows"]:
            raise AssertionError("Source record identity collision")
        queries = {
            "bronze.parquet": "SELECT * FROM bronze ORDER BY source_row_number",
            "silver.parquet": "SELECT * FROM silver ORDER BY source_row_number",
            "quarantine.parquet": "SELECT * FROM checked WHERE len(error_reasons)>0 ORDER BY source_row_number",
        }
        for name, query in queries.items():
            print(f"Writing {name}...", flush=True)
            db.execute(f"COPY ({query}) TO {sql_string(staging / name)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        (staging / "selected-users.json").write_text(json.dumps(chosen, indent=2) + "\n")
        manifest = {
            "batch_id": batch_id, "run_id": uuid.uuid4().hex,
            "specification": specification, "source_path": str(source),
            "source_bytes": source.stat().st_size, "ingested_at": ingested_at,
            "selected_users": None if users is None else len(chosen), "duckdb_version": duckdb.__version__,
            "adapter_runtime": {"memory_limit": memory_limit, "threads": 2},
            "counts": counts,
            "selection_notes": ("All source records, including missing user IDs." if users is None else
                                "All source rows of first N distinct users; chronological selection bias. Not a representative population sample."),
            "reconciliation": "bronze = silver + quarantine; event IDs unique within this batch",
            "output_sha256": {name: sha256(staging / name) for name in [*queries, "selected-users.json"]},
        }
        # Detect changes while ingesting before publishing the immutable batch.
        if sha256(source) != file_hash:
            raise ValueError("Source file changed while ingesting")
        manifest["elapsed_seconds"] = round(perf_counter() - started, 3)
        manifest["output_bytes"] = {name: (staging / name).stat().st_size for name in [*queries, "selected-users.json"]}
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        staging.rename(destination)
        print(json.dumps(counts, indent=2))
        print(f"Published batch: {destination}")
        return destination, True
    finally:
        db.close()
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/REES46/2019-Oct.csv")
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/local-batches/rees46")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--users", type=positive, default=100)
    selection.add_argument("--all", action="store_true", help="Ingest every source record, including rows missing user ID")
    args = parser.parse_args()
    ingest(args.source, args.output_root, None if args.all else args.users)


if __name__ == "__main__":
    main()
