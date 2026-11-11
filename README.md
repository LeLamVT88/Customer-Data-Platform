# Customer Data Platform

Dự án local gồm hai nhánh: batch REES46 → Iceberg Bronze/Silver/Gold và nguồn
website/hành vi/nghiệp vụ → Snowplow/Kafka + PostgreSQL/Debezium.

- [Kiến trúc và tiến độ](docs/project-plan.md)
- [Vận hành, kiểm thử và dữ liệu kiểm chứng](docs/operations.md)
- [Cấu trúc code demo](src/demo/README.md)

Cấu trúc mã nguồn:

| Thư mục | Nội dung |
| --- | --- |
| `src/demo/` | Website, API, nguồn Kafka/CDC, bot tracking và catalog seed chung |
| `src/pipelines/` | Pipeline REES46 và job Micro cũ trong `snowplow_micro/` |
| `src/tools/` | Script vận hành và benchmark Lakehouse |

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
