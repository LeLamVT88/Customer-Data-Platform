#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config/snowplow/tools/build_schemas.py — sinh Iglu schema cho CDP Demo.

Snowplow dùng *self-describing JSON*: mỗi event type có một JSON Schema riêng,
được định danh bằng URI ``iglu:<vendor>/<name>/jsonschema/<version>``.

Schema nằm trong static repository theo cấu trúc:

    <root>/<vendor>/<name>/<format>/<version>

và file ``<version>`` không có đuôi, chứa JSON Schema tự mô tả (có trường
``self`` khớp với đường dẫn).

Chạy lại sau khi sửa danh mục event:

    python config/snowplow/tools/build_schemas.py

Quy tắc versioning (SchemaVer = MODEL-REVISION-ADDITION):
- Thêm field optional, đổi mô tả        -> bump ADDITION  (1-0-0 -> 1-0-1)
- Thêm/sửa field có thể ảnh hưởng dữ liệu cũ -> bump REVISION (1-0-0 -> 1-1-0)
- Đổi kiểu, thêm/xoá field bắt buộc      -> bump MODEL    (1-0-0 -> 2-0-0)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

VENDOR = "com.cdp.demo"
FORMAT = "jsonschema"
VERSION = "1-0-0"

ROOT = Path(__file__).resolve().parents[1]
# Iglu client embedded yêu cầu layout: <path>/schemas/<vendor>/<name>/<format>/<version>
# và path phải chứa thư mục "schemas".
SCHEMA_ROOT = ROOT / "iglu-client-embedded" / "schemas"

SELF_DESC_META = (
    "http://iglucentral.com/schemas/com.snowplowanalytics.self-desc/schema/jsonschema/1-0-0#"
)


# ── Reusable property fragments ──────────────────────────────────────────────

def _string(description: str, **extra) -> dict:
    return {"type": "string", "description": description, **extra}


def _int(description: str, **extra) -> dict:
    return {"type": "integer", "description": description, **extra}


def _number(description: str, **extra) -> dict:
    return {"type": "number", "description": description, **extra}


def _bool(description: str, **extra) -> dict:
    return {"type": "boolean", "description": description, **extra}


def _array(description: str, item: dict) -> dict:
    return {"type": "array", "description": description, "items": item}


# Cart line item — dùng lại cho begin_checkout / purchase_observed / cart_abandoned.
ITEM_SCHEMA = {
    "type": "object",
    "description": "Một dòng sản phẩm trong giỏ hàng.",
    "properties": {
        "product_id": _string("Mã sản phẩm trong catalog."),
        "quantity": _int("Số lượng.", minimum=1),
        "price": _string(
            "Gá đơn vị, chuỗi decimal tối đa 2 chữ số thập phân. "
            "Không làm tròn và không suy ra currency từ giá."
        ),
        "currency": _string("Mã tiền tệ ISO 4217 do nguồn cung cấp."),
    },
    "required": ["product_id", "quantity", "price", "currency"],
    "additionalProperties": False,
}


# ── Event schemas ────────────────────────────────────────────────────────────
#
# Danh sách bám sát SUPPORTED_EVENT_TYPES của src/demo/api/server.py (sẽ bị
# thay bằng Snowplow). Mọi field được gửi từ web (src/demo/web/js/catalog.js)
# và từ bot (src/demo/bot/driver.py) đều phải có mặt ở đây.

EVENTS: dict[str, dict] = {
    "page_view": {
        "description": "Người dùng chuyển trang trong web demo.",
        "properties": {
            "path": _string("Đường dẫn trang, ví dụ '/catalog'."),
            "title": _string("Tiêu đề trang."),
        },
        # Iglu JSON Schema bắt buộc "required" có ít nhất 1 phần tử.
        "required": ["path"],
    },
    "product_view": {
        "description": "Người dùng xem chi tiết hoặc thẻ sản phẩm.",
        "properties": {
            "product_id": _string("Mã sản phẩm."),
            "category_id": _string("Danh mục phân cấp, ví dụ 'electronics.audio'."),
            "price": _string("Giá bán, chuỗi decimal tối đa 2 chữ số thập phân."),
            "currency": _string("Mã tiền tệ ISO 4217."),
            "source": _string("Nguồn điều hướng tới sản phẩm, ví dụ 'recommendation'."),
        },
        "required": ["product_id"],
    },
    "add_to_cart": {
        "description": "Sản phẩm được thêm vào giỏ hàng hoặc số lượng được tăng.",
        "properties": {
            "product_id": _string("Mã sản phẩm."),
            "quantity": _int("Số lượng sau thay đổi.", minimum=1),
            "price": _string("Gá đơn vị, chuỗi decimal tối đa 2 chữ số thập phân."),
            "currency": _string("Mã tiền tệ ISO 4217."),
            "category_id": _string("Danh mục phân cấp."),
            "updated": _bool("True khi sự kiện này là tăng số lượng, không phải thêm mới."),
        },
        "required": ["product_id", "quantity", "price", "currency"],
    },
    "remove_from_cart": {
        "description": "Sản phẩm bị xoá khỏi giỏ hàng.",
        "properties": {
            "product_id": _string("Mã sản phẩm."),
            "quantity": _int("Số lượng bị xoá."),
            "price": _string("Giá đơn vị tại thời điểm xoá."),
            "currency": _string("Mã tiền tệ ISO 4217."),
        },
        "required": ["product_id"],
    },
    "begin_checkout": {
        "description": "Người dùng bắt đầu quy trình thanh toán.",
        "properties": {
            "cart_id": _string("Định danh giỏ hàng, UUID."),
            "items": _array("Dòng sản phẩm trong giỏ.", ITEM_SCHEMA),
            "total_price": _string("Tổng tiền, chuỗi decimal tối đa 2 chữ số thập phân."),
            "currency": _string("Mã tiền tệ ISO 4217."),
        },
        "required": ["cart_id", "items", "total_price", "currency"],
    },
    "purchase_observed": {
        "description": "Quan sát được một đơn hàng hoàn tất. Không suy ra doanh thu thực.",
        "properties": {
            "cart_id": _string("Định danh đơn hàng, UUID."),
            "items": _array("Dòng sản phẩm trong đơn.", ITEM_SCHEMA),
            "total_price": _string("Tổng tiền, chuỗi decimal tối đa 2 chữ số thập phân."),
            "currency": _string("Mã tiền tệ ISO 4217."),
        },
        "required": ["cart_id", "items", "total_price", "currency"],
    },
    "element_click": {
        "description": "Người dùng bấm một phần tử UI cụ thể.",
        "properties": {
            "selector": _string("CSS selector của phần tử."),
            "tag": _string("Tên thẻ HTML."),
            "sort": _string("Giá trị sắp xếp nếu phần tử là dropdown."),
        },
        "required": ["selector"],
    },
    "scroll_depth": {
        "description": "Người dùng cuộn trang tới một mức độ nhất định.",
        "properties": {
            "depth_percent": _number("Phần trăm chiều cao trang đã cuộn, 0-100."),
        },
        "required": ["depth_percent"],
    },
    "search": {
        "description": "Người dùng gửi từ khoá tìm kiếm.",
        "properties": {
            "query": _string("Từ khoá tìm kiếm."),
            "results_count": _int("Số kết quả trả về."),
            "type": _string("Loại tìm kiếm, ví dụ 'catalog_search'."),
        },
        "required": ["query"],
    },
    "error": {
        "description": "Lỗi JavaScript xảy ra phía client.",
        "properties": {
            "message": _string("Thông điệp lỗi."),
            "stack": _string("Stack trace nếu có."),
        },
        "required": ["message"],
    },
    "cart_abandoned": {
        "description": "Rời trang khi giỏ hàng vẫn còn sản phẩm.",
        "properties": {
            "items": _array("Dòng sản phẩm còn lại trong giỏ.", ITEM_SCHEMA),
            "total_price": _string("Tổng tiền, chuỗi decimal tối đa 2 chữ số thập phân."),
            "currency": _string("Mã tiền tệ ISO 4217."),
        },
        "required": ["items", "total_price", "currency"],
    },
    "apply_filter": {
        "description": "Người dùng áp dụng bộ lọc danh mục.",
        "properties": {
            "filter_type": _string("Loại bộ lọc, ví dụ 'category'."),
            "filter_value": _string("Giá trị bộ lọc."),
        },
        "required": ["filter_type"],
    },
    "wishlist_add": {
        "description": "Sản phẩm được thêm vào danh sách yêu thích.",
        "properties": {
            "product_id": _string("Mã sản phẩm."),
            "price": _string("Giá bán tại thời điểm thêm."),
            "currency": _string("Mã tiền tệ ISO 4217."),
        },
        "required": ["product_id"],
    },
    "wishlist_remove": {
        "description": "Sản phẩm bị xoá khỏi danh sách yêu thích.",
        "properties": {
            "product_id": _string("Mã sản phẩm."),
        },
        "required": ["product_id"],
    },
    "newsletter_signup": {
        "description": "Người dùng đăng ký nhận bản tin.",
        "properties": {
            "email": _string("Địa chỉ email."),
        },
        "required": ["email"],
    },
}


# ── Entity schemas ───────────────────────────────────────────────────────────
#
# Entity là dữ liệu tham chiếu có thể gắn vào nhiều event (context trong
# tracker). Enriched event lưu entity trong cột contexts_<vendor>_<name>_1.

ENTITIES: dict[str, dict] = {
    "session": {
        "description": "Phiên làm việc phía client. Snowplow tự quản lý domain_sessionid, "
                       "entity này giữ session_id do ứng dụng cấp.",
        "properties": {
            "session_id": _string("Định danh phiên do client sinh, UUID."),
        },
        "required": ["session_id"],
    },
    "product": {
        "description": "Thuộc tính sản phẩm dùng chung cho nhiều event.",
        "properties": {
            "product_id": _string("Mã sản phẩm."),
            "category_id": _string("Danh mục phân cấp."),
            "brand": _string("Thương hiệu."),
            "price": _string("Giá bán, chuỗi decimal tối đa 2 chữ số thập phân."),
            "currency": _string("Mã tiền tệ ISO 4217."),
        },
        "required": ["product_id"],
    },
}


# ── Builder ──────────────────────────────────────────────────────────────────

def build_schema(name: str, definition: dict) -> dict:
    """Bọc definition thành self-describing JSON Schema chuẩn của Iglu."""
    schema = {
        "$schema": SELF_DESC_META,
        "description": definition["description"],
        "self": {
            "vendor": VENDOR,
            "name": name,
            "format": FORMAT,
            "version": VERSION,
        },
        "type": "object",
        "properties": definition["properties"],
        "additionalProperties": False,
    }
    # Iglu JSON Schema yêu cầu "required" có ít nhất 1 phần tử — bỏ hẳn nếu rỗng.
    required = definition.get("required") or []
    if required:
        schema["required"] = required
    return schema


def write_schema(name: str, definition: dict) -> Path:
    target_dir = SCHEMA_ROOT / VENDOR / name / FORMAT
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / VERSION
    payload = json.dumps(build_schema(name, definition), indent=2, ensure_ascii=False)
    target.write_text(payload + "\n", encoding="utf-8")
    return target


def main() -> int:
    if SCHEMA_ROOT.exists():
        import shutil
        shutil.rmtree(SCHEMA_ROOT)
    SCHEMA_ROOT.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for name, definition in EVENTS.items():
        written.append(write_schema(name, definition))
    for name, definition in ENTITIES.items():
        written.append(write_schema(name, definition))

    print(f"Vendor: {VENDOR}")
    print(f"Version: {VERSION}")
    print(f"Events: {len(EVENTS)} | Entities: {len(ENTITIES)} | Total: {len(written)}")
    print(f"Root:   {SCHEMA_ROOT}")
    for path in written:
        rel = path.relative_to(SCHEMA_ROOT.parent)
        print(f"  iglu:{VENDOR}/{path.parent.parent.name}/{FORMAT}/{VERSION}  <- {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
