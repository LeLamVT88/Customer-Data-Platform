-- src/demo/lakehouse/sql/01_bronze.sql
-- Iceberg DDL for Bronze table: cdp.bronze.demo_events
-- Partitioned by batch_id (matches REES46 Bronze contract)

CREATE TABLE IF NOT EXISTS cdp.bronze.demo_events (
    event_id        STRING  NOT NULL,
    event_time      STRING  NOT NULL,
    event_type      STRING  NOT NULL,
    session_id      STRING,
    user_id         STRING,
    namespace       STRING  NOT NULL DEFAULT 'cdp.demo.events',
    source          STRING  NOT NULL DEFAULT 'web-demo',
    url             STRING,
    referrer        STRING,
    user_agent      STRING,
    viewport        STRING,
    payload         STRING,                          -- JSON serialised
    quality_flags   STRING,                          -- comma-separated
    ordinal         INT,
    batch_id        STRING  NOT NULL,
    ingestion_time  STRING  NOT NULL
)
USING iceberg
PARTITIONED BY (batch_id)
LOCATION 's3://cdp/warehouse/cdp.bronze.demo_events'
TBLPROPERTIES (
    'format-version' = '2'
);
