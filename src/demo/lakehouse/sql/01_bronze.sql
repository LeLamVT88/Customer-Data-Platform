-- src/demo/lakehouse/sql/01_bronze.sql
-- Iceberg DDL for Bronze table: cdp.bronze.demo_events
--
-- Bronze giữ nguyên enriched event mà Snowplow ghi xuống PostgreSQL storage
-- backend. Không validate, không diễn giải: đây là bản "as collected".
--
-- Partitioned by batch_id (mỗi lần chạy ingestion = 1 batch) + ngày event.

CREATE TABLE IF NOT EXISTS cdp.bronze.demo_events (
    -- Định danh & thời gian
    event_id         STRING    NOT NULL,   -- Snowplow event_id (UUID)
    event_time       TIMESTAMP NOT NULL,   -- timestamp của storage backend
    event_type       STRING    NOT NULL,   -- event_name, ví dụ product_view
    event_date       DATE      NOT NULL,

    -- Định danh người dùng / phiên
    user_id          STRING,
    session_id       STRING,
    namespace        STRING    NOT NULL,   -- com.cdp.demo (gán ở tầng Python)
    app_id           STRING,

    -- Ngữ cảnh trang
    url             STRING,
    referrer        STRING,
    user_agent      STRING,
    platform        STRING,
    name_tracker    STRING,
    v_tracker       STRING,

    -- Ngữ cảnh pipeline
    collector_tstamp TIMESTAMP,
    derived_tstamp   TIMESTAMP,
    device_sent_tstamp TIMESTAMP,

    -- Payload self-describing event (JSON) và entity (JSON)
    payload          STRING,               -- unstruct_event_com_cdp_demo_<event>_1
    contexts         STRING,               -- contexts_com_cdp_demo_session_1, ...

    -- Cờ chất lượng do Snowplow Enrich gắn
    failed           BOOLEAN  NOT NULL,   -- true = bad stream

    -- Quản lý batch của pipeline demo
    batch_id         STRING    NOT NULL
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id), days(event_date))
LOCATION 's3://cdp/warehouse/cdp.bronze.demo_events'
TBLPROPERTIES (
    'format-version' = '2'
);
