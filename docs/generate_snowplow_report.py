# -*- coding: utf-8 -*-
"""
Generate Snowplow Theory & CDP Project Application Report
Báo cáo lý thuyết Snowplow và ứng dụng trong dự án CDP
"""

from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

doc = Document()

# ─── Page margins ─────────────────────────────────────────────────────────────
section = doc.sections[0]
section.page_width  = Cm(21)
section.page_height = Cm(29.7)
section.left_margin   = Cm(3.0)
section.right_margin  = Cm(2.5)
section.top_margin    = Cm(2.5)
section.bottom_margin = Cm(2.5)

# ─── Color palette ────────────────────────────────────────────────────────────
BLUE_DARK  = RGBColor(0x1A, 0x3A, 0x5C)   # đậm — headings
BLUE_MID   = RGBColor(0x1E, 0x6F, 0xBF)   # vừa — sub-headings
BLUE_LIGHT = RGBColor(0xD6, 0xE8, 0xF8)   # nhạt — table header bg
SNOWPLOW_RED = RGBColor(0xE5, 0x5B, 0x3F) # Snowplow brand accent
GREEN_OK   = RGBColor(0x1E, 0x8A, 0x4F)
ORANGE_WRN = RGBColor(0xE6, 0x7E, 0x22)
GRAY_TEXT  = RGBColor(0x44, 0x44, 0x44)
GRAY_MID   = RGBColor(0x77, 0x77, 0x77)
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)


# ─── Helper: shade table cell ────────────────────────────────────────────────
def shade_cell(cell, hex_color: str):
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  hex_color)
    tcPr.append(shd)


# ─── Helper: set paragraph borders ──────────────────────────────────────────
def add_bottom_border(para, color="1A3A5C", size=12):
    pPr  = para._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bot  = OxmlElement('w:bottom')
    bot.set(qn('w:val'),   'single')
    bot.set(qn('w:sz'),    str(size))
    bot.set(qn('w:space'), '4')
    bot.set(qn('w:color'), color)
    pBdr.append(bot)
    pPr.append(pBdr)


# ─── Helper: heading styles ──────────────────────────────────────────────────
def heading1(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(22)
    p.paragraph_format.space_after  = Pt(6)
    run = p.add_run(text)
    run.bold       = True
    run.font.size  = Pt(17)
    run.font.color.rgb = BLUE_DARK
    add_bottom_border(p, "1E6FBF", 8)
    return p


def heading2(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run(text)
    run.bold       = True
    run.font.size  = Pt(13)
    run.font.color.rgb = BLUE_MID
    return p


def heading3(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(2)
    run = p.add_run(text)
    run.bold       = True
    run.font.size  = Pt(11)
    run.font.color.rgb = RGBColor(0x2C, 0x3E, 0x50)
    return p


def body(text, indent=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    if indent:
        p.paragraph_format.left_indent = Cm(0.5)
    run = p.add_run(text)
    run.font.size = Pt(11)
    run.font.color.rgb = GRAY_TEXT
    return p


def bullet(text, level=0):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.space_after  = Pt(3)
    p.paragraph_format.left_indent  = Cm(0.5 + level * 0.5)
    run = p.add_run(text)
    run.font.size = Pt(11)
    run.font.color.rgb = GRAY_TEXT
    return p


def code_block(text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent  = Cm(0.5)
    p.paragraph_format.space_after  = Pt(6)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  'F0F4F8')
    pPr.append(shd)
    run = p.add_run(text)
    run.font.name  = 'Courier New'
    run.font.size  = Pt(9)
    run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)
    return p


def note_box(text, kind="info"):
    colors = {
        "info":    ("D6E8F8", "1E6FBF"),
        "warning": ("FFF3CD", "856404"),
        "success": ("D4EDDA", "155724"),
        "snowplow":("FDECEA", "E55B3F"),
    }
    fill, border = colors.get(kind, colors["info"])
    p = doc.add_paragraph()
    p.paragraph_format.left_indent  = Cm(0.4)
    p.paragraph_format.space_after  = Pt(8)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'),   'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'),  fill)
    pPr.append(shd)
    run = p.add_run("ℹ " + text if kind == "info" else
                    "⚠ " + text if kind == "warning" else
                    "✅ " + text if kind == "success" else
                    "❄ " + text)
    run.font.size = Pt(10.5)
    run.font.color.rgb = RGBColor.from_string(border)
    return p


def spacer(n=1):
    for _ in range(n):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)


# ─── Helper: simple 2-col table ─────────────────────────────────────────────
def table2(col1, col2, header=None, widths=(5, 11)):
    t = doc.add_table(rows=1, cols=2)
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    # col widths
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)
    # header row
    if header:
        r = t.rows[0]
        shade_cell(r.cells[0], "1A3A5C")
        shade_cell(r.cells[1], "1A3A5C")
        for i, txt in enumerate(header):
            cell = r.cells[i]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after  = Pt(4)
            run = p.add_run(txt)
            run.bold = True
            run.font.size = Pt(10)
            run.font.color.rgb = WHITE
    # data rows
    for row_data in zip(col1, col2):
        row = t.add_row()
        for i, txt in enumerate(row_data):
            cell = row.cells[i]
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after  = Pt(3)
            run = p.add_run(txt)
            run.font.size = Pt(10)
            run.font.color.rgb = GRAY_TEXT
    doc.add_paragraph()
    return t


# ─── Helper: multi-col table ─────────────────────────────────────────────────
def table_multi(headers, rows, col_widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    if col_widths:
        for i, w in enumerate(col_widths):
            t.columns[i].width = Cm(w)
    # header
    hr = t.rows[0]
    shade_cell(hr.cells[0], "1A3A5C")
    for i in range(1, len(headers)):
        shade_cell(hr.cells[i], "1A3A5C")
    for i, h in enumerate(headers):
        p = hr.cells[i].paragraphs[0]
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after  = Pt(4)
        run = p.add_run(h)
        run.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = WHITE
    # data
    for row_data in rows:
        row = t.add_row()
        for i, txt in enumerate(row_data):
            p = row.cells[i].paragraphs[0]
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after  = Pt(3)
            run = p.add_run(str(txt))
            run.font.size = Pt(10)
            run.font.color.rgb = GRAY_TEXT
    spacer()
    return t


# ═══════════════════════════════════════════════════════════════════════════
#  COVER PAGE
# ═══════════════════════════════════════════════════════════════════════════
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(60)
run = p.add_run("BÁO CÁO KỸ THUẬT")
run.bold = True
run.font.size = Pt(13)
run.font.color.rgb = GRAY_MID
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(4)
run = p.add_run("Snowplow Analytics")
run.bold = True
run.font.size = Pt(30)
run.font.color.rgb = BLUE_DARK
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

p = doc.add_paragraph()
run = p.add_run("Lý thuyết chi tiết & Ứng dụng trong dự án Customer Data Platform")
run.font.size = Pt(14)
run.font.color.rgb = BLUE_MID
p.alignment = WD_ALIGN_PARAGRAPH.CENTER

spacer(4)

# Separator line
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(8)
p.paragraph_format.space_after  = Pt(8)
pPr = p._p.get_or_add_pPr()
pBdr = OxmlElement('w:pBdr')
bot  = OxmlElement('w:bottom')
bot.set(qn('w:val'),   'single')
bot.set(qn('w:sz'),    '6')
bot.set(qn('w:space'), '1')
bot.set(qn('w:color'), '1E6FBF')
pBdr.append(bot)
pPr.append(pBdr)

# Meta info
meta = [
    ("Dự án",     "Customer Data Platform (CDP)"),
    ("Tài liệu",  "Lý thuyết Snowplow Analytics — Kiến trúc, Thành phần, Pipeline & Tích hợp"),
    ("Ngày",      "Tháng 10 / 2026"),
    ("Phiên bản", "1.0"),
]
for label, value in meta:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p.add_run(f"{label}: ")
    r1.bold = True
    r1.font.size = Pt(11)
    r1.font.color.rgb = BLUE_MID
    r2 = p.add_run(value)
    r2.font.size = Pt(11)
    r2.font.color.rgb = GRAY_TEXT

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════
#  TABLE OF CONTENTS (manual)
# ═══════════════════════════════════════════════════════════════════════════
heading1("Mục lục")
toc_items = [
    ("PHẦN 1 — LÝ THUYẾT SNOWPLOW ANALYTICS", None),
    ("1.1", "Snowplow Analytics là gì?"),
    ("1.2", "Lịch sử và sự phát triển"),
    ("1.3", "Kiến trúc tổng quan"),
    ("1.4", "Các thành phần cốt lõi (Core Components)"),
    ("  1.4.1", "Event Collector (Bộ thu thập sự kiện)"),
    ("  1.4.2", "Iglu Schema Registry"),
    ("  1.4.3", "Stream Enrich (Bộ làm giàu dòng)"),
    ("  1.4.4", "Stream Loader (Bộ tải dữ liệu)"),
    ("  1.4.5", "Data Warehouse Loader"),
    ("  1.4.6", "Snowplow Mini"),
    ("1.5", "Enrichment Process (Quy trình làm giàu dữ liệu)"),
    ("1.6", "Snowplow Iglu — Schema Registry"),
    ("1.7", "Các mô hình dữ liệu (Data Models)"),
    ("1.8", "Cấu trúc dữ liệu sự kiện (Event Schema)"),
    ("1.9", "Snowplow BDP Cloud vs. Snowplow Open Source"),
    ("1.10", "Snowplow vs. các giải pháp khác (so sánh)"),
    ("PHẦN 2 — ỨNG DỤNG TRONG DỰ ÁN CDP", None),
    ("2.1", "Kiến trúc hiện tại của dự án"),
    ("2.2", "Event collection trong CDP Demo"),
    ("2.3", "Ánh xạ khái niệm Snowplow → CDP Demo"),
    ("2.4", "Điểm tích hợp (Integration Points)"),
    ("2.5", "Lộ trình nâng cấp lên Snowplow thực sự"),
    ("2.6", "Kết luận và khuyến nghị"),
]
for num, title in toc_items:
    if title is None:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after  = Pt(4)
        run = p.add_run(num)
        run.bold = True
        run.font.size = Pt(11)
        run.font.color.rgb = BLUE_DARK
    else:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        r1 = p.add_run(num + "  ")
        r1.font.size = Pt(10.5)
        r1.font.color.rgb = BLUE_MID
        r2 = p.add_run(title)
        r2.font.size = Pt(10.5)
        r2.font.color.rgb = GRAY_TEXT

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════
#  PART 1 — SNOWPLOW THEORY
# ═══════════════════════════════════════════════════════════════════════════
heading1("PHẦN 1 — LÝ THUYẾT SNOWPLOW ANALYTICS")

spacer()
note_box(
    "Snowplow Analytics là một open-source web analytics platform mạnh mẽ, "
    "cho phép doanh nghiệp thu thập, làm giàu và phân tích dữ liệu hành vi "
    "người dùng ở cấp độ sự kiện (event-level) với quyền kiểm soát hoàn toàn "
    "đối với dữ liệu — không bị ràng buộc bởi các nền tảng third-party như "
    "Google Analytics hay Mixpanel.",
    kind="snowplow"
)

# ─── 1.1 What is Snowplow ───────────────────────────────────────────────────
heading2("1.1  Snowplow Analytics là gì?")

body(
    "Snowplow Analytics là một **Event Analytics Platform** được thiết kế để "
    "thu thập dữ liệu hành vi người dùng ở cấp độ event-level, thay vì chỉ "
    "đếm pageview như các công cụ analytics truyền thống. Khác với Google "
    "Analytics — vốn tổng hợp dữ liệu theo mô hình proprietary — Snowplow "
    "cho phép tổ chức sở hữu toàn bộ dữ liệu thô, lưu trong hạ tầng của "
    "chính mình (self-hosted hoặc cloud)."
)
body(
    "Snowplow hoạt động theo mô hình **data-first**: mỗi tương tác nhỏ nhất "
    "của người dùng (click, scroll, search, add-to-cart, checkout...) đều được "
    "ghi lại dưới dạng một sự kiện có cấu trúc (structured event) với ngữ cảnh "
    "phong phú (timestamp, session, user-agent, geolocation, device...)."
)

heading3("Đặc điểm nổi bật của Snowplow")
bullet("**Open-source hoàn toàn** — mã nguồn mở trên GitHub, không vendor lock-in")
bullet("**Event-level data** — ghi nhận từng sự kiện riêng lẻ, không phải mẫu (sampled) hay tổng hợp")
bullet("**Custom event schema** — định nghĩa cấu trúc sự kiện tùy theo nghiệp vụ qua Iglu Schema Registry")
bullet("**Enrichment linh hoạt** — làm giàu dữ liệu thô bằng IP geolocation, UA parsing, campaign attribution, currency conversion...")
bullet("**Đa đích tải (Multi-destination)** — gửi dữ liệu đồng thời đến nhiều warehouse: Snowflake, BigQuery, Redshift, PostgreSQL, Elasticsearch, Kinesis...")
bullet("**Data ownership hoàn toàn** — doanh nghiệp kiểm soát 100% dữ liệu, không có third-party cookie hoặc data sharing")
bullet("**Schema evolution** — Iglu cho phép schema tiến hóa theo version mà không phá vỡ pipeline")

# ─── 1.2 History ────────────────────────────────────────────────────────────
heading2("1.2  Lịch sử và sự phát triển")

body(
    "Snowplow được thành lập vào năm 2012 bởi **Alex Yavorski** và **Dean McGee**, "
    "ban đầu với tên gọi 'Snowplow Analytics' — một công ty startup tại London, UK. "
    "Ý tưởng cốt lõi xuất phát từ nhu cầu thực tế: các doanh nghiệp cần "
    "sở hữu dữ liệu hành vi của chính mình thay vì phụ thuộc vào các nền tảng "
    "third-party."
)

body(
    "**Các cột mốc quan trọng:**"
)
bullet("2012 — Snowplow Analytics Ltd. thành lập, phiên bản đầu tiên dựa trên Amazon Kinesis")
bullet("2015 — Ra mắt Snowplow 0.9.0 với kiến trúc stream enrichment hoàn chỉnh")
bullet("2016 — Giới thiệu **Iglu** — schema registry cho event validation")
bullet("2017 — Snowplow R99, hỗ trợ Kafka thay thế Kinesis cho on-premise deployments")
bullet("2019 — Snowplow BDP (Business Data Platform) — dịch vụ cloud-hosted, quản lý hoàn toàn bởi Snowplow")
bullet("2020 — Snowplow Ruby Tracker 1.0 và Python Tracker mở rộng hệ sinh thái")
bullet("2022 — Snowplow Analytics trở thành **Snowplow Inc.**, huy động vốn Series B; BDP chuyển thành **Snowplow Analytics** (Managed)")
bullet("2023–2024 — Snowplow Pipelines dành cho Micro, Mini, Enterprise; tích hợp sâu với dbt, Looker, Tableau")

body(
    "Snowplow hiện được sử dụng bởi hàng nghìn doanh nghiệp toàn cầu, từ "
    "startup đến enterprise, bao gồm các tên tuổi như **BBC, DoorDash, Khan Academy, "
    "Wise (TransferWise), Figma** và hàng trăm công ty khác."
)

# ─── 1.3 Architecture ───────────────────────────────────────────────────────
heading2("1.3  Kiến trúc tổng quan")

body(
    "Kiến trúc Snowplow tuân theo mô hình **Lambda Architecture** kết hợp "
    "**Kappa Architecture**, cho phép xử lý dữ liệu real-time (stream) và "
    "batch processing song song. Toàn bộ pipeline được chia thành các tầng "
    "(layer) rõ ràng, mỗi tầng đảm nhiệm một chức năng riêng biệt."
)

heading3("Sơ đồ kiến trúc Snowplow")

arch_diagram = """
┌─────────────────────────────────────────────────────────────────┐
│                    SNOWPLOW ANALYTICS PIPELINE                    │
└─────────────────────────────────────────────────────────────────┘

 TẦNG THU THẬP (Collection Layer)
 ┌──────────────┐     ┌───────────────────┐
 │  Web/Mobile  │     │  Server-side Apps  │
 │  Tracker JS  │     │  Python/Java/     │
 │  (Browser)   │     │  Ruby/Go Trackers │
 └──────┬───────┘     └────────┬──────────┘
        │ HTTP GET/POST              │
        │ /com.snowplowanalytics    │
        ▼                           ▼
 ┌─────────────────────────────────────────────────────────┐
 │              EVENT COLLECTOR (Scala)                   │
 │  • Kinesis / Kafka / NSQ endpoint                      │
 │  • HTTP 1.1 / 2.0 receiver                            │
 │  • Thrift / JSON / CloudFront   →   Raw Events Stream │
 │    (Kinesis / Kafka)                                   │
 └──────────────────────────┬──────────────────────────────┘
                           │
 TẦNG LÀM GIÀU (Enrichment Layer)
 ┌──────────────────────────▼──────────────────────────────┐
 │              STREAM ENRICH (Flink / Spark Streaming)    │
 │  • 3rd-party enrichments (IP geo, UA, campaign)       │
 │  • Custom enrichments (JSON schema validation)         │
 │  • Deduplication & referer parsing                      │
 │  • Currency / Price normalization                      │
 │                           Good Events  →  Enriched Stream│
 │                           Bad Events   →  Bad Stream     │
 └─────────────────────────────────────────────────────────┘
                           │
 TẦNG TẢI (Loading Layer)
 ┌──────────▼──────────────┬───────────────────────────────┐
 │ STREAM LOADER           │ WAREHOUSE LOADER             │
 │ • Elasticsearch         │ • Snowflake                  │
 │ • PostgreSQL            │ • BigQuery                   │
 │ • Redshift / TimescaleDB│ • Redshift                   │
 │ • Google Pub/Sub       │ • Databricks (Delta Lake)    │
 │                         │ • S3 / Azure Blob           │
 └─────────────────────────┴───────────────────────────────┘
                           │
 TẦNG PHÂN TÍCH (Analytics Layer)
 ┌──────────▼──────────────────────────────────────────────┐
 │  dbt (Data Models)  │  BI Tools  │  ML / Data Science │
 │  • Sessions         │  Tableau   │  Python / R        │
 │  • Users            │  Looker    │  Jupyter          │
 │  • Funnels          │  Sigma     │  ML pipelines      │
 │  • Lifetime Value   │  Mode      │                   │
 └─────────────────────────────────────────────────────────┘
"""
code_block(arch_diagram)

# ─── 1.4 Core Components ───────────────────────────────────────────────────
heading2("1.4  Các thành phần cốt lõi (Core Components)")

# 1.4.1 Event Collector
heading3("1.4.1  Event Collector (Bộ thu thập sự kiện)")

body(
    "Event Collector là thành phần **đầu tiên** tiếp nhận dữ liệu từ các tracker. "
    "Nó hoạt động như một HTTP endpoint (receiver) — lắng nghe các HTTP GET/POST "
    "request từ web tracker (JavaScript), mobile tracker (iOS/Android), hoặc "
    "server-side tracker (Python, Ruby, Go, Java, PHP, .NET, Scala)."
)

body("**Vai trò chính:**")
bullet("Tiếp nhận event payload từ tracker dưới dạng Thrift serialization (nhị phân) hoặc JSON")
bullet("Gán event ID duy nhất (UUID v4) cho mỗi event")
bullet("Gán `collector_tstamp` — thời gian server nhận được event")
bullet("Ghi event thô vào **Raw Events Stream** (Kinesis / Kafka) — không sửa đổi")
bullet("Trả về HTTP 200 ngay lập tức cho tracker (fire-and-forget, không blocking)")

body("**Các deployment options:**")
bullet("**Snowplow Stream Collector** (Scala) — chạy trên Kinesis hoặc Kafka, tự quản lý infrastructure")
bullet("**Snowplow BDP Cloud Collector** — hosted collector trên AWS/GCP, fully-managed")
bullet("**Snowplow Mini** — embedded collector + enrichment + Elasticsearch, chạy trên Docker/K8s")

note_box(
    "Collector CHỈ ghi event thô vào stream. Nó không validate schema, "
    "không làm giàu dữ liệu, và không thực hiện bất kỳ business logic nào. "
    "Đây là nguyên tắc thiết kế quan trọng: separation of concerns hoàn toàn.",
    kind="info"
)

# 1.4.2 Iglu
heading3("1.4.2  Iglu Schema Registry")

body(
    "**Iglu** là một **schema registry** phân tán, dùng để lưu trữ, version và "
    "validate JSON Schemas cho các loại sự kiện trong Snowplow. Mỗi sự kiện "
    "trong Snowplow có một JSON Schema riêng (gọi là **self-describing event**), "
    "cho phép schema evolution mà không phá vỡ backward compatibility."
)

body("**Iglu URI format — mỗi schema có định danh duy nhất:**")
code_block(
    "  iglu:<vendor>/<path>/jsonschema/<schema-version>\n"
    "  Ví dụ:\n"
    "  iglu:com.snowplowanalytics.snowplow/add_to_cart/jsonschema/1-0-0\n"
    "  iglu:com.mycompany/checkout_step/jsonschema/2-1-0"
)

body("**Cấu trúc một self-describing JSON event:**")
code_block(
    "  {\n"
    "    \"schema\": \"iglu:com.mycompany/product_view/jsonschema/1-0-0\",\n"
    "    \"data\": {\n"
    "      \"productId\": \"SKU-12345\",\n"
    "      \"brand\": \"Nike\",\n"
    "      \"price\": 89.99,\n"
    "      \"currency\": \"USD\",\n"
    "      \"category\": \"footwear\"\n"
    "    }\n"
    "  }"
)

body("**Các thành phần của Iglu:**")
bullet("**Iglu Server** — server lưu trữ schemas (REST API), hỗ trợ S3, PostgreSQL, GCS, Azure Blob Storage backend")
bullet("**Iglu Client** (Scala, JavaScript, Python) — library dùng để resolve và cache schemas tại runtime")
bullet("**Schema Compatibility Checking** — Iglu kiểm tra xem một event payload có hợp lệ với schema đã đăng ký hay không")

body("**Tại sao Iglu quan trọng?**")
bullet("Đảm bảo **data quality** ở pipeline level — event không hợp lệ bị từ chối ngay tại Enrichment step")
bullet("Cho phép **schema versioning** — schema cũ vẫn hợp lệ khi schema mới được thêm")
bullet("Tự động **document** tất cả event types trong hệ thống")
bullet("Hỗ trợ **multi-team**: mỗi vendor (team/product) có namespace riêng trong Iglu")

# 1.4.3 Stream Enrich
heading3("1.4.3  Stream Enrich (Bộ làm giàu dòng)")

body(
    "Stream Enrich là thành phần **core enrichment engine** của Snowplow. Nó đọc "
    "event thô từ Raw Stream, validate và làm giàu chúng bằng các enrichment "
    "plugins, rồi ghi vào **Enriched Stream**."
)

body("**Các bước xử lý trong Stream Enrich:**")
bullet("**1. Parse & Deserialize** — Đọc event từ Thrift/JSON, tách payload thành các trường")
bullet("**2. Schema Validation** — Kiểm tra event có đúng Iglu schema không; sai → ghi vào Bad Stream")
bullet("**3. Context Enrichment** — Gắn thêm ngữ cảnh từ các enrichment plugins")
bullet("**4. Derived Timestamps** — Tính toán các timestamp phái sinh (dvce_created_tstamp, derived_tstamp...)")
bullet("**5. Output** — Event hợp lệ → Enriched Stream; Event lỗi → Bad Stream")

body("**Built-in Enrichments (có sẵn):**")
table_multi(
    ["Enrichment", "Mô tả", "Input → Output"],
    [
        ["IP Geolocation", "Tra cứu IP → country, city, lat/long", "ipaddress → geo_* fields"],
        ["User-Agent Parsing (YAUAA)", "Parse UA string → browser, OS, device, isBot", "useragent → os_*, br_*, dvce_*"],
        ["Campaign Attribution (Referer)", "Parse URL referer → source, medium, campaign", "page_url → mkt_*"],
        ["Currency Conversion", "Convert prices sang base currency (ISO 4217)", "price → tr_currency_base"],
        ["Event Fingerprint", "Hash các trường để detect duplicates", "event fields → event_fingerprint"],
        ["IAB Enrichment", "Filter bot/traffic từ IAB audience taxonomy", "useragent → IAB flags"],
        ["YA Enrichment", "Validate bot traffic qua YouTube Analytics", "useragent → ya_* flags"],
    ],
    col_widths=[4, 7, 6]
)

# 1.4.4 Stream Loader
heading3("1.4.4  Stream Loader (Bộ tải dữ liệu)")

body(
    "Stream Loader đọc event đã được làm giàu từ Enriched Stream và tải "
    "xuống các **real-time destination** như Elasticsearch, PostgreSQL, "
    "TimescaleDB, Google Pub/Sub. Khác với Warehouse Loader (xử lý batch), "
    "Stream Loader cung cấp **near real-time data** — độ trễ chỉ vài giây."
)

body("**Khi nào dùng Stream Loader?**")
bullet("Cần **real-time dashboarding** với Kibana/Elasticsearch")
bullet("Cần **near real-time alerting** khi có event bất thường")
bullet("Cần **live operational metrics** từ event stream")
bullet("Phục vụ **low-latency queries** cho internal tools")

# 1.4.5 Warehouse Loader
heading3("1.4.5  Data Warehouse Loader (Snowflake, BigQuery, Redshift, Databricks)")

body(
    "Warehouse Loader đọc event từ Enriched Stream và tải vào data warehouse "
    "theo mô hình **batch micro-batching** (thường mỗi vài phút) hoặc **streaming** "
    "(ghi liên tục vào staging table, rồi merge vào final table theo schedule)."
)

body("**Warehouse Loader hoạt động theo 3 giai đoạn:**")
bullet("**Stage** — Ghi event mới vào staging table (append-only)")
bullet("**Load** — Merge staging vào main table theo event ID (upsert)")
bullet("**Archive** — Archive/evict old staging data để tiết kiệm storage")

body("**Ưu điểm của việc dùng Warehouse thay vì chỉ Stream:**")
bullet("**SQL analytics mạnh** — JOIN, window functions, aggregations phức tạp")
bullet("**dbt integration** — xây dựng data models bằng SQL với version control")
bullet("**Historical analysis** — truy vấn toàn bộ lịch sử event không giới hạn")
bullet("**Compliance** — data warehouse cung cấp audit trail, row-level security")

note_box(
    "Snowplow khuyến nghị dùng **cả hai**: Stream Loader cho real-time "
    "(Elasticsearch/Kibana dashboard) VÀ Warehouse Loader cho deep analytics "
    "(dbt, BI tools). Đây là mô hình 'best of both worlds'.",
    kind="info"
)

# 1.4.6 Mini
heading3("1.4.6  Snowplow Mini — Local/Edge Deployment")

body(
    "**Snowplow Mini** là một phiên bản **all-in-one, self-contained** của "
    "Snowplow pipeline, đóng gói toàn bộ stack (Collector + Enrichment + "
    "Stream Loader + Elasticsearch) chạy trên Docker hoặc Kubernetes. "
    "Đây là giải pháp lý tưởng cho:"
)

bullet("**Development & Testing** — local pipeline mà không cần cloud account")
bullet("**Edge/On-premise** — doanh nghiệp không thể gửi data ra cloud")
bullet("**Proof of Concept** — demo Snowplow trước khi cam kết cloud deployment")
bullet("**Training** — học cách vận hành Snowplow mà không lo phí cloud")

body(
    "Mini bao gồm: **Iglu Server** (schema registry), **Stream Collector**, "
    "**Stream Enrich**, **Stream Loader → Elasticsearch**, và giao diện "
    "**Kibana** để visualize events. Tất cả chạy trong Docker containers, "
    "tiêu tốn khoảng 4-8GB RAM."
)

# ─── 1.5 Enrichment Process ────────────────────────────────────────────────
heading2("1.5  Enrichment Process (Quy trình làm giàu dữ liệu)")

body(
    "Enrichment là quá trình **bổ sung ngữ cảnh** (context) vào event thô, "
    "biến một event đơn giản thành một record giàu thông tin phục vụ phân tích. "
    "Mỗi enrichment nhận event thô và trả về event mới có thêm các trường."
)

heading3("Các loại Enrichment trong Snowplow")

table_multi(
    ["Loại Enrichment", "Ví dụ", "Trường thêm vào event"],
    [
        ["IP-based", "IP Geolocation Lookup", "geo_country, geo_city, geo_latitude, geo_longitude"],
        ["User-Agent-based", "YAUAA Parser", "os_name, os_version, br_name, dvce_type, is_bot"],
        ["Referer-based", "Campaign Parser", "mkt_source, mkt_medium, mkt_campaign, mkt_term, mkt_content"],
        ["Time-based", "Derived Timestamp", "dvce_created_tstamp, derived_tstamp"],
        ["Currency", "Currency Conversion", "tr_total_base, tr_tax_base, tr_shipping_base, base_currency"],
        ["Network", "Cookie Extractor", "network_userid (first-party cookie)"],
        ["Privacy", "IAB Bot Detection", "iab_spider_or_bot, iab_agency, iab_brand"],
        ["Custom", "Custom JSON Enrichment", "Không giới hạn — tự định nghĩa"],
    ],
    col_widths=[3.5, 6, 7.5]
)

heading3("Quy trình enrichment chi tiết (step-by-step)")

steps = [
    ("Bước 1 — Raw Event Received",
     "Collector nhận HTTP request từ tracker. Event được ghi vào Raw Stream "
     "với các trường cơ bản: event_id, event_name, true_tstamp, dvce_sent_tstamp."),
    ("Bước 2 — Deserialization",
     "Stream Enrich đọc event từ stream. Payload được deserialize từ "
     "Thrift (nhị phân) hoặc JSON thành object model."),
    ("Bước 3 — Schema Validation (Iglu)",
     "Event payload được validate qua Iglu Client. Nếu schema URI không tìm "
     "thấy hoặc payload không hợp lệ → event ghi vào Bad Stream với lý do."),
    ("Bước 4 — Enrichment Pipeline",
     "Event lần lượt đi qua từng enrichment theo thứ tự ưu tiên. "
     "Mỗi enrichment thêm fields vào event record. Các enrichment độc lập "
     "(stateless) và có thể bật/tắt qua cấu hình."),
    ("Bước 5 — Deduplication",
     "Event có cùng fingerprint (dựa trên event_id hoặc event fingerprint hash) "
     "bị loại bỏ nếu đã xuất hiện trong khoảng thời gian dedup window."),
    ("Bước 6 — Derived Timestamps",
     "Snowplow tính toán các derived timestamps dựa trên true_tstamp và "
     "collector timezone để đảm bảo timezone consistency."),
    ("Bước 7 — Output",
     "Event đã làm giàu được serialize lại và ghi vào Enriched Stream. "
     "Bad events (schema violation, enrichment failure) được ghi vào Bad Stream."),
]

for title, desc in steps:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after  = Pt(2)
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = BLUE_MID
    body(desc)

# ─── 1.6 Iglu Schema ────────────────────────────────────────────────────────
heading2("1.6  Snowplow Iglu — Schema Registry (Chi tiết)")

body(
    "Iglu là trái tim của hệ thống **schema management** trong Snowplow. "
    "Nó giải quyết một vấn đề cốt lõi: làm sao để schema event có thể "
    "tiến hóa theo thời gian mà không phá vỡ các pipeline downstream."
)

heading3("Cấu trúc Schema Repository")
body("Iglu Server lưu trữ schemas theo cấu trúc thư mục:")
code_block(
    "  schemas/\n"
    "  └── com.mycompany/                    ← Vendor (organization)\n"
    "      └── product_interaction/           ← Schema path\n"
    "          └── jsonschema/\n"
    "              ├── 1-0-0    ← Version 1.0.0 (JSON Schema file)\n"
    "              ├── 1-0-1    ← Version 1.0.1 (patches)\n"
    "              └── 1-1-0    ← Version 1.1.0 (minor changes OK)"
)

heading3("JSON Schema trong Iglu")
body("Mỗi schema là một JSON Schema draft-07:")
code_block(
    "  {\n"
    "    \"$schema\": \"http://json-schema.org/draft-07/schema#\",\n"
    "    \"description\": \"Product interaction event\",\n"
    "    \"type\": \"object\",\n"
    "    \"properties\": {\n"
    "      \"productId\":    { \"type\": \"string\" },\n"
    "      \"action\":       { \"type\": \"string\", \"enum\": [\"view\",\"click\",\"buy\"] },\n"
    "      \"price\":        { \"type\": \"number\", \"minimum\": 0 },\n"
    "      \"currency\":     { \"type\": \"string\", \"pattern\": \"^[A-Z]{3}$\" },\n"
    "      \"quantity\":     { \"type\": \"integer\", \"minimum\": 1 }\n"
    "    },\n"
    "    \"required\": [\"productId\", \"action\", \"currency\"],\n"
    "    \"additionalProperties\": false\n"
    "  }"
)

heading3("Schema Compatibility Rules (tương thích ngược)")
body("Iglu hỗ trợ 4 loại compatibility:")
bullet("**BACKWARD** — schema mới có thể thiếu trường so với cũ (consumer vẫn đọc được)")
bullet("**FORWARD** — schema mới có thêm trường mới (consumer cũ bỏ qua trường lạ)")
bullet("**FULL** — kết hợp BACKWARD + FORWARD (điều kiện an toàn nhất)")
bullet("**NONE** — không kiểm tra compatibility (development only)")

# ─── 1.7 Data Models ────────────────────────────────────────────────────────
heading2("1.7  Các mô hình dữ liệu (Data Models) trong Snowplow")

body(
    "Snowplow thu thập event-level data thô. Để phục vụ phân tích, dữ liệu "
    "thô cần được **aggregate** thành các data models — các bảng/tview trong "
    "warehouse phục vụ các use case cụ thể. Snowplow khuyến nghị dùng **dbt** "
    "(data build tool) để xây dựng các data models này."
)

heading3("Standard Snowplow Data Models")

table_multi(
    ["Model", "Mô tả", "Output Table"],
    [
        ["**Users**", "Deduplicate & stitch user identities across devices/sessions", "snowplow_web_users / snowplow_mobile_users"],
        ["**Sessions**", "Sessionize events → build session boundaries", "snowplow_web_sessions / snowplow_mobile_sessions"],
        ["**Page Views**", "Aggregate page views per session", "snowplow_web_page_views"],
        ["**Conversion Funnels**", "Track user journeys through defined steps", "Custom funnel tables"],
        ["**Engagement**", "Calculate engagement metrics: scroll depth, time on page, video plays", "snowplow_web_engagement"],
        ["**Lifetime Value (LTV)**", "Estimate user value based on purchase events", "snowplow_customer_lifetime_value"],
        ["**Attribution**", "Assign credit to marketing channels (first-touch, last-touch, linear)", "snowplow_marketing_attribution"],
        ["** Consent**", "Track consent given/withdrawn across properties", "snowplow_consent_users"],
    ],
    col_widths=[4, 9, 4]
)

body(
    "Các data models này được xây dựng bằng **dbt** (data build tool) — cho phép "
    "SQL-based transformation với version control, testing, và documentation. "
    "Mỗi model có unit tests và dbt docs generation."
)

# ─── 1.8 Event Schema ───────────────────────────────────────────────────────
heading2("1.8  Cấu trúc dữ liệu sự kiện (Snowplow Event Schema)")

body(
    "Mỗi event trong Snowplow được lưu với **~130 columns** — bao gồm "
    "các trường tự động (auto-filled) và các trường tùy chỉnh (custom contexts)."
)

heading3("Core Snowplow Event Fields (tự động)")

table_multi(
    ["Field Category", "Trường tiêu biểu", "Mô tả"],
    [
        ["**Event Identity**", "event_id, event, event_name, event_vendor", "Định danh sự kiện duy nhất"],
        ["**Timestamp**", "collector_tstamp, dvce_created_tstamp, derived_tstamp, true_tstamp", "4 loại timestamp phục vụ debugging"],
        ["**Session**", "se_session_id, se_category, se_action, se_label", "Session-scoped metrics"],
        ["**User Identity**", "user_id, user_fingerprint, domain_userid, network_userid", "Các identity identifiers"],
        ["**Device**", "dvce_type, dvce_ismobile, os_name, os_family", "Thông tin thiết bị"],
        ["**Location**", "geo_country, geo_region, geo_city, geo_zipcode", "Geolocation từ IP"],
        ["**Page/Content**", "page_url, page_title, br_viewheight, doc_height", "Trang và nội dung"],
        ["**Marketing**", "mkt_source, mkt_medium, mkt_campaign, mkt_term", "Campaign attribution từ URL"],
        ["**Transaction**", "tr_total, tr_order_id, ti_price, ti_quantity", "E-commerce transaction fields"],
        ["**Contexts**", "unstruct_event, contexts, derived_contexts", "Self-describing JSON payloads"],
    ],
    col_widths=[4, 5, 8]
)

heading3("Snowplow vs. Google Analytics — So sánh data model")
table_multi(
    ["Khía cạnh", "Snowplow", "Google Analytics 4"],
    [
        ["Data ownership", "100% self-owned, on-premise or cloud", "Google owns data"],
        ["Event model", "~130 auto fields + unlimited custom", "~25 fixed fields"],
        ["Sampling", "None — full data", "Sampled in free tier"],
        ["Custom events", "Unlimited, typed via Iglu", "Limited to ~25 custom params"],
        ["Historical data", "Unlimited retention", "14 months (paid: 14 months)"],
        ["Data latency", "Seconds (stream) to minutes (warehouse)", "4-8 hours (GA4)"],
        ["Cost model", "Infrastructure cost only (open-source)", "Per-event pricing (GA4 360)"],
        ["Schema flexibility", "Full JSON Schema + versioning", "Fixed flat schema"],
        ["Integration ecosystem", "Snowflake, BigQuery, Redshift, dbt, BI", "BigQuery (GA4 360)"],
    ],
    col_widths=[4, 7, 7]
)

# ─── 1.9 BDP vs OSS ─────────────────────────────────────────────────────────
heading2("1.9  Snowplow BDP Cloud vs. Snowplow Open Source")

body(
    "Snowplow có hai phương án triển khai chính: **Snowplow Open Source** "
    "(tự vận hành) và **Snowplow Analytics (BDP Cloud)** (managed service)."
)

table_multi(
    ["Tiêu chí", "Snowplow Open Source", "Snowplow Analytics (Cloud)"],
    [
        ["**Chi phí**", "Chi phí infrastructure (EC2/K8s) + engineering time", "Subscription theo event volume (từ ~$1K/tháng)"],
        ["**Vận hành**", "Self-managed: bạn chịu trách nhiệm upgrades, monitoring, scaling", "Fully managed bởi Snowplow; 99.9% SLA"],
        ["**Customization**", "Toàn quyền control — thay đổi collector, enrichment, loader", "Configurable enrichment; limited custom collector"],
        ["**Setup time**", "2-4 tuần (infrastructure + configuration)", "1-2 ngày (quickstart templates)"],
        ["**Support**", "Community forum; enterprise support (có phí)", "24/7 enterprise support"],
        ["**Iglu Server**", "Self-hosted (S3/Postgres/GCS)", "Shared Iglu registry + private registry"],
        ["**Enrichments**", "Tất cả enrichment + custom enrichments", "Tất cả enrichment + proprietary enrichments"],
        ["**Rủi ro**", "Vendor lock-in thấp; portable", "Phụ thuộc vào Snowplow; migration cost cao"],
    ],
    col_widths=[4, 7, 7]
)

note_box(
    "Đối với dự án CDP này, **Snowplow Open Source** là lựa chọn phù hợp nhất: "
    "không phí subscription, full customization, và hoàn toàn tương thích với "
    "kiến trúc self-hosted đã có (Docker, Kubernetes, S3-compatible storage).",
    kind="success"
)

# ─── 1.10 Comparison ────────────────────────────────────────────────────────
heading2("1.10  Snowplow vs. các giải pháp Analytics khác")

table_multi(
    ["Tiêu chí", "Snowplow", "Google Analytics 4", "Mixpanel", "Amplitude"],
    [
        ["Event model", "Custom (Iglu)", "Preset + custom params", "Preset + custom", "Preset + custom"],
        ["Data ownership", "✅ Full", "❌ Google", "❌ Mixpanel", "❌ Amplitude"],
        ["Self-hosted", "✅", "❌", "❌", "❌"],
        ["Open source", "✅", "❌", "❌", "❌"],
        ["Real-time stream", "✅ Kinesis/Kafka", "❌ (4-8h delay)", "✅ Real-time", "✅ Real-time"],
        ["Schema registry", "✅ Iglu", "❌", "❌", "❌"],
        ["dbt integration", "✅", "⚠️ BigQuery export", "❌", "❌"],
        ["SQL warehouse", "✅ 8+ destinations", "⚠️ BigQuery only", "❌", "❌"],
        ["Revenue attribution", "Advanced (multi-touch)", "Basic (data-driven)", "Advanced", "Advanced"],
        ["Free tier", "✅ (infra only)", "✅ (sampled)", "✅ (100K MAU)", "✅ (100K events)"],
        ["Enterprise pricing", "High (infra + engineering)", "Medium", "High", "High"],
    ],
    col_widths=[3.5, 4.5, 4.5, 4.5, 4]
)

body(
    "Snowplow nổi bật với **data ownership hoàn toàn** và **schema flexibility**, "
    "nhưng đòi hỏi **engineering effort cao hơn** để vận hành so với các "
    "giải pháp SaaS. Đây là trade-off giữa 'khả năng kiểm soát' và 'tốc độ triển khai'."
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════
#  PART 2 — APPLICATION IN CDP PROJECT
# ═══════════════════════════════════════════════════════════════════════════
heading1("PHẦN 2 — ỨNG DỤNG TRONG DỰ ÁN CDP")

spacer()
note_box(
    "Phần này phân tích cách các khái niệm và thành phần của Snowplow Analytics "
    "ánh xạ sang kiến trúc hiện tại của dự án Customer Data Platform, đồng thời "
    "đề xuất lộ trình nâng cấp từng bước từ CDP Demo sang một pipeline "
    "dựa trên Snowplow thực thụ.",
    kind="info"
)

# ─── 2.1 Current Architecture ───────────────────────────────────────────────
heading2("2.1  Kiến trúc hiện tại của dự án CDP")

body(
    "Dự án CDP hiện tại triển khai một **mini-event-collection pipeline** với "
    "4 thành phần chính:"
)

current_arch_diagram = """
┌────────────────────────────────────────────────────────────────┐
│           CDP PROJECT — CURRENT ARCHITECTURE                   │
└────────────────────────────────────────────────────────────────┘

 ┌──────────────────────────────┐
 │  Web Demo SPA (HTML/JS/CSS)  │  ← Giao diện người dùng
 │  src/demo/web/               │    SPA 1 trang, hash routing
 │  http://localhost:8081       │    4 persona flows (Lina/Minh/Hoa/Quang)
 └──────────────┬───────────────┘
                │ POST /api/events  (batch, 5s interval OR beforeunload)
                ▼
 ┌──────────────────────────────┐
 │  Demo API (FastAPI)          │  ← Event Collection + Validation
 │  src/demo/api/server.py      │    Namespace: cdp.demo.events
 │  http://localhost:8000       │    16 event types
 │                              │    Batch idempotency (POST body hash)
 └──────────────┬───────────────┘
                │ CSV file per batch
                ▼
 ┌──────────────────────────────┐
 │  data/demo-events/<batch>/   │  ← Event Storage (raw)
 │  ├── events.csv              │    Batch Parquet (scaffold)
 │  ├── quarantine.csv          │    Manifest với checksum
 │  └── manifest.json           │
 └──────────────┬───────────────┘
                │ CSV → Spark → Iceberg (scaffold)
                ▼
 ┌──────────────────────────────┐
 │  Lakehouse Scaffold          │  ← Data Processing (Docker stack)
 │  src/demo/lakehouse/         │    Bronze → Silver → Gold
 │  config/docker/              │    Spark + Iceberg + SeaweedFS S3
 └──────────────────────────────┘
                │
                ▼
 ┌──────────────────────────────┐
 │  Dashboard (JavaScript)      │  ← Analytics & Visualization
 │  src/demo/web/js/dashboard.js│    GET /api/summary (10s polling)
 │                              │    Stats cards, persona funnels,
 │                              │    bar charts (Canvas)
 └──────────────────────────────┘
"""
code_block(current_arch_diagram)

heading3("Điểm mạnh của kiến trúc hiện tại")
bullet("**Event types phong phú** — 16 event types bao gồm cả legacy và persona-driven")
bullet("**Idempotency** — batch được deduplicate bằng POST body hash")
bullet("**Quarantine** — bad events được cách ly riêng, không silently dropped")
bullet("**Manifest & Checksum** — đảm bảo data lineage và detect corruption")
bullet("**Persona-driven** — 4 personas với event signature khác nhau phục vụ testing")
bullet("**Dashboard real-time** — auto-refresh 10s cho thấy pipeline hoạt động ngay")

heading3("Giới hạn so với Snowplow")
bullet("❌ Không có schema registry — event schema không được version/validate")
bullet("❌ Không có enrichment engine — không có IP geo, UA parsing, campaign attribution")
bullet("❌ Không có stream processing — chỉ batch file-based")
bullet("❌ Không có deduplication thông minh — chỉ idempotent POST, không deduplicate event trong batch")
bullet("❌ Không có identity resolution — user_id được gửi từ client, không có stitching")
bullet("❌ Không có warehouse loader — chỉ CSV/Parquet local file")
bullet("❌ Không có multi-destination — chỉ một đích duy nhất (file storage)")

# ─── 2.2 Event Collection in CDP Demo ───────────────────────────────────────
heading2("2.2  Event Collection trong CDP Demo — Chi tiết kỹ thuật")

body(
    "CDP Demo thu thập event theo mô hình **client-side tracking** với "
    "JavaScript tracker (`catalog.js`). Mỗi event được gửi lên Demo API "
    "qua `POST /api/events`."
)

heading3("Event flow trong CDP Demo")

body("**1. Event Tracking (client-side):**")
code_block(
    "  // catalog.js — event tracking\n"
    "  const _eventQueue = [];\n"
    "  let _batchId = crypto.randomUUID();\n"
    "\n"
    "  export function track(eventType, payload = {}) {\n"
    "    const event = {\n"
    "      event_type:   eventType,\n"
    "      event_time:   new Date().toISOString(),\n"
    "      session_id:   getSessionId(),\n"
    "      user_id:      getUserId(),\n"
    "      namespace:    'cdp.demo.events',\n"
    "      source:       'web-demo',\n"
    "      url:          location.href,\n"
    "      user_agent:   navigator.userAgent,\n"
    "      viewport:     `${window.innerWidth}x${window.innerHeight}`,\n"
    "      payload,\n"
    "      _client_batch_id: _batchId,\n"
    "    };\n"
    "    _eventQueue.push(event);\n"
    "    scheduleFlush();  // flush sau 5s\n"
    "  }"
)

body("**2. Batch Flush:**")
bullet("Cứ 5 giây: `flushEvents()` gửi POST với batch JSON body")
bullet("On page unload: `navigator.sendBeacon()` gửi remaining events (đảm bảo delivery)")
bullet("`cart_abandoned` event: special case — fire qua `beforeunload` + `sendBeacon`")

body("**3. Server-side Processing (FastAPI):**")
bullet("`POST /api/events` — nhận batch, validate event_type, assign batch_id + ordinal + event_id")
bullet("`GET /api/catalog` — trả về 250 products từ config JSON (không cần database)")
bullet("`GET /api/summary` — đọc tất cả batch CSV → aggregate counts → trả về dashboard")

heading3("16 Event Types hiện tại")
table_multi(
    ["Event Type", "Khi nào bắn", "Snowplow tương đương"],
    [
        ["page_view", "Hash routing thay đổi", "page_view"],
        ["product_view", "Click product card", "product_view"],
        ["add_to_cart", "Nhấn 'Thêm vào giỏ'", "add_to_cart"],
        ["remove_from_cart", "Nhấn 'Xóa'", "remove_from_cart"],
        ["begin_checkout", "Nhấn 'Đặt hàng'", "checkout"],
        ["purchase_observed", "Thanh toán thành công", "transaction"],
        ["element_click", "Click sort/filter/button", "click (custom)"],
        ["scroll_depth", "(Reserved) cuộn sâu", "page_ping (partial)"],
        ["search", "Submit search form", "site_search"],
        ["error", "JS error xảy ra", "error (Snowplow JS tracker)"],
        ["cart_abandoned", "beforeunload khi có cart", "form_submit (adapted)"],
        ["apply_filter", "Đổi category filter", "form_submit (adapted)"],
        ["wishlist_add", "Nhấn Wishlist (lần đầu)", "add_to_wishlist"],
        ["wishlist_remove", "Bỏ Wishlist", "remove_from_wishlist"],
        ["newsletter_signup", "Submit newsletter form", "form_submit (adapted)"],
    ],
    col_widths=[3.5, 8, 5.5]
)

# ─── 2.3 Mapping ────────────────────────────────────────────────────────────
heading2("2.3  Ánh xạ khái niệm Snowplow → CDP Demo")

body(
    "Bảng dưới đây cho thấy cách các khái niệm cốt lõi của Snowplow Analytics "
    "ánh xạ sang các thành phần hiện có trong CDP Demo."
)

table_multi(
    ["Snowplow Concept", "CDP Demo tương đương", "Khác biệt chính"],
    [
        ["Event Collector", "Demo API (`POST /api/events`)", "CDP: HTTP POST; Snowplow: Thrift collector"],
        ["Raw Events Stream", "`data/demo-events/<batch>/events.csv`", "CDP: batch file; Snowplow: Kinesis/Kafka"],
        ["Iglu Schema Registry", "❌ Không có", "CDP: không validate schema; Snowplow: JSON Schema + versioning"],
        ["Stream Enrich", "❌ Không có", "CDP: không có geo/UA/currency enrichment"],
        ["Bad Stream / Quarantine", "`quarantine.csv`", "CDP: file-based; Snowplow: dedicated bad stream"],
        ["Warehouse Loader", "❌ Không có", "CDP: CSV local; Snowplow: Snowflake/BigQuery/Redshift"],
        ["YAUAA (UA Parser)", "❌ Không có", "CDP: raw user_agent string lưu không parse"],
        ["IP Geolocation", "❌ Không có", "CDP: không có IP lookup"],
        ["Campaign Attribution", "❌ Không có", "CDP: không parse referer/UTM"],
        ["Event ID", "`event_id` (UUID)", "CDP: client-side UUID; Snowplow: server-side UUID"],
        ["Session ID", "`session_id` (crypto.randomUUID)", "CDP: client-side; Snowplow: server-cookie + enrichment"],
        ["User ID", "`user_id` (cookie `cdp_demo_uid`)", "CDP: first-party cookie; Snowplow: 1st+3rd party cookies + identity graph"],
        ["Dashboard", "`dashboard.js` (polling /api/summary)", "CDP: JS render; Snowplow: Kibana/Looker/Tableau"],
        ["Data Models (dbt)", "❌ Không có", "CDP: không có dbt models; Snowplow: sessions, users, funnels, LTV"],
        ["Identity Resolution", "❌ Không có", "CDP: 1 user_id = 1 user; Snowplow: cross-device stitching"],
        ["Multi-destination", "❌ Không có", "CDP: 1 đích (file); Snowplow: 8+ warehouse destinations"],
    ],
    col_widths=[4.5, 5, 7.5]
)

# ─── 2.4 Integration Points ─────────────────────────────────────────────────
heading2("2.4  Điểm tích hợp (Integration Points) — Kết nối CDP Demo với Snowplow")

body(
    "Có 3 chiến lược tích hợp chính. Chiến lược nào phù hợp tùy thuộc "
    "vào mục tiêu và resource của dự án."
)

heading3("Chiến lược A — Thay thế hoàn toàn (Full Migration)")
body(
    "**Mục tiêu:** Dự án production cần full Snowplow pipeline. "
    "CDP Demo được dùng làm **prototype/UI layer**, phía backend chuyển "
    "hoàn toàn sang Snowplow."
)

table_multi(
    ["Thành phần CDP Demo", "Thay thế bằng Snowplow", "Effort"],
    [
        ["`catalog.js` track()", "Snowplow JavaScript Tracker", "Thấp — swap SDK"],
        ["Demo API POST /events", "Snowplow Collector (Kinesis/Kafka)", "Cao — infra setup"],
        ["`quarantine.csv`", "Snowplow Bad Stream (Kafka topic)", "Trung bình"],
        ["`data/demo-events/*.csv`", "Snowflake / BigQuery / Redshift", "Cao — warehouse setup"],
        ["Lakehouse Spark/Iceberg", "Snowplow Warehouse Loader", "Cao — data modeling"],
        ["`dashboard.js`", "Looker / Tableau / Sigma + dbt", "Trung bình — BI tools"],
        ["Bot Driver", "Snowplow Simulator (testing pipeline)", "Trung bình"],
    ],
    col_widths=[4.5, 8, 4.5]
)

heading3("Chiến lược B — Layered Addition (Bổ sung từng tầng)")
body(
    "**Mục tiêu:** Giữ nguyên CDP Demo làm frontend (để demo personas), "
    "bổ sung Snowplow infrastructure bên dưới theo từng tầng."
)

layered_steps = [
    ("Tầng 1 — Iglu Schema Registry",
     "Định nghĩa Iglu schemas cho tất cả 16 event types của CDP Demo. "
     "Migrate event model sang self-describing JSON format. "
     "→ **Effort: Thấp | Impact: Cao**"),
    ("Tầng 2 — Stream Enrichment",
     "Thêm enrichment layer: YAUAA (parse user-agent), IP geolocation, "
     "campaign attribution (UTM parsing). Thay thế raw string fields bằng "
     "parsed fields (os_name, geo_country, mkt_source...) "
     "→ **Effort: Trung bình | Impact: Cao**"),
    ("Tầng 3 — Warehouse Loader",
     "Thay thế CSV/Parquet local bằng Snowflake hoặc BigQuery. "
     "Thêm dbt data models: sessions, users, funnel, LTV. "
     "→ **Effort: Cao | Impact: Trung bình**"),
    ("Tầng 4 — Identity Resolution",
     "Thêm Snowplow Identity Resolution (JS sp.js + server-side identity graph). "
     "Stitch anonymous visitors → authenticated users across devices. "
     "→ **Effort: Trung bình | Impact: Cao**"),
]
for title, desc in layered_steps:
    heading3(title)
    body(desc)

heading3("Chiến lược C — CDP Demo + Snowplow Side-by-Side (Production-ready)")
body(
    "**Mục tiêu:** Dùng CDP Demo cho internal demo/education, triển khai "
    "Snowplow thực sự cho production. Hai hệ thống chạy song song, "
    "CDP Demo chỉ dùng để visualize persona behavior."
)

bullet("CDP Demo: chạy như cũ, gửi event về CDP Demo API (cho demo purposes)")
bullet("Snowplow: thu thập event từ ứng dụng production thực (nếu có)")
bullet("Dashboard CDP Demo: chỉ để show concept — không dùng cho production analytics")
bullet("Snowplow BI: dùng cho production analytics, reporting, LTV modeling")

# ─── 2.5 Migration Roadmap ──────────────────────────────────────────────────
heading2("2.5  Lộ trình nâng cấp lên Snowplow thực sự")

body(
    "Đề xuất lộ trình 4 giai đoạn, mỗi giai đoạn mang lại giá trị rõ ràng "
    "và có thể demo được, không phụ thuộc giai đoạn tiếp theo."
)

heading3("Giai đoạn 1 — Schema Registry (2-3 tuần)")
body("**Mục tiêu:** Thêm Iglu Schema Registry vào CDP Demo để validate event schema.")

bullet("Cài đặt **Iglu Server** (Docker, S3 backend hoặc PostgreSQL)")
bullet("Định nghĩa JSON Schema cho tất cả 16 event types của CDP Demo")
bullet("Thêm **schema validation** vào Demo API (thay thế enum check đơn giản)")
bullet("Event không hợp lệ → quarantine với lý do schema violation cụ thể")
bullet("Thêm **schema version tracking** vào manifest.json")

body("**Deliverable:** CDP Demo API reject bad events với descriptive error, "
     "CDP Demo có documented schema cho mọi event type.")

heading3("Giai đoạn 2 — Stream Enrichment (3-4 tuần)")
body("**Mục tiêu:** Thêm enrichment layer để CDP Demo data trở nên giàu thông tin hơn.")

bullet("Triển khai **Snowplow Stream Enrich** (Flink hoặc Spark Streaming)")
bullet("Cấu hình built-in enrichments: YAUAA (UA parsing), IP Geolocation (MaxMind DB)")
bullet("Thêm **UTM/Campaign enrichment** — parse referer URL → source/medium/campaign")
bullet("**Currency conversion enrichment** — chuẩn hóa prices về base currency")
bullet("Cập nhật Dashboard để hiển thị enriched fields: OS, device type, country, campaign")

body("**Deliverable:** Mỗi event trong CDP Demo có đầy đủ context: device, OS, "
     "geolocation, campaign source. Dashboard show enriched breakdowns.")

heading3("Giai đoạn 3 — Warehouse + Data Models (4-6 tuần)")
body("**Mục tiêu:** Thay thế CSV/Parquet bằng cloud data warehouse + dbt models.")

bullet("Cài đặt **Snowflake** (recommended) hoặc **BigQuery** / **Redshift**")
bullet("Triển khai **Snowplow Warehouse Loader** (Kakfa → S3 → Snowpipe → Snowflake)")
bullet("Viết **dbt models** cho CDP Demo data:")
bullet("   - `snowplow_web_sessions` — sessionize events, calculate engagement metrics")
bullet("   - `snowplow_web_users` — deduplicate & stitch user identities")
bullet("   - `cdp_daily_events` — aggregate daily event counts theo type")
bullet("   - `cdp_persona_funnel` — persona-specific funnel: view→cart→checkout→purchase")
bullet("   - `cdp_user_journey` — timeline view của từng user persona")
bullet("Kết nối BI tool (Looker Studio / Tableau / Sigma) với Snowflake")

body("**Deliverable:** SQL-based analytics cho CDP Demo data. Team có thể viết "
     "SQL queries phức tạp: retention cohorts, LTV by persona, attribution modeling.")

heading3("Giai đoạn 4 — Production Deployment & Identity Resolution (4-8 tuần)")
body("**Mục tiêu:** CDP Demo trở thành production-ready CDP platform dựa trên Snowplow.")

bullet("Triển khai **Snowplow Analytics (BDP Cloud)** hoặc self-hosted Snowplow pipeline")
bullet("Thêm **Identity Resolution**: Snowplow JavaScript Tracker (sp.js) + server-side identity graph")
bullet("**Cross-device stitching**: anonymous visitor → login → cross-session identity")
bullet("Triển khai **Customer 360 view** — JOIN events với customer data (PostgreSQL nghiệp vụ)")
bullet("Thêm **CDC pipeline** (Debezium/Kafka Connect) theo kiến trúc đã định nghĩa trong project-plan.md")
bullet("Production **monitoring & alerting**: SLOs, data quality checks, Slack notifications")

body("**Deliverable:** Production CDP platform đầy đủ: event collection → enrichment → "
     "warehouse → data models → Customer 360 → BI dashboard.")

heading3("Tổng quan lộ trình")
table_multi(
    ["Giai đoạn", "Mục tiêu", "Thành phần mới", "Effort", "Impact"],
    [
        ["**G1: Schema Registry**", "Validate event schema", "Iglu Server + JSON Schema", "2-3 tuần", "Cao"],
        ["**G2: Enrichment**", "Làm giàu event data", "Stream Enrich + YAUAA + GeoIP", "3-4 tuần", "Cao"],
        ["**G3: Warehouse**", "SQL analytics", "Snowflake + dbt models", "4-6 tuần", "Trung bình"],
        ["**G4: Production**", "Full Snowplow + Identity", "BDP Cloud + sp.js + CDC", "4-8 tuần", "Rất Cao"],
    ],
    col_widths=[3, 5.5, 6, 2.5, 3]
)

# ─── 2.6 Conclusion ──────────────────────────────────────────────────────────
heading2("2.6  Kết luận và Khuyến nghị")

heading3("Tổng kết")
body(
    "Snowplow Analytics là nền tảng **event analytics mạnh mẽ nhất** hiện có "
    "cho các doanh nghiệp muốn sở hữu toàn bộ dữ liệu hành vi người dùng. "
    "Kiến trúc modular của Snowplow — từ Collector → Enrichment → Loader → "
    "Warehouse — cho phép tổ chức bắt đầu từ prototype nhỏ và mở rộng "
    "theo nhu cầu mà không phải thay đổi kiến trúc nền tảng."
)

body(
    "CDP Demo hiện tại đã triển khai một **mini-Snowplow** với 4 thành phần "
    "cốt lõi (Event Tracking → API Collection → File Storage → Dashboard). "
    "Đây là nền tảng tốt để đào tạo và demo các khái niệm CDP, nhưng cần "
    "bổ sung thêm 3 lớp (Schema Registry, Stream Enrichment, Warehouse) "
    "để trở thành production-ready CDP."
)

heading3("Khuyến nghị ngay lập tức (Quick wins)")
bullet("**Ngay:** Thêm Iglu Schema Registry — effort thấp nhất, impact cao nhất. "
       "Đảm bảo data quality ngay từ đầu pipeline.")
bullet("**Ngay:** Parse `user_agent` string trong Demo API bằng thư viện `user-agents` Python "
       "(thay vì lưu raw string). Thêm `user_agent` parsed fields vào event model.")
bullet("**1-2 tuần:** Thêm **Snowplow Mini** như một local development environment. "
       "Team học cách vận hành Snowplow thực sự trước khi cam kết cloud deployment.")
bullet("**1-2 tuần:** Export CDP Demo events từ `data/demo-events/` sang Snowflake/BigQuery "
       "bằng manual CSV load. Thử viết SQL queries đầu tiên với dbt.")
bullet("**2-4 tuần:** Đánh giá Snowplow BDP Cloud vs. self-hosted: "
       "tính toán TCO (infrastructure + engineering + support) cho 2 lựa chọn.")

heading3("Điểm mấu chốt để nhớ")
note_box(
    "1. CDP Demo đã có event model tốt (16 types, 4 personas) — đây là điểm khởi đầu tuyệt vời.\n"
    "2. Snowplow không phải 'thay thế' CDP Demo mà là 'nâng cấp' kiến trúc bên dưới.\n"
    "3. Bắt đầu với Iglu Schema Registry — effort thấp, đảm bảo chất lượng dữ liệu ngay.\n"
    "4. Dùng Snowplow Mini để team học pipeline vận hành trước khi cam kết cloud.\n"
    "5. Lộ trình 4 giai đoạn: mỗi giai đoạn độc lập, deliverable rõ ràng, không phụ thuộc.",
    kind="success"
)

# ═══════════════════════════════════════════════════════════════════════════
#  REFERENCES
# ═══════════════════════════════════════════════════════════════════════════
doc.add_page_break()
heading1("Tài liệu tham khảo")

refs = [
    ("Snowplow Analytics", "https://snowplow.io/"),
    ("Snowplow GitHub (Open Source)", "https://github.com/snowplow/snowplow"),
    ("Snowplow Documentation", "https://docs.snowplow.io/"),
    ("Snowplow Stream Collector", "https://docs.snowplow.io/docs/pipeline-components-and-applications/stream-collector/"),
    ("Snowplow Stream Enrich", "https://docs.snowplow.io/docs/pipeline-components-and-applications/enrichment-components/stream-enrich/"),
    ("Iglu Schema Registry", "https://docs.snowplow.io/docs/pipeline-components-and-applications/iglu/"),
    ("Snowplow Analytics (BDP Cloud)", "https://snowplow.io/snowplow-analytics/"),
    ("Snowplow Mini", "https://docs.snowplow.io/docs/pipeline-components-and-applications/snowplow-mini/"),
    ("YAUAA (Yet Another UserAgent Analyzer)", "https://github.com/nielsbasjes/yauaa"),
    ("MaxMind GeoIP2", "https://dev.maxmind.com/geoip/geoip2/"),
    ("Snowplow dbt Models", "https://github.com/snowplow/dbt-snowplow-web"),
    ("dbt (Data Build Tool)", "https://www.getdbt.com/"),
    ("JSON Schema Specification (draft-07)", "https://json-schema.org/specification.html"),
    ("CDP Project — Project Plan", "docs/project-plan.md"),
    ("CDP Project — Development Guide", "docs/development-guide.md"),
    ("CDP Demo — README", "src/demo/README.md"),
    ("CDP Demo — Bot Driver", "src/demo/bot/driver.py"),
]

for i, (title, url) in enumerate(refs, 1):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.left_indent = Cm(0.5)
    run = p.add_run(f"[{i}] {title}: ")
    run.font.size = Pt(10.5)
    run.font.color.rgb = BLUE_MID
    run2 = p.add_run(url)
    run2.font.size = Pt(10.5)
    run2.font.color.rgb = GRAY_MID

# ─── Final save ──────────────────────────────────────────────────────────────
output_path = "docs/snowplow-theory-and-cdp-application-report.docx"
doc.save(output_path)
print(f"Saved: {output_path}")
print(f"File size: {__import__('os').path.getsize(output_path):,} bytes")
