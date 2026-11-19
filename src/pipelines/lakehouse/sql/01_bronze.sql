-- ---------------------------------------------------------------------------
-- Bronze layer: raw, append-only, no interpretation.
--
-- Rules (docs/lakehouse-contract.md):
--   * One table per source. No unions, no cross-source columns.
--   * Every row carries the provenance columns that make it replayable.
--   * Partitioned by event_date so a day can be rewritten in isolation.
--   * format-version 2 gives row-level deletes and schema evolution.
-- ---------------------------------------------------------------------------

CREATE NAMESPACE IF NOT EXISTS cdp.bronze;
CREATE NAMESPACE IF NOT EXISTS cdp.silver;
CREATE NAMESPACE IF NOT EXISTS cdp.gold;

-- ── REES46 e-commerce history ───────────────────────────────────────────────
-- Source: monthly CSV dumps, one file per month. 42.4M rows, 5.6 GB.
-- currency is always NULL: the source carries no currency information.
CREATE TABLE IF NOT EXISTS cdp.bronze.rees46_events (
    -- Business columns, kept close to the source shape.
    event_time        TIMESTAMP,
    event_type        STRING    NOT NULL,
    product_id        STRING,
    category_id       STRING,
    category_code     STRING,
    brand             STRING,
    price_raw         STRING,
    price             DECIMAL(18, 2),
    currency          STRING,
    user_id           STRING,
    user_session      STRING,

    -- Derived partition column.
    event_date        DATE      NOT NULL,

    -- Provenance: makes the row traceable and the batch replayable.
    source_system         STRING    NOT NULL,
    source_file           STRING    NOT NULL,
    source_file_checksum  STRING    NOT NULL,
    source_row_number     BIGINT    NOT NULL,
    ingested_at           TIMESTAMP NOT NULL,
    batch_id              STRING    NOT NULL
)
USING iceberg
PARTITIONED BY (days(event_date))
TBLPROPERTIES (
    'format-version' = '2',
    'write.parquet.compression-codec' = 'zstd'
);

-- ── Website web events (Snowplow, Kafka topic cdp.web.good) ─────────────────
-- Dedup key: (kafka_topic, kafka_partition, kafka_offset).
CREATE TABLE IF NOT EXISTS cdp.bronze.web_events (
    event_id           STRING,
    event_type         STRING,
    event_timestamp    TIMESTAMP,
    event_date         DATE      NOT NULL,
    user_id            STRING,
    anonymous_id       STRING,
    user_session       STRING,
    page_url           STRING,
    page_title         STRING,
    referrer_url       STRING,
    device_type        STRING,
    os_name            STRING,
    os_version         STRING,
    browser_name       STRING,
    browser_version    STRING,
    ip_address         STRING,
    payload            STRING,

    -- Kafka provenance.
    kafka_topic        STRING    NOT NULL,
    kafka_partition    INT       NOT NULL,
    kafka_offset       BIGINT    NOT NULL,
    kafka_timestamp    TIMESTAMP,

    ingested_at        TIMESTAMP NOT NULL,
    batch_id           STRING    NOT NULL
)
USING iceberg
PARTITIONED BY (days(event_date))
TBLPROPERTIES (
    'format-version' = '2',
    'write.parquet.compression-codec' = 'zstd'
);

-- ── Website web events rejected by Enrich ───────────────────────────────────
-- Source: Kafka topics cdp.web.bad / cdp.web.failed / cdp.web.collector_bad.
-- Kept separately so the failure reason survives (contract P4).
CREATE TABLE IF NOT EXISTS cdp.bronze.web_events_failed (
    event_date       DATE      NOT NULL,
    error_message    STRING,
    error_stack      STRING,
    payload          STRING,

    kafka_topic      STRING    NOT NULL,
    kafka_partition  INT       NOT NULL,
    kafka_offset     BIGINT    NOT NULL,
    kafka_timestamp  TIMESTAMP,

    ingested_at      TIMESTAMP NOT NULL,
    batch_id         STRING    NOT NULL
)
USING iceberg
PARTITIONED BY (days(event_date))
TBLPROPERTIES (
    'format-version' = '2',
    'write.parquet.compression-codec' = 'zstd'
);

-- ── PostgreSQL business CDC (Debezium, Kafka topic cdp.business.public.*) ──
-- Dedup key: (kafka_topic, kafka_partition, kafka_offset).
-- Rows are never deleted physically; a delete is op = 'd' with a null image.
CREATE TABLE IF NOT EXISTS cdp.bronze.business_cdc (
    source_table     STRING    NOT NULL,
    op              STRING    NOT NULL,          -- c | u | d | r
    op_category     STRING    NOT NULL,          -- snapshot | change
    primary_key     STRING,
    before_image    STRING,
    after_image     STRING,
    change_ts       TIMESTAMP,
    change_ts_ms    BIGINT,
    source_lsn      BIGINT,
    event_date      DATE      NOT NULL,

    kafka_topic     STRING    NOT NULL,
    kafka_partition INT       NOT NULL,
    kafka_offset    BIGINT    NOT NULL,
    kafka_timestamp TIMESTAMP,

    ingested_at     TIMESTAMP NOT NULL,
    batch_id        STRING    NOT NULL
)
USING iceberg
PARTITIONED BY (days(event_date))
TBLPROPERTIES (
    'format-version' = '2',
    'write.parquet.compression-codec' = 'zstd'
);
