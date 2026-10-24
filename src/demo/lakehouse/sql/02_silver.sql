-- src/demo/lakehouse/sql/02_silver.sql
-- Iceberg DDL for Silver and Quarantine tables:
--   cdp.silver.demo_events       — event hợp lệ, đã chuẩn hoá
--   cdp.silver.demo_quarantine   — event lỗi (bad stream của Snowplow Enrich)
--
-- Snowplow Enrich đã validate payload theo Iglu schema, nên Silver chỉ còn:
--   • loại bỏ event failed = true (đã nằm ở quarantine)
--   • chuẩn hoá tên field, ép kiểu số/ngày, gắn quality_flags cho edge case
--   • đảm bảo event_date khớp event_time (phân vùng ở tầng partition)

CREATE TABLE IF NOT EXISTS cdp.silver.demo_events (
    event_id         STRING    NOT NULL,
    event_time       TIMESTAMP NOT NULL,
    event_type       STRING    NOT NULL,
    event_date       DATE      NOT NULL,
    user_id          STRING    NOT NULL,
    session_id       STRING    NOT NULL,
    namespace        STRING    NOT NULL,
    app_id           STRING,
    source           STRING    NOT NULL,   -- 'snowplow'
    url              STRING,
    referrer         STRING,
    user_agent       STRING,
    platform         STRING,
    name_tracker     STRING,
    v_tracker        STRING,
    product_id       STRING,
    category_id      STRING,
    quantity         INT,
    total_price      DECIMAL(18, 2),
    currency         STRING,
    payload          STRING,
    quality_flags    ARRAY<STRING>,
    collector_tstamp TIMESTAMP,
    ingestion_time   TIMESTAMP NOT NULL,
    batch_id         STRING    NOT NULL
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id), days(event_date))
LOCATION 's3://cdp/warehouse/cdp.silver.demo_events'
TBLPROPERTIES (
    'format-version' = '2'
);


CREATE TABLE IF NOT EXISTS cdp.silver.demo_quarantine (
    event_id         STRING,
    event_time       TIMESTAMP,
    event_type       STRING,
    event_date       DATE,
    user_id          STRING,
    session_id       STRING,
    namespace        STRING,
    app_id           STRING,
    source           STRING    NOT NULL,   -- 'snowplow'
    url              STRING,
    user_agent       STRING,
    platform         STRING,
    payload          STRING,
    contexts         STRING,
    quality_flags    ARRAY<STRING>,
    quarantine_reason STRING   NOT NULL,
    failure_detail   STRING,
    collector_tstamp TIMESTAMP,
    ingestion_time   TIMESTAMP,
    batch_id         STRING
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id))
LOCATION 's3://cdp/warehouse/cdp.silver.demo_quarantine'
TBLPROPERTIES (
    'format-version' = '2'
);
