import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

spec = importlib.util.spec_from_file_location("ingest", Path(__file__).resolve().parents[1] / "ingest_rees46_batch.py")
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)


class IngestionTests(unittest.TestCase):
    def test_full_user_history_quarantine_and_idempotence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "events.csv"
            def event(user="A", timestamp="2019-10-01 00:00:00 UTC", price="10.25", kind="view"):
                return [timestamp, kind, "P1", "C1", "", "", price, user, ""]
            records = [event(), event("B"), event(price="0"), event(timestamp="broken"),
                       event(price="10.257"), event(price="-1"), event(), event(kind="unknown")]
            with source.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(ingest.FIELDS)
                writer.writerows(records)
            batch, created = ingest.ingest(source, root / "batches", users=1)
            self.assertTrue(created)
            manifest = json.loads((batch / "manifest.json").read_text())
            self.assertEqual(manifest["counts"], {"bronze_rows": 7, "silver_rows": 3, "quarantine_rows": 4})
            db = duckdb.connect()
            try:
                bronze = db.execute("SELECT source_row_number, event_id, raw_payload FROM read_parquet(?) ORDER BY source_row_number", [str(batch / "bronze.parquet")]).fetchall()
                self.assertEqual([row[0] for row in bronze], [1, 3, 4, 5, 6, 7, 8])
                self.assertEqual(json.loads(bronze[0][2]), json.loads(bronze[5][2]))
                self.assertNotEqual(bronze[0][1], bronze[5][1])
                flags = db.execute("SELECT quality_flags FROM read_parquet(?) WHERE price=0", [str(batch / "silver.parquet")]).fetchone()[0]
                self.assertIn("zero_price", flags)
                reasons = db.execute("SELECT unnest(error_reasons) FROM read_parquet(?)", [str(batch / "quarantine.parquet")]).fetchall()
                self.assertEqual({r[0] for r in reasons}, {"invalid_event_time", "invalid_price", "negative_price", "unsupported_event_type"})
            finally:
                db.close()
            before = (batch / "manifest.json").read_bytes()
            repeated, created = ingest.ingest(source, root / "batches", users=1)
            self.assertFalse(created)
            self.assertEqual(repeated, batch)
            self.assertEqual(before, (batch / "manifest.json").read_bytes())
            (batch / "selected-users.json").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "changed or corrupted"):
                ingest.ingest(source, root / "batches", users=1)

class FullFileTests(unittest.TestCase):
    def test_all_records_include_missing_user_and_rerun(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'all.csv'
            with source.open('w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(ingest.FIELDS)
                writer.writerows([
                    ['2019-10-01 00:00:00 UTC', 'view', 'P1', 'C1', '', '', '1', 'A', 'S'],
                    ['2019-10-01 00:00:01 UTC', 'view', 'P1', 'C1', '', '', '1', '', 'S'],
                ])
            batch, created = ingest.ingest(source, root / 'batches', users=None)
            self.assertTrue(created)
            manifest = json.loads((batch / 'manifest.json').read_text())
            self.assertEqual(manifest['counts'], {'bronze_rows': 2, 'silver_rows': 1, 'quarantine_rows': 1})
            self.assertIsNone(manifest['selected_users'])
            self.assertEqual(manifest['specification']['selection'], 'all_source_records')
            self.assertEqual(json.loads((batch / 'selected-users.json').read_text()), [])
            self.assertFalse(ingest.ingest(source, root / 'batches', users=None)[1])


if __name__ == "__main__":
    unittest.main()
