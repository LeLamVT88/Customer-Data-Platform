# Vận hành local và dữ liệu kiểm chứng

Tất cả lệnh chạy từ root project. Xem [project-plan.md](project-plan.md) cho
kiến trúc, quy tắc REES46 và tiến độ; [README demo](../src/demo/README.md) cho
cấu trúc code. Báo cáo [Snowplow DOCX](snowplow-theory-and-cdp-application-report.docx)
là tài liệu lý thuyết và kiến trúc lịch sử; lệnh vận hành hiện hành nằm ở đây.

## Nguồn website, Kafka và CDC

```text
Browser/TP2 → Collector :9091 → Kafka raw → Enrich/Iglu → good/bad/failed
Website/generator → FastAPI :8000 → PostgreSQL :15433 → Debezium :8083 → Kafka CDC
Kafka → observer PostgreSQL → /api/summary → dashboard :8081
```

Cần Docker Compose v2, Python 3.11+ và Docker đang chạy:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r src/demo/requirements.txt
.venv/bin/python -m src.demo.sources.runtime up
.venv/bin/python -m src.demo.sources.runtime status
```

Website: http://127.0.0.1:8081/; API: http://127.0.0.1:8000/docs.
Có thể dùng `localhost`, nhưng giữ cùng hostname trong một phiên để cookie
đăng nhập nhất quán. Broker host: `127.0.0.1:19092`.

Đăng ký → đăng nhập → chọn sản phẩm → tạo đơn → Tài khoản để mô phỏng thanh toán,
hủy hoặc hoàn tiền. Giá catalog và đơn lấy từ database. `up` tạo topic, seed
catalog, đăng ký connector và chạy API/observer/web. Log/PID ở `.cache/sources/`.
Không chạy đồng thời stack Micro cũ trên cùng cổng API/web.

```sh
.venv/bin/python -m src.demo.sources.generate --users 4 --seed 42
.venv/bin/python -m src.demo.sources.verify --restart-kafka
.venv/bin/python -m src.demo.sources.runtime down
```

`down` giữ volume. Kafka và PostgreSQL nằm trong Docker volumes, không nằm trong
`data/`; không dùng `down -v` nếu cần giữ dữ liệu.

### Hợp đồng dữ liệu

| Trường / quy tắc | Ý nghĩa |
| --- | --- |
| `anonymous_id` | Định danh trình duyệt/bot, chưa phải danh tính xác thực |
| `session_id` | UUID phiên, entity `com.cdp.demo/session` |
| `customer_id` | UUID do API cấp; tracking `user_id` chỉ có sau xác thực |
| `identity_links` | Nối anonymous/session/customer bằng bằng chứng `authenticated_login` |
| `run_id` | Gom dữ liệu một lần chạy; không dùng làm danh tính khách hàng |
| `event_id` | UUID tracking; payload giống nhau không tự coi là trùng |
| `order_id` | ID đơn từ API; checkout/purchase schema `1-0-1` |
| Tiền | Decimal hai chữ số, giá từ DB, một currency mỗi đơn |
| Thời gian | UTC; phân biệt event time, ingestion time và Kafka observation |
| Trạng thái đơn | `CREATED → PAID → REFUNDED` hoặc `CREATED → CANCELLED` |
| Idempotency | Key theo khách hàng; cùng nội dung trả đơn cũ, khác nội dung trả 409 |

Không ghép ID REES46 với khách demo nếu thiếu bằng chứng xác thực.
`purchase_observed` không tự trở thành doanh thu. Thanh toán là mô phỏng demo.
CDC gồm `customers`, `products`, `orders`, `order_items`, `identity_links`;
loại `password_hash` và bảng `auth_sessions`. PostgreSQL dùng
`REPLICA IDENTITY FULL` để giữ before image.

Topic hành vi: `cdp.web.raw`, `cdp.web.good`, `cdp.web.bad`,
`cdp.web.collector_bad`, `cdp.web.failed`. Good là enriched TSV, raw giữ bytes;
CDC JSON ở `cdp.business.public.<table>`, có `op=r/c/u/d`, before/after/source
và tombstone null. Topic heartbeat phải tồn tại vì auto-create bị tắt.
Các topic Connect giữ config/offset/status; topic `cdp.snapshot.public.products`
dùng cho nghiệm thu snapshot độc lập. Cấu hình ở
[create-topics.sh](../config/kafka/create-topics.sh) và
[business-connector.json](../config/kafka/business-connector.json).

Topic dữ liệu có 3 partition, replication factor 1, retention 7 ngày.
Ordering chỉ trong từng partition; đây là stack local một broker, chưa có HA.
Observer ghi raw transport trước khi commit Kafka offset; khóa
(topic, partition, offset) chống lặp khi đọc lại. Projection dashboard chưa phải
Bronze/Silver Lakehouse; chưa có bảo đảm exactly-once đầu cuối.

### Nghiệm thu nguồn

Bộ bằng chứng giữ lại là lần chạy đầy đủ ngày 09/11/2026, **24 kiểm tra PASS**:
[acceptance.json](../data/source-runs/acceptance-19813b36-14d4-45e5-8860-8dc04333c03f/acceptance.json),
[ground-truth.json](../data/source-runs/acceptance-19813b36-14d4-45e5-8860-8dc04333c03f/ground-truth.json),
[bad-event.json](../data/source-runs/acceptance-19813b36-14d4-45e5-8860-8dc04333c03f/bad-event.json).

Đã đối soát snapshot đủ 250 sản phẩm, 16 good event của 4 persona, một đơn PAID,
order items và identity link. Có kiểm tra auth, retry đồng thời, xung đột key,
chuyển trạng thái sai, WAL insert/update/delete, before image, tombstone,
bad row giữ payload/lý do, đọc lại bytes sau restart Kafka và pipeline phục hồi.
Đây là bằng chứng lịch sử, không thay thế việc chạy lại sau thay đổi code.
Verifier tạo run riêng, không reset offset/slot CDC chính; ground truth không
được dùng làm đầu vào tính dashboard.

Chẩn đoán:

```sh
docker compose -f config/docker/compose.sources.yml logs --tail 80 enrich connect
curl http://127.0.0.1:8083/connectors/cdp-business/status
```

Task RUNNING và Collector HTTP 2xx chưa chứng minh event vào good; dùng verifier.
Lần chạy đầu cần mạng tới Iglu Central. Sửa schema demo thì restart Enrich để
tránh cache cũ. Muốn replay observer: dừng observer cũ, chạy với consumer group
mới qua `CDP_OBSERVER_GROUP`; chỉ replay được record còn trong retention.

## Khảo sát REES46 và chuẩn bị Lakehouse chung

Lakehouse cũ đã được gỡ ngày 12/11/2026 để xây lại một hệ thống chung cho
REES46 và nguồn website/Kafka/CDC. Hiện chưa có lệnh khởi chạy Lakehouse mới.
Không còn các job Spark/Iceberg hoặc batch Bronze/Silver/Gold cũ.

Các tài nguyên đã xóa: stack Docker `cdp-lakehouse`, hai volume
`cdp-lakehouse_catalog-data`, `cdp-lakehouse_storage-data`, image riêng
`cdp-lakehouse-spark:latest`, code/config Lakehouse, batch REES46 và các thư mục
report Gold/benchmark. Không chạy lệnh prune toàn Docker; volume nguồn Kafka
và PostgreSQL nghiệp vụ được giữ.

### Khảo sát REES46 dung lượng lớn

Nguồn local `data/REES46/2019-Oct.csv`: 5.668.612.855 byte, 42.448.764 sự kiện.
Báo cáo [rees46-full.json](../data/reports/rees46-full.json) được giữ vì mô tả
nguồn CSV, không phải kết quả Lakehouse. Distinct trong profiling là ước lượng.
Nguồn/ngày tải và điều kiện sử dụng bản tải chưa xác minh.

```sh
.venv/bin/python -m pip install -r src/pipelines/requirements.txt
.venv/bin/python src/pipelines/inspect_rees46_dataset.py --help
# Chỉ xuất prefix để xem, không phải mẫu đại diện hoặc đủ lịch sử mỗi user.
.venv/bin/python src/pipelines/inspect_rees46_dataset.py sample --rows 1000
# Chỉ chạy nếu cần khảo sát lại toàn file, dùng output mới.
.venv/bin/python src/pipelines/inspect_rees46_dataset.py profile --full --output data/reports/rees46-full-new.json
```

Xem [thiết kế và lộ trình Lakehouse chung](project-plan.md). Dữ liệu REES46
và website sẽ cùng hạ tầng nhưng giữ namespace và danh tính nguồn độc lập.

## Cấu hình được giữ

| Đường dẫn trong `config/` | Vai trò |
| --- | --- |
| `docker/compose.sources.yml` | Stack Kafka/CDC mặc định |
| `docker/compose.snowplow.yml` | Nhánh Micro cũ còn được bot và job demo sử dụng |
| `business/init.sql`, `kafka/` | Schema nghiệp vụ, topic và connector CDC |
| `snowplow/collector.kafka.hocon`, `enrich.kafka.hocon`, `iglu.kafka.json` | Collector/Enrich và resolver HTTP cho Kafka |
| `snowplow/micro.conf`, `storage.conf`, `iglu.json` | Cấu hình Micro và resolver embedded; khác nhánh Kafka |
| `snowplow/iglu-client-embedded/schemas/` | Nguồn schema Iglu hiện hành, dùng chung hai nhánh |
| `snowplow/enrichments/.gitkeep` | Giữ thư mục rỗng được mount vào Enrich; không xóa |
| `demo/catalog.products.json` | Catalog seed synthetic cho API và generator |

Catalog có 250 sản phẩm, giá chuỗi decimal theo USD. Đây là dữ liệu demo độc
lập với REES46; không suy ra nguồn gốc hoặc liên kết danh tính từ mã sản phẩm.
Seed chỉ thêm sản phẩm chưa có, không ghi đè giá đã sửa trong PostgreSQL.

Các schema có URI theo vendor/name/format/version. Giữ các bản `1-0-0` để tương
thích tracking cũ; checkout/purchase có `order_id` dùng `1-0-1`. Schema
`identity_authenticated` và entity `source` phục vụ liên kết danh tính/run.
Schema JSON trong repository là nguồn cấu hình chính; generator cũ chỉ tạo một
phần schema và đã được loại bỏ để tránh xóa các phiên bản hiện hành. Khi thêm
schema, giữ các phiên bản đã phát hành và restart Enrich để nạp cấu hình mới.

## Kiểm thử

Lệnh unit test và PostgreSQL test nằm trong [README demo](../src/demo/README.md#kiểm-thử).
Các kiểm thử Lakehouse cũ đã gỡ cùng implementation; sẽ bổ sung bộ kiểm thử
cho hai nguồn khi xây Lakehouse chung.

## Cache và môi trường Python

`.cache/`, `.venv/` và `__pycache__/` là dữ liệu có thể tạo lại, không commit Git.
Chỉ dọn sau khi dừng các tiến trình dự án. Xóa `.venv/` thì cần cài lại dependency
trước lần chạy tiếp theo; runtime tự tạo lại `.cache/sources/` khi khởi chạy.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r src/demo/requirements.txt -r src/pipelines/requirements.txt
```

## Quy tắc giữ dữ liệu

| Nội dung | Chính sách |
| --- | --- |
| CSV REES46 gốc | Giữ để replay và truy vết |
| Profiling REES46 | Giữ báo cáo khảo sát nguồn CSV |
| Source acceptance | Giữ một run PASS đầy đủ nhất, gồm ground truth và bad row |
| Run lỗi, run bị thay thế, bot metadata, thư mục rỗng, `.DS_Store` | Có thể dọn sau khi xác nhận không còn được tham chiếu |
| Sơ đồ kiến trúc | Giữ PNG để xem/chèn báo cáo; Mermaid trong project-plan.md mô tả thiết kế mới |

`data/` bị Git ignore: các liên kết tới artifact local chỉ có trên máy giữ dữ
liệu; máy khác cần có nguồn REES46 hoặc chạy verifier để tạo bằng chứng mới.
Tài liệu và báo cáo DOCX nằm trong `docs/`; log/PID runtime nằm ở `.cache/`.
