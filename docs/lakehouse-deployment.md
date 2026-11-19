# Triển khai Lakehouse chung (Apache Iceberg)

Hướng dẫn dựng Lakehouse chung cho REES46 + Website nguồn theo
[contract](lakehouse-contract.md). Tài liệu này chỉ dạy **cách triển khai**;
thiết kế dữ liệu nằm ở contract.

> **Trạng thái:** chưa triển khai. Stack cũ (`cdp-lakehouse`) đã bị gỡ ngày
> 12/11/2026 cùng code Spark/Iceberg, batch REES46 và benchmark. Tài liệu này
> dựng lại từ đầu, dựa trên bản cũ đã chạy thật.

---

## 0. Kiến trúc stack

```text
                    ┌──────────────────┐
                    │  catalog         │  PostgreSQL 16
                    │  (JDBC catalog)  │  ← metadata Iceberg (vài KB)
                    │  :5432           │
                    └────────┬─────────┘
                             │ đọc/ghi metadata
                    ┌────────▼─────────┐
                    │  spark           │  Spark 3.5.8 + Iceberg 1.11
                    │  (job PySpark)   │  Java 17
                    └────────┬─────────┘
                             │ đọc/ghi file Parquet
                    ┌────────▼─────────┐
                    │  storage         │  MinIO (S3-compatible)
                    │  :9000           │  ← dữ liệu thật
                    └──────────────────┘
```

**Điểm cần nhớ:** catalog ≠ dữ liệu.
- `catalog` (PostgreSQL) chỉ chứa *metadata*: schema, partition spec, snapshot, manifest.
- `storage` (MinIO) chứa *file dữ liệu* Parquet.
- Mất catalog → mất schema nhưng **không** mất dữ liệu thô.

**Tại sao chọn JDBC catalog thay vì REST catalog:** local 1 engine, đơn giản
nhất, không cần thêm service. Khi lên multi-engine thì chuyển sang REST
catalog (Polaris/Lakekeeper) — chỉ đổi 3 dòng config, dữ liệu không đổi.

**Tại sao chọn MinIO thay vì SeaweedFS:** bản cũ dùng SeaweedFS, chạy được
nhưng cấu hình S3 phức tạp và ít tài liệu. MinIO là lựa chọn mặc định phổ
biến, cũng chính là `minio/minio` mà nhiều tài liệu Iceberg dùng.

---

## Bước 1 — Chuẩn bị môi trường

### 1.1 Bật Docker Desktop

```powershell
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
```

Đợi đến khi `docker version` trả về server version (không phải lỗi):

```powershell
docker version --format "{{.Server.Version}}"
```

> **Hiện tại Docker Desktop chưa chạy.** Đây là điều kiện tiên quyết cho
> toàn bộ các bước sau.

### 1.2 Kiểm tra tài nguyên

```powershell
Get-PSDrive C | Select-Object @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}
```

| Tài nguyên | Tối thiểu | Khuyến nghị | Ghi chú |
|---|---|---|---|
| Disk trống | 20 GB | **40 GB+** | REES46 CSV 5,6 GB + bản Parquet ~2-3 GB + Spark overhead |
| RAM | 8 GB | 12 GB+ | Spark driver 3 GB + JVM + Postgres + MinIO |
| Docker Desktop RAM | 6 GB | 8 GB | Settings → Resources |

> Máy hiện có: **150 GB trống**, **15,2 GB RAM** → đủ.

### 1.3 Python

Contract yêu cầu Python 3.11+:

```powershell
py -3.13 --version
python3 --version
```

`.venv` hiện tại là **Python 3.10.0** — có thể giữ, nhưng nếu gặp lỗi type
hinting hoặc `Self` thì nên tạo lại venv bằng 3.13:

```powershell
Remove-Item -Recurse -Force .venv
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r src/demo/requirements.txt -r src/pipelines/requirements.txt
```

---

## Bước 2 — Tạo cấu hình S3 cho storage

Tạo file `config/storage/s3.local.json` — định nghĩa identity và credentials
mà Iceberg/AWS SDK sẽ dùng:

```json
{
  "identities": [
    {
      "name": "cdp-local",
      "credentials": [
        {"accessKey": "cdp-local", "secretKey": "cdp-local-storage"}
      ],
      "actions": ["Admin", "Read", "Write", "List", "Tagging"]
    }
  ]
}
```

> MinIO mặc định không cần file này (dùng `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`).
> File này dùng khi chuyển sang SeaweedFS, hoặc khi cần tool S3 CLI riêng.
> Có thể bỏ qua nếu dùng MinIO.

---

## Bước 3 — Cấu hình Spark cho Iceberg

Tạo `config/spark/lakehouse.conf`. Đây là file quan trọng nhất — nó định nghĩa
3 khái niệm hay bị nhầm:

```properties
# Bật extension Iceberg cho Spark: MERGE INTO, add_files, rewrite_data_files.
spark.sql.extensions org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions

# ── Catalog ───────────────────────────────────────────────────────────────────
spark.sql.catalog.cdp org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.cdp.catalog-impl org.apache.iceberg.jdbc.JdbcCatalog
spark.sql.catalog.cdp.uri jdbc:postgresql://catalog:5432/iceberg
spark.sql.catalog.cdp.jdbc.user cdp
spark.sql.catalog.cdp.jdbc.password cdp-local-catalog
spark.sql.catalog.cdp.warehouse s3://cdp/warehouse

# ── Object storage ────────────────────────────────────────────────────────────
spark.sql.catalog.cdp.io-impl org.apache.iceberg.aws.s3.S3FileIO
spark.sql.catalog.cdp.s3.endpoint http://storage:9000
spark.sql.catalog.cdp.s3.path-style-access true
spark.sql.catalog.cdp.s3.chunked-encoding-enabled false

# ── Behaviour ─────────────────────────────────────────────────────────────────
spark.sql.session.timeZone UTC
spark.sql.ansi.enabled true
spark.sql.shuffle.partitions 32
spark.sql.adaptive.enabled true
spark.sql.ui.enabled false
spark.local.dir /workspace/data/spark-temp
```

**Giải thích từng dòng quan trọng:**

| Dòng | Ý nghĩa | Sai hậu quả nếu bỏ/sai |
|---|---|---|
| `spark.sql.extensions` | Bật extension Iceberg | Không dùng được `MERGE INTO`, `CALL rewrite_data_files` |
| `spark.sql.catalog.cdp` | **Tên catalog** dùng trong SQL (`cdp.bronze.xxx`) | SQL phải viết `spark_catalog.bronze.xxx` |
| `catalog-impl` | Loại catalog thật | `ClassNotFoundException` |
| `uri` | JDBC URL tới PostgreSQL catalog | `Connection refused` tới catalog |
| `warehouse` | Bucket + prefix chứa file Parquet | `NoSuchBucketException` / ghi sai chỗ |
| `io-impl` | Bộ đọc/ghi file S3 | `ClassNotFoundException: S3FileIO` |
| `s3.endpoint` | Endpoint của MinIO | Iceberg cố gọi AWS thật → `UnknownHostException` |
| `path-style-access` | `s3://bucket/key` thay vì `s3://bucket.s3.amazonaws.com/key` | `The specified bucket does not exist` |
| `chunked-encoding-enabled false` | Tắt chunked transfer | `SignatureDoesNotMatch` với S3 server cũ |
| `spark.session.timeZone UTC` | Múi giờ | Lệch ngày giữa Bronze và Gold |
| `spark.local.dir` | Nơi ghi spill/temp | Đầy đĩa container |

---

## Bước 4 — Tạo Dockerfile cho Spark

Tạo `config/docker/lakehouse.Dockerfile`:

```dockerfile
# Spark 3.5.x base image đi kèm Java 11, nhưng Iceberg 1.11 yêu cầu Java 17.
FROM eclipse-temurin:17.0.18_8-jre-jammy AS java_runtime

FROM apache/spark:3.5.8
USER root
COPY --from=java_runtime /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk

# DuckDB để đọc CSV REES46 theo kiểu streaming (không load vào RAM).
RUN pip3 install --no-cache-dir duckdb==1.5.6

# Iceberg runtime + AWS bundle + JDBC driver cho PostgreSQL catalog.
ADD https://repo.maven.apache.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/1.11.0/iceberg-spark-runtime-3.5_2.12-1.11.0.jar /opt/spark/jars/
ADD https://repo.maven.apache.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.11.0/iceberg-aws-bundle-1.11.0.jar /opt/spark/jars/
ADD https://repo.maven.apache.org/maven2/org/postgresql/postgresql/42.7.8/postgresql-42.7.8.jar /opt/spark/jars/
RUN chmod 644 /opt/spark/jars/*.jar

WORKDIR /workspace
```

**Ba jar cần thiết và lý do:**

| Jar | Bắt buộc vì |
|---|---|
| `iceberg-spark-runtime-3.5_2.12` | Engine Iceberg cho Spark 3.5, Scala 2.12 |
| `iceberg-aws-bundle` | `S3FileIO` — đọc/ghi file trên MinIO |
| `postgresql` | JDBC driver để `JdbcCatalog` nói chuyện với PostgreSQL |

> **Sai lầm thường gặp:** dùng `iceberg-spark-runtime-3.5_2.12` với Spark
> build Scala 2.13 → `NoClassDefFoundError`. Kiểm tra bằng:
> ```powershell
> docker run --rm apache/spark:3.5.8 spark-submit --version
> ```
> Nếu in `spark-submit` với `Scala version: 2.12.x` thì đúng.

**Cách build:**
```powershell
docker build -f config/docker/lakehouse.Dockerfile -t cdp-lakehouse-spark:latest .
```

---

## Bước 5 — Tạo Compose file

Tạo `config/docker/compose.lakehouse.yml`:

```yaml
name: cdp-lakehouse

services:
  # ── Catalog: lưu metadata Iceberg (schema, snapshot, manifest) ─────────────
  catalog:
    image: postgres:16.10-bookworm
    environment:
      POSTGRES_DB: iceberg
      POSTGRES_USER: cdp
      POSTGRES_PASSWORD: cdp-local-catalog
    volumes:
      - catalog-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cdp -d iceberg"]
      interval: 3s
      timeout: 5s
      retries: 30

  # ── Storage: object storage S3-compatible, chứa file Parquet ───────────────
  storage:
    image: minio/minio:RELEASE.2025-04-22T22-12-26Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: cdp-local
      MINIO_ROOT_PASSWORD: cdp-local-storage
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9001:9001"
    volumes:
      - storage-data:/data
    healthcheck:
      test: ["CMD-SHELL", "mc ready local || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 30

  # ── Spark: chạy job ingestion ─────────────────────────────────────────────
  spark:
    build:
      context: ../..
      dockerfile: config/docker/lakehouse.Dockerfile
    image: cdp-lakehouse-spark:latest
    user: "0:0"
    entrypoint:
      ["/opt/spark/bin/spark-submit", "--master", "local[4]",
       "--driver-memory", "3g",
       "--properties-file", "/workspace/config/spark/lakehouse.conf"]
    environment:
      AWS_ACCESS_KEY_ID: cdp-local
      AWS_SECRET_ACCESS_KEY: cdp-local-storage
      AWS_REGION: us-east-1
      # Tương thích S3 server local: bỏ checksum trailer tuỳ chọn.
      AWS_REQUEST_CHECKSUM_CALCULATION: WHEN_REQUIRED
      AWS_RESPONSE_CHECKSUM_VALIDATION: WHEN_REQUIRED
      SPARK_LOCAL_IP: 127.0.0.1
      PYSPARK_PYTHON: python3
    volumes:
      - ../../src:/workspace/src:ro
      - ../../config/spark:/workspace/config/spark:ro
      - ../../data:/workspace/data
    depends_on:
      catalog:
        condition: service_healthy
      storage:
        condition: service_healthy
    networks:
      - default
      # Đọc thẳng PostgreSQL business (đã đổi sang :15433) của stack nguồn.
      - cdp-sources-net

networks:
  cdp-sources-net:
    external: true
    name: cdp-sources_default

volumes:
  catalog-data:
  storage-data:
```

**Những điểm cần chú ý:**

| Điểm | Giải thích |
|---|---|
| `network cdp-sources-net` external | Spark cần đọc PostgreSQL business (CDC) và Kafka. Network phải được tạo **trước** bởi stack nguồn |
| `user: "0:0"` | Spark ghi vào volume `data/` cần quyền ghi |
| `../../src:/workspace/src:ro` | Job nằm trong `src/pipelines/`. Mount read-only để không sửa code từ container |
| `../../data:/workspace/data` | Cần **ghi** (Spark temp, file output). Không mount `:ro` |
| `SPARK_LOCAL_IP` | Bắt buộc khi chạy `local[*]` trong container, tránh lỗi hostname resolve |
| `driver-memory 3g` | Spark driver JVM. Đủ cho xử lý 42 triệu dòng theo chunk |
| `master local[4]` | 4 thread trong container. Tăng lên 8 nếu CPU mạnh |

**Thứ tự khởi động quan trọng:**
```powershell
# 1. Stack nguồn trước (tạo network + Kafka + Postgres business)
.venv\Scripts\python.exe -m src.demo.sources.runtime up

# 2. Lakehouse sau (cần network của stack nguồn)
docker compose -f config/docker/compose.lakehouse.yml up -d --wait --wait-timeout 180
```

---

## Bước 6 — Tạo bucket S3

MinIO tạo bucket tự động ở lần đầu truy cập, nhưng làm thủ công để chắc chắn:

```powershell
docker compose -f config/docker/compose.lakehouse.yml exec storage `
  mc alias set local http://localhost:9000 cdp-local cdp-local-storage
docker compose -f config/docker/compose.lakehouse.yml exec storage `
  mc mb local/cdp
docker compose -f config/docker/compose.lakehouse.yml exec storage `
  mc ls local/
```

> Iceberg tự tạo "folder" con (`s3://cdp/warehouse/cdp.bronze.xxx/`) khi ghi lần
> đầu — không cần tạo trước.

---

## Bước 7 — Tạo bảng Bronze

### 7.1 Tạo file DDL

`src/pipelines/lakehouse/sql/01_bronze.sql`:

```sql
-- cdp.bronze.rees46_events — event từ CSV REES46, chưa diễn giải.
CREATE TABLE IF NOT EXISTS cdp.bronze.rees46_events (
    -- Nội dung nguồn (giữ nguyên, không diễn giải ở tầng Bronze)
    event_time        TIMESTAMP,
    event_type        STRING    NOT NULL,
    product_id        STRING,
    category_id       STRING,
    category_code     STRING,
    brand             STRING,
    price_raw         STRING,              -- giữ chuỗi gốc
    price             DECIMAL(18, 2),      -- parse từ price_raw, lỗi → NULL
    currency          STRING,              -- LUÔN NULL: REES46 không có currency
    user_id           STRING,              -- namespace REES46, không ghép với web
    user_session      STRING,

    -- Metadata truy vết
    source_system         STRING    NOT NULL,   -- 'rees46'
    source_file           STRING    NOT NULL,
    source_file_checksum  STRING    NOT NULL,   -- sha256 file gốc
    source_row_number     BIGINT    NOT NULL,   -- 1-based, không tính header
    ingested_at           TIMESTAMP NOT NULL,
    batch_id              STRING    NOT NULL
)
USING iceberg
PARTITIONED BY (days(event_date))
LOCATION 's3://cdp/warehouse/cdp.bronze.rees46_events'
TBLPROPERTIES ('format-version' = '2');
```

> **Lưu ý:** `event_date` không có trong danh sách cột ở trên nhưng lại dùng
> trong `PARTITIONED BY`. Phải thêm cột `event_date DATE NOT NULL` vào danh
> sách cột. Iceberg yêu cầu cột partition phải tồn tại trong schema.
>
> Hoặc bỏ `PARTITIONED BY` và dùng `ALTER TABLE ... ADD PARTITION FIELD`
> sau khi tạo bảng — cách này an toàn hơn vì không bỏ sót cột.

### 7.2 Áp dụng DDL

```powershell
docker compose -f config/docker/compose.lakehouse.yml exec spark `
  /opt/spark/bin/spark-sql --master "local[2]" `
  --properties-file /workspace/config/spark/lakehouse.conf `
  -f /workspace/src/pipelines/lakehouse/sql/01_bronze.sql
```

**Kiểm tra kết quả:**
```powershell
docker compose -f config/docker/compose.lakehouse.yml exec spark `
  /opt/spark/bin/spark-sql --master "local[2]" `
  --properties-file /workspace/config/spark/lakehouse.conf `
  -e "SHOW NAMESPACES IN cdp; SHOW TABLES IN cdp.bronze;"
```

---

## Bước 8 — Job ingestion đầu tiên (REES46)

### 8.1 Nguyên tắc bắt buộc

REES46 là 5,6 GB / 42,4 triệu dòng. **Không được** load vào RAM.

```python
# SAI — sẽ OOM
import pandas as pd
df = pd.read_csv("data/REES46/2019-Oct.csv")

# ĐÚNG — DuckDB streaming
import duckdb
db = duckdb.connect()
db.execute("SET memory_limit = '512MB'")
db.execute("SET temp_directory = '/workspace/data/duckdb-temp'")
db.execute("""
    CREATE VIEW source AS SELECT * FROM read_csv(
        'data/REES46/2019-Oct.csv', header=true, all_varchar=true, nullstr='',
        sample_size=20480, ignore_errors=false)
""")
```

Pattern này đã có sẵn trong `src/pipelines/inspect_rees46_dataset.py` — tái sử dụng.

### 8.2 Cấu trúc job

`src/pipelines/lakehouse/ingest_rees46.py`:

```python
from pyspark.sql import SparkSession, functions as F
from pyspark.sql.types import (StringType, TimestampType, DecimalType,
                                DateType, LongType)

spark = SparkSession.builder.appName("ingest-rees46").getOrCreate()

BATCH_ID = "rees46-2019-10-v1"

# 1) Đọc CSV bằng DuckDB, chỉ lấy tập cột cần, ép kiểu ngay.
source = spark.read.format("csv") \
    .option("header", "true") \
    .option("inferSchema", "false") \
    .option("mode", "PERMISSIVE") \
    .schema(RAW_SCHEMA) \
    .csv("data/REES46/2019-Oct.csv") \
    .withColumn("source_file", F.lit("data/REES46/2019-Oct.csv")) \
    .withColumn("source_file_checksum", F.lit(FILE_CHECKSUM)) \
    .withColumn("batch_id", F.lit(BATCH_ID)) \
    .withColumn("ingested_at", F.current_timestamp())

# 2) Chuẩn hoá nhẹ + tạo cột partition.
target = source \
    .withColumn("event_time", F.col("event_time").cast(TimestampType())) \
    .withColumn("event_date", F.to_date("event_time")) \
    .withColumn("price", F.col("price_raw").cast(DecimalType(18, 2))) \
    .withColumn("currency", F.lit(None).cast(StringType())) \
    .withColumn("source_system", F.lit("rees46")) \
    .withColumn("source_row_number", F.monotonically_increasing_id() + 1)

# 3) Ghi idempotent: chỉ thay batch này.
target.writeTo("cdp.bronze.rees46_events") \
    .overwrite(F.col("batch_id") == F.lit(BATCH_ID))
```

**Điểm then chốt của đoạn `overwrite`:**
```python
.overwrite(F.col("batch_id") == F.lit(BATCH_ID))
```
→ Ghi đè **chỉ** dòng có `batch_id = BATCH_ID`. Các batch khác không bị đụng.
Job chạy lại cùng batch → an toàn. Đây là ứng dụng cốt lõi của Iceberg.

### 8.3 Chạy

```powershell
docker compose -f config/docker/compose.lakehouse.yml run --rm spark `
  /workspace/src/pipelines/lakehouse/ingest_rees46.py --batch-id rees46-2019-10-v1
```

### 8.4 Kiểm chứng

```sql
SELECT COUNT(*) FROM cdp.bronze.rees46_events;
SELECT COUNT(DISTINCT source_row_number) FROM cdp.bronze.rees46_events;
SELECT event_type, COUNT(*) FROM cdp.bronze.rees46_events GROUP BY 1 ORDER BY 2 DESC;
```

**Đối soát bắt buộc** (contract §9):
- Số dòng đọc từ CSV = số dòng ghi vào Bronze
- Không có dòng trùng `source_row_number`
- `price` null rate hợp lý (không phải 100% → lỗi parse)

---

## Bước 9 — Job ingestion Kafka (web events)

Đọc topic `cdp.web.good` (output của Snowplow Enrich):

```python
from pyspark.sql import functions as F
from pyspark.sql.types import StringType

# Đọc từ đầu topic, mỗi batch = 1 micro-batch.
raw = (spark.readStream
       .format("kafka")
       .option("kafka.bootstrap.servers", "kafka:9092")
       .option("subscribe", "cdp.web.good")
       .option("startingOffsets", "earliest")
       .load())
```

**Vấn đề:** Kafka source trong Spark trả về `value` là **binary**, cần decode
theo từng loại topic:
- `cdp.web.good` → Snowplow TSV enriched (không phải JSON) → cần parser riêng
- `cdp.business.public.*` → JSON (Debezium) → `from_json` được

> **Khuyến nghị cho local:** dùng **batch read** (`spark.read.format("kafka")`
> không phải `readStream`) với `startingOffsets=earliest` + offset filter, thay
> vì streaming. Lý do: xử lý batch cho phép `overwrite(batch_id)` idempotent,
> còn structured streaming với `writeTo().overwrite()` có giới hạn về
> idempotency và khó truy vết.

```python
raw = (spark.read.format("kafka")
       .option("kafka.bootstrap.servers", "kafka:9092")
       .option("subscribe", "cdp.web.good")
       .option("startingOffsets", "earliest")
       .option("endingOffsets", "latest")
       .option("failOnDataLoss", "false")
       .load())
```

**Metadata truy vết bắt buộc** (contract §3.2) — không được bỏ:
```python
raw.select(
    F.col("topic").alias("kafka_topic"),
    F.col("partition").alias("kafka_partition"),
    F.col("offset").alias("kafka_offset"),
    F.col("timestamp").alias("kafka_timestamp"),
    F.col("value").alias("value_bytes"),
)
```

**Khoá chống lặp = `(kafka_topic, kafka_partition, kafka_offset)`** — đây là
khoá chuẩn của Kafka, đọc lại cùng offset không tạo bản ghi mới.

---

## Bước 10 — Job ingestion CDC

Đọc `cdp.business.public.*` (JSON của Debezium):

```python
cdc = (raw
       .withColumn("payload", F.from_json(F.col("value").cast(StringType()),
                  schema=DEBEZIUM_SCHEMA))
       .select(
           F.col("kafka_topic"),
           F.col("kafka_partition"),
           F.col("kafka_offset"),
           F.col("payload.source.table").alias("source_table"),
           F.col("payload.op").alias("op"),
           F.col("payload.before").alias("before_image"),
           F.col("payload.after").alias("after_image"),
           F.col("payload.source.ts_ms").alias("change_ts_ms"),
           F.col("payload.source.lsn").alias("source_lsn"),
       ))
```

**Phân biệt snapshot và change** (contract P8):
```python
# Debezium đánh dấu snapshot bằng op='r' khi source.lsn = null
cdc = cdc.withColumn(
    "op_category",
    F.when(F.col("op") == "r", F.lit("snapshot"))
     .otherwise(F.lit("change"))
)
```

**Tombstone:** khi `after_image` là NULL → đó là delete. Phải giữ bản ghi với
`op='d'`, **không** xoá vật lý.

---

## Bước 11 — Tầng Silver

Áp dụng quy tắc chuẩn hoá (contract §5.1) và tách quarantine:

```python
silver = (bronze
    .withColumn("event_date", F.to_date("event_time"))
    .withColumn("quantity", F.col("quantity").cast("int"))
    .withColumn("total_price", F.col("total_price").cast(DecimalType(18, 2)))
    .withColumn("quality_flags", quality_flags_udf(F.col("payload"))))
```

**Bộ kiểm tra chất lượng** (contract §9) — chạy sau mỗi batch, fail thì dừng:

```python
def assert_quality(silver, quarantine, source, expected_rows):
    total = silver.count() + quarantine.count()
    assert total == expected_rows, f"Row loss: {total} != {expected_rows}"
    assert silver.filter(F.col("failed")).count() == 0
    assert silver.filter(F.col("event_date") != F.to_date(F.col("event_time"))).count() == 0
    assert silver.filter(F.col("source_system").isNull()).count() == 0
```

> **Bắt buộc:** đối soát cả **ID, giá trị và tổng số dòng** — không được chỉ
> dựa vào thông báo "job chạy xong". Code cũ (`src/pipelines/lakehouse/common.py`)
> có sẵn hàm `assert_same_rows()` làm full outer join + null-safe equality.

---

## Bước 12 — Tầng Gold

Xây `gold.user_behavior`, `gold.session_funnel`, `gold.transaction`,
`gold.customer_360` theo contract §7.

**Ràng buộc phải kiểm tra bằng test, không chỉ bằng code:**

```python
# gold.transaction KHÔNG được chứa doanh thu suy từ purchase_observed
assert gold_transaction.join(
    gold_user_behavior.filter(F.col("purchase_observed") > 0), "customer_id"
).count() == 0   # hoặc kiểm tra ngược lại cho đúng ngữ nghĩa

# gold.customer_360 chỉ có customer_id từ nguồn web
assert gold_customer_360.filter(F.col("identity_source") != "postgres_business").count() == 0
```

---

## Bước 13 — Bộ kiểm thử

Theo contract, cần kiểm chứng:

| Kiểm tra | Cách làm |
|---|---|
| **Replay idempotent** | Chạy lại job cùng `batch_id` → số dòng không đổi |
| **Batch isolation** | Ghi batch B không ảnh hưởng batch A |
| **Row count đối soát** | Số dòng nguồn = Bronze + Quarantine |
| **Key uniqueness** | Không trùng khoá chống lặp |
| **Time travel** | `SELECT * FROM cdp.bronze.x VERSION AS OF <snapshot_id>` |
| **Partition pruning** | `EXPLAIN` cho thấy chỉ đọc 1 partition |
| **Schema evolution** | `ALTER TABLE ADD COLUMN` rồi đọc dữ liệu cũ không lỗi |
| **Delete/ẩn dòng** | `is_deleted = true` thay vì xoá vật lý |

**Time travel — kiểm tra quan trọng nhất về mặt nghiệp vụ:**
```sql
-- Xem trạng thái bảng TRƯỚC khi job ghi đè batch
SELECT * FROM cdp.bronze.rees46_events VERSION AS OF 1234567890;
```

---

## Bước 14 — Kết nối API/dashboard với Gold

Hiện `src/demo/api/dashboard.py` đọc `observer.events` trong PostgreSQL.
Thêm nguồn `gold`:

```python
EVENT_SOURCE = os.getenv("CDP_EVENT_SOURCE", "kafka")   # "kafka" | "gold"
```

```python
if EVENT_SOURCE == "gold":
    return psycopg.connect(
        host=SNOWPLOW_PG_HOST, port=SNOWPLOW_PG_PORT,
        dbname=SNOWPLOW_PG_DATABASE, user=SNOWPLOW_PG_USER,
        password=SNOWPLOW_PG_PASSWORD, connect_timeout=5, row_factory=dict_row,
    )
```

Rồi đổi câu SQL từ `FROM events` sang `FROM gold.user_behavior`.

---

## Bước 15 — Vận hành

### Lệnh thường dùng

```powershell
# Bật
docker compose -f config/docker/compose.lakehouse.yml up -d --wait --wait-timeout 180

# Tắt (GIỮ volume)
docker compose -f config/docker/compose.lakehouse.yml down

# Xoá sạch (MẤT dữ liệu — dùng khi cần dựng lại từ đầu)
docker compose -f config/docker/compose.lakehouse.yml down -v

# Chạy 1 job
docker compose -f config/docker/compose.lakehouse.yml run --rm spark `
  /workspace/src/pipelines/lakehouse/ingest_rees46.py --batch-id rees46-2019-10-v1

# Chạy SQL tương tác
docker compose -f config/docker/compose.lakehouse.yml exec spark `
  /opt/spark/bin/spark-sql --master "local[2]" `
  --properties-file /workspace/config/spark/lakehouse.conf
```

### Chẩn đoán

| Triệu chứng | Nguyên nhân | Cách sửa |
|---|---|---|
| `ClassNotFoundException: S3FileIO` | Thiếu `iceberg-aws-bundle` | Thêm jar, rebuild image |
| `NoClassDefFoundError: Scala 2.13` | Sai bản `iceberg-spark-runtime` | Dùng đúng `-3.5_2.12` |
| `UnknownHostException: s3.amazonaws.com` | Thiếu `s3.endpoint` | Thêm `spark.sql.catalog.cdp.s3.endpoint` |
| `The specified bucket does not exist` | Thiếu `path-style-access` | Thêm `...s3.path-style-access true` |
| `SignatureDoesNotMatch` | Chunked encoding | Thêm `...s3.chunked-encoding-enabled false` |
| `Connection refused` tới catalog | Catalog chưa healthy | Kiểm tra `docker compose ps`, đợi healthcheck |
| `Table ... does not exist` | Chưa tạo DDL | Chạy lại Bước 7 |
| `OutOfMemoryError` | Đang dùng pandas thay vì DuckDB | Xem lại Bước 8.1 |
| Job chạy nhưng không thấy dữ liệu | Ghi sai `batch_id` | Kiểm tra `SELECT DISTINCT batch_id` |
| Lệch ngày giữa Bronze và Gold | Thiếu `timeZone UTC` | Thêm `spark.sql.session.timeZone UTC` |

---

## Checklist triển khai

- [ ] Docker Desktop chạy, `docker version` trả server version
- [ ] Disk trống ≥ 40 GB, RAM ≥ 8 GB
- [ ] `config/storage/s3.local.json` (nếu dùng SeaweedFS)
- [ ] `config/spark/lakehouse.conf` — đủ 3 nhóm: catalog / storage / behaviour
- [ ] `config/docker/lakehouse.Dockerfile` — 3 jar, Java 17
- [ ] Build image: `docker build -f config/docker/lakehouse.Dockerfile -t cdp-lakehouse-spark:latest .`
- [ ] `config/docker/compose.lakehouse.yml` — catalog + storage + spark
- [ ] Stack nguồn đã `up` (để có network `cdp-sources_default`)
- [ ] Lakehouse `up -d --wait`
- [ ] Bucket `cdp` tồn tại trong MinIO
- [ ] `SHOW NAMESPACES IN cdp` trả về namespace
- [ ] DDL Bronze tạo thành công
- [ ] Job REES46 chạy, đối soát số dòng khớp
- [ ] Job Kafka + CDC chạy
- [ ] Silver + quarantine + bộ kiểm tra chất lượng
- [ ] Gold + test ràng buộc nghiệp vụ
- [ ] Bộ kiểm thử replay / time travel / partition pruning

---

## Ghi chú về Airflow / Kubernetes

Contract §10 quy định: **chỉ sau khi pipeline local được nghiệm thu**. Cụ thể:

| Công nghệ | Khi nào | Lý do |
|---|---|---|
| Airflow | Sau khi ≥ 3 job ổn định | Orchestration chỉ có giá trị khi job đã chạy ổn định |
| Kubernetes | Sau khi cần HA | Local 1 broker, không có HA; K8s thừa |
| Trino | Khi cần query ngoài Spark | Iceberg đã hỗ trợ sẵn |
