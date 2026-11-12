# Customer Data Platform

Dự án chuẩn bị hai nguồn cho một Lakehouse chung: dữ liệu lịch sử REES46 và
website demo (hành vi Snowplow/Kafka cùng nghiệp vụ PostgreSQL/Debezium).
Lakehouse REES46 cũ đã được gỡ ngày 12/11/2026; Lakehouse chung chưa triển khai.

- [Kiến trúc và tiến độ](docs/project-plan.md)
- [Vận hành, kiểm thử và dữ liệu kiểm chứng](docs/operations.md)
- [Cấu trúc code demo](src/demo/README.md)

Cấu trúc mã nguồn:

| Thư mục | Nội dung |
| --- | --- |
| `src/demo/` | Website, API, nguồn Kafka/CDC, bot tracking và catalog seed chung |
| `src/pipelines/` | Công cụ khảo sát CSV REES46; chưa có pipeline Lakehouse |

Khởi chạy nguồn demo từ root, sau khi cài Docker và Python dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r src/demo/requirements.txt
.venv/bin/python -m src.demo.sources.runtime up
.venv/bin/python -m src.demo.sources.verify --restart-kafka
```

Website: http://127.0.0.1:8081/. Dừng và giữ dữ liệu:

```sh
.venv/bin/python -m src.demo.sources.runtime down
```
