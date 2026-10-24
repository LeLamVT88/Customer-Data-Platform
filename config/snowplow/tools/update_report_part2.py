#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config/snowplow/tools/update_report_part2.py — cap nhat PHAN 2 cua bao cao DOCX.

Bao cao ly thuyet Snowplow ban dau mo ta kien truc CDP Demo cu (FastAPI tu
thu thap event -> ghi CSV) va deu xuat "nang cap len Snowplow" nhu mot buoc
trong tuong lai. Sau khi backend duoc thay hoan toan bang Snowplow, PHAN 2
da lech thuc te.

Script nay:
  1. Khoi phuc mau chu cua tai lieu goc cho cac doan van ban dung chung
     (do moi ban DOCX moi lam mat mau).
  2. Thay the PHAN 2 bang mo ta kien truc dang chay that, giu nguyen
     formatting (co chu, mau heading, style List Bullet).

    python config/snowplow/tools/update_report_part2.py
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import docx
from docx.oxml import parse_xml
from docx.shared import Pt, RGBColor

_REPO = Path(__file__).resolve().parents[3]
DOCX = _REPO / "docs" / "snowplow-theory-and-cdp-application-report.docx"

# Mau heading dung trong tai lieu goc.
BLUE = "1E6FBF"
NAVY = "1A3A5C"
BODY = "444444"

# Kich thuoc (Pt) theo dung style goc.
SIZE_H1 = Pt(17)     # tieu de PHAN
SIZE_H2 = Pt(13)     # tieu de muc 2.x
SIZE_H3 = Pt(11)     # tieu de muc nho
SIZE_BODY = Pt(11)

_W_P = ('<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main"/>')


# ── helpers ───────────────────────────────────────────────────────────────────

def _code_style(paragraph):
    """Gan style khoi code cho paragraph (giong PHAN 1).

    Font monospace 9pt, nen xam nhat, thut le trai — dung dinh dang cua
    cac khoi code trong tai lieu goc de Part 1 va Part 2 dong nhat.
    """
    pPr = paragraph._p.get_or_add_pPr()
    shd = parse_xml(
        '<w:shd xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main" w:val="clear" w:color="auto" w:fill="F0F4F8"/>')
    pPr.append(shd)
    spacing = parse_xml(
        '<w:spacing xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main" w:after="120"/>')
    pPr.append(spacing)
    ind = parse_xml(
        '<w:ind xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main" w:left="283"/>')
    pPr.append(ind)


def _set_text(paragraph, text, *, bold=False, size=SIZE_BODY, color=BODY,
              font="Calibri", code=False):
    """Ghi de noi dung cua paragraph, giu lai run dau tien de giu formatting.

    Chuoi ``**...**`` duoc phan tich thanh cac run bold that, thay vi de lai
    literal dau ``*`` trong tai lieu.
    """
    if code:
        font = "Courier New"
        size = Pt(9)
    runs = paragraph.runs
    if runs:
        first = runs[0]
        for extra in runs[1:]:
            extra._element.getparent().remove(extra._element)
    else:
        first = paragraph.add_run("")

    first.text = ""
    first.bold = bold
    first.font.size = size
    first.font.color.rgb = RGBColor.from_string(color)
    if font:
        first.font.name = font

    if not text:
        return paragraph

    # Tach cac doan bold theo cu phap **...**.
    for i, chunk in enumerate(text.split("**")):
        if not chunk:
            continue
        if i == 0:
            run = first
            run.text = chunk
        else:
            run = paragraph.add_run(chunk)
            run.bold = not bold
            run.font.size = size
            run.font.color.rgb = RGBColor.from_string(color)
            if font:
                run.font.name = font
    return paragraph


def _insert_after(anchor, text, *, style=None, bold=False, size=SIZE_BODY,
                  color=BODY, font="Consolas"):
    """Chen mot paragraph moi ngay sau anchor."""
    new_el = parse_xml(_W_P)
    anchor._p.addnext(new_el)
    new_p = docx.text.paragraph.Paragraph(new_el, anchor._parent)
    if style:
        new_p.style = style
    _set_text(new_p, text, bold=bold, size=size, color=color, font=font)
    return new_p


def _insert_before(anchor, text, *, style=None, bold=False, size=SIZE_BODY,
                   color=BODY, font="Calibri", code=False):
    """Chen mot paragraph moi ngay truoc anchor."""
    new_el = parse_xml(_W_P)
    anchor._p.addprevious(new_el)
    new_p = docx.text.paragraph.Paragraph(new_el, anchor._parent)
    if style:
        new_p.style = style
    _set_text(new_p, text, bold=bold, size=size, color=color, font=font,
              code=code)
    if code:
        _code_style(new_p)
    return new_p


def _delete_range(paragraphs, start, end):
    """Xoa cac paragraph trong khoang [start, end) (theo chi so)."""
    for p in paragraphs[start:end]:
        p._element.getparent().remove(p._element)


# ── Nội dung các bảng thuộc PHẦN 2 ───────────────────────────────────────────
# Mỗi bảng: (tiêu đề cột đầu tiên, dữ liệu). Bảng cũ mô tả kiến trúc
# trước khi chuyển sang Snowplow nên được thay bằng bản mới.

_TABLE_CONCEPTS = {
    "header": ("Snowplow Concept", "Thành phần trong CDP Demo", "Khác biệt chính"),
    "rows": [
        ("Event Collector",
         "Snowplow Micro (`config/docker/compose.snowplow.yml`, cổng 9090)",
         "Giống nhau: đều là HTTP endpoint nhận event"),
        ("Raw Events Stream",
         "Collector ghi thẳng vào PostgreSQL (Micro là all-in-one)",
         "CDP: không có stream layer; Snowplow: tách riêng Kinesis/Kafka"),
        ("Iglu Schema Registry",
         "Schema nhúng `config/snowplow/iglu-client-embedded/`",
         "CDP: không có; Snowplow: có, version hoá được schema"),
        ("Stream Enrich",
         "Enrich trong Snowplow Micro (YAUAA, IP geolocation)",
         "CDP: không có; Snowplow: tự động làm giàu mọi event"),
        ("Good Events Stream",
         "Bảng `events` với `failed = false`",
         "CDP: không có khái niệm good/bad stream"),
        ("Bad Events Stream",
         "Bảng `events` với `failed = true`",
         "CDP: file `quarantine.csv` tự viết; Snowplow: cột cờ trong DB"),
        ("Tracker Protocol",
         "TP2 (`payload_data/jsonschema/1-0-4`)",
         "CDP: JSON tự định nghĩa; Snowplow: chuẩn hoá, có sẵn cho mọi tracker"),
        ("Schema Validation",
         "Enrich validate theo Iglu schema `com.cdp.demo/*`",
         "CDP: enum check trong FastAPI; Snowplow: JSON Schema đầy đủ"),
        ("Event ID",
         "`event_id` UUID do Collector gán",
         "CDP: checksum + ordinal tự tính; Snowplow: chuẩn UUID"),
        ("Collector Timestamp",
         "`collector_tstamp` (thời gian Collector nhận event)",
         "CDP: `event_time` từ client; Snowplow: thời gian server"),
        ("Derived Timestamps",
         "`derived_tstamp`, `dvce_created_tstamp`",
         "CDP: không có; Snowplow: chuẩn hoá theo tầng"),
        ("User Identity",
         "`domain_userid` / `user_id` từ tracker",
         "CDP: `user_id` tự sinh; Snowplow: hỗ trợ stitched identity"),
        ("Storage Target",
         "PostgreSQL (storage backend của Micro)",
         "CDP: CSV/Parquet cục bộ; Snowplow: nhiều đích tải"),
        ("Query Layer",
         "Demo API read-only (`GET /api/summary`)",
         "CDP: cần tự viết; Snowplow: có sẵn data models"),
        ("Pipeline Bridge",
         "Spark JDBC đọc bảng `events`",
         "CDP: Spark đọc file CSV; Snowplow: đọc trực tiếp storage"),
        ("Enrichment Context",
         "`os_*`, `os_version`, `device_type`, `browser_*`",
         "CDP: chỉ lưu raw `user_agent`; Snowplow: đã phân rã"),
        ("Warehouse Loader",
         "Chưa dùng (giữ PostgreSQL local)",
         "CDP: không có; Snowplow: Stream/Warehouse Loader sẵn sàng"),
    ],
}

_TABLE_EVENT_TYPES = {
    "header": ("Event Type", "Khi nào bắn", "Iglu schema"),
    "rows": [
        ("page_view", "Hash routing thay đổi", "com.cdp.demo/page_view"),
        ("product_view", "Click product card", "com.cdp.demo/product_view"),
        ("search", "Nhập từ khoá tìm kiếm", "com.cdp.demo/search"),
        ("apply_filter", "Chọn bộ lọc / sắp xếp", "com.cdp.demo/apply_filter"),
        ("add_to_cart", "Bấm \"Thêm vào giỏ hàng\"", "com.cdp.demo/add_to_cart"),
        ("remove_from_cart", "Bấm \"Xoá\" trong giỏ", "com.cdp.demo/remove_from_cart"),
        ("wishlist_add", "Bấm icon trái tim", "com.cdp.demo/wishlist_add"),
        ("wishlist_remove", "Bấm lại icon trái tim", "com.cdp.demo/wishlist_remove"),
        ("begin_checkout", "Bấm \"Thanh toán\"", "com.cdp.demo/begin_checkout"),
        ("purchase_observed", "Xác nhận đơn hàng", "com.cdp.demo/purchase_observed"),
        ("cart_abandoned", "Rời trang khi giỏ còn hàng", "com.cdp.demo/cart_abandoned"),
        ("newsletter_signup", "Đăng ký nhận tin", "com.cdp.demo/newsletter_signup"),
        ("scroll_depth", "Cuộn qua mốc 25/50/75/100%", "com.cdp.demo/scroll_depth"),
        ("element_click", "Click phần tử có data-track", "com.cdp.demo/element_click"),
        ("error", "Lỗi JS / promise rejection", "com.cdp.demo/error"),
        ("session", "Entity ngữ cảnh, gắn theo session", "com.cdp.demo/session"),
    ],
}

_TABLE_ROADMAP = {
    "header": ("Giai đoạn", "Mục tiêu", "Thành phần mới", "Effort", "Impact"),
    "rows": [
        ("G0: Snowplow-native backend",
         "Thay toàn bộ backend tự viết bằng Snowplow",
         "Snowplow Micro + Iglu + PostgreSQL",
         "Đã xong", "Cao"),
        ("G1: dbt Data Models",
         "Chuẩn hoá dữ liệu đã enrich thành bảng phân tích",
         "dbt models + dbt tests",
         "1-2 tuần", "Cao"),
        ("G2: Warehouse Loader",
         "Đưa dữ liệu ra khỏi local PostgreSQL",
         "Snowflake/BigQuery + Warehouse Loader",
         "2-3 tuần", "Cao"),
        ("G3: Identity Resolution",
         "Nối anonymous với user đã đăng nhập",
         "sp.js + identity graph",
         "2-4 tuần", "Trung bình"),
        ("G4: Production Hardening",
         "Scale ngang + giám sát data quality",
         "Tách service + monitoring/alerting",
         "3-4 tuần", "Trung bình"),
    ],
}


_TABLE_INTEGRATION = {
    "header": ("Thành phần CDP Demo", "Thay thế bằng Snowplow", "Trạng thái"),
    "rows": [
        ("`catalog.js` track()", "Snowplow Browser Tracker (`tracker.js`)",
         "Đã xong — TP2 tới collector"),
        ("Demo API `POST /api/events`", "Snowplow Collector (Micro :9090)",
         "Đã xong — route đã bị gỡ bỏ"),
        ("FastAPI enum validation", "Iglu Schema Registry + Snowplow Enrich",
         "Đã xong — 17 schema `com.cdp.demo/*`"),
        ("`quarantine.csv`", "Bad Stream (`failed = true` trong bảng `events`)",
         "Đã xong — cột cờ thay cho file"),
        ("`data/demo-events/*.csv`", "PostgreSQL storage backend (bảng `events`)",
         "Đã xong — dữ liệu còn nguyên sau restart"),
        ("Lakehouse Spark/Iceberg", "Spark JDBC đọc thẳng từ `events`",
         "Đã xong — bỏ bước đọc CSV"),
        ("`dashboard.js`", "Demo API read-only + (sau này) dbt models",
         "Đã xong — đọc `/api/summary`"),
        ("Bot Driver", "Snowplow Simulator (kiểm thử pipeline)",
         "Đã xong — bot tự gửi TP2"),
    ],
}


def _write_table(table, header, rows):
    """Ghi lai noi dung bang, giu nguyen style cua bang goc."""
    # Header row.
    for cell, text in zip(table.rows[0].cells, header):
        cell.text = ""
        para = cell.paragraphs[0]
        _set_text(para, text, bold=True, size=SIZE_BODY, color=BODY,
                  font="Calibri")

    # Cac dong du lieu: dung lai dong cu neu du, them moi neu thieu.
    while len(table.rows) - 1 < len(rows):
        table.add_row()
    while len(table.rows) - 1 > len(rows):
        tr = table.rows[-1]._tr
        tr.getparent().remove(tr)

    for row, values in zip(table.rows[1:], rows):
        for cell, text in zip(row.cells, values):
            cell.text = ""
            para = cell.paragraphs[0]
            _set_text(para, text, bold=False, size=SIZE_BODY, color=BODY,
                      font="Calibri")


def _update_tables(document) -> int:
    """Cap nhat cac bang thuoc PHAN 2 theo kien truc Snowplow moi."""
    specs = [
        ("Snowplow Concept", _TABLE_CONCEPTS),
        ("Event Type", _TABLE_EVENT_TYPES),
        ("Thành phần CDP Demo", _TABLE_INTEGRATION),
        ("Giai đoạn", _TABLE_ROADMAP),
    ]

    updated = 0
    for table in document.tables:
        if not table.rows:
            continue
        first = table.rows[0].cells[0].text.strip()
        for probe, spec in specs:
            if first != probe:
                continue
            _write_table(table, spec["header"], spec["rows"])
            updated += 1
            break
    return updated


def _key(text):
    """Khoa so sanh noi dung bo qua dau cach dau chung."""
    return re.sub(r'[^a-z0-9]', '', text.lower())


def _restore_colors(work_doc, head_path: Path) -> int:
    """Khoi phuc mau chu cho cac doan van ban dung chung voi ban goc."""
    head_doc = docx.Document(str(head_path))

    head_by_key = {}
    for p in head_doc.paragraphs:
        k = _key(p.text)
        if not k:
            continue
        colored = [(r.font.color.rgb, r.bold, r.font.size)
                   for r in p.runs
                   if (r.font.color and r.font.color.type is not None
                       and r.font.color.rgb)]
        if colored and k not in head_by_key:
            head_by_key[k] = colored

    restored = 0
    for p in work_doc.paragraphs:
        k = _key(p.text)
        if not k or k not in head_by_key:
            continue
        colored = head_by_key[k]
        if not p.runs:
            continue
        # Chi gan lai mau cho run dau tien; giu bold/size hien tai.
        run = p.runs[0]
        run.font.color.rgb = RGBColor.from_string(str(colored[0][0]))
        for extra in p.runs[1:]:
            extra.font.color.rgb = RGBColor.from_string(str(colored[0][0]))
        restored += 1
    return restored


def main() -> None:
    if not DOCX.exists():
        raise SystemExit(f"Khong tim thay file: {DOCX}")

    head_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        _REPO / "logs" / "head_report.docx")

    backup = DOCX.with_suffix(".docx.bak")
    shutil.copy2(DOCX, backup)

    document = docx.Document(str(DOCX))

    if head_path.exists():
        n = _restore_colors(document, head_path)
        print(f"Khoi phuc mau cho {n} doan van dung chung voi ban goc.")

    paragraphs = document.paragraphs

    # PHAN 2 trong than bai: tu tieu de "PHAN 2" (lan 2) toi truoc
    # "Tai lieu tham khao".
    start = None
    ref_idx = None
    seen = 0
    for i, p in enumerate(paragraphs):
        if p.text.strip().startswith("PH\u1ea6N 2"):
            seen += 1
            if seen == 2:          # lan 2 = phan than bai (lan 1 = muc luc)
                start = i
                break
    for i, p in enumerate(paragraphs):
        if (p.text.strip().startswith("T\u00e0i li\u1ec7u tham kh\u1ea3o")
                and i > (start or 0)):
            ref_idx = i
            break

    if start is None or ref_idx is None:
        raise SystemExit("Khong xac dinh duoc vung PHAN 2 can thay the.")

    print(f"Thay the PHAN 2: paragraph {start}..{ref_idx - 1} "
          f"({ref_idx - start} paragraph)")

    _delete_range(paragraphs, start, ref_idx)
    anchor = paragraphs[ref_idx]

    n_tables = _update_tables(document)
    print(f"Da cap nhat {n_tables} bang thuoc PHAN 2.")

    B = []   # blocks

    def add(text, **kw):
        B.append(("p", text, kw))

    def bullet(text, **kw):
        B.append(("b", text, kw))

    def h2(text):
        B.append(("h2", text, {}))

    def h3(text):
        B.append(("h3", text, {}))

    add("PH\u1ea6N 2 \u2014 \u1ee8NG D\u1ee4NG TRONG D\u1ef0 \u00c1N CDP",
        bold=True, size=SIZE_H1, color=NAVY, font="Calibri")
    add("\u2139 Ph\u1ea7n n\u00e0y m\u00f4 t\u1ea3 c\u00e1ch Snowplow \u0111\u01b0\u1ee3c tri\u1ec7n "
        "khai th\u1ef1c t\u1ebf trong d\u1ef1 \u00e1n Customer Data Platform: backend t\u1ef1 "
        "vi\u1ebft \u0111\u00e3 \u0111\u01b0\u1ee3c thay ho\u00e0n to\u00e0n b\u1eb1ng Snowplow, "
        "m\u1ecdi th\u00e0nh ph\u1ea7n c\u1ee7a pipeline Snowplow \u0111\u1ec1u \u0111\u01b0\u1ee3c "
        "v\u1eadn h\u00e0nh th\u1eadt (Collector, Enrich, Iglu Schema Registry, Storage "
        "backend) v\u00e0 \u0111\u01b0\u1ee3c ki\u1ec3m ch\u1ee9ng b\u1eb1ng d\u1eef li\u1ec7u "
        "ch\u1ea1y th\u1eadt.",
        font="Calibri")

    h2("2.1  Ki\u1ebfn tr\u00fac hi\u1ec7n t\u1ea1i c\u1ee7a d\u1ef1 \u00e1n CDP")
    add("D\u1ef1 \u00e1n CDP hi\u1ec7n t\u1ea1i ch\u1ea1y pipeline Snowplow \u0111\u1ea7y \u0111\u1ee7, "
        "v\u1edbi 5 th\u00e0nh ph\u1ea7n ch\u00ednh:", font="Calibri")
    add("""\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
\u2502        CDP PROJECT \u2014 SNOWPLOW-NATIVE ARCHITECTURE              \u2502
\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518

 \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
 \u2502  Web Demo SPA (HTML/JS/CSS)  \u2502  \u2190 Giao di\u1ec7n ng\u01b0\u1eddi d\u00f9ng
 \u2502  src/demo/web/               \u2502    @snowplow/browser-tracker
 \u2502  http://localhost:8081       \u2502    4 persona flows (Lina/Minh/Hoa/Quang)
 \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
                \u2502 TP2 POST (self-describing events)
                \u2502 iglu:com.cdp.demo/<event_type>/jsonschema/1-0-0
                \u25bc
 \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
 \u2502  Snowplow Micro (:9090)      \u2502  \u2190 Collector + Stream Enrich
 \u2502  config/snowplow/micro.conf  \u2502    G\u00e1n event_id + collector_tstamp
 \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
                \u2502 Iglu validation + YAUAA enrichment
                \u25bc
 \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
 \u2502  PostgreSQL (storage)        \u2502  \u2190 Storage backend
 \u2502  b\u1ea3ng `events`               \u2502    Enriched event + failed flag
 \u2502  :5432                       \u2502    Bad stream = failed = true
 \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
        \u2502               \u2502
        \u2502 psycopg       \u2502 JDBC
        \u25bc               \u25bc
 \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510  \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510  \u2190 Analytics & Modeling
 \u2502  Demo API   \u2502  \u2502  Lakehouse       \u2502    Bronze \u2192 Silver \u2192 Quarantine \u2192 Gold
 \u2502  (read-only)\u2502  \u2502  Spark \u2192 Iceberg \u2502    src/demo/
 \u2502  :8000      \u2502  \u2502  src/demo/       \u2502
 \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u253c\u2500\u2500\u2500\u2518  \u2502  lakehouse/      \u2518\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
        \u2502 GET
        \u2502 /api/summary
        \u25bc
 \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
 \u2502  Dashboard (JavaScript)      \u2502  \u2190 Visualization
 \u2502  src/demo/web/js/dashboard.js\u2502    Stats cards, persona funnels,
 \u2502                              \u2502    bar charts (Canvas)
 \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518

 \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
 \u2502  Bot Driver (synthetic)      \u2502  \u2190 Ngu\u1ed3n traffic th\u1ee9 hai
 \u2502  src/demo/bot/driver.py      \u2502    TP2 tr\u1ef1c ti\u1ebfp t\u1edbi collector
 \u2502  src/demo/snowplow/tp2.py    \u2502    C\u00f9ng schema, c\u00f9ng validation
 \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518""", code=True)
    add("\u0110i\u1ec3m m\u1ea1nh c\u1ee7a ki\u1ebfn tr\u00fac hi\u1ec7n t\u1ea1i", bold=True,
        size=SIZE_H3, color=NAVY, font="Calibri")
    bullet("**Schema validation th\u1eadt** \u2014 17 Iglu schema `com.cdp.demo/*` "
           "\u0111\u01b0\u1ee3c Snowplow Enrich ki\u1ec3m tra, kh\u00f4ng ph\u1ea3i enum check "
           "trong FastAPI")
    bullet("**Bad stream chu\u1ea9n** \u2014 event l\u1ed7i \u0111\u01b0\u1ee3c \u0111\u00e1nh d\u1ea5u "
           "`failed = true` ngay trong b\u1ea3ng `events`, kh\u00f4ng c\u1ea7n file quarantine ri\u00eang")
    bullet("**Enrichment c\u00f3 s\u1ea5n** \u2014 YAUAA parse user-agent, b\u1ed5 sung device/OS/browser")
    bullet("**M\u1ed9t ngu\u1ed3n d\u1eef li\u1ec7u duy nh\u1ea5t** \u2014 traffic web v\u00e0 traffic "
           "bot c\u00f9ng ghi v\u00e0o m\u1ed9t b\u1ea3ng, c\u00f9ng b\u1ecb validate b\u1ed1i c\u00f9ng b\u1ed9 schema")
    bullet("**Idempotency chu\u1ea9n** \u2014 `event_id` UUID c\u1ee7a Snowplow thay cho checksum "
           "th\u1ee7 c\u1ee7a c\u1ee7a batch")
    bullet("**Lakehouse n\u1ed1i tr\u1ef1c ti\u1ebfp** \u2014 Spark \u0111\u1ecdc PostgreSQL qua JDBC, "
           "kh\u00f4ng c\u00f2n b\u01b0\u1edbc trung gian ghi/\u0111\u1ecdc CSV")
    bullet("**Persona-driven** \u2014 4 personas v\u1edbi event signature kh\u00e1c nhau ph\u1ee5c v\u1ee5 testing")
    bullet("**Dashboard real-time** \u2014 auto-refresh 10s cho th\u1ea5y pipeline ho\u1ea1t \u0111\u1ed9ng ngay")
    add("\u0110i\u1ec3m c\u00f2n h\u1ea1n ch\u1ebf", bold=True, size=SIZE_H3,
        color=NAVY, font="Calibri")
    bullet("\u274c D\u00f9ng Snowplow Micro (all-in-one) \u2014 ch\u01b0a t\u00e1ch Collector/Enrich "
           "th\u00e0nh service ri\u00eang nh\u01b0 production")
    bullet("\u274c Ch\u1ec9 m\u1ed9t storage backend \u2014 ch\u01b0a c\u00f3 multi-destination "
           "(Snowflake, BigQuery, S3)")
    bullet("\u274c Ch\u01b0a c\u00f3 identity stitching \u2014 `user_id` do client g\u1eedi, "
           "ch\u01b0a c\u00f3 anonymous \u2192 logged-in resolution")
    bullet("\u274c Data model ch\u01b0a d\u00f9ng dbt \u2014 \u0111ang d\u00f9ng Spark SQL thu\u1ea7n")
    bullet("\u274c Ch\u01b0a c\u00f3 monitoring/alerting cho data quality")

    h2("2.2  Event Collection trong CDP Demo \u2014 Chi ti\u1ebft k\u1ef9 thu\u1eadt")
    add("CDP Demo thu th\u1eadp event theo m\u00f4 h\u00ecnh **self-describing events**. "
        "C\u1ea3 web app v\u00e0 bot \u0111\u1ec1u g\u1eedi **Tracker Protocol 2 (TP2)** "
        "th\u1eb3ng t\u1edbi Snowplow Micro \u2014 kh\u00f4ng c\u00f3 b\u01b0\u1edbc g\u1ecdi v\u00e0o "
        "Demo API n\u1eefa.", font="Calibri")
    add("Event flow trong CDP Demo", bold=True, size=SIZE_H3, color=NAVY, font="Calibri")
    add("1  Client-side tracking (web):")
    add("""// src/demo/web/js/tracker.js \u2014 Snowplow Browser Tracker
snowplow.newTracker(TRACKER_NAME, COLLECTOR_URL, {
  appId: APP_ID,
  platform: 'web',
  eventMethod: 'post',
  bufferSize: 1,          // g\u1eedi ngay, kh\u00f4ng gom trong store
});

snowplow.trackSelfDescribing({
  schema: 'iglu:com.cdp.demo/product_view/jsonschema/1-0-0',
  data: { product_id, price, currency, category_id },
  context: [ sessionEntity, productEntity ],
});""", code=True)
    add("2  Wire format \u2014 Tracker Protocol 2:")
    add("""{
  "e": "ue",
  "ue_pr": "{\\"schema\\":\\"iglu:com.snowplowanalytics.snowplow/unstruct_event/jsonschema/1-0-0\\",
             \\"data\\":{\\"schema\\":\\"iglu:com.cdp.demo/product_view/jsonschema/1-0-0\\",
             \\"data\\":{...}}}",
  "co":   "{\\"schema\\":\\"iglu:com.snowplowanalytics.snowplow/contexts/jsonschema/1-0-0\\",
             \\"data\\":[{...},{...}]}",
  "eid": "<uuid>", "dtm": "<epoch ms>", "tna": "cdpDemo",
  "aid": "cdp-demo", "p": "web", "tv": "js-4.10.2"
}""", code=True)
    add("3  Server-side processing (Snowplow Enrich):")
    bullet("Collector nh\u1eadn payload, g\u00e1n `event_id` UUID + `collector_tstamp`")
    bullet("Enrich validate theo Iglu schema trong "
           "`config/snowplow/iglu-client-embedded/schemas/com.cdp.demo/`")
    bullet("Enrich b\u1ed5 sung ng\u1eef c\u1ea3nh: YAUAA (device/OS/browser), IP geolocation")
    bullet("Event h\u1ee3p l\u1ec7 \u2192 b\u1ea3ng `events` v\u1edbi `failed = false`")
    bullet("Event sai schema \u2192 b\u1ea3ng `events` v\u1edbi `failed = true` (bad stream)")
    add("4  Query layer (Demo API \u2014 ch\u1ec9 \u0111\u1ecdc):")
    bullet("`GET /api/catalog` \u2014 tr\u1ea3 v\u1ec1 250 products t\u1eeb config JSON")
    bullet("`GET /api/summary` \u2014 \u0111\u1ecdc b\u1ea3ng `events` qua `psycopg`, aggregate "
           "counts / users / sessions / top search / wishlist / category")
    bullet("`GET /health` \u2014 health check")
    add("5  Lakehouse (Spark \u2192 Iceberg):")
    bullet("Spark \u0111\u1ecdc b\u1ea3ng `events` qua JDBC driver `postgresql`")
    bullet("Bronze: m\u1ecdi event (k\u1ec3 c\u1ea3 `failed`), Silver: ch\u1ec9 event h\u1ee3p l\u1ec7, "
           "Quarantine: event Enrich t\u1eeb ch\u1ed1i k\u00e8m l\u00fd do")
    bullet("Gold: t\u1ed5ng h\u1ee3p h\u00e0nh vi theo user/ng\u00e0y + ph\u1ec5u h\u00e0nh vi theo session")
    add("Event Types hi\u1ec7n t\u1ea1i", bold=True, size=SIZE_H3, color=NAVY, font="Calibri")
    bullet("**16 event types** \u2014 m\u1ed7i type l\u00e0 m\u1ed9t Iglu schema ri\u00eang trong vendor "
           "`com.cdp.demo`, version `jsonschema/1-0-0`")
    bullet("**2 entity types** \u2014 `com.cdp.demo/session` (session_id, ...) v\u00e0 "
           "`com.cdp.demo/product` (product_id, price, currency, ...)")

    h2("2.3  \u00c1nh x\u1ea1 kh\u00e1i ni\u1ec7m Snowplow \u2192 CDP Demo")
    add("B\u1ea3ng b\u00ean d\u01b0\u1edbi cho th\u1ea5y c\u00e1c kh\u00e1i ni\u1ec7m c\u1ed1t l\u00f5i "
        "c\u1ee7a Snowplow Analytics \u0111\u01b0\u1ee3c \u00e1nh x\u1ea1 th\u00e0nh th\u00e0nh ph\u1ea7n "
        "c\u1ee5 th\u1ec3 trong d\u1ef1 \u00e1n.", font="Calibri")

    h2("2.4  \u0110i\u1ec3m t\u00edch h\u1ee3p (Integration Points) \u2014 Tr\u1ea1ng th\u00e1i hi\u1ec7n t\u1ea1i")
    add("Chi\u1ebfn l\u01b0\u1ee3c \u0111\u00e3 ch\u1ecdn v\u00e0 \u0111\u00e3 tri\u1ec7n khai: **Thay "
        "th\u1ebf ho\u00e0n to\u00e0n (Full Migration)** \u2014 backend t\u1ef1 vi\u1ebft b\u1ecb lo\u1ea1i "
        "b\u1ecf, to\u00e0n b\u1ed9 event collection chuy\u1ec3n sang Snowplow.", font="Calibri")
    bullet("**Collector** \u2014 `config/docker/compose.snowplow.yml` ch\u1ea1y Snowplow Micro 4.6.1, "
           "expose `127.0.0.1:9090`")
    bullet("**Iglu Schema Registry** \u2014 schema nh\u00fang trong container t\u1ea1i "
           "`config/snowplow/iglu-client-embedded/`, kh\u00f4ng c\u1ea7n Iglu Server ri\u00eang")
    bullet("**Stream Enrich** \u2014 b\u1eadt trong `micro.conf` v\u1edbi YAUAA enrichment")
    bullet("**Storage backend** \u2014 PostgreSQL 16, b\u1ea3ng `events` trong schema "
           "`public`, d\u00f9ng chung cho dashboard v\u00e0 lakehouse")
    bullet("**Tracker** \u2014 `@snowplow/browser-tracker` (web) + "
           "`src/demo/snowplow/tp2.py` (bot), c\u00f9ng n\u00f3i TP2")
    add("C\u00e1c chi\u1ebfn l\u01b0\u1ee3c t\u00edch h\u1ee3p kh\u00e1c \u0111\u00e3 c\u00e2n nh\u1eafc",
        bold=True, size=SIZE_H3, color=NAVY, font="Calibri")
    bullet("**Layered Addition** \u2014 gi\u1eef FastAPI l\u00e0m collection layer, th\u00eam Snowplow "
           "b\u00ean d\u01b0\u1edbi. \u0110\u00e3 b\u1ecf: t\u1ea1o hai n\u01a1i validate event, d\u1ec5 l\u1ec7ch schema")
    bullet("**Side-by-side** \u2014 ch\u1ea1y c\u1ea3 hai h\u1ec7 th\u1ed1ng song song \u0111\u1ec3 so "
           "s\u00e1nh. \u0110\u00e3 b\u1ecf: chi ph\u00ed v\u1eadn h\u00e0nh kh\u00f4ng \u0111\u00e1ng v\u1edbi quy m\u00f4 demo")
    bullet("**Ch\u1ec9 d\u00f9ng Snowplow Storage** \u2014 gi\u1eef FastAPI validate r\u1ed3i \u0111\u1ea5y xu\u1ed1ng "
           "Snowplow. \u0110\u00e3 b\u1ecf: Enrich v\u1eabn validate l\u1ea7n n\u1eefa, th\u1eeba")

    h2("2.5  L\u1ed9 tr\u00ecnh ti\u1ebfp theo")
    add("Giai \u0111o\u1ea1n hi\u1ec7n t\u1ea1i (t\u1ea7ng backend chuy\u1ec3n sang Snowplow) \u0111\u00e3 "
        "ho\u00e0n t\u1ea5t. L\u1ed9 tr\u00ecnh ti\u1ebfp theo t\u1eadp trung v\u00e0o nh\u1eefng t\u1ea7ng "
        "c\u00f2n thi\u1ebfu:", font="Calibri")
    h3("Giai \u0111o\u1ea1n 1 \u2014 Production Storage & Multi-destination")
    bullet("Thay PostgreSQL local b\u1eb1ng warehouse (Snowflake/BigQuery) qua Snowplow "
           "Warehouse Loader")
    bullet("Th\u00eam S3 l\u00e0m raw storage layer cho to\u00e0n b\u1ed9 event")
    h3("Giai \u0111o\u1ea1n 2 \u2014 Data Models b\u1eb1ng dbt")
    bullet("Vi\u1ebft dbt models tr\u00ean n\u1ec1n d\u1eef li\u1ec7u \u0111\u00e3 enrich: session, user, funnel")
    bullet("Th\u00eam dbt tests cho data quality, thay cho ki\u1ec3m tra th\u1ee7 c\u1ea5ng")
    h3("Giai \u0111o\u1ea1n 3 \u2014 Identity Resolution")
    bullet("Th\u00eam `sp.js` \u0111\u1ec3 \u0111\u1ecbnh danh anonymous \u2192 logged-in, cross-device stitching")
    bullet("Customer 360 view: JOIN event v\u1edbi d\u1eef li\u1ec7u kh\u00e1ch h\u00e0ng nghi\u1ec7p v\u1ee5")
    h3("Giai \u0111o\u1ea1n 4 \u2014 Production Hardening")
    bullet("T\u00e1ch Collector / Enrich / Loader th\u00e0nh service ri\u00eang, scale ngang")
    bullet("Monitoring & alerting cho data quality (schema violation rate, "
           "late-arriving events)")
    add("T\u1ed5ng quan l\u1ed9 tr\u00ecnh", bold=True, size=SIZE_H3, color=NAVY, font="Calibri")

    h2("2.6  K\u1ebft lu\u1eadn v\u00e0 Khuy\u1ebfn ngh\u1ecb")
    add("T\u1ed5ng k\u1ebft", bold=True, size=SIZE_H3, color=NAVY, font="Calibri")
    add("Snowplow Analytics l\u00e0 n\u1ec1n t\u1ea3ng **event analytics m\u1ea1nh m\u1eb3 nh\u1ea5t** "
        "hi\u1ec7n c\u00f3 cho c\u00e1c doanh nghi\u1ec7p mu\u1ed1n s\u1edf h\u1eefu to\u00e0n b\u1ed9 d\u1eef li\u1ec7u "
        "h\u00e0nh vi ng\u01b0\u1eddi d\u00f9ng. Ki\u1ebfn tr\u00fac modular c\u1ee7a Snowplow \u2014 t\u1eeb "
        "Collector \u2192 Enrichment \u2192 Loader \u2192 Warehouse \u2014 cho ph\u00e9p t\u1ed5 ch\u1ee9c b\u1eaft \u0111\u1ea7u "
        "t\u1eeb prototype nh\u1ecf v\u00e0 m\u1edf r\u1ed9ng theo nhu c\u1ea7u m\u00e0 kh\u00f4ng ph\u1ea3i thay "
        "\u0111\u1ed5i ki\u1ebfn tr\u00fac n\u1ec1n t\u1ea3ng.", font="Calibri")
    add("Trong d\u1ef1 \u00e1n n\u00e0y, ki\u1ebfn tr\u00fac backend t\u1ef1 vi\u1ebft \u0111\u00e3 \u0111\u01b0\u1ee3c "
        "**thay ho\u00e0n to\u00e0n** b\u1eb1ng Snowplow: Collector + Enrich + Iglu validation + "
        "PostgreSQL storage. Ph\u1ea7n backend c\u00f2n l\u1ea1i ch\u1ec9 l\u00e0 m\u1ed9t **read layer** "
        "truy v\u1ea5n b\u1ea3ng `events` \u0111\u1ec3 d\u1ef1ng dashboard, v\u00e0 m\u1ed9t job Spark \u1ed1 d\u1eef "
        "li\u1ec7u sang Iceberg. Nh\u01a1 v\u1eady to\u00e0n b\u1ed9 t\u00ednh n\u0103ng c\u1ee7a Snowplow \u2014 "
        "schema validation, enrichment, bad stream \u2014 kh\u00f4ng c\u00f2n l\u00e0 l\u00fd thuy\u1ebft m\u00e0 "
        "\u0111\u00e3 \u0111\u01b0\u1ee3c ki\u1ec3m ch\u1ee9ng b\u1eb1ng d\u1eef li\u1ec7u ch\u1ea1y th\u1eadt trong demo.",
        font="Calibri")
    add("K\u1ebft qu\u1ea3 ki\u1ec3m ch\u1ee9ng", bold=True, size=SIZE_H3, color=NAVY, font="Calibri")
    bullet("To\u00e0n b\u1ed9 event g\u1eedi t\u1eeb web v\u00e0 bot \u0111\u1ec1u pass Iglu validation "
           "(`failed = false`)")
    bullet("Unit test kh\u00f3a ch\u1eb7t contract gi\u1eefa payload frontend v\u00e0 Iglu schema "
           "\u2014 26/26 pass")
    bullet("Lakehouse ch\u1ea1y th\u1eadt: Bronze \u2192 Silver + Quarantine \u2192 Gold, ki\u1ec3m tra "
           "b\u1eb1ng `verify_demo.py`")
    bullet("Dashboard \u0111\u1ecdc tr\u1ef1c ti\u1ebfp t\u1eeb b\u1ea3ng `events`, t\u1ef1 c\u1eadp nh\u1eadt m\u1ed7i 10s")
    add("Khuy\u1ebfn ngh\u1ecb ti\u1ebfp theo", bold=True, size=SIZE_H3, color=NAVY, font="Calibri")
    bullet("**\u01b0u ti\u00ean 1:** dbt models \u2014 bi\u1ebfn b\u1ea3ng `events` th\u00e0nh c\u00e1c b\u1ea3ng "
           "ph\u00e2n t\u00edch chu\u1ea9n, c\u00f3 version control")
    bullet("**\u01b0u ti\u00ean 2:** warehouse loader \u2014 \u0111\u01b0a d\u1eef li\u1ec7u ra kh\u1ecfi local "
           "PostgreSQL \u0111\u1ec3 scale v\u00e0 ph\u00e2n quy\u1ec1n truy c\u1eadp")
    bullet("**\u01b0u ti\u00ean 3:** identity stitching \u2014 n\u1ed1i anonymous v\u1edbi user \u0111\u00e3 \u0111\u0103ng nh\u1eadp")
    add("\u0110i\u1ec3m m\u1ea5u ch\u1ed1t \u0111\u1ec3 nh\u1edb", bold=True, size=SIZE_H3,
        color=NAVY, font="Calibri")
    add("\u2705 1. Backend t\u1ef1 vi\u1ebft \u0111\u00e3 b\u1ecb lo\u1ea1i b\u1ecf ho\u00e0n to\u00e0n \u2014 Snowplow "
        "ch\u1ec9u tr\u00e1ch nhi\u1ec7m thu th\u1eadp, validate v\u00e0 l\u00e0m gi\u00e0u event.\n"
        "2. M\u1ed9t b\u1ea3ng `events` l\u00e0 ngu\u1ed3n d\u1eef li\u1ec7u duy nh\u1ea5t cho c\u1ea3 dashboard l\u1eabn lakehouse.\n"
        "3. Schema `com.cdp.demo/*` l\u00e0 h\u1ee3p \u0111\u1ed3ng gi\u1eefa client, collector v\u00e0 pipeline.\n"
        "4. Bad event kh\u00f4ng bi\u1ebfn m\u1ea5t \u2014 n\u00f3 \u0111\u01b0\u1ee3c gi\u1eef l\u1ea1i v\u1edbi "
        "`failed = true` \u0111\u1ec3 audit.\n"
        "5. L\u1ed9 tr\u00ecnh ti\u1ebfp theo \u0111i t\u1eeb prototype \u0111\u00e3 ch\u1ea1y th\u1eadt l\u00ean production, "
        "kh\u00f4ng ph\u1ea3i t\u1eeb concept.", font="Calibri")

    # Chen cac block ngay TRUOC "Tai lieu tham khao", theo thu tu thuan.
    for kind, text, kw in B:
        if kind == "b":
            _insert_before(anchor, text, style="List Bullet", **kw)
        elif kind == "h2":
            _insert_before(anchor, text, bold=True, size=SIZE_H2,
                           color=BLUE, font="Calibri", **kw)
        elif kind == "h3":
            _insert_before(anchor, text, bold=True, size=SIZE_H3,
                           color=NAVY, font="Calibri", **kw)
        else:
            _insert_before(anchor, text, **kw)

    document.save(str(DOCX))
    print(f"Da cap nhat: {DOCX}")
    print(f"Backup:      {backup}")


if __name__ == "__main__":
    sys.exit(main())
