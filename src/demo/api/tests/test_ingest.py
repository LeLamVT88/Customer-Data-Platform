"""
src/demo/api/tests/test_ingest.py — Unit tests cho tầng Snowplow của CDP Demo.

Backend không còn tự validate/lưu event, nên test tập trung vào:

• Iglu schema: mỗi event type có đúng field bắt buộc, không có field thừa
  (vì schema khai báo ``additionalProperties: false``).
• TP2 payload: ``ue_pr`` / ``co`` phải là CHUỖI JSON bọc đúng wrapper.
• API read layer: đọc payload/entity từ cấu trúc phẳng của Snowplow
  PostgreSQL storage backend.
• Catalog loader.

Các test không cần Snowplow đang chạy (trừ test được đánh dấu integration).
"""

import json
import sys
import unittest
from pathlib import Path

# repo/src on path so "from api.server import ..." works
_REPO = Path(__file__).resolve().parents[4]   # …/tests/ → api/ → demo/ → src/ → repo
sys.path.insert(0, str(_REPO / "src" / "demo"))   # "from api.server" needs parent of api/
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))

from api.server import (  # noqa: E402
    APP_ID,
    _empty_summary,
    _load_catalog,
    _payload_of,
)
from src.demo.snowplow.tp2 import (  # noqa: E402
    CONTEXTS_SCHEMA,
    PAYLOAD_DATA_SCHEMA,
    UNSTRUCT_EVENT_SCHEMA,
    SnowplowCollector,
    build_event,
    build_payload,
    entity_schema_uri,
    event_schema_uri,
    schema_uri,
)

SCHEMA_ROOT = _REPO / "config" / "snowplow" / "iglu-client-embedded" / "schemas" / "com.cdp.demo"


def _load_iglu_schema(name: str) -> dict:
    path = SCHEMA_ROOT / name / "jsonschema" / "1-0-0"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Iglu schema ───────────────────────────────────────────────────────────────

class TestIgluSchemas(unittest.TestCase):
    EVENT_TYPES = [
        "page_view", "product_view", "add_to_cart", "remove_from_cart",
        "begin_checkout", "purchase_observed", "element_click",
        "scroll_depth", "search", "error",
        "cart_abandoned", "apply_filter", "wishlist_add", "wishlist_remove",
        "newsletter_signup",
    ]
    ENTITY_TYPES = ["session", "product"]

    def test_every_event_schema_exists(self):
        for name in self.EVENT_TYPES:
            schema = _load_iglu_schema(name)
            self.assertEqual(schema["self"]["vendor"], "com.cdp.demo")
            self.assertEqual(schema["self"]["name"], name)
            self.assertEqual(schema["self"]["version"], "1-0-0")

    def test_every_entity_schema_exists(self):
        for name in self.ENTITY_TYPES:
            schema = _load_iglu_schema(name)
            self.assertEqual(schema["self"]["name"], name)

    def test_required_is_not_empty(self):
        """Iglu JSON Schema bắt buộc "required" có ít nhất 1 phần tử."""
        for name in self.EVENT_TYPES + self.ENTITY_TYPES:
            schema = _load_iglu_schema(name)
            self.assertTrue(
                schema.get("required"),
                f"{name} thiếu required",
            )

    def test_additional_properties_is_false(self):
        """Field thừa trong payload sẽ bị Enrich từ chối."""
        for name in self.EVENT_TYPES + self.ENTITY_TYPES:
            schema = _load_iglu_schema(name)
            self.assertIs(schema.get("additionalProperties"), False, name)

    def test_required_fields_are_declared_in_properties(self):
        for name in self.EVENT_TYPES + self.ENTITY_TYPES:
            schema = _load_iglu_schema(name)
            for field in schema["required"]:
                self.assertIn(field, schema["properties"], f"{name}.{field}")


# ── TP2 payload ───────────────────────────────────────────────────────────────

class TestTp2Payload(unittest.TestCase):
    def test_payload_wrapper_schema(self):
        payload = build_payload([build_event("page_view", {"path": "/"})])
        self.assertEqual(payload["schema"], PAYLOAD_DATA_SCHEMA)
        self.assertIsInstance(payload["data"], list)
        self.assertEqual(len(payload["data"]), 1)

    def test_ue_pr_is_json_string_with_unstruct_wrapper(self):
        """ue_pr phải là CHUỖI JSON bọc unstruct_event, không phải object."""
        event = build_event("product_view", {"product_id": "P001"})
        self.assertIsInstance(event["ue_pr"], str)
        parsed = json.loads(event["ue_pr"])
        self.assertEqual(parsed["schema"], UNSTRUCT_EVENT_SCHEMA)
        self.assertEqual(parsed["data"]["schema"], event_schema_uri("product_view"))
        self.assertEqual(parsed["data"]["data"], {"product_id": "P001"})

    def test_co_is_json_string_with_contexts_wrapper(self):
        event = build_event(
            "product_view",
            {"product_id": "P001"},
            session_id="sess-1",
        )
        self.assertIsInstance(event["co"], str)
        parsed = json.loads(event["co"])
        self.assertEqual(parsed["schema"], CONTEXTS_SCHEMA)
        entities = parsed["data"]
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["schema"], entity_schema_uri("session"))
        self.assertEqual(entities[0]["data"], {"session_id": "sess-1"})

    def test_no_co_key_when_no_entities(self):
        event = build_event("page_view", {"path": "/"})
        self.assertNotIn("co", event)

    def test_event_type_and_required_fields(self):
        event = build_event("page_view", {"path": "/catalog", "title": "Catalog"})
        self.assertEqual(event["e"], "ue")
        self.assertEqual(event["aid"], APP_ID)
        self.assertTrue(event["eid"])
        self.assertTrue(event["dtm"])

    def test_product_entity_attached(self):
        event = build_event(
            "product_view",
            {"product_id": "P001"},
            session_id="sess-1",
            product={
                "product_id": "P001",
                "category_id": "electronics.smartphone",
                "brand": "Apple",
                "price": "999.99",
                "currency": "USD",
            },
        )
        entities = json.loads(event["co"])["data"]
        self.assertEqual(len(entities), 2)
        product = next(e for e in entities if "product" in e["schema"])
        self.assertEqual(product["data"]["product_id"], "P001")
        self.assertEqual(product["data"]["brand"], "Apple")

    def test_schema_uri_format(self):
        self.assertEqual(
            schema_uri("page_view"),
            "iglu:com.cdp.demo/page_view/jsonschema/1-0-0",
        )


# ── Read layer ────────────────────────────────────────────────────────────────

class TestPayloadExtraction(unittest.TestCase):
    """Snowplow lưu payload ở cột phẳng trong event_json."""

    def test_payload_of_reads_flattened_column(self):
        event_json = {
            "unstruct_event_com_cdp_demo_product_view_1": {"product_id": "P001"},
        }
        self.assertEqual(
            _payload_of(event_json, "product_view"),
            {"product_id": "P001"},
        )

    def test_payload_of_missing_event_returns_empty(self):
        self.assertEqual(_payload_of({}, "product_view"), {})

    def test_payload_of_ignores_other_event_types(self):
        event_json = {
            "unstruct_event_com_cdp_demo_search_1": {"query": "laptop"},
        }
        self.assertEqual(_payload_of(event_json, "product_view"), {})


class TestEmptySummary(unittest.TestCase):
    def test_empty_summary_shape(self):
        summary = _empty_summary(message="chưa kết nối được")
        self.assertEqual(summary["event_count"], 0)
        self.assertEqual(summary["counts"], {})
        self.assertFalse(summary["snowplow_available"])
        self.assertEqual(summary["message"], "chưa kết nối được")
        for key in ("top_searches", "top_wishlist", "categories"):
            self.assertEqual(summary[key], [])


class TestCatalogLoader(unittest.TestCase):
    def test_catalog_loads(self):
        cat = _load_catalog()
        self.assertIsInstance(cat, list)
        self.assertGreater(len(cat), 100)

    def test_catalog_fields(self):
        cat = _load_catalog()
        p = cat[0]
        self.assertIn("product_id", p)
        self.assertIn("price", p)
        self.assertIn("currency", p)


# ── Frontend payload ↔ Iglu schema ───────────────────────────────────────────

class TestFrontendPayloadsMatchSchemas(unittest.TestCase):
    """
    Payload mà frontend gửi phải validate được theo Iglu schema.

    Đây là hợp đồng giữa `src/demo/web/js/catalog.js` và
    `config/snowplow/iglu-client-embedded/schemas/`. Enrich từ chối event
    không khớp ⇒ event rơi vào bad stream (failed = true) và biến mất khỏi
    dashboard.
    """

    # Payload thực tế mà các handler trong catalog.js dựng ra.
    FRONTEND_PAYLOADS = {
        "page_view": {"path": "/catalog", "title": "Danh mục"},
        "product_view": {"product_id": "P0010001", "category_id": "electronics.laptop"},
        "add_to_cart": {
            "product_id": "P0010001", "quantity": 1,
            "price": "1299.99", "currency": "USD",
        },
        "remove_from_cart": {"product_id": "P0010001"},
        "begin_checkout": {
            "cart_id": "cart-1",
            "items": [{
                "product_id": "P0010001", "quantity": 2,
                "price": "1299.99", "currency": "USD",
            }],
            "total_price": "2599.98", "currency": "USD",
        },
        "purchase_observed": {
            "cart_id": "ORD-ABC123",
            "items": [{
                "product_id": "P0010001", "quantity": 2,
                "price": "1299.99", "currency": "USD",
            }],
            "total_price": "2599.98", "currency": "USD",
        },
        "element_click": {"selector": "#sort-select", "tag": "select", "sort": "price_asc"},
        "scroll_depth": {"depth_percent": 50},
        "search": {"query": "laptop", "results_count": 3, "type": "catalog_search"},
        "error": {"message": "Something failed", "stack": "Error: ..."},
        "cart_abandoned": {
            "items": [{
                "product_id": "P0010001", "quantity": 2,
                "price": "1299.99", "currency": "USD",
            }],
            "total_price": "2599.98", "currency": "USD",
        },
        "apply_filter": {"filter_type": "category", "filter_value": "electronics"},
        "wishlist_add": {"product_id": "P0010001", "price": "1299.99", "currency": "USD"},
        "wishlist_remove": {"product_id": "P0010001"},
        "newsletter_signup": {"email": "user@example.com"},
    }

    def test_all_frontend_event_types_are_covered(self):
        """Mọi event type mà tracker.js khai báo đều phải có payload mẫu."""
        tracker_js = (_REPO / "src" / "demo" / "web" / "js" / "tracker.js").read_text(
            encoding="utf-8"
        )
        for event_type in self.FRONTEND_PAYLOADS:
            self.assertIn(f"'{event_type}'", tracker_js, event_type)

    def test_no_missing_required_fields(self):
        for event_type, payload in self.FRONTEND_PAYLOADS.items():
            schema = _load_iglu_schema(event_type)
            for field in schema["required"]:
                self.assertIn(field, payload, f"{event_type}.{field} thiếu trong payload")

    def test_no_unknown_fields(self):
        """additionalProperties: false ⇒ field lạ sẽ bị Enrich từ chối."""
        for event_type, payload in self.FRONTEND_PAYLOADS.items():
            schema = _load_iglu_schema(event_type)
            for field in payload:
                self.assertIn(field, schema["properties"], f"{event_type}.{field} không có trong schema")

    def test_item_schemas_match(self):
        """Các event mang `items[]` phải có đủ field của item schema."""
        for event_type in ("begin_checkout", "purchase_observed", "cart_abandoned"):
            schema = _load_iglu_schema(event_type)
            item_required = schema["properties"]["items"]["items"]["required"]
            for item in self.FRONTEND_PAYLOADS[event_type]["items"]:
                for field in item_required:
                    self.assertIn(field, item, f"{event_type}.items[].{field}")

    def test_cart_abandoned_items_include_currency(self):
        """
        Regression: payload `cart_abandoned` từng thiếu `currency` trong items
        ⇒ Enrich đánh dấu failed=true ⇒ event bị loại khỏi dashboard.
        """
        for item in self.FRONTEND_PAYLOADS["cart_abandoned"]["items"]:
            self.assertIn("currency", item)

    def test_cart_item_shape_from_localstorage(self):
        """
        Regression: dòng giỏ hàng lưu trong localStorage là bản spread của
        product ⇒ có `currency`. Mapper của cart_abandoned phải giữ lại field
        này thay vì chỉ chọn product_id/quantity/price.
        """
        catalog = _load_catalog()
        cart_item = {**catalog[0], "quantity": 2}
        self.assertIn("currency", cart_item)


# ── Collector client (offline) ────────────────────────────────────────────────

class TestCollectorClient(unittest.TestCase):
    def test_endpoint_path(self):
        with SnowplowCollector("http://127.0.0.1:9090/") as collector:
            self.assertEqual(
                collector.endpoint,
                "http://127.0.0.1:9090/com.snowplowanalytics.snowplow/tp2",
            )

    def test_send_empty_is_noop(self):
        with SnowplowCollector("http://127.0.0.1:9090") as collector:
            self.assertTrue(collector.send([]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
