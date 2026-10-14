"""
src/demo/api/tests/test_ingest.py — Unit tests for the Demo API ingest logic.

Tests
-----
• Schema validation: missing/invalid event_type, bad timestamp → caught.
• Idempotency: rerunning the same content returns existing batch, no new files.
• New batch on different content: checksum changes → new batch_id.
• Quarantine routing: missing session_id and missing user_id are isolated.
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# repo/src on path so "from api.server import ..." works
_REPO = Path(__file__).resolve().parents[4]   # …/tests/ → api/ → demo/ → src/ → repo
sys.path.insert(0, str(_REPO / "src" / "demo"))   # "from api.server" needs parent of api/
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))

from api.server import (
    ingest_events,
    _batch_checksum,
    _compute_event_id,
    SUPPORTED_EVENT_TYPES,
    IncomingEvent,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_event(extra: dict | None = None) -> IncomingEvent:
    d = {
        "event_type": "product_view",
        "event_time": "2026-01-01T10:00:00.000Z",
        "session_id": "sess-test",
        "user_id": "uid-test",
        "namespace": "cdp.demo.events",
        "source": "test",
        "url": "http://localhost",
        "referrer": "",
        "user_agent": "test-agent",
        "viewport": "1920x1080",
        "payload": {"product_id": "P0010001"},
    }
    if extra:
        d.update(extra)
    return IncomingEvent(**d)


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestSchemaValidation(unittest.TestCase):
    def test_unknown_event_type_raises(self):
        with self.assertRaises(ValueError) as ctx:
            IncomingEvent(
                event_type="made_up_event",
                event_time=datetime.now(timezone.utc).isoformat(),
                session_id="sess-1",
                user_id="uid-1",
            )
        self.assertIn("Unsupported event_type", str(ctx.exception))

    def test_missing_timezone_raises(self):
        with self.assertRaises(ValueError) as ctx:
            IncomingEvent(
                event_type="page_view",
                event_time="2026-01-01T00:00:00",   # no Z or +00:00
                session_id="sess-1",
                user_id="uid-1",
            )
        self.assertIn("timezone", str(ctx.exception))

    def test_valid_event_passes(self):
        ev = IncomingEvent(
            event_type="product_view",
            event_time="2026-01-01T12:00:00.000Z",
            session_id="sess-1",
            user_id="uid-1",
            payload={"product_id": "P0010001"},
        )
        self.assertEqual(ev.event_type, "product_view")
        self.assertEqual(ev.namespace, "cdp.demo.events")

    def test_all_supported_event_types_pass(self):
        for et in SUPPORTED_EVENT_TYPES:
            ev = IncomingEvent(
                event_type=et,
                event_time=datetime.now(timezone.utc).isoformat(),
                session_id="sess-1",
                user_id="uid-1",
            )
            self.assertEqual(ev.event_type, et)


class TestChecksum(unittest.TestCase):
    def test_same_content_same_checksum(self):
        ev = IncomingEvent(
            event_type="page_view",
            event_time="2026-01-01T00:00:00Z",
            session_id="sess-1",
            user_id="uid-1",
        )
        raw = [ev.model_dump()]
        c1 = _batch_checksum(raw)
        c2 = _batch_checksum(raw)
        self.assertEqual(c1, c2)

    def test_different_content_different_checksum(self):
        ev1 = IncomingEvent(
            event_type="page_view",
            event_time="2026-01-01T00:00:00Z",
            session_id="sess-1",
            user_id="uid-1",
        )
        ev2 = IncomingEvent(
            event_type="page_view",
            event_time="2026-01-01T00:00:01Z",   # different time
            session_id="sess-1",
            user_id="uid-1",
        )
        self.assertNotEqual(
            _batch_checksum([ev1.model_dump()]),
            _batch_checksum([ev2.model_dump()]),
        )

    def test_event_id_derivation_deterministic(self):
        eid1 = _compute_event_id("ns", "abc123", 1)
        eid2 = _compute_event_id("ns", "abc123", 1)
        self.assertEqual(eid1, eid2)

    def test_event_id_changes_with_ordinal(self):
        eid1 = _compute_event_id("ns", "abc123", 1)
        eid2 = _compute_event_id("ns", "abc123", 2)
        self.assertNotEqual(eid1, eid2)

    def test_event_id_changes_with_namespace(self):
        eid1 = _compute_event_id("ns1", "abc123", 1)
        eid2 = _compute_event_id("ns2", "abc123", 1)
        self.assertNotEqual(eid1, eid2)


class TestIngestIdempotency(unittest.TestCase):
    """These tests use a temp directory so they don't touch real data."""

    def setUp(self):
        import api.server as srv
        self._orig_root = srv.EVENTS_ROOT
        self._tmpdir = Path(tempfile.mkdtemp(prefix="cdp_test_"))
        srv.EVENTS_ROOT = self._tmpdir / "data" / "demo-events"
        srv.EVENTS_ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import api.server as srv
        srv.EVENTS_ROOT = self._orig_root
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_rerun_same_content_returns_same_batch_id(self):
        ev = _make_event()
        resp1, _ = ingest_events([ev])
        resp2, _ = ingest_events([ev])   # identical payload
        self.assertEqual(resp1.batch_id, resp2.batch_id)
        self.assertIn("already exists", resp2.message)

    def test_rerun_does_not_create_duplicate_batch_dirs(self):
        """Idempotency: re-sending the same events must not create a second batch directory."""
        import api.server as srv
        ev = _make_event()
        resp1, _ = ingest_events([ev])
        batch_dirs_before = list(self._tmpdir.rglob("manifest.json"))
        resp2, _ = ingest_events([ev])
        batch_dirs_after = list(self._tmpdir.rglob("manifest.json"))
        self.assertEqual(len(batch_dirs_before), 1)
        self.assertEqual(len(batch_dirs_after), 1)
        self.assertEqual(batch_dirs_before[0], batch_dirs_after[0])
        self.assertEqual(resp1.batch_id, resp2.batch_id)

    def test_different_content_creates_new_batch(self):
        ev1 = _make_event({"session_id": "sess-1"})
        ev2 = _make_event({"session_id": "sess-2"})
        resp1, _ = ingest_events([ev1])
        resp2, _ = ingest_events([ev2])
        self.assertNotEqual(resp1.batch_id, resp2.batch_id)

    def test_quarantine_missing_session_strict_off(self):
        ev = _make_event({"session_id": ""})
        resp, q_count = ingest_events([ev], strict_user=False)
        self.assertEqual(resp.total_accepted, 0)
        self.assertEqual(q_count, 1)

    def test_quarantine_missing_user_strict_on(self):
        ev = _make_event({"user_id": ""})
        resp, q_count = ingest_events([ev], strict_user=True)
        self.assertEqual(resp.total_accepted, 0)
        self.assertEqual(q_count, 1)

    def test_multiple_events_ordinal_sequential(self):
        evs = [_make_event({"session_id": f"sess-{i}"}) for i in range(5)]
        resp, _ = ingest_events(evs)
        self.assertEqual(resp.total_accepted, 5)
        # One batch dir created
        self.assertEqual(len(list(self._tmpdir.rglob("manifest.json"))), 1)

    def test_quarantine_unknown_event_type_raises(self):
        """IncomingEvent validator rejects unknown event_type before reaching ingest."""
        with self.assertRaises(ValueError):
            IncomingEvent(
                event_type="impossible_type",
                event_time="2026-01-01T00:00:00Z",
                session_id="sess-1",
                user_id="uid-1",
            )

    def test_valid_event_accepted(self):
        ev = _make_event()
        resp, q_count = ingest_events([ev], strict_user=True)
        self.assertEqual(resp.total_accepted, 1)
        self.assertEqual(q_count, 0)


class TestCatalogLoader(unittest.TestCase):
    def test_catalog_loads(self):
        import api.server as srv
        cat = srv._load_catalog()
        self.assertIsInstance(cat, list)
        self.assertGreater(len(cat), 100)

    def test_catalog_fields(self):
        import api.server as srv
        cat = srv._load_catalog()
        p = cat[0]
        self.assertIn("product_id", p)
        self.assertIn("price", p)
        self.assertIn("currency", p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
