# Hướng dẫn phát triển và vận hành local

Các lệnh bên dưới chạy từ root project, trừ khi có lệnh `cd`. Môi trường `.venv`, dữ liệu `data/` và cache giữ ở root và không đưa vào Git.

## Đọc tài liệu nào?

- [Kế hoạch project](project-plan.md): mục tiêu, kiến trúc CDP, lộ trình và tiêu chí nghiệm thu.
- [Hướng dẫn phát triển](development-guide.md): cấu trúc project, trạng thái, cài đặt, chạy và kiểm thử.
- [Mở rộng REES46](development-guide.md#benchmark): funnel, mẫu 1.000 user, export và chế độ toàn file.
- [Lakehouse local](development-guide.md#lakehouse-local): cấu hình Spark/Iceberg/S3, chạy batch và đối soát.
- [Data contract](development-guide.md#data-contract-rees46): schema, mapping trường, identity và quy tắc xử lý dữ liệu.
- [Báo cáo REES46](development-guide.md#khảo-sát-rees46-dung-lượng-lớn): số liệu profiling, checksum và giới hạn dataset.

## Cấu trúc project

```text
src/                                  # Toàn bộ mã nguồn, dependency và test
├── pipelines/
│   ├── inspect_rees46_dataset.py       # Khảo sát CSV, tạo preview/report
│   ├── ingest_rees46_batch.py          # Nạp mẫu thành Bronze/Silver/quarantine
│   ├── lakehouse/                     # Job Spark, writer Iceberg, SQL và integration test
│   ├── requirements.txt               # Dependency Python cho xử lý dữ liệu
│   └── tests/
│       └── test_rees46_batch_ingestion.py
└── tools/
    ├── benchmark_lakehouse.py          # Chạy job và đo RSS JVM/Python
    └── run_local_lakehouse.sh          # Chạy batch trên Iceberg/S3

config/                                # Cấu hình Docker, Spark và S3
├── docker/
│   ├── compose.local-lakehouse.yml
│   └── lakehouse.Dockerfile
├── spark/                            # Spark và Iceberg catalog
└── storage/                          # S3 local

docs/                                  # Tài liệu theo mục đích
├── project-plan.md                    # Mục tiêu, kiến trúc, lộ trình, nghiệm thu
└── development-guide.md               # Cài đặt, contract, benchmark và vận hành

data/                                  # CSV nguồn, preview, report, batch output
```

`data/`, `.venv/`, `.cache/` và output build không đưa vào Git.

## Trạng thái hiện tại

| Phần | Kết quả |
| --- | --- |
| Dataset REES46 | Có CSV local khoảng 5,67 GB; đã profiling 42.448.764 dòng |
| Batch prototype | 100 user, 4.312 sự kiện; Parquet Bronze/Silver/quarantine, manifest và checksum |
| Chạy lại | Cùng batch kiểm tra output rồi bỏ qua, không ghi thêm |
| Batch Lakehouse | Mẫu 10.000 user: 435.937 Silver; Gold daily/user/funnel 93/10.000/87.230; đối soát và integration test pass |
| Hệ thống CDP đầy đủ | Chưa có Kafka/CDC, backend nghiệp vụ, identity resolution hay Customer 360 |

Contract REES46 được mô tả trong [data contract](development-guide.md#data-contract-rees46). Mọi ngưỡng hiệu năng trong kế hoạch là mục tiêu, không phải kết quả đã đạt.

## 1. Nạp dữ liệu test

Từ thư mục gốc:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r src/pipelines/requirements.txt
.venv/bin/python src/pipelines/ingest_rees46_batch.py --users 100000
```

Mặc định nguồn `data/REES46/2019-Oct.csv`. Lệnh trên đọc toàn file để giữ toàn bộ hoạt động của 100.000 user đầu tiên không rỗng, tính checksum trước/sau và không nạp toàn bộ CSV vào dataframe Python. Chạy lần đầu phải quét file vài lượt, lâu hơn đọc preview.

Output: `data/local-batches/rees46/<batch-id>/` gồm:

```text
bronze.parquet        # Cột gốc, raw JSON, ordinal nguồn, metadata
silver.parquet        # Typed events, tên sự kiện chuẩn hóa, quality flags
quarantine.parquet    # Bản ghi lỗi và lý do; có thể rỗng
selected-users.json   # Danh sách user của mẫu
manifest.json         # Checksum nguồn/output, cấu hình, counts và kết quả đối soát
```

Chạy lại đúng lệnh sẽ xác minh output và báo `Already ingested`; không tạo batch mới. Thay số user hoặc nội dung file tạo batch khác, có thể chồng lặp. Đọc một batch cụ thể, không cộng tất cả batch làm một bảng đích duy nhất. Xem giới hạn trong contract.

Tạo preview khi cần kiểm tra nhanh với nguồn nhỏ:

```sh
.venv/bin/python src/pipelines/inspect_rees46_dataset.py sample --rows 1000 --output data/REES46/2019-Oct.preview-1000.csv
.venv/bin/python src/pipelines/ingest_rees46_batch.py --source data/REES46/2019-Oct.preview-1000.csv --users 5 --output-root data/preview-batches
```

Lệnh trên chỉ giữ toàn bộ lịch sử trong file preview, không phải lịch sử toàn tháng.

## 2. Kiểm thử

Python: lỗi timestamp, price, loại sự kiện; giữ dòng giống nhau; lấy đủ lịch sử user; kiểm tra idempotency và phát hiện output bị sửa:

```sh
.venv/bin/python -m unittest discover -s src/pipelines/tests -v
```

## 3. Tiếp theo

1. Đã kiểm chứng mẫu 100.000 user, partition và funnel; chưa cần chạy toàn tháng.
2. Hoàn thiện kiểm thử tiến hóa schema, replay và khôi phục.
3. Bổ sung PostgreSQL nghiệp vụ, generator và CDC theo contract riêng.
4. Phát triển Gold nghiệp vụ, API tra cứu và giao diện Customer 360 khi có đủ nguồn.

Không cần crawl hoặc tải thêm dataset để hoàn thành mốc batch hiện tại.

## Khảo sát REES46 dung lượng lớn

### Xem vài dòng

```sh
.venv/bin/python src/pipelines/inspect_rees46_dataset.py sample --rows 1000
```

Mở `data/REES46/preview.csv` trong IDE. Đây là 1.000 dòng đầu để xem cấu trúc, không đại diện cho toàn bộ tháng và không đảm bảo giữ trọn phiên.

### Khảo sát nhanh 100.000 dòng đầu

```sh
.venv/bin/python src/pipelines/inspect_rees46_dataset.py profile --limit 100000
```

Báo cáo lưu ở `data/reports/rees46-first-100000.json`: schema, số dòng đã đọc, khoảng thời gian, phân bố sự kiện, tỷ lệ thiếu, giá bất thường và số người dùng/phiên/sản phẩm xấp xỉ. Không suy rộng tỷ lệ của phần đầu file thành tỷ lệ toàn bộ dataset.

### Kiểm tra toàn bộ tháng

```sh
.venv/bin/python src/pipelines/inspect_rees46_dataset.py profile --full
```

Báo cáo lưu ở `data/reports/rees46-full.json`. Job phải quét file và có thể quét lại cho thống kê loại sự kiện; thời gian phụ thuộc ổ đĩa và CPU. Script không giữ toàn bộ dữ liệu trong một dataframe Python, không chủ động bỏ qua dòng lỗi và không sửa file nguồn. Lỗi CSV làm job thất bại để điều tra.

Các lệnh không ghi đè output đã có. Để chạy lại, chọn đường dẫn mới, ví dụ:

```sh
.venv/bin/python src/pipelines/inspect_rees46_dataset.py profile --full --output data/reports/rees46-full-run2.json
```

### Truy vấn một người dùng

Tạo script Python nhỏ hoặc chạy đoạn dưới từ thư mục gốc. Thay mã người dùng bằng mã cần tìm:

```python
import duckdb

db = duckdb.connect()
db.execute("SET memory_limit = '512MB'")
db.execute("SET threads = 2")
rows = db.execute(
    """
    SELECT event_time, event_type, product_id, brand, price, user_session
    FROM read_csv('data/REES46/2019-Oct.csv', header=true, all_varchar=true)
    WHERE user_id = ?
    ORDER BY event_time
    LIMIT 100
    """,
    ["541312140"],
).fetchall()
for row in rows:
    print(row)
db.close()
```

Query vẫn có thể quét toàn bộ CSV dù kết quả chỉ có 100 dòng. Khi truy vấn lặp lại nhiều, bước tiếp theo là chuyển dữ liệu sang Parquet hoặc bảng Iceberg; CSV nguyên bản giữ ở landing để replay. Không chia file tùy ý rồi coi mỗi phần là một tập phiên đầy đủ.

### Giới hạn của profiling

- Số lượng distinct là ước lượng, không dùng làm đáp án đối soát chính xác.
- Chưa kiểm tra bản ghi trùng, thứ tự trong phiên hoặc tính đúng của liên kết danh tính.
- Thiếu brand/category_code không mặc nhiên là dữ liệu vô dụng; đánh giá theo mục đích sử dụng.
- Sự kiện purchase không mặc nhiên là đơn hàng đầy đủ hoặc doanh thu thực thu.
- SHA-256 cần chạy riêng nếu muốn kiểm tra file thay đổi; trên macOS dùng `shasum -a 256 data/REES46/2019-Oct.csv`. File giải nén và file nén có checksum khác nhau.

Chỉ sau khi đọc báo cáo full mới chốt quy tắc Silver và số liệu dataset trong báo cáo tốt nghiệp.

## Phiên bản và dependency

| Thành phần | Phiên bản | Vai trò |
| --- | --- | --- |
| DuckDB | 1.5.6 | Profiling và batch Parquet |
| Python của môi trường hiện tại | 3.14 | `.venv` local |

Python dependency trong `src/pipelines/requirements.txt`; stack Spark/Iceberg/PostgreSQL/S3 được ghim trong cấu hình Lakehouse.

Kiểm thử đã thực hiện: ingestion fixture lỗi/rerun/corruption, funnel có đáp án chuẩn và ingestion mẫu toàn lịch sử tháng của 100, 1.000, 10.000 và 100.000 user. Stack batch và cách chạy nằm trong [hướng dẫn Lakehouse](development-guide.md#lakehouse-local). Kafka/Debezium chưa triển khai. Không suy ra phiên bản production tương thích từ mốc này.

## Data contract REES46

Namespace `rees46.marketplace`. `view` → `product_view`, `cart` → `add_to_cart`,
`purchase` → `purchase_observed`; không coi purchase là đơn đã xác nhận.
Timestamp UTC, giá decimal(18,2), currency và verified_customer_id luôn NULL.
Timestamp lỗi, loại sự kiện không hỗ trợ, thiếu product/user hoặc giá sai/âm vào
quarantine. Giá 0, thiếu brand/category_code/session được giữ và gắn cờ.
Event ID dựa trên namespace + checksum file + ordinal bản ghi CSV; hai payload
bằng nhau không tự bị loại. `--all` giữ mọi dòng, cả thiếu user; selected_users
là NULL và selected-users.json rỗng. Batch mẫu có thể chồng lặp; luôn lọc batch.

Funnel grain batch/namespace/user/session. View → cart → purchase yêu cầu thời
gian tăng nghiêm ngặt; không dùng ordinal để suy ra thứ tự khi timestamp hòa.
Thiếu session bị loại khỏi funnel và báo số lượng. Mỗi bước đếm phiên một lần.

## Lakehouse local

Stack: Spark 3.5.8, Iceberg 1.11.0, Java 17, PostgreSQL 16.10/JDBC 42.7.8,
SeaweedFS 4.17, DuckDB 1.5.6. S3 là local, bucket cdp, warehouse
`s3://cdp/warehouse`; dữ liệu/meta Iceberg lưu ở Docker named volume.
CSV, batch Parquet và report vẫn trên host, không tự upload CSV lên S3.

Cấu hình cho batch lớn: Spark local[4], heap driver 3g, 32 shuffle partitions,
AQE bật, input split 64 MiB và spill vào `data/spark-temp`. SeaweedFS giới hạn
volume 256 MB, tự tính số volume tối đa theo disk. Disk và JVM/Python memory
phải được đo riêng; heap 3g không phải giới hạn RSS toàn container.

Partition giữ batch_id; Silver/quarantine thêm days(event_at), Gold daily thêm
days(event_date). Bronze giữ batch vì event_time nguồn là text có thể lỗi.
Writer tiến hóa partition spec một lần, không xóa hoặc viết lại batch cũ.
Các file cũ và mới cùng đọc được. Target data file 64 MiB, không đảm bảo mọi file
đạt kích thước đó. Một writer, overwrite phần batch trong từng bảng, không có
transaction đa bảng. Chờ report pass trước khi dùng kết quả.

```sh
sh src/tools/run_local_lakehouse.sh data/local-batches/rees46/<batch-id>
.venv/bin/python src/tools/benchmark_lakehouse.py --batch data/local-batches/rees46/<batch-id>
docker compose -f config/docker/compose.local-lakehouse.yml run --rm spark /workspace/src/pipelines/lakehouse/tests/integration.py
```

Benchmark runner lưu log và memory report dưới `data/reports/lakehouse`.
Script run và benchmark là hai cách chạy cùng job; không chạy đồng thời.

Xuất CSV (đọc Gold, không tính lại từ CSV nguồn):

```sh
docker compose -f config/docker/compose.local-lakehouse.yml run --rm spark /workspace/src/pipelines/lakehouse/export_gold.py --batch-id <batch-id>
```

Các bảng: cdp.bronze.rees46_events, cdp.silver.rees46_events,
cdp.silver.rees46_quarantine, cdp.gold.rees46_daily_events,
cdp.gold.rees46_user_behavior, cdp.gold.rees46_session_funnel.
CSV export lưu ở `data/reports/gold/<batch-id>/`. Dừng bằng Compose down, không
thêm -v nếu muốn giữ catalog/S3. Snapshot cũ không được expire tự động; đợt dọn thủ công đã được ghi ở phần dữ liệu đang giữ.

## Benchmark

Job report gồm counts, funnel, input bytes, runtime, elapsed_seconds và file
bytes hiện hành của từng batch từ metadata Iceberg. Không gồm metadata/snapshot
cũ hoặc disk spill. Job duration gồm đối soát, không gồm build/pull/startup.
Memory runner đọc /proc khoảng mỗi 2 giây: RSS Java và Python; có thể bỏ lỡ peak
cuối, RSS Python nhiều tiến trình có thể tính trùng shared pages; không đo RAM
storage/catalog. Đây chưa phải cold/warm benchmark vì không kiểm soát cache.

Mẫu trước đổi cấu hình: 10.000 user, 435.937 Silver, 93 daily, 10.000 user Gold,
87.230 session funnel. Ingestion 36,957 giây; job 41,489 giây; Java RSS quan sát
1,56 GiB. Không so thời gian các mẫu như cùng cấu hình sau khi thay đổi tài nguyên.

Tài liệu partition: [Iceberg Spark DDL](https://iceberg.apache.org/docs/1.11.0/spark-ddl/).

### Kết quả batch 100.000 user

Đã chạy thành công 3.551.431 Bronze = 3.551.431 Silver + 0 quarantine.
Gold: 93 dòng daily, 100.000 user, 711.942 phiên. View 3.402.193, cart 75.473,
purchase_observed 73.765 sự kiện. Giữ toàn bộ lịch sử tháng 10/2019 của 100.000
user đầu tiên; đây không phải mẫu ngẫu nhiên.

Adapter mất 90,407 giây; Lakehouse gồm đối soát mất 229,719 giây. Java RSS cao
nhất quan sát 3,75 GiB; không gồm Python, catalog và storage. Cấu hình local[4],
heap 3g, shuffle 32. Phép đo này trước tối ưu đối soát theo khóa và cache DISK_ONLY.

Báo cáo: `data/reports/lakehouse/benchmark-100000.json`. CSV Gold tại
`data/reports/gold/b451baabfcfce093d6fdd117269d3daaff0e55ef435d6c4a84876f3a71c7a168/`.
Chưa chạy toàn tháng vào Iceberg; đã dừng chuẩn bị toàn tháng theo yêu cầu.

### Dữ liệu đang giữ sau khi dọn

Giữ CSV gốc `data/REES46/2019-Oct.csv`, báo cáo khảo sát nguồn
`data/reports/rees46-full.json`, batch Parquet và Gold/export/report của 100.000
user. Báo cáo khảo sát toàn nguồn chỉ là profiling, không phải kết quả pipeline
toàn tháng. Đã xóa batch/report/export 100, 1.000, 10.000 user, preview CSV và
báo cáo khảo sát 100.000 dòng đầu. Các lệnh preview/profile phía trên là hướng
dẫn tạo lại khi cần; những file đó hiện không được giữ.

Đã dọn cả Iceberg/S3 local bằng `src/pipelines/lakehouse/prune_batches.py`: xóa đúng
ba batch cũ, kiểm số dòng và danh sách file của batch giữ lại, sau đó gọi
`expire_snapshots` giữ snapshot hiện hành. Cả sáu bảng hiện chỉ có kết quả
100.000 user (quarantine rỗng); mỗi bảng còn một snapshot. Đã xóa 235 data file,
386 manifest file và 312 manifest list không còn được tham chiếu bởi snapshot
giữ lại. Báo cáo: `data/reports/lakehouse/cleanup-9200eb092f544403960c0c9c5848c5e1.json`.
Không còn time travel tới các snapshot đã expire. CSV gốc và batch 100.000 user
vẫn giữ để replay.

Script maintenance nhận các `--batch-id` cần xóa và `--keep-report` là báo cáo
benchmark pass của batch cần giữ. Chỉ chạy khi không có writer khác hoặc reader
cần snapshot lịch sử; script giữ một snapshot hiện hành cho mỗi bảng.
Tham chiếu: [Iceberg expire_snapshots](https://iceberg.apache.org/docs/1.11.0/spark-procedures/#expire_snapshots).

### Báo cáo tối giản

`data/reports/` hiện giữ báo cáo khảo sát nguồn `rees46-full.json`, báo cáo tổng
hợp `lakehouse/benchmark-100000.json`, báo cáo dọn Iceberg và ba CSV Gold của
100.000 user. Báo cáo benchmark đã gộp kết quả đối soát job và số liệu RAM; log,
báo cáo job riêng và chuỗi mẫu RAM chi tiết đã xóa.

Năm file trong batch 100.000 user đều thuộc manifest/checksum và được giữ để
chạy lại: Bronze, Silver, quarantine Parquet, selected-users.json, manifest.json.
Quarantine rỗng vẫn cần để job đối soát; không xóa riêng file trong batch.
`.gitignore` dùng `/data/` chỉ bỏ qua dữ liệu ở root, không bỏ qua code `src/pipelines/`.

## Demo website

A synthetic e-commerce demo that generates typed behavioral events for the CDP pipeline.
The demo implements **4 user personas** with distinct event signatures:

| Persona | Description | Event signature |
|---|---|---|
| **Lina** (Window Shopper) | Browses many products, no purchase | `product_view` × N, `scroll_depth` |
| **Minh** (Decisive Buyer) | 1-2 products, fast checkout | Full funnel → `purchase_observed` |
| **Hoa** (Researcher) | Search-heavy, no purchase | `search`, `product_view` × N, `wishlist_add` |
| **Quang** (Cart Abandoner) | Adds many items, abandons | `add_to_cart` × N, `cart_abandoned` |

New event types: `cart_abandoned`, `apply_filter`, `wishlist_add`, `wishlist_remove`, `newsletter_signup`.

Quick-reference commands (from repo root, with `.venv` active):

```sh
# Install deps
pip install -r src/demo/requirements.txt

# Start API
python -m src.demo.api.server

# Start web (in a second terminal)
cd src/demo/web && python -m http.server 8081

# Run bot smoke test (mixed personas: 40% lina, 25% minh, 20% hoa, 15% quang)
python -m src.demo.bot.driver --users 5

# Run bot with specific persona
python -m src.demo.bot.driver --users 10 --profile lina
python -m src.demo.bot.driver --users 10 --profile minh
python -m src.demo.bot.driver --users 10 --profile hoa
python -m src.demo.bot.driver --users 10 --profile quang

# Run API tests
python -m pytest src/demo/api/tests -q
```

See [`src/demo/README.md`](src/demo/README.md) for full documentation including:
- Architecture diagram (web → API → lakehouse)
- Persona task flows
- Event taxonomy table (16 event types)
- Dashboard interpretation guide
