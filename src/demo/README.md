# CDP Demo Website — Hướng dẫn sử dụng

Một trang thử nghiệm thương mại điện tử tổng hợp hành vi người dùng thành các sự kiện có kiểu
(`page_view`, `product_view`, `add_to_cart`, `purchase_observed`, v.v.) cho pipeline Customer Data Platform.

> **Tầng backend đã được thay hoàn toàn bằng Snowplow.**
> Demo API không còn nhận, validate hay lưu event. Mọi event do **Snowplow Browser Tracker**
> và **bot TP2** gửi thẳng tới **Snowplow Micro collector**, được **Enrich** validate theo Iglu
> schema, rồi lưu vào **PostgreSQL**. Demo API chỉ còn là một *read layer* truy vấn bảng `events`.

---

## Kiến trúc tổng quan

```
┌──────────────────────┐         ┌─────────────────────────────┐
│   Web Demo (SPA)     │         │  Snowplow Micro (collector  │
│  src/demo/web/       │  HTTP   │  + enrich) :9090            │
│                      │────────▶│  ┌────────────────────────┐  │
│  • Snowplow Browser  │  TP2    │  │ Iglu validation       │  │
│    Tracker (UMD)     │         │  │ YAUAA enrichment      │  │
│  • js/tracker.js     │         │  │ → PostgreSQL storage  │  │
│  • js/catalog.js     │         │  └────────────────────────┘  │
│  • js/dashboard.js   │         └──────────────┬──────────────┘
└──────────┬───────────┘                        │
           │ GET /api/catalog                    │ JDBC
           │ GET /api/summary                   ▼
           │                        ┌─────────────────────────────┐
           ▼                        │  Spark → Apache Iceberg     │
┌──────────────────────┐            │  Bronze / Silver /          │
│  Demo API (FastAPI)  │            │  Quarantine / Gold          │
│  src/demo/api/       │            │  src/demo/lakehouse/        │
│  server.py           │            └─────────────────────────────┘
│  • Read-only         │
│  • Query PostgreSQL  │
└──────────────────────┘
```

Điểm khác biệt cốt lõi so với kiến trúc cũ:

| Trước (tự viết) | Sau (Snowplow) |
|---|---|
| `POST /api/events` nhận batch | Tracker/bot gửi **TP2** thẳng tới collector |
| Server validate event type | **Enrich** validate theo **Iglu schema** |
| Ghi `events.csv` + `quarantine.csv` | **PostgreSQL** `events` table (`failed` = bad stream) |
| `batch_id` / `quality_flags` tự sinh | `collector_tstamp` / `derived_tstamp` của Snowplow |
| Idempotency bằng checksum | `event_id` UUID của Snowplow |

---

## Data Flow

```
1. User Action (click, search, scroll, checkout)
   └─ js/catalog.js → track('product_view', payload)
        └─ js/tracker.js → Snowplow Browser Tracker
             └─ trackSelfDescribingEvent({
                  event:  { schema: 'iglu:com.cdp.demo/product_view/jsonschema/1-0-0', data },
                  context:[ session entity, product entity ]
                })

2. Tracker đóng gói TP2 → POST /com.snowplowanalytics.snowplow/tp2
   (bufferSize = 1 ⇒ mỗi event gửi ngay, không chờ đủ batch)

3. Snowplow Micro — Collector nhận & Enrich
   ├─ Iglu validation: payload khớp schema? → failed = false
   ├─ YAUAA: user-agent → device/browser/OS
   └─ Storage: PostgreSQL bảng `events`

4. Bot (nếu chạy) gửi TP2 payload_data 1-0-4 tới cùng collector
   └─ src/demo/bot/driver.py → src/demo/snowplow/tp2.py

5. Demo API đọc bảng `events` (read-only)
   ├─ GET /api/catalog  → catalog tĩnh
   └─ GET /api/summary  → tổng hợp event cho dashboard

6. Lakehouse (tùy chọn) — Spark đọc PostgreSQL qua JDBC
   ├─ cdp.bronze.demo_events       (nguyên bản, gồm cả event lỗi)
   ├─ cdp.silver.demo_events       (chỉ event hợp lệ, đã chuẩn hoá)
   ├─ cdp.silver.demo_quarantine   (event Enrich đánh dấu failed)
   └─ cdp.gold.demo_user_behavior / demo_session_funnel
```

---

## User Personas & Task Flows

Bốn nhân khẩu học người dùng, mỗi người để lại một "chữ ký" sự kiện riêng biệt trên dashboard.

| Persona | Mô tả | Mục tiêu | Task Flow | Event Signature |
|---|---|---|---|---|
| **Lina** (Window Shopper) | Duyệt nhanh, không mua | Xây depth signal | `#catalog` → duyệt nhiều sản phẩm → `#home` | `product_view` × N, `scroll_depth`, 0 `add_to_cart` |
| **Minh** (Decisive Buyer) | Thêm ít sản phẩm, mua nhanh | Clear purchase signal | `#catalog` → xem sản phẩm → `add_to_cart` → `#checkout` → `purchase_observed` | Đầy đủ phễu: `product_view` → `add_to_cart` → `begin_checkout` → `purchase_observed` |
| **Hoa** (Researcher) | Tìm kiếm, so sánh, không mua | High-engagement non-buyer signal | `#catalog` → thanh tìm kiếm → xem nhiều sản phẩm → `wishlist_add` | `search` × N, `product_view` × N, `wishlist_add`, 0 `purchase_observed` |
| **Quang** (Cart Abandoner) | Thêm nhiều sản phẩm, bỏ ở checkout | Cart abandonment signal | `#catalog` → `add_to_cart` × N → `#cart` → rời trang | `add_to_cart` × N, `cart_abandoned`, 0 `begin_checkout` |

---

## Sơ đồ Event Taxonomy (Iglu schema `com.cdp.demo`)

Mỗi event type có **một Iglu schema riêng** trong
`config/snowplow/iglu-client-embedded/schemas/com.cdp.demo/<event_type>/jsonschema/1-0-0`.
Schema được sinh bởi `config/snowplow/tools/build_schemas.py`.

| Event Type | Khi nào bắn | Payload chính | Ghi chú |
|---|---|---|---|
| `page_view` | Mỗi lần chuyển route (hash routing) | `path`, `title` | `path` = `/`, `/catalog`, `/cart`… |
| `product_view` | Click vào product card | `product_id`, `category_id` | |
| `add_to_cart` | Nhấn "Thêm vào giỏ hàng" | `product_id`, `quantity`, `price`, `currency` | |
| `remove_from_cart` | Nhấn "Xóa" trong giỏ hàng | `product_id` | |
| `begin_checkout` | Nhấn "Đặt hàng" | `cart_id`, `items[]`, `total_price`, `currency` | |
| `purchase_observed` | Thanh toán thành công | `cart_id`, `items[]`, `total_price`, `currency` | Không suy ra doanh thu thực |
| `element_click` | Click vào control cụ thể | `selector`, `tag`, `sort` | Sort dropdown, clear cart |
| `scroll_depth` | Cuộn tới mốc 25/50/75/100% | `depth_percent` | |
| `search` | Gõ trong ô tìm kiếm catalog | `query`, `results_count`, `type` | |
| `error` | Lỗi JS / unhandled rejection | `message`, `stack` | |
| `cart_abandoned` | Rời trang khi giỏ còn sản phẩm | `items[]`, `total_price`, `currency` | Chỉ bắn 1 lần mỗi session |
| `apply_filter` | Đổi bộ lọc danh mục | `filter_type`, `filter_value` | |
| `wishlist_add` | Nhấn nút Wishlist (lần đầu) | `product_id`, `price`, `currency` | |
| `wishlist_remove` | Nhấn lại nút Wishlist | `product_id` | |
| `newsletter_signup` | Gửi form newsletter | `email` | |

### Entity (context)

| Entity | Trường | Gắn vào event nào |
|---|---|---|
| `com.cdp.demo/session` | `session_id` | Mọi event |
| `com.cdp.demo/product` | `product_id`, `category_id`, `brand`, `price`, `currency` | Event có thông tin sản phẩm |

---

## Hướng dẫn chạy nhanh

### 0 — Cài đặt dependencies (chỉ làm 1 lần)

```powershell
# Tạo virtualenv nếu chưa có
python -m venv .venv

# Kích hoạt virtualenv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Cài dependencies
pip install -r src/demo/requirements.txt
```

### 1 — Khởi động Snowplow (collector + storage)

```powershell
docker compose -f config/docker/compose.snowplow.yml up -d --wait
```

| Service | Địa chỉ | Vai trò |
|---|---|---|
| `cdp-snowplow-micro` | `http://127.0.0.1:9090` | Collector + Enrich + storage writer |
| `cdp-snowplow-postgres` | `127.0.0.1:5432` | Storage backend — bảng `events` |

Micro tự nạp schema Iglu trong `config/snowplow/iglu-client-embedded/`.
Sau khi sửa schema, restart Micro để nạp lại:

```powershell
docker compose -f config/docker/compose.snowplow.yml restart snowplow-micro
```

### 2 — Khởi động Demo API (read layer)

```powershell
# Từ thư mục gốc repo
.venv\Scripts\python.exe -m src.demo.api.server
```

API lắng nghe tại `http://127.0.0.1:8000`. Các endpoint:

| Endpoint | Mô tả |
|---|---|
| `GET /health` | Health check |
| `GET /api/catalog` | Trả về danh sách sản phẩm JSON (tĩnh) |
| `GET /api/summary` | Tổng hợp event từ bảng `events` của Snowplow cho dashboard |

> Không còn `POST /api/events` — việc thu thập event do Snowplow đảm nhiệm.

### 3 — Khởi động Web UI

```powershell
# Trong terminal thứ hai (từ thư mục gốc repo)
.venv\Scripts\python.exe src\demo\web\serve.py --port 8081
```

Mở `http://127.0.0.1:8081/` trong trình duyệt. Trang tự gửi event tới collector `:9090`.

> **Dùng `serve.py`, không dùng `python -m http.server`.**
> `http.server` không gửi header `Cache-Control`, nên trình duyệt cache ES module
> (`js/*.js`) và giữ bản cũ. Sau khi `git pull`, trang vẫn chạy code cũ — dashboard
> có thể hiện phần trùng lặp, event mới không được gửi. `serve.py` phát
> `Cache-Control: no-store` nên mỗi lần reload đều lấy code mới nhất.

### 4 — Chạy Bot (tùy chọn)

```powershell
# Smoke test: 5 users
.venv\Scripts\python.exe -m src.demo.bot.driver --users 5

# Full run: 200 users, ~5000 events/min
.venv\Scripts\python.exe -m src.demo.bot.driver --users 200

# Force a specific persona
.venv\Scripts\python.exe -m src.demo.bot.driver --users 20 --profile lina
.venv\Scripts\python.exe -m src.demo.bot.driver --users 20 --profile minh
.venv\Scripts\python.exe -m src.demo.bot.driver --users 20 --profile hoa
.venv\Scripts\python.exe -m src.demo.bot.driver --users 20 --profile quang
```

Bot dùng `src/demo/snowplow/tp2.py` để dựng payload **Tracker Protocol 2** và POST tới
`http://127.0.0.1:9090/com.snowplowanalytics.snowplow/tp2`.

### 5 — Chạy API tests

```powershell
.venv\Scripts\python.exe -m pytest src/demo/api/tests -q
```

---

## Lakehouse (Iceberg) — tùy chọn

Nạp event từ PostgreSQL của Snowplow vào Iceberg:

```powershell
# 1. Khởi động catalog + storage
docker compose -f config/docker/compose.local-lakehouse.yml up -d --wait catalog storage

# 2. Chạy Spark job (đọc Snowplow PostgreSQL qua JDBC)
docker compose -f config/docker/compose.local-lakehouse.yml run --rm spark `
    /workspace/src/demo/lakehouse/ingest_demo.py --batch-id demo-local

# 3. Kiểm tra dữ liệu ở từng tầng
docker compose -f config/docker/compose.local-lakehouse.yml run --rm spark `
    /workspace/src/demo/lakehouse/verify_demo.py --batch-id demo-local
```

| Bảng Iceberg | Nội dung |
|---|---|
| `cdp.bronze.demo_events` | Enriched event nguyên bản, gồm cả event lỗi |
| `cdp.silver.demo_events` | Chỉ event hợp lệ (`failed = false`), đã chuẩn hoá + `quality_flags` |
| `cdp.silver.demo_quarantine` | Event mà Enrich đánh dấu `failed` (bad stream) |
| `cdp.gold.demo_user_behavior` | Tổng hợp hành vi theo user + ngày |
| `cdp.gold.demo_session_funnel` | Phễu hành vi theo session |

> Iceberg **không hỗ trợ** `DEFAULT` cho cột — giá trị mặc định được gán ở tầng Python
> (`ingest_demo.py`), không phải trong DDL.

---

## Hướng dẫn quan sát Dashboard

Mở `http://127.0.0.1:8081/` → click **Dashboard**. Dashboard poll `GET /api/summary` mỗi 10s.

### Cách nhận biết từng Persona

**Lina (Window Shopper) — thẻ màu tím**
- Nhiều `product_view`, `page_view`
- Ít hoặc không có `add_to_cart`
- Dashboard: dòng product_view cao, dòng add_to_cart thấp

**Minh (Decisive Buyer) — thẻ màu xanh lá**
- Đầy đủ phễu: product_view → add_to_cart → begin_checkout → purchase_observed
- Dashboard: biểu đồ phễu có đầy đủ 4 cột, cột purchase_observed > 0

**Hoa (Researcher) — thẻ màu vàng**
- Nhiều `search`, nhiều `product_view`
- KHÔNG có `purchase_observed`
- Dashboard: thẻ "Top tìm kiếm (search)" có giá trị > 0

**Quang (Cart Abandoner) — thẻ màu đỏ**
- Nhiều `add_to_cart`, có `cart_abandoned`
- Ít hoặc không có `begin_checkout`
- Dashboard: thẻ "Tỷ lệ bỏ giỏ hàng" cao (%)
- Thẻ top wishlist có giá trị > 0 nếu Hoa đã chạy

### Kiểm tra nhanh dữ liệu trong Snowplow

```powershell
# Event theo loại, đếm cả event lỗi
docker exec cdp-snowplow-postgres psql -U snowplow -d snowplow -c "
  SELECT event_name, count(*), count(*) FILTER (WHERE failed) AS failed
  FROM events GROUP BY 1 ORDER BY 2 DESC;"
```

`failed = 0` ở mọi dòng ⇒ payload khớp Iglu schema ⇒ Enrich đã validate thành công.

---

## Cấu trúc file

```
src/demo/
├── web/
│   ├── index.html          # SPA entry (hash routing) + bootstrap tracker
│   ├── serve.py            # Dev server tĩnh, tắt cache (no-store)
│   ├── css/main.css        # Styles (mobile-friendly, CSS variables)
│   ├── js/
│   │   ├── tracker.js      # Lớp tracking: init tracker, track(), trackPageView()
│   │   ├── catalog.js      # Catalog, cart, routing, gắn event vào hành động
│   │   └── dashboard.js    # Dashboard với per-persona funnel, insights
│   └── vendor/
│       └── snowplow-browser-tracker.min.js   # @snowplow/browser-tracker (UMD)
├── api/
│   ├── server.py           # FastAPI read layer: /api/catalog, /api/summary
│   └── tests/
│       └── test_ingest.py  # Test Iglu schema, TP2, payload extraction
├── bot/
│   ├── driver.py           # Multi-threaded synthetic user driver (gửi TP2)
│   ├── profiles.py         # 4 persona profiles + 3 legacy profiles
│   └── scenarios.py        # 8 deterministic test scenarios
├── snowplow/
│   └── tp2.py              # Bộ dựng payload Tracker Protocol 2 + HTTP client
├── lakehouse/
│   ├── ingest_demo.py      # Spark job: Snowplow PostgreSQL → Iceberg
│   ├── verify_demo.py      # Kiểm tra dữ liệu từng tầng Iceberg
│   └── sql/                # DDL Bronze / Silver+Quarantine / Gold
└── requirements.txt

config/
├── demo/catalog.products.json          # 250 sản phẩm synthetic
└── snowplow/
    ├── compose.snowplow.yml             # Snowplow Micro + PostgreSQL
    ├── iglu-client-embedded/schemas/    # Iglu schema com.cdp.demo/*
    └── tools/build_schemas.py           # Sinh schema từ định nghĩa tập trung
```

---

## Snowplow contract

**Collector endpoint:** `POST http://127.0.0.1:9090/com.snowplowanalytics.snowplow/tp2`
**Payload schema:** `iglu:com.snowplowanalytics.snowplow/payload_data/jsonschema/1-0-4`
**app_id:** `cdp-demo` · **tracker namespace:** `cdpDemo` (web) / `cdpDemoBot` (bot)

Cấu trúc event tự mô tả trong TP2:

| Trường TP2 | Nội dung |
|---|---|
| `ue_pr` | JSON **string** bọc `iglu:com.snowplowanalytics.snowplow/unstruct_event/jsonschema/1-0-0` → `data.schema` = schema event của app, `data.data` = payload |
| `co` | JSON **string** bọc `iglu:com.snowplowanalytics.snowplow/contexts/jsonschema/1-0-0` → mảng entity |

Bảng lưu trữ (PostgreSQL, Snowplow Micro schema):

| Cột | Ý nghĩa |
|---|---|
| `event_id` | UUID, khóa chính của event |
| `timestamp` | Thời điểm storage backend ghi |
| `event_json` | jsonb chứa toàn bộ enriched event |
| `failed` | `true` = bad stream (Enrich validate fail) |
| `event_name` | Tên event lấy từ Iglu schema |
| `user_id` / `domain_userid` | Định danh người dùng |
| `name_tracker` | `cdpDemo` hoặc `cdpDemoBot` |

Trong `event_json`, dữ liệu app nằm ở cột phẳng:

```
event_json -> 'unstruct_event_com_cdp_demo_<event_type>_1'   : payload
event_json -> 'contexts_com_cdp_demo_session_1'              : entity session
event_json -> 'contexts_com_cdp_demo_product_1'              : entity product
```

---

## Milestone status

| Milestone | Trạng thái |
|---|---|
| M0 — Catalog | ✅ 250 sản phẩm, 19 danh mục |
| M1 — Static SPA | ✅ HTML + ES module JS |
| M2 — Demo API | ✅ Chuyển sang read layer trên Snowplow PostgreSQL |
| M3 — Bot Driver | ✅ 4 persona profiles, gửi TP2 tới collector |
| M4 — Lakehouse | ✅ Spark + Iceberg (Bronze/Silver/Quarantine/Gold) |
| M5 — Snowplow | ✅ Micro collector + Iglu schema + Browser Tracker + TP2 bot |

---

## Các lệnh nhanh

```powershell
# Snowplow
docker compose -f config/docker/compose.snowplow.yml up -d --wait
docker compose -f config/docker/compose.snowplow.yml restart snowplow-micro

# API
.venv\Scripts\python.exe -m src.demo.api.server

# Web UI (no-cache dev server — xem ghi chú trong README)
.venv\Scripts\python.exe src\demo\web\serve.py --port 8081

# Bot smoke test
.venv\Scripts\python.exe -m src.demo.bot.driver --users 5

# Bot full run (200 users)
.venv\Scripts\python.exe -m src.demo.bot.driver --users 200

# Test persona individually
.venv\Scripts\python.exe -m src.demo.bot.driver --users 10 --profile lina
.venv\Scripts\python.exe -m src.demo.bot.driver --users 10 --profile minh
.venv\Scripts\python.exe -m src.demo.bot.driver --users 10 --profile hoa
.venv\Scripts\python.exe -m src.demo.bot.driver --users 10 --profile quang

# Run tests
.venv\Scripts\python.exe -m pytest src/demo/api/tests -q

# Lakehouse
docker compose -f config/docker/compose.local-lakehouse.yml up -d --wait catalog storage
docker compose -f config/docker/compose.local-lakehouse.yml run --rm spark `
    /workspace/src/demo/lakehouse/ingest_demo.py --batch-id demo-local

# Verify API health
curl http://127.0.0.1:8000/health
```

---

## Xử lý sự cố

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| Dashboard không đổi số liệu | Tracker đang gom event trong buffer | Đảm bảo `bufferSize: 1` trong `js/tracker.js` |
| Trang hiện code cũ sau khi `git pull` | Trình duyệt cache ES module (dev server không gửi `Cache-Control`) | Dùng `python src/demo/web/serve.py` thay vì `python -m http.server`, rồi hard reload (Ctrl+Shift+R) |
| `failed > 0` trong bảng `events` | Payload không khớp Iglu schema | Đọc log Micro (`docker logs cdp-snowplow-micro`) để xem field thiếu; sửa schema **và** payload cho khớp, rồi restart Micro |
| Micro trả `400` | Sai định dạng TP2 | `ue_pr`/`co` phải là **JSON string**, không phải object |
| API báo `snowplow_available=false` | Không kết nối được PostgreSQL | Kiểm tra `docker compose -f config/docker/compose.snowplow.yml ps` và biến `SNOWPLOW_PG_*` |
