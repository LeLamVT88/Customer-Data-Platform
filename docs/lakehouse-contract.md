# Hợp đồng dữ liệu Lakehouse chung — REES46 + Website

Lập ngày 19/11/2026, trước khi xây bất kỳ job ingestion nào. Tài liệu này là
hợp đồng giữa **tầng Bronze** (nơi dữ liệu được ghi) và **tầng Silver/Gold**
(nơi dữ liệu được đọc và tổng hợp). Mọi thay đổi phải cập nhật tài liệu này
trước.

Tài liệu liên quan:
- [project-plan.md](project-plan.md) — kiến trúc tổng thể và lộ trình
- [lakehouse-deployment.md](lakehouse-deployment.md) — hướng dẫn dựng stack Iceberg local
- [operations.md](operations.md) — vận hành stack nguồn, hợp đồng dữ liệu nguồn

---

## 1. Nguyên tắc bất di bất dịch

| # | Nguyên tắc | Hệ quả |
|---|---|---|
| P1 | Giữ namespace nguồn độc lập | Không có bảng nào chứa dữ liệu của cả hai nguồn mà không có cột `source_system` |
| P2 | Không tự ghép ID giữa hai nguồn | `rees46.user_id` **không bao giờ** bằng `web.customer_id`; cột ghép chỉ tồn tại trong `gold.customer_360` với cột `identity_source` |
| P3 | Lưu payload nguồn + metadata truy vết | Mọi bảng Bronze giữ nguyên payload gốc **và** metadata vị trí nguồn |
| P4 | Dữ liệu lỗi giữ lý do cách ly | Quarantine lưu `quarantine_reason` **và** `failure_detail`, không chỉ dữ liệu lỗi |
| P5 | UTC, phân biệt event time và ingestion time | Cột `event_time` (nghiệp vụ) tách biệt `ingested_at` (hệ thống) |
| P6 | Tiền: decimal, currency có nguồn xác định | REES46 không có currency → `currency = NULL`, giữ `price_raw` |
| P7 | Idempotency theo từng nguồn | Mỗi nguồn một khoá chống lặp riêng, ghi rõ ở §4 |
| P8 | CDC phân biệt snapshot / insert / update / delete / tombstone | Không dùng chung cột `op` mơ hồ |

---

## 2. Phân tầng và namespace

```text
cdp.bronze.*   — dữ liệu "as collected", không diễn giải
cdp.silver.*   — chuẩn hoá, đã qua kiểm tra chất lượng
cdp.gold.*     — data mart phục vụ phân tích / API
```

| Bảng | Nguồn | Grain (1 dòng =) |
|---|---|---|
| `cdp.bronze.rees46_events` | REES46 CSV | 1 sự kiện trong CSV gốc |
| `cdp.bronze.web_events` | Kafka `cdp.web.good` | 1 Snowplow event đã enrich |
| `cdp.bronze.web_events_failed` | Kafka `cdp.web.bad` / `.failed` / `.collector_bad` | 1 event bị Enrich từ chối |
| `cdp.bronze.business_cdc` | Kafka `cdp.business.public.*` | 1 thay đổi CDC (r/c/u/d) |
| `cdp.silver.web_events` | web_events | 1 event hợp lệ, đã chuẩn hoá |
| `cdp.silver.rees46_events` | rees46_events | 1 event REES46 đã chuẩn hoá |
| `cdp.silver.quarantine` | cả 3 nguồn | 1 bản ghi bị cách ly |
| `cdp.silver.business_cdc` | business_cdc | 1 thay đổi CDC đã áp dụng |
| `cdp.gold.user_behavior` | silver.web_events | 1 user × 1 ngày |
| `cdp.gold.session_funnel` | silver.web_events | 1 session |
| `cdp.gold.transaction` | silver.business_cdc | 1 order |
| `cdp.gold.customer_360` | silver.business_cdc + identity_links | 1 customer |

> **Quyết định:** REES46 và website **không** dùng chung một bảng Bronze. Lý do:
> grain khác nhau (CSV event vs Kafka record), khoá chống lặp khác nhau, và
> `price` của REES46 không có currency trong khi web event thì có. Ép chung sẽ
> tạo cột nullable ở mọi nơi và làm mất ý nghĩa.

---

## 3. Bảng Bronze

### 3.1 `cdp.bronze.rees46_events`

Nguồn: `data/REES46/2019-Oct.csv`, 42.448.764 dòng, 5.668.612.855 byte.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `event_time` | TIMESTAMP | Từ cột `event_time` của CSV, parse theo ISO-8601 UTC |
| `event_type` | STRING | Từ cột `event_type` |
| `product_id` | STRING | |
| `category_id` | STRING | |
| `category_code` | STRING | |
| `brand` | STRING | |
| `price_raw` | STRING | **Giữ nguyên chuỗi gốc**, không parse ở tầng Bronze |
| `price` | DECIMAL(18,2) | Nullable. Parse từ `price_raw`; vi phạm định dạng → NULL + cờ chất lượng |
| `currency` | STRING | **Luôn NULL.** REES46 không có trường currency (P6) |
| `user_id` | STRING | Namespace REES46, không dùng để ghép với web |
| `user_session` | STRING | |
| `source_system` | STRING | Hằng số `'rees46'` |
| `source_file` | STRING | Đường dẫn tương đối tới file gốc |
| `source_row_number` | BIGINT | Số thứ tự dòng trong CSV (1-based, không tính header) |
| `source_file_checksum` | STRING | sha256 của file gốc, tính 1 lần cho cả batch |
| `ingested_at` | TIMESTAMP | Thời điểm job đọc dòng này (UTC) |
| `batch_id` | STRING | Định danh lần chạy ingestion |

**Khoá chống lặp:** `(source_file_checksum, source_row_number)`.

> **Vì sao cần checksum file:** REES46 không có `event_id`, nên số thứ tự dòng là
> định danh duy nhất. Nếu file gốc bị thay đổi giữa chừng (thêm/bớt dòng), số
> thứ tự dòng không còn ổn định → có thể ghi trùng hoặc bỏ sót dữ liệu. Cột
> `source_file_checksum` cho phép phát hiện việc này: nếu checksum đổi giữa
> chừng batch, batch phải bị dừng và tạo `batch_id` mới.
>
> **Không dùng `batch_id` làm một phần của khoá chống lặp.** Nếu khoá chứa
> `batch_id`, chạy lại cùng file sẽ tạo bản ghi mới ⇒ vi phạm idempotency.
> `batch_id` là thuộc tính lần chạy, dùng để truy vết, không dùng để chống lặp.

### 3.2 `cdp.bronze.web_events`

Nguồn: topic Kafka `cdp.web.good` — output của Snowplow Enrich (đã validate
Iglu, đã enrich YAUAA).

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `event_id` | STRING | UUID của Snowplow. **Khoá chính** |
| `event_name` | STRING | `page_view`, `product_view`, ... (tên schema không có vendor) |
| `event_version` | STRING | `1-0-0` hoặc `1-0-1` (checkout/purchase) |
| `event_schema` | STRING | URI Iglu đầy đủ, ví dụ `iglu:com.cdp.demo/product_view/jsonschema/1-0-0` |
| `event_time` | TIMESTAMP | `collector_tstamp` — thời điểm Collector nhận |
| `client_event_time` | TIMESTAMP | `dtm` — thời điểm client sinh event |
| `app_id` | STRING | `cdp-demo` |
| `tracker_name` | STRING | `tna` |
| `tracker_version` | STRING | `tv` |
| `platform` | STRING | `p` |
| `url` | STRING | |
| `referrer` | STRING | |
| `user_agent` | STRING | |
| `user_id` | STRING | Atomic user_id của Snowplow. NULL nếu chưa đăng nhập |
| `anonymous_id` | STRING | Từ entity `com.cdp.demo/source` |
| `session_id` | STRING | Từ entity `com.cdp.demo/session` |
| `customer_id` | STRING | Từ entity `source`, chỉ có sau xác thực |
| `run_id` | STRING | Gom dữ liệu một lần chạy — **không phải** danh tính |
| `persona` | STRING | `lina` / `minh` / `hoa` / `quang`, NULL với traffic thật |
| `payload` | VARIANT | JSON payload của self-describing event (đã bóc khỏi wrapper `unstruct_event`) |
| `contexts` | VARIANT | JSON entities, dạng mảng `{schema, data}` |
| `device_type` | STRING | Từ YAUAA enrichment |
| `os_name` | STRING | Từ YAUAA enrichment |
| `os_version` | STRING | Từ YAUAA enrichment |
| `browser_name` | STRING | Từ YAUAA enrichment |
| `browser_version` | STRING | Từ YAUAA enrichment |
| `source_system` | STRING | Hằng số `'snowplow_web'` |
| `kafka_topic` | STRING | `cdp.web.good` |
| `kafka_partition` | INT | |
| `kafka_offset` | BIGINT | **Khoá chống lặp** cùng topic+partition |
| `kafka_timestamp` | TIMESTAMP | Timestamp broker gắn |
| `ingested_at` | TIMESTAMP | |
| `batch_id` | STRING | |

**Khoá chống lặp:** `(kafka_topic, kafka_partition, kafka_offset)`. Đây là khoá
chuẩn của Kafka — đọc lại cùng partition/offset không tạo bản ghi mới.

> **Cách đọc payload:** Snowplow lưu payload của self-describing event ở cột
> phẳng trong `event_json`, tên cột dạng
> `unstruct_event_com_cdp_demo_<event_name>_<versionIndex>` — ví dụ
> `unstruct_event_com_cdp_demo_product_view_1` (1-0-0) và
> `unstruct_event_com_cdp_demo_purchase_observed_2` (1-0-1). `versionIndex` là
> số thứ tự phiên bản, **không phải** số `1-0-0`. Job Bronze phải dò tiền
> tố `unstruct_event_com_cdp_demo_<event_name>_` thay vì ghép cứng hậu tố.
> Entity nằm ở `contexts_com_cdp_demo_<entity_name>_<versionIndex>`.
>
> Xem `src/demo/api/dashboard.py` (`payload_of`) để tham chiếu cách đọc này.

> **Quan trọng:** `user_id` của Snowplow **không** đồng nghĩa với khách hàng
> đã xác thực. Xem §6.

### 3.3 `cdp.bronze.web_events_failed`

Nguồn: `cdp.web.bad` (Enrich từ chối), `cdp.web.failed` (lỗi enrich),
`cdp.web.collector_bad` (Collector từ chối).

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `event_id` | STRING | Nếu có thể trích từ payload; nếu không, hash `topic:partition:offset` |
| `event_name` | STRING | Suy ra từ payload nếu parse được |
| `event_time` | TIMESTAMP | |
| `payload_raw` | STRING | **Payload gốc dạng bytes/string**, không diễn giải |
| `contexts_raw` | STRING | |
| `failure_stage` | STRING | `collector` / `enrich` — suy ra từ topic |
| `quarantine_reason` | STRING | Bắt buộc (P4) |
| `failure_detail` | STRING | Thông báo lỗi chi tiết |
| `source_system` | STRING | `'snowplow_web'` |
| `kafka_topic` / `kafka_partition` / `kafka_offset` | | Khoá chống lặp |
| `ingested_at` | TIMESTAMP | |
| `batch_id` | STRING | |

### 3.4 `cdp.bronze.business_cdc`

Nguồn: `cdp.business.public.{customers,products,orders,order_items,identity_links}`.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `source_table` | STRING | `customers` / `orders` / ... |
| `op` | STRING | `r` (snapshot/insert) / `c` (create) / `u` (update) / `d` (delete) |
| `op_category` | STRING | `snapshot` / `change` — tách rõ theo P8 |
| `before_image` | VARIANT | JSON `before`, NULL nếu không có |
| `after_image` | VARIANT | JSON `after`, NULL nếu là tombstone |
| `primary_key` | MAP<STRING,STRING> | Khoá chính của bản ghi |
| `change_ts` | TIMESTAMP | `source.ts_ms` của Debezium |
| `source_lsn` | BIGINT | `source.lsn` — khoá chống lặp |
| `tx_id` | STRING | `source.txId` |
| `source_system` | STRING | Hằng số `'postgres_business'` |
| `kafka_topic` / `kafka_partition` / `kafka_offset` | | |
| `ingested_at` | TIMESTAMP | |
| `batch_id` | STRING | |

**Khoá chống lặp:** `(kafka_topic, kafka_partition, kafka_offset)`.

> **Hạn chế đã biết:** Debezium không cung cấp `lsn` ổn định cho mọi bản ghi
> (snapshot có `lsn = null`). Vì vậy khoá chính xác là offset; `source_lsn` chỉ
> để tham khảo và đối soát.

**Tombstone:** giá trị Kafka là NULL kèm key. Bronze lưu `after_image = NULL`
và `op = 'd'`. Không được xoá bản ghi — CDC là append-only.

---

## 4. Chính sách chống lặp và replay

| Nguồn | Khoá | Phạm vi replay | Ghi chú |
|---|---|---|---|
| REES46 | `(source_file_checksum, source_row_number)` | Chỉ replay trong cùng file gốc | File đổi → checksum đổi → phải tạo `batch_id` mới và ghi lại từ đầu |
| Snowplow web | `(kafka_topic, kafka_partition, kafka_offset)` | Chỉ trong retention Kafka (7 ngày) | Offset cũ hơn retention → không replay được, phải chấp nhận gap |
| CDC | `(kafka_topic, kafka_partition, kafka_offset)` | Chỉ trong retention | Cần snapshot mới để lấp gap |

**Về `batch_id`:** là thuộc tính của *lần chạy*, dùng để truy vết và đối soát,
**không** dùng làm một phần của khoá chống lặp. Nếu đưa `batch_id` vào khoá,
chạy lại cùng dữ liệu sẽ tạo bản ghi mới ⇒ vi phạm idempotency.

**Checkpoint:** mỗi job Bronze ghi checkpoint sau khi commit thành công. Job
đọc từ checkpoint, không đọc lại từ đầu.

**Cấm:** cộng dồn các bản sample REES46 chồng lặp thành dữ liệu "toàn tháng".
Mỗi lần chạy = 1 `batch_id` khác, và phải có bước đối soát để biết dữ liệu
đang tính là bản nào.

---

## 5. Tầng Silver — chuẩn hoá

### 5.1 Nguyên tắc chuẩn hoá

| Trường | Quy tắc |
|---|---|
| `event_date` | `date(event_time)` — dùng để partition |
| `quantity` | `INT`, NULL nếu không có |
| `total_price` / `price` | `DECIMAL(18,2)`, parse từ chuỗi; lỗi → NULL |
| `currency` | Giữ nguyên; REES46 luôn NULL |
| `quality_flags` | `ARRAY<STRING>`, ghi các vấn đề: `missing_currency`, `price_unparseable`, `invalid_quantity`, `negative_price`, `missing_session_id`, `unauthenticated_user` |
| `ingestion_time` | `ingested_at` từ Bronze |

### 5.2 `cdp.silver.quarantine`

Bảng **thống nhất** cho cả 3 nguồn:

| Cột | Ghi chú |
|---|---|
| `source_system` | `rees46` / `snowplow_web` / `postgres_business` |
| `quarantine_reason` | Bắt buộc, không NULL |
| `failure_detail` | Chi tiết lỗi |
| `raw_payload` | Dữ liệu gốc bị lỗi (STRING hoặc VARIANT tuỳ nguồn) |
| `error_stage` | `parse` / `validate` / `apply` |
| `kafka_topic/partition/offset` | NULL với nguồn REES46 |
| `source_file` / `source_row_number` | NULL với nguồn Kafka |
| `batch_id`, `ingestion_time` | |

### 5.3 `cdp.silver.business_cdc` — trạng thái CDC

Bảng này áp dụng chuỗi thay đổi theo thứ tự để tạo **trạng thái hiện tại**:

- `r`/`c` → tạo bản ghi
- `u` → cập nhật (giữ `before_image` để audit)
- `d` → đánh dấu `is_deleted = true` (không xoá vật lý)
- Tombstone (`after_image = NULL`) → đánh dấu `is_deleted = true`

Quy tắc áp dụng:
1. Sắp xếp theo `(source_table, primary_key, change_ts, kafka_offset)`
2. `change_ts` có thể bằng nhau → phải phá thế hoá bằng `kafka_offset` (đây là lý do
   cần giữ cả hai trong Bronze)
3. `is_deleted = true` **không** được đưa vào Gold — chỉ ẩn, không xoá

---

## 6. Danh tính — quy tắc quan trọng nhất

| Khái niệm | Nguồn | Ý nghĩa |
|---|---|---|
| `anonymous_id` | entity `source` | Định danh trình duyệt/bot. **Chưa** là danh tính |
| `user_id` | atomic Snowplow | Có thể là khách đã đăng nhập, **hoặc** anonymous id từ bot |
| `customer_id` | entity `source` | Chỉ có sau `identity_authenticated` |
| `identity_links.evidence` | bảng nghiệp vụ | Chỉ nhận giá trị `'authenticated_login'` |

**Quy tắc:**
1. Một `anonymous_id` **không** được coi là khách hàng.
2. `user_id` trong bảng `events` của Snowplow có thể là anonymous (bot gán
   `bot_uid_*`). Trong `silver.web_events` phải có cột `identity_status`:
   - `anonymous` — không có `customer_id`
   - `authenticated` — có `customer_id` và có bản ghi trong `identity_links`
   - `unlinked` — có `customer_id` nhưng không tìm thấy bằng chứng liên kết
3. `gold.customer_360` chỉ xây từ `identity_links` với `evidence =
   'authenticated_login'`.
4. `run_id` **không bao giờ** dùng làm danh tính khách hàng.

---

## 7. Tầng Gold

### 7.1 `cdp.gold.user_behavior`

Grain: 1 `customer_id` (hoặc `anonymous_id` khi chưa xác thực) × 1 ngày.

Cột đo lường: `event_count`, `page_views`, `product_views`, `searches`,
`add_to_cart`, `remove_from_cart`, `begin_checkout`, `purchase_observed`,
`cart_abandoned`, `wishlist_add`, `scroll_depth_max`, `distinct_products`,
`total_search_terms`.

> `purchase_observed` là **hành vi quan sát**, không phải doanh thu. Cột này
> đếm sự kiện, không đếm tiền.

### 7.2 `cdp.gold.session_funnel`

Grain: 1 `session_id`.

Cột: `session_start`, `session_end`, `persona`, `anonymous_id`, `customer_id`,
`has_page_view`, `has_product_view`, `has_search`, `has_add_to_cart`,
`has_begin_checkout`, `has_purchase`, `has_cart_abandoned`, `event_count`,
`product_count`, `duration_seconds`.

### 7.3 `cdp.gold.transaction`

Grain: 1 `order_id`.

Nguồn: **chỉ** từ `silver.business_cdc` (bảng `orders`), không từ event.

Cột: `order_id`, `customer_id`, `status`, `total_price`, `currency`,
`item_count`, `created_at`, `paid_at`, `cancelled_at`, `refunded_at`,
`created_date`.

> **Quy tắc P3/P6:** `purchase_observed` **không** được dùng để suy ra doanh
> thu hay đơn hàng. Chỉ số giao dịch dựa trên trạng thái đơn nghiệp vụ.
> Thanh toán trong demo là mô phỏng.

### 7.4 `cdp.gold.customer_360`

Grain: 1 `customer_id`.

Cột: `customer_id`, `email`, `name`, `registered_at`, `first_event_at`,
`last_event_at`, `total_sessions`, `total_orders`, `total_paid_amount`,
`currency`, `last_order_status`, `identity_source` (= `'postgres_business'`).

> **Không có dòng nào trong bảng này đến từ REES46.** REES46 không có bằng
> chứng xác thực nên không thể ghép (P2).

---

## 8. Phân vùng (partitioning)

| Bảng | Partition |
|---|---|
| `bronze.rees46_events` | `days(event_date)` — dữ liệu lịch sử, không cần batch trong partition |
| `bronze.web_events` | `days(event_date)` + `bucket(16, app_id)` |
| `bronze.business_cdc` | `days(change_date)` |
| `silver.*` | Theo nguồn, giống Bronze |
| `gold.*` | `days(*_date)`; `gold.customer_360` không partition (nhỏ) |

> Bản cũ (đã gỡ) partition theo `bucket(16, batch_id)`. Không dùng lại: `batch_id`
> là thuộc tính của lần chạy, không phải của dữ liệu — partition theo nó làm
> phân mảnh bảng và mỗi lần chạy lại tạo partition mới.

---

## 9. Kiểm tra chất lượng (bắt buộc trước khi vào Gold)

| Kiểm tra | Mức | Hành động khi fail |
|---|---|---|
| Bronze: số dòng đọc = số dòng ghi + số dòng quarantine | Bắt buộc | Dừng batch |
| Bronze: không trùng khoá chống lặp | Bắt buộc | Dừng batch |
| Silver: không còn dòng `failed = true` | Bắt buộc | Dừng batch |
| Silver: `event_date` khớp `event_time` | Bắt buộc | Dừng batch |
| Silver: mọi dòng có `source_system` | Bắt buộc | Dừng batch |
| Gold: `purchase_observed` không xuất hiện trong `gold.transaction` | Bắt buộc | Dừng batch |
| Gold: `gold.customer_360` chỉ chứa `customer_id` từ nguồn web | Bắt buộc | Dừng batch |
| REES46: tỉ lệ `price` null | Cảnh báo | Ghi `quality_flags` |
| REES46: tỉ lệ dòng thiếu `user_id` | Cảnh báo | Ghi `quality_flags` |

**Đối soát phải kiểm tra cả ID, giá trị và tổng số dòng** — không được chỉ dựa
vào thông báo "job chạy xong".

---

## 10. Công nghệ dự kiến

| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| Compute | Apache Spark (PySpark) | Đọc REES46 bằng **DuckDB streaming** rồi ghi Iceberg, không dùng pandas cho file 5.6 GB |
| Storage format | Apache Iceberg | `format-version = 2` |
| Catalog | Iceberg REST catalog (Spark 3.5+) hoặc JDBC catalog (PostgreSQL) | JDBC catalog đơn giản hơn cho local |
| Object storage | MinIO (S3-compatible) | Chạy local bằng Docker |
| Orchestration | Airflow | **Chỉ sau khi** pipeline local được nghiệm thu |

---

## 11. Câu hỏi cần thầy/team review

1. **REES46 không có currency.** Giữ `currency = NULL` hay quy ước một currency
   cho toàn bộ nguồn (ví dụ VND/EUR)? Khuyến nghị: giữ NULL + `quality_flags`.
2. **Số phân vùng của Bronze web_events.** 16 bucket là quá nhiều cho dataset
   demo (vài trăm nghìn event). Khuyến nghị: 4, hoặc chỉ partition theo ngày.
3. **`gold.customer_360` chỉ có khách demo.** Chấp nhận bảng này nhỏ (hàng chục
   dòng) hay cần định nghĩa rộng hơn cho tương lai?
4. **Có cần bảng `gold.product_performance`?** (REES46 có `product_id`,
   `category_id`, `price` — đủ để tính doanh số ước tính, nhưng không có
   `quantity` hay `currency` nên chỉ là số lượt xem.)
5. **Thời gian giữ dữ liệu.** Kafka retention 7 ngày có đủ cho demo không, hay
   cần tăng?

---

## 12. Checklist bắt đầu

- [ ] Thầy/team review và chốt §11
- [ ] Dựng stack Iceberg local (catalog + MinIO + Spark)
- [ ] Viết DDL Bronze cho 4 bảng (§3)
- [ ] Viết job ingestion REES46 (DuckDB → Bronze)
- [ ] Viết job ingestion Kafka web (good/bad → Bronze)
- [ ] Viết job ingestion CDC (→ Bronze)
- [ ] Viết DDL Silver + Quarantine (§5)
- [ ] Viết job Silver + bộ kiểm tra chất lượng (§9)
- [ ] Viết DDL + job Gold (§7)
- [ ] Bộ kiểm thử: replay, khôi phục, đối soát số dòng
