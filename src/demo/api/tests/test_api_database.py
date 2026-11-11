"""Real PostgreSQL regression tests, using a disposable database.

Set CDP_TEST_POSTGRES_DSN to a PostgreSQL instance whose user may create databases.
The tests create and drop their own database; existing databases are not modified.
"""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from src.demo.api import business, dashboard
from src.demo.api.server import app

ADMIN_DSN = os.getenv("CDP_TEST_POSTGRES_DSN")
ROOT = Path(__file__).resolve().parents[4]


@unittest.skipUnless(ADMIN_DSN, "Set CDP_TEST_POSTGRES_DSN to run PostgreSQL tests")
class TestApiDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = "cdp_test_" + uuid.uuid4().hex
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database)))
        cls.addClassCleanup(cls.drop_database)
        cls.dsn = make_conninfo(ADMIN_DSN, dbname=cls.database)
        for patcher in (patch.object(business, "DSN", cls.dsn), patch.object(dashboard, "EVENT_SOURCE", "kafka")):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        with business.connect() as conn:
            conn.execute((ROOT / "config/business/init.sql").read_text())
        business.seed_catalog([
            {"product_id": "a", "category_id": "books", "brand": "demo", "price": "2.50", "currency": "USD"},
            {"product_id": "b", "category_id": "books", "brand": "demo", "price": "1.20", "currency": "USD"},
        ])

    @classmethod
    def drop_database(cls):
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(cls.database)))

    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        with business.connect() as conn:
            conn.execute("TRUNCATE observer.events, observer.kafka_records")

    def login(self):
        credentials = {"email": f"{uuid.uuid4().hex}@example.com", "password": "test-password-42"}
        self.assertEqual(self.client.post("/api/auth/register", json={**credentials, "name": "Test"}).status_code, 201)
        response = self.client.post("/api/auth/login", json={**credentials, "anonymous_id": "anon", "session_id": "session"})
        self.assertEqual(response.status_code, 200)

    def create_order(self, key):
        return self.client.post("/api/orders", headers={"Idempotency-Key": key}, json={
            "items": [{"product_id": "b", "quantity": 2}, {"product_id": "a", "quantity": 1},
                      {"product_id": "a", "quantity": 2}],
        })

    def test_order_list_batching_and_response_contract(self):
        self.login()
        created = []
        for i in range(3):
            response = self.create_order(str(i))
            self.assertEqual(response.status_code, 201)
            created.append(response.json())
        queries = []

        class CountingConnection(psycopg.Connection):
            def execute(self, query, *args, **kwargs):
                queries.append(query)
                return super().execute(query, *args, **kwargs)

        def counted_connection():
            return CountingConnection.connect(self.dsn, row_factory=psycopg.rows.dict_row)

        with patch.object(business, "connect", counted_connection):
            orders = self.client.get("/api/orders").json()
        # Authentication, orders, and one item query, regardless of order count.
        self.assertEqual(len(queries), 3)
        self.assertEqual({o["order_id"] for o in orders}, {o["order_id"] for o in created})
        for order in orders:
            self.assertEqual(order["total_price"], "9.90")
            self.assertNotIn("request_hash", order)
            self.assertNotIn("idempotency_key", order)
            self.assertEqual(order["items"], [
                {"product_id": "a", "quantity": 3, "price": "2.50", "currency": "USD"},
                {"product_id": "b", "quantity": 2, "price": "1.20", "currency": "USD"},
            ])
        self.assertEqual(self.create_order("0").json(), created[0])

    def test_order_status_and_idempotency_conflict(self):
        self.login()
        order = self.create_order("status").json()
        url = f"/api/orders/{order['order_id']}/status"
        self.assertEqual(self.client.patch(url, json={"status": "PAID"}).json()["status"], "PAID")
        self.assertEqual(self.client.patch(url, json={"status": "CANCELLED"}).status_code, 409)
        self.assertEqual(self.client.patch(url, json={"status": "REFUNDED"}).json()["status"], "REFUNDED")
        response = self.client.post("/api/orders", headers={"Idempotency-Key": "status"},
                                    json={"items": [{"product_id": "a", "quantity": 1}]})
        self.assertEqual(response.status_code, 409)

    def test_empty_order_list(self):
        self.login()
        self.assertEqual(self.client.get("/api/orders").json(), [])

    def test_empty_dashboard(self):
        summary = self.client.get("/api/summary").json()
        self.assertTrue(summary["snowplow_available"])
        self.assertEqual(summary["event_count"], 0)
        self.assertEqual(summary["unique_users"], 0)
        self.assertEqual(summary["unique_sessions"], 0)
        self.assertEqual(summary["cart_abandon_rate"], 0)

    def seed_events(self):
        rows = []
        # More than one cursor fetch; anonymous identity survives login.
        for i in range(1010):
            name = "search" if i < 1005 else ["add_to_cart", "cart_abandoned", "product_view", "wishlist_add", "error"][i - 1005]
            payload = {"query": " laptop ", "product_id": "a", "category_id": "books"}
            event = {
                "contexts_com_cdp_demo_source_1": [{"anonymous_id": "anon"}],
                "contexts_com_cdp_demo_session_1": [{"session_id": "session"}],
                f"unstruct_event_com_cdp_demo_{name}_1": payload,
            }
            rows.append((str(i), Jsonb(event), name == "error", name,
                         "customer" if i % 2 else None, "session", "minh"))
        with business.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO observer.events(event_id,timestamp,event_json,failed,event_name,user_id,session_id,persona,app_id) "
                    "VALUES(%s,now(),%s,%s,%s,%s,%s,%s,'cdp-demo')", rows)
            conn.execute("INSERT INTO observer.events(event_id,timestamp,event_json,failed,event_name,app_id) "
                         "VALUES('old',now()-interval '25 hours','{}',false,'search','cdp-demo'), "
                         "('other',now(),'{}',false,'search','other-app')")

    def test_dashboard_counts_identity_and_cursor_batches(self):
        self.seed_events()
        summary = self.client.get("/api/summary").json()
        self.assertTrue(summary["snowplow_available"], summary.get("message"))
        self.assertEqual(summary["event_count"], 1009)
        self.assertEqual(summary["failed_count"], 1)
        self.assertEqual(summary["unique_users"], 1)
        self.assertEqual(summary["unique_sessions"], 1)
        self.assertEqual(summary["cart_abandon_rate"], 100)
        self.assertEqual(summary["top_searches"], [{"query": "laptop", "count": 1005}])
        self.assertEqual(summary["top_wishlist"], [{"product_id": "a", "count": 1}])
        self.assertEqual(summary["categories"], [{"category_id": "books", "count": 1}])
        self.assertEqual(summary["personas"]["minh"]["search"], 1005)

    def test_legacy_dashboard_path(self):
        self.seed_events()
        def connect_observer():
            return psycopg.connect(self.dsn, options="-c search_path=observer", row_factory=psycopg.rows.dict_row)
        with patch.object(dashboard, "EVENT_SOURCE", "micro"), patch.object(dashboard, "_connect", connect_observer):
            summary = dashboard.query_summary(24)
        self.assertEqual(summary["event_count"], 1009)
        self.assertEqual(summary["unique_users"], 1)
        self.assertEqual(summary["source"], "Snowplow Micro PostgreSQL")
        self.assertNotIn("personas", summary)
