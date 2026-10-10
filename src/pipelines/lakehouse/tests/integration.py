"""Run correctness/recovery checks against real PostgreSQL + S3 + Iceberg.

Executed in the Spark container; uses isolated fixture batches, not a mock sink.
"""
import csv
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[2]))
from pyspark.sql import SparkSession, functions as F
from ingest_rees46_batch import FIELDS, ingest
from run_rees46 import TABLES, read_batch, run, verify_batch
from common import assert_same_rows, write_batch


def test_row_comparison(spark):
    """Equal row counts must not hide changed values, keys or duplicates."""
    schema = "event_id string, value string"
    expected = spark.createDataFrame([("A", None), ("B", "original")], schema)
    assert_same_rows(expected, expected, "equal values, including NULL")
    cases = {
        "changed value": [("A", None), ("B", "changed")],
        "changed key": [("A", None), ("C", "original")],
        "duplicate key": [("A", None), ("A", None)],
        "null key": [(None, None), ("B", "original")],
        "missing row": [("A", None)],
        "extra row": [("A", None), ("B", "original"), ("C", "extra")],
    }
    for description, rows in cases.items():
        changed = spark.createDataFrame(rows, schema)
        for actual, reference in ((changed, expected), (expected, changed)):
            try:
                assert_same_rows(actual, reference, description)
            except AssertionError:
                pass
            else:
                raise AssertionError(f"Comparator accepted {description}")
    print("PASS: exact comparator rejects changed values/keys, duplicates, NULL keys and missing/extra rows")


def test_funnel(spark, root):
    source = root / "funnel.csv"
    def event(session, kind, second, user="A"):
        return [f"2019-10-01 00:00:{second:02d} UTC", kind, "P", "C", "", "", "1", user, session]
    records = [
        event("complete", "view", 0), event("complete", "cart", 1), event("complete", "purchase", 2),
        event("complete", "purchase", 2),  # Duplicate payload must not count a session twice.
        event("ties", "view", 0), event("ties", "cart", 0), event("ties", "purchase", 1),
        event("reverse", "purchase", 0), event("reverse", "cart", 1), event("reverse", "view", 2),
        event("recover", "cart", 0), event("recover", "view", 1), event("recover", "cart", 2),
        event("recover", "purchase", 2), event("recover", "purchase", 3),
        event("shared", "view", 0, "A"), event("shared", "cart", 1, "B"), event("shared", "purchase", 2, "B"),
        event("", "view", 0), event("missing-user", "view", 0, ""),
    ]
    with source.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        writer.writerows(records)
    batch, _ = ingest(source, root / "funnel-batches", users=None)
    report = run(spark, batch, root / "reports")
    assert report["counts"] == {"bronze_rows": 20, "silver_rows": 19, "quarantine_rows": 1}
    assert report["funnel"] == {
        "sessions_total": 6, "sessions_with_view": 5,
        "sessions_with_cart_after_view": 2, "sessions_with_purchase_after_cart": 2,
        "excluded_missing_session_events": 1,
    }, report["funnel"]
    for table in TABLES.values():
        spark.sql(f"DELETE FROM {table} WHERE batch_id = '{report['batch_id']}'")
    print("PASS: funnel strict order, ties, duplicates, user isolation, missing session/user, full-file mode")


def main():
    spark = SparkSession.builder.appName("cdp-lakehouse-integration").getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    try:
        test_row_comparison(spark)
        with tempfile.TemporaryDirectory(dir="/workspace/data") as temporary:
            root = Path(temporary)
            source = root / "fixture.csv"
            def event(kind="view", price="10.25", at="2019-10-01 00:00:00 UTC", user="A"):
                return [at, kind, "P1", "C1", "", "", price, user, "session-A"]
            rows = [event(), event(user="B"), event(), event(kind="cart", price="0"),
                    event(kind="purchase", at="2019-10-02 00:00:00 UTC"),
                    event(price="10.257"), event(price="-1"), event(at="broken"),
                    event(kind="unknown")]
            with source.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(FIELDS)
                writer.writerows(rows)
            batch, _ = ingest(source, root / "batches", users=1)
            first = run(spark, batch, root / "reports")
            assert first["counts"] == {"bronze_rows": 8, "silver_rows": 4, "quarantine_rows": 4}
            assert first["tables"]["user_behavior"]["batch_rows"] == 1
            batch_id = first["batch_id"]
            before = {name: read_batch(spark, table, batch_id).collect() for name, table in TABLES.items()}
            # Rerun must preserve row values and counts across all tables.
            run(spark, batch, root / "reports")
            for name, table in TABLES.items():
                assert set(read_batch(spark, table, batch_id).toJSON().collect()) == set(
                    spark.createDataFrame(before[name], spark.table(table).schema).toJSON().collect())
            # Corrupt just Gold, simulating interrupted/incomplete downstream output.
            empty = read_batch(spark, TABLES["daily_events"], batch_id).limit(0)
            write_batch(spark, empty, TABLES["daily_events"], batch_id)
            assert read_batch(spark, TABLES["daily_events"], batch_id).count() == 0
            run(spark, batch, root / "reports")
            assert read_batch(spark, TABLES["daily_events"], batch_id).count() == len(before["daily_events"])
            # A second batch must not overwrite the first batch.
            second, _ = ingest(source, root / "batches", users=2)
            second_report = run(spark, second, root / "reports")
            assert second_report["tables"]["user_behavior"]["batch_rows"] == 2
            for name, table in TABLES.items():
                assert read_batch(spark, table, batch_id).count() == len(before[name])
            # Reject changed input before it can touch an Iceberg table.
            (batch / "selected-users.json").write_text("tampered")
            try:
                verify_batch(batch)
            except ValueError:
                pass
            else:
                raise AssertionError("Corrupted input was accepted")
            # Remove only test batches, retaining the real development sample.
            for test_batch_id in (batch_id, second_report["batch_id"]):
                for table in TABLES.values():
                    spark.sql(f"DELETE FROM {table} WHERE batch_id = '{test_batch_id}'")
            test_funnel(spark, root)
            print("PASS: bad data, exact values, rerun, recovery, batch isolation, corrupted input")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
