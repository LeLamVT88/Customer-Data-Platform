# CDP Demo Website — Hướng dẫn sử dụng

Một trang thử nghiệm thương mại điện tử tổng hợp hành vi người dùng thành các sự kiện có kiểu
(`page_view`, `product_view`, `add_to_cart`, `purchase_observed`, v.v.) cho pipeline Customer Data Platform.

---

## Kiến trúc tổng quan

```
┌──────────────────────┐      ┌─────────────────────┐      ┌──────────────────────┐
│   Web Demo (SPA)     │      │  Demo API (FastAPI)  │      │   Data Lakehouse     │
│  src/demo/web/       │ POST │  src/demo/api/       │ CSV  │  data/demo-events/    │
│                      │─────▶│  server.py           │─────▶│  <batch-id>/         │
│  • HTML/CSS/JS       │      │                     │      │  events.csv          │
│  • catalog.js        │      │  • Validate events  │      │  manifest.json       │
│  • dashboard.js      │      │  • Assign batch_id  │      │                      │
│                      │      │  • Quarantine bad   │      │  [Scaffold] Spark →  │
│                      │      │    rows             │      │  Iceberg Bronze/     │
│  http://localhost:   │      │                     │      │  Silver/Gold         │
│   8081               │      │  http://localhost:   │      │                      │
│                      │      │   8000              │      │                      │
└──────────────────────┘      └─────────────────────┘      └──────────────────────┘
         │                              │
         │ GET /api/catalog             │ POST /api/events
         │ GET /api/summary             │ GET /api/summary
         └──────────────────────────────┘
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

## Task Flow (Data Flow)

Dòng dữ liệu từ hành động người dùng đến dashboard:

```
1. User Click / Action
   └─ JS: track(eventType, payload)
        └─ Event queued in _eventQueue[]

2. Batch Flush (5s interval OR page unload)
   └─ navigator.sendBeacon(POST /api/events)
        └─ API: FastAPI /api/events endpoint

3. Server-side Processing
   └─ Validate: event_type in SUPPORTED_EVENT_TYPES?
   └─ Check: session_id, user_id present?
   └─ Assign: batch_id, ordinal, ingestion_time, event_id
   └─ Route: good → events.csv | bad → quarantine.csv

4. File Write
   └─ data/demo-events/<batch-id>/
        ├── events.csv        (accepted rows)
        ├── quarantine.csv     (rejected rows)
        └── manifest.json     (counts, checksum, metadata)

5. Lakehouse (Scaffold — requires Docker stack)
   └─ Spark job reads events.csv
        ├─ Bronze layer:  raw columns
        ├─ Silver layer:  typed events, quality flags
        └─ Gold layer:    daily/user/funnel aggregates

6. Dashboard
   └─ GET /api/summary (every 10s)
        └─ Render: stats cards, bar charts, persona funnels
```

---

## Sơ đồ Event Taxonomy

| Event Type | Khi nào bắn | Payload chính | Ghi chú |
|---|---|---|---|
| `page_view` | Mỗi lần chuyển trang (hash routing) | `path`, `title` | Bắt đầu mỗi phiên |
| `product_view` | Click vào product card hoặc card trong danh sách | `product_id`, `category_id`, `price`, `currency` | |
| `add_to_cart` | Nhấn "Thêm vào giỏ hàng" | `product_id`, `quantity`, `price`, `currency` | |
| `remove_from_cart` | Nhấn "Xóa" trong giỏ hàng | `product_id` | |
| `begin_checkout` | Nhấn "Đặt hàng" (trước khi xử lý thanh toán) | `cart_id`, `items[]`, `total_price` | |
| `purchase_observed` | Thanh toán thành công | `cart_id`, `items[]`, `total_price` | |
| `element_click` | Click vào nút/sự kiện UI cụ thể | `selector`, `tag`, `sort` | Sort dropdown, clear cart |
| `scroll_depth` | (Reserved) Khi người dùng cuộn sâu | `depth_percent` | |
| `search` | Gửi tìm kiếm ở catalog | `query`, `results_count`, `type` | |
| `error` | Lỗi JavaScript xảy ra | `message`, `stack` | |
| `cart_abandoned` | Rời trang khi có sản phẩm trong giỏ (sendBeacon on beforeunload) | `items[]`, `total_price`, `currency` | Chỉ bắn 1 lần mỗi session |
| `apply_filter` | Thay đổi bộ lọc danh mục | `filter_type`, `filter_value` | |
| `wishlist_add` | Nhấn nút Wishlist (lần đầu) | `product_id`, `price`, `currency` | |
| `wishlist_remove` | Nhấn lại nút Wishlist (bỏ chọn) | `product_id` | |
| `newsletter_signup` | Gửi form newsletter | `email` | |

---

## Hướng dẫn chạy nhanh

### 1 — Khởi động API

```powershell
# Từ thư mục gốc repo
python -m src.demo.api.server
```

API lắng nghe tại `http://127.0.0.1:8000`. Các endpoint:

| Endpoint | Mô tả |
|---|---|
| `GET /health` | Health check |
| `GET /api/catalog` | Trả về danh sách sản phẩm JSON |
| `POST /api/events` | Nhận batch sự kiện, validate, ghi file |
| `GET /api/summary` | Counts cho dashboard (batch mới nhất) |

### 2 — Khởi động Web UI

```powershell
# Trong terminal thứ hai
cd src/demo/web
python -m http.server 8081
```

Mở `http://127.0.0.1:8081/` trong trình duyệt.

### 3 — Chạy Bot (tùy chọn)

```powershell
# Smoke test: 5 users
python -m src.demo.bot.driver --users 5

# Full run: 200 users, ~5000 events/min
python -m src.demo.bot.driver --users 200

# Force a specific persona
python -m src.demo.bot.driver --users 20 --profile lina
python -m src.demo.bot.driver --users 20 --profile minh
python -m src.demo.bot.driver --users 20 --profile hoa
python -m src.demo.bot.driver --users 20 --profile quang
```

Bot gửi events trực tiếp đến API. Mỗi lần chạy ghi metadata vào `data/demo-events/bot-run-*.json`.

### 4 — Chạy API tests

```powershell
.venv\Scripts\python.exe -m pytest src/demo/api/tests -q
```

---

## Hướng dẫn quan sát Dashboard

Mở `http://127.0.0.1:8081/` → click **Dashboard**.

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

---

## Cấu trúc file

```
src/demo/
├── web/
│   ├── index.html          # SPA entry (hash routing: #home, #catalog, #cart…)
│   ├── css/main.css        # Styles (mobile-friendly, CSS variables)
│   └── js/
│       ├── catalog.js      # Catalog, cart, event tracking, routing, personas
│       └── dashboard.js    # Dashboard với per-persona funnel, insights
├── api/
│   ├── server.py           # FastAPI: catalog, events, summary, quarantine
│   └── tests/
│       └── test_ingest.py  # Schema, idempotency, quarantine tests
├── bot/
│   ├── driver.py           # Multi-threaded synthetic user driver
│   ├── profiles.py         # 4 persona profiles + 3 legacy profiles
│   └── scenarios.py        # 8 deterministic test scenarios
├── requirements.txt

config/demo/
└── catalog.products.json   # 250 sản phẩm synthetic
```

---

## Data Contract

**Namespace:** `cdp.demo.events`

| Trường | Ghi chú |
|---|---|
| `event_id` | `sha256(namespace + batch_checksum + ordinal)` — duy nhất mỗi dòng |
| `event_time` | ISO 8601 UTC, client-generated |
| `event_type` | Một trong 16 kiểu được hỗ trợ |
| `session_id` | Bắt buộc; thiếu → quarantine |
| `user_id` | Bắt buộc (strict mode); thiếu → quarantine |
| `batch_id` | Server-assigned UUID per POST request |
| `ingestion_time` | Server UTC timestamp |
| `quality_flags` | `missing_session`, `missing_user_id` |

**Idempotency:** cùng POST body (cùng bytes JSON) luôn trả về cùng `batch_id`
và KHÔNG ghi thêm file mới.

---

## M4 note (Lakehouse scaffold)

`src/demo/lakehouse/` là **scaffold thuần túy** — cần Docker stack để chạy.
Sự kiện được lưu dưới dạng CSV tại `data/demo-events/<batch-id>/` cho đến khi
Docker stack được khởi động:

```powershell
docker compose -f config/docker/compose.local-lakehouse.yml up -d
# Then run the Spark job
sh src/tools/run_local_lakehouse.sh data/demo-events/<batch-id>/
```

---

## M4 status — CDP Demo M0–M3 ✅

| Milestone | Trạng thái |
|---|---|
| M0 — Catalog | ✅ 250 sản phẩm, 19 danh mục |
| M1 — Static SPA | ✅ HTML + ES module JS |
| M2 — Demo API | ✅ FastAPI, validate, idempotency |
| M3 — Bot Driver | ✅ 4 persona profiles, scenarios |
| M4 — Lakehouse | 🔧 Scaffold (cần Docker) |

---

## Các lệnh nhanh

```powershell
# API
python -m src.demo.api.server

# Web UI
cd src/demo/web; python -m http.server 8081

# Bot smoke test
python -m src.demo.bot.driver --users 5

# Bot full run (200 users)
python -m src.demo.bot.driver --users 200

# Test persona individually
python -m src.demo.bot.driver --users 10 --profile lina
python -m src.demo.bot.driver --users 10 --profile minh
python -m src.demo.bot.driver --users 10 --profile hoa
python -m src.demo.bot.driver --users 10 --profile quang

# Run tests
python -m pytest src/demo/api/tests -q

# Verify API health
curl http://127.0.0.1:8000/health
```
