# Triển khai Lakehouse chung (Apache Iceberg)

Hướng dẫn dựng và vận hành Lakehouse chung cho REES46 + Website nguồn theo
[contract](lakehouse-contract.md).

> **Trạng thái:** stack đã dựng và kiểm chứng trên máy Windows local.
> 23/23 kiểm tra trong `verify_lakehouse.py` đạt. Còn thiếu: job Kafka/CDC
> (cần stack nguồn), tầng Silver và Gold.

---

## 0. Vì sao không dùng Docker

Bản hướng dẫn đầu tiên dựa trên Docker Compose. Trên máy này **WSL2 không
hoạt động** (`HCS_E_SERVICE_NOT_AVAILABLE`), nên Docker Desktop không khởi
động được, và việc bật `VirtualMachinePlatform` cần quyền administrator.

Vì vậy stack chạy dưới dạng **tiến trình Windows native**:

| Thành phần | Docker (phương án A) | Native (phương án B — đang dùng) |
|---|---|---|
| Catalog | `postgres:16` | PostgreSQL 18 đã cài, cluster riêng port 15434 |
| Storage | `minio/minio` | `tools/bin/minio.exe` port 9000 |
| Compute | `apache/spark:3.5.8` | PySpark 3.5.8 trong `.venv` |
| Quản lý | `docker compose up` | `scripts/lakehouse.ps1 start` |

Phương án B không cần đổi một dòng nào trong DDL hay trong code ingestion —
chỉ khác cách khởi động và các biến môi trường.

---

## 1. Kiến trúc stack

```text
                    ┌──────────────────────────────┐
                    │  catalog                     │
                    │  PostgreSQL 18  :15434       │
                    │  db=iceberg user=cdp         │
                    │  ← metadata Iceberg (vài KB) │
                    └──────────┬───────────────────┘
                               │ đọc/ghi metadata
                    ┌──────────▼───────────────────┐
                    │  spark (pyspark 3.5.8)       │
                    │  Iceberg 1.11 + Java 17      │
                    └──────────┬───────────────────┘
                               │ đọc/ghi file Parquet
                    ┌──────────▼───────────────────┐
                    │  storage (MinIO)  :9000      │
                    │  s3://cdp/warehouse/          │
                    │  ← dữ liệu thật              │
                    └──────────────────────────────┘
```

**Điểm cần nhớ:** catalog ≠ dữ liệu.

- `catalog` (PostgreSQL) chỉ chứa *metadata*: schema, partition spec, snapshot, manifest.
  Bảng `iceberg_tables` và `iceberg_namespace_properties`.
- `storage` (MinIO) chứa *file dữ liệu* Parquet + `metadata.json` + `.avro` manifest.
- Mất catalog → mất schema nhưng **không** mất dữ liệu thô.

**Tại sao JDBC catalog:** local 1 engine, đơn giản nhất, không thêm service.
Khi lên multi-engine thì chuyển sang REST catalog — chỉ đổi 3 dòng config.

---

## Bước 1 — Chuẩn bị môi trường

Kiểm tra nhanh:

```powershell
.\scripts\lakehouse.ps1 status
```

Yêu cầu tối thiểu đã được kiểm tra trên máy này:

| Tài nguyên | Cần | Máy này |
|---|---|---|
| Disk trống | 20 GB | 150 GB ✅ |
| RAM | 8 GB | 15.2 GB ✅ |
| CPU | 4 core | 12 logical ✅ |
| JDK | 17 | `C:\Program Files\Java\jdk-17` ✅ |
| Python | 3.10+ | 3.13.7 qua `py -3.13` ✅ |

> **JDK 21 mặc định của máy không dùng được với Spark 3.5.** Script launcher
> tự trỏ `JAVA_HOME` về JDK 17.

---

## Bước 2 — Khởi động stack

```powershell
.\scripts\lakehouse.ps1 start
```

Lần đầu tiên script sẽ:

1. `initdb` tạo cluster PostgreSQL mới ở `%LOCALAPPDATA%\cdp-iceberg-catalog`,
   ghi `port = 15434` và `listen_addresses = '127.0.0.1'` vào `postgresql.conf`.
2. Khởi động MinIO với `MINIO_ROOT_USER=cdp-local`,
   `MINIO_ROOT_PASSWORD=cdp-local-storage`, dữ liệu ở `data/minio`.
3. Tạo bucket `cdp` trong MinIO.

Các lệnh khác:

```powershell
.\scripts\lakehouse.ps1 status    # xem trạng thái
.\scripts\lakehouse.ps1 stop      # dừng (giữ dữ liệu)
.\scripts\lakehouse.ps1 restart   # dừng rồi bật lại
.\scripts\lakehouse.ps1 reset     # XOÁ sạch dữ liệu, dựng lại từ đầu
```

---

## Bước 3 — Cấu hình Spark cho Iceberg

File `config/spark/lakehouse.conf` — định nghĩa 3 khái niệm hay bị nhầm:

```properties
spark.sql.extensions org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions

spark.sql.catalog.cdp org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.cdp.catalog-impl org.apache.iceberg.jdbc.JdbcCatalog
spark.sql.catalog.cdp.uri jdbc:postgresql://127.0.0.1:15434/iceberg
spark.sql.catalog.cdp.jdbc.user cdp
spark.sql.catalog.cdp.jdbc.password cdp-local-catalog
spark.sql.catalog.cdp.warehouse s3://cdp/warehouse

spark.sql.catalog.cdp.io-impl org.apache.iceberg.aws.s3.S3FileIO
spark.sql.catalog.cdp.s3.endpoint http://127.0.0.1:9000
spark.sql.catalog.cdp.s3.path-style-access true
spark.sql.catalog.cdp.s3.chunked-encoding-enabled false
spark.sql.catalog.cdp.s3.access-key-id cdp-local
spark.sql.catalog.cdp.s3.secret-access-key cdp-local-storage
spark.sql.catalog.cdp.s3.region us-east-1

spark.sql.session.timeZone UTC
spark.sql.shuffle.partitions 16
spark.sql.adaptive.enabled true
spark.local.dir data/spark-temp
```

**Giải thích từng dòng quan trọng:**

| Dòng | Ý nghĩa | Sai hậu quả nếu bỏ/sai |
|---|---|---|
| `spark.sql.extensions` | Bật extension Iceberg | Không dùng được `MERGE INTO`, `CALL rewrite_data_files` |
| `spark.sql.catalog.cdp` | **Tên catalog** dùng trong SQL (`cdp.bronze.xxx`) | SQL phải viết `spark_catalog.bronze.xxx` |
| `catalog-impl` | Loại catalog thật | `ClassNotFoundException` |
| `uri` | JDBC URL tới PostgreSQL catalog | `Connection refused` tới catalog |
| `warehouse` | Bucket + prefix chứa file Parquet | `NoSuchBucketException` |
| `io-impl` | Bộ đọc/ghi file S3 | `ClassNotFoundException: S3FileIO` |
| `s3.endpoint` | Endpoint của MinIO | Iceberg cố gọi AWS thật → `UnknownHostException` |
| `s3.path-style-access` | `s3://bucket/key` thay vì `s3://bucket.s3.amazonaws.com/key` | `The specified bucket does not exist` |
| `chunked-encoding-enabled false` | Tắt chunked transfer | `SignatureDoesNotMatch` |
| `s3.access-key-id` / `secret-access-key` | Credentials cho MinIO | `AccessDenied` |
| `session.timeZone UTC` | Múi giờ | Lệch ngày giữa Bronze và Gold |
| `spark.local.dir` | Nơi ghi spill/temp | Đầy đĩa |

---

## Bước 4 — Jars Iceberg

Ba jar bắt buộc nằm ở `tools/jars/`:

| Jar | Bắt buộc vì |
|---|---|
| `iceberg-spark-runtime-3.5_2.12` | Engine Iceberg cho Spark 3.5, Scala 2.12 |
| `iceberg-aws-bundle` | `S3FileIO` — đọc/ghi file trên MinIO |
| `postgresql` | JDBC driver để `JdbcCatalog` nói chuyện với PostgreSQL |

```powershell
$jars = "tools\jars"
$urls = @(
  "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/1.11.0/iceberg-spark-runtime-3.5_2.12-1.11.0.jar",
  "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.11.0/iceberg-aws-bundle-1.11.0.jar",
  "https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.8/postgresql-42.7.8.jar"
)
foreach ($u in $urls) { curl.exe -sL -o "$jars\$(Split-Path $u -Leaf)" "$u" }
```

> **Sai lầm thường gặp:** dùng `iceberg-spark-runtime-3.5_2.13` (Scala 2.13)
> với Spark build Scala 2.12 → `NoClassDefFoundError`. Kiểm tra:
> ```powershell
> .venv\Scripts\python.exe -c "import pyspark,os;print(os.listdir(os.path.join(os.path.dirname(pyspark.__file__),'jars'))[:3])"
> ```

**Jars được copy tự động** vào `pyspark/jars/` bởi `session.install_jars()`.
Không dùng `spark.jars` vì nó copy jar vào thư mục temp của session, rồi
Windows không xoá được thư mục đó (JVM vẫn giữ file handle).

---

## Bước 5 — Tạo bảng Bronze

File DDL: `src/pipelines/lakehouse/sql/01_bronze.sql`. Chạy:

```powershell
.\scripts\run-job.ps1 src\pipelines\lakehouse\apply_ddl.py
```

Tạo 3 namespace (`bronze`, `silver`, `gold`) và 4 bảng:

| Bảng | Nguồn | Khoá chống lặp |
|---|---|---|
| `cdp.bronze.rees46_events` | CSV REES46 | `(source_file_checksum, source_row_number)` |
| `cdp.bronze.web_events` | Kafka `cdp.web.good` | `(kafka_topic, kafka_partition, kafka_offset)` |
| `cdp.bronze.web_events_failed` | Kafka `cdp.web.bad` / `.failed` | `(kafka_topic, kafka_partition, kafka_offset)` |
| `cdp.bronze.business_cdc` | Kafka `cdp.business.public.*` | `(kafka_topic, kafka_partition, kafka_offset)` |

Tất cả dùng `format-version = '2'`, partition `days(event_date)`,
compression `zstd`.

> **Cột partition phải tồn tại trong schema.** Iceberg sẽ báo lỗi nếu
> `PARTITIONED BY (days(event_date))` mà bảng không có cột `event_date`.
> Đây là lý do `event_date DATE NOT NULL` có mặt trong mọi bảng Bronze.

---

## Bước 6 — Job ingestion REES46

### 6.1 Nguyên tắc bắt buộc

REES46 thật là 5,6 GB / 42,4 triệu dòng. **Không được** load vào RAM.

```python
# SAI — sẽ OOM
import pandas as pd
df = pd.read_csv("data/REES46/2019-Oct.csv")

# ĐÚNG — DuckDB streaming
import duckdb
db = duckdb.connect()
db.execute("SET memory_limit = '512MB'")
db.execute("SET temp_directory = '.../duckdb-temp'")
db.execute("CREATE VIEW source AS SELECT * FROM read_csv('...', header=true, all_varchar=true)")
```

### 6.2 Chạy job

```powershell
.\scripts\run-job.ps1 src\pipelines\lakehouse\ingest_rees46.py `
  --source data\REES46\2019-Oct.csv `
  --batch-id rees46-2019-10-v1
```

Job thực hiện:
1. Tính `sha256` file gốc → `source_file_checksum`.
2. DuckDB stream CSV → Parquet staging (ZSTD).
3. Spark đọc staging, ép kiểu, ghi vào Iceberg.
4. Đối soát số dòng.

### 6.3 Điểm then chốt: `overwrite` theo batch

```python
raw.writeTo("cdp.bronze.rees46_events") \
    .overwrite(F.col("batch_id") == F.lit(batch_id))
```

Ghi đè **chỉ** dòng có `batch_id` tương ứng. Các batch khác không bị đụng.
Job chạy lại cùng batch → an toàn. Đây là ứng dụng cốt lõi của Iceberg.

**Đã kiểm chứng:** chạy job 2 lần liên tiếp → bảng vẫn có 20.000 dòng
(không phải 40.000).

### 6.4 Xử lý giá trị lỗi

```python
.withColumn("price", F.expr("try_cast(price as decimal(18,2))"))
```

Dùng `try_cast`, không dùng `cast`. Với `cast`, một giá trị `"n/a"` làm hỏng
cả batch:

```
SparkNumberFormatException: [CAST_INVALID_INPUT] The value 'n/a' ...
```

Với `try_cast`, giá trị lỗi thành `NULL` và được đánh dấu qua
`quality_flags` ở tầng Silver (contract §5.1).

### 6.5 Dataset mẫu

Dataset REES46 thật không được phân phối kèm repo. Bộ mẫu cùng schema:

```powershell
.venv\Scripts\python.exe src\pipelines\lakehouse\make_sample_rees46.py --rows 20000
.\scripts\run-job.ps1 src\pipelines\lakehouse\ingest_rees46.py `
  --source data\REES46\sample.csv --batch-id rees46-sample-v1
```

Bộ mẫu cố ý chứa giá trị `price` sai định dạng (`n/a`) và âm (`-5.00`)
để kích hoạt cờ chất lượng và cảnh báo tỉ lệ null.

> **Không được** cộng dồn các bản sample thành dữ liệu "toàn tháng"
> (contract §4). Mỗi lần chạy = 1 `batch_id` khác.

---

## Bước 7 — Truy vấn

```powershell
.\scripts\run-job.ps1 src\pipelines\lakehouse\query.py --tables
.\scripts\run-job.ps1 src\pipelines\lakehouse\query.py "SELECT COUNT(*) FROM cdp.bronze.rees46_events"
.\scripts\run-job.ps1 src\pipelines\lakehouse\query.py --file scripts.sql
```

Time travel:

```sql
SELECT * FROM cdp.bronze.rees46_events VERSION AS OF 1196041924026619828;
```

---

## Bước 8 — Kiểm chứng

```powershell
.\scripts\run-job.ps1 src\pipelines\lakehouse\verify_lakehouse.py
```

23 kiểm tra, theo 8 nhóm:

| Nhóm | Kiểm tra |
|---|---|
| 1. Catalog | 3 namespace tồn tại |
| 2. Bronze tables | 4 bảng tồn tại |
| 3. Partitioning | cả 4 bảng partition theo `days(event_date)` |
| 4. Dedup key | khoá chống lặp unique (đếm distinct = đếm tổng) |
| 5. REES46 contract | `currency` luôn NULL, `source_system` đúng, `event_date` khớp `event_time`, checksum luôn có |
| 6. Time travel | snapshot cũ vẫn đọc được |
| 7. Partition pruning | plan lọc trên cột partition |
| 8. Storage layout | file parquet nằm dưới `s3://cdp/warehouse` |

---

## Bước 9 — Job ingestion Kafka (web events)

**Chưa làm** — cần stack nguồn (`src/demo/sources/runtime.py`) chạy được.

Đọc topic `cdp.web.good` (output của Snowplow Enrich):

```python
raw = (spark.read.format("kafka")
       .option("kafka.bootstrap.servers", "127.0.0.1:19092")
       .option("subscribe", "cdp.web.good")
       .option("startingOffsets", "earliest")
       .option("endingOffsets", "latest")
       .option("failOnDataLoss", "false")
       .load())
```

**Vấn đề:** Kafka source trả về `value` là **binary**, cần decode theo từng loại topic:
- `cdp.web.good` → Snowplow TSV enriched (không phải JSON) → cần parser riêng
- `cdp.business.public.*` → JSON (Debezium) → `from_json` được

> **Khuyến nghị cho local:** dùng **batch read** (`spark.read.format("kafka")`
> không phải `readStream`) với `startingOffsets=earliest` + offset filter.
> Batch cho phép `overwrite(batch_id)` idempotent; structured streaming thì
> không.

Metadata truy vết bắt buộc (contract §3.2):

```python
raw.select(
    F.col("topic").alias("kafka_topic"),
    F.col("partition").alias("kafka_partition"),
    F.col("offset").alias("kafka_offset"),
    F.col("timestamp").alias("kafka_timestamp"),
    F.col("value").alias("value_bytes"),
)
```

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

Phân biệt snapshot và change (contract P8):

```python
cdc = cdc.withColumn(
    "op_category",
    F.when(F.col("op") == "r", F.lit("snapshot")).otherwise(F.lit("change"))
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

Bộ kiểm tra chất lượng (contract §9) — chạy sau mỗi batch, fail thì dừng:

```python
def assert_quality(silver, quarantine, source, expected_rows):
    total = silver.count() + quarantine.count()
    assert total == expected_rows, f"Row loss: {total} != {expected_rows}"
    assert silver.filter(F.col("failed")).count() == 0
    assert silver.filter(F.col("event_date") != F.to_date(F.col("event_time"))).count() == 0
    assert silver.filter(F.col("source_system").isNull()).count() == 0
```

> **Bắt buộc:** đối soát cả **ID, giá trị và tổng số dòng** — không được chỉ
> dựa vào thông báo "job chạy xong".

---

## Bước 12 — Tầng Gold

Xây `gold.user_behavior`, `gold.session_funnel`, `gold.transaction`,
`gold.customer_360` theo contract §7.

Ràng buộc phải kiểm bằng test, không chỉ bằng code:

```python
# gold.transaction KHÔNG được chứa doanh thu suy từ purchase_observed
assert gold_transaction.join(
    gold_user_behavior.filter(F.col("purchase_observed") > 0), "customer_id"
).count() == 0

# gold.customer_360 chỉ có customer_id từ nguồn web
assert gold_customer_360.filter(F.col("identity_source") != "postgres_business").count() == 0
```

---

## Bước 13 — Kết nối API/dashboard với Gold

Hiện `src/demo/api/dashboard.py` đọc `observer.events` trong PostgreSQL.
Thêm nguồn `gold`:

```python
EVENT_SOURCE = os.getenv("CDP_EVENT_SOURCE", "kafka")   # "kafka" | "gold"
```

Rồi đổi câu SQL từ `FROM events` sang `FROM gold.user_behavior`.

---

## Bước 14 — Vận hành

```powershell
# Bật / tắt / xem trạng thái
.\scripts\lakehouse.ps1 start
.\scripts\lakehouse.ps1 stop
.\scripts\lakehouse.ps1 status

# Chạy job
.\scripts\run-job.ps1 src\pipelines\lakehouse\check_environment.py
.\scripts\run-job.ps1 src\pipelines\lakehouse\apply_ddl.py
.\scripts\run-job.ps1 src\pipelines\lakehouse\ingest_rees46.py --source data\REES46\sample.csv
.\scripts\run-job.ps1 src\pipelines\lakehouse\verify_lakehouse.py

# Xem file trong storage
.\tools\bin\mc.exe ls --recursive local/cdp/warehouse/

# Xem metadata trong catalog
$env:PGPASSWORD = "cdp-local-catalog"
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -p 15434 -U cdp -d iceberg -c "\dt"
```

### Chẩn đoán

| Triệu chứng | Nguyên nhân | Cách sửa |
|---|---|---|
| `Hadoop home directory C:\hadoop does not exist` | Chưa set `HADOOP_HOME` | Dùng `scripts\run-job.ps1` (tự set) |
| `ClassNotFoundException: S3FileIO` | Thiếu `iceberg-aws-bundle` | Copy jar vào `pyspark/jars/` |
| `NoClassDefFoundError: Scala 2.13` | Sai bản `iceberg-spark-runtime` | Dùng đúng `-3.5_2.12` |
| `UnknownHostException: s3.amazonaws.com` | Thiếu `s3.endpoint` | Thêm `...s3.endpoint` |
| `The specified bucket does not exist` | Thiếu `path-style-access` | Thêm `...s3.path-style-access true` |
| `SignatureDoesNotMatch` | Chunked encoding | Thêm `...s3.chunked-encoding-enabled false` |
| `Connection refused` tới catalog | Catalog chưa chạy | `.\scripts\lakehouse.ps1 start` |
| `SparkNumberFormatException` | Dùng `cast` cho cột có giá trị lỗi | Dùng `try_cast` |
| `Table ... does not exist` | Chưa tạo DDL | `apply_ddl.py` |
| `OutOfMemoryError` | Đang dùng pandas thay vì DuckDB | Xem lại Bước 6.1 |
| Job chạy nhưng không thấy dữ liệu | Ghi sai `batch_id` | `SELECT DISTINCT batch_id` |
| Lệch ngày giữa Bronze và Gold | Thiếu `timeZone UTC` | Thêm `spark.sql.session.timeZone UTC` |
| `HCS_E_SERVICE_NOT_AVAILABLE` | WSL2 chưa bật | Docker không dùng được → dùng native |

---

## Checklist triển khai

- [x] `scripts/lakehouse.ps1 start` — catalog + storage chạy
- [x] `config/spark/lakehouse.conf` — đủ 3 nhóm: catalog / storage / behaviour
- [x] `tools/jars/` — 3 jar
- [x] `config/storage/s3.local.json` — credentials S3
- [x] DDL Bronze — 4 bảng, `format-version = 2`
- [x] Job REES46 (DuckDB → Bronze), idempotent
- [x] Bộ kiểm chứng 23/23
- [ ] Stack nguồn chạy được trên Windows (`runtime.py` dùng `ps -p` POSIX)
- [ ] Job ingestion Kafka web events
- [ ] Job ingestion CDC
- [ ] DDL + job Silver + quarantine
- [ ] DDL + job Gold
- [ ] Kết nối API/dashboard với Gold

---

## Ghi chú về Airflow / Kubernetes

Contract §10 quy định: **chỉ sau khi pipeline local được nghiệm thu**.

| Công nghệ | Khi nào | Lý do |
|---|---|---|
| Airflow | Sau khi ≥ 3 job ổn định | Orchestration chỉ có giá trị khi job đã chạy ổn định |
| Kubernetes | Sau khi cần HA | Local 1 broker, không có HA |
| Trino | Khi cần query ngoài Spark | Iceberg đã hỗ trợ sẵn |
