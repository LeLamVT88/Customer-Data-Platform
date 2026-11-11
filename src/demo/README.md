# CDP Demo — nguồn Kafka và nghiệp vụ

Luồng hiện hành: Browser/TP2 → Collector → Kafka raw → Enrich/Iglu → good/bad,
và FastAPI/PostgreSQL → Debezium → CDC theo bảng. Website có tài khoản và đơn hàng.

Xem [hướng dẫn vận hành và nghiệm thu](../../docs/operations.md).
Các lệnh dưới đây chạy từ root project:

```sh
.venv/bin/python -m src.demo.sources.runtime up
.venv/bin/python -m src.demo.sources.verify --restart-kafka
```

Website: http://127.0.0.1:8081/. Dừng và giữ dữ liệu:

```sh
.venv/bin/python -m src.demo.sources.runtime down
```

## Tổ chức mã nguồn

| Đường dẫn | Trách nhiệm |
| --- | --- |
| `api/server.py` | Khởi tạo FastAPI, CORS, lifecycle và HTTP endpoints |
| `api/business.py` | Xác thực, catalog PostgreSQL, đơn hàng và quy tắc nghiệp vụ |
| `catalog.py` | Catalog JSON dùng chung cho API seed, runtime và bot |
| `api/dashboard.py` | Truy vấn số liệu observer Kafka hoặc storage Micro cũ |
| `api/tests/test_tracking_contracts.py` | Kiểm tra Iglu, TP2 và cấu trúc payload tracking |
| `api/tests/test_api_database.py` | Hồi quy API/truy vấn trên PostgreSQL thật |
| `sources/runtime.py` | Khởi chạy và dừng stack local |
| `sources/generate.py` | Hành trình có liên kết hành vi–khách hàng–đơn hàng |
| `sources/observer.py` | Giữ raw transport và chiếu dữ liệu cho dashboard |
| `sources/verify.py` | Nghiệm thu nguồn Kafka/CDC |
| `web/` | Website và browser tracking |
| `bot/` | Bot tracking cũ; không thay thế generator nghiệp vụ |
| `../pipelines/snowplow_micro/` | Job Micro cũ: `ingest.py` nạp dữ liệu, `show_tables.py` hiển thị thống kê; chưa xử lý Kafka/CDC |

## Bot tracking tùy chọn

Bot chỉ gửi event TP2; generator `sources/generate.py` mới tạo tài khoản, đơn
hàng và bằng chứng danh tính qua API. Chạy stack mặc định bằng `runtime up`, rồi:

```sh
.venv/bin/python -m src.demo.bot.driver --users 5
.venv/bin/python -m src.demo.bot.driver --users 200 --rate 5000 --seed 42
.venv/bin/python -m src.demo.bot.driver --users 5 --profile minh
```

Các cờ: `--users` (200), `--rate` (5.000 event/phút mục tiêu), `--seed` (42),
`--workers` (tối đa 50 mặc định), `--profile`, `--collector`.
Profile mặc định được lấy mẫu theo trọng số Lina/Minh/Hoa/Quang = 40/25/20/15;
seed cố định tái lập việc chọn profile, không cam kết timestamp/UUID giống nhau.
Các alias `visitor`, `cart_abandoner`, `buyer` vẫn được giữ.

Collector mặc định là `http://127.0.0.1:9091`, có thể đổi qua `--collector` hoặc
`SNOWPLOW_COLLECTOR_URL`. Muốn dùng Micro cũ, khởi chạy
`config/docker/compose.snowplow.yml` và truyền `--collector http://127.0.0.1:9090`.
Metadata mỗi lần bot chạy nằm ở `data/demo-events/`; đây là output có thể dọn.
HTTP accepted chưa chứng minh event đã qua Enrich; dùng observer để đối soát.

## Kiểm thử

Test offline không cần Docker/PostgreSQL (test database tự skip):

```sh
.venv/bin/python -m unittest discover -s src/demo/api/tests -v
.venv/bin/python -m unittest discover -s src/pipelines/tests -v
```

Để chạy cả test database, đặt `CDP_TEST_POSTGRES_DSN` trỏ tới PostgreSQL test.
Tài khoản phải có quyền tạo database. Bộ test tự tạo database riêng với tên
ngẫu nhiên và xóa sau khi chạy; không thay đổi database có sẵn.
Ví dụ với PostgreSQL test cài local:

```sh
CDP_TEST_POSTGRES_DSN='host=127.0.0.1 port=5432 dbname=postgres' \
  .venv/bin/python -m unittest discover -s src/demo/api/tests -v
```

Dashboard dùng SQL để đếm distinct user/session, đọc payload qua server-side
cursor theo từng nhóm 1.000 dòng và lấy các chỉ số trong cùng snapshot read-only.
Danh sách đơn hàng lấy chi tiết của toàn bộ đơn bằng một truy vấn.
Các endpoint dùng psycopg đồng bộ chạy trong thread pool của FastAPI.

Lệnh vận hành và chính sách giữ dữ liệu nằm trong
[hướng dẫn chung](../../docs/operations.md). Job Micro cũ được giữ trong code
để tham chiếu; nhánh mặc định hiện tại dùng Kafka/CDC.
