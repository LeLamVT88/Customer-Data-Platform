-- src/demo/lakehouse/sql/02_silver.sql
-- Iceberg DDL for Silver and Quarantine tables: cdp.silver.demo_events, cdp.silver.demo_quarantine
-- Partitioned by (batch_id, event_date); quarantine has same schema + quality_reason

CREATE TABLE IF NOT EXISTS cdp.silver.demo_events (
    event_id        STRING  NOT NULL,
    event_time      TIMESTAMP NOT NULL,
    event_type      STRING  NOT NULL,
    session_id      STRING  NOT NULL,
    user_id         STRING  NOT NULL,
    namespace       STRING  NOT NULL,
    source          STRING  NOT NULL,
    url             STRING,
    referrer        STRING,
    user_agent      STRING,
    viewport        STRING,
    payload         MAP<STRING, STRING>,
    quality_flags   ARRAY<STRING>,
    ordinal         INT     NOT NULL,
    batch_id        STRING  NOT NULL,
    event_date      DATE    NOT NULL,
    ingestion_time   TIMESTAMP NOT NULL
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id), days(event_date))
LOCATION 's3://cdp/warehouse/cdp.silver.demo_events'
TBLPROPERTIES (
    'format-version' = '2'
);


CREATE TABLE IF NOT EXISTS cdp.silver.demo_quarantine (
    event_id        STRING,
    event_time      STRING,
    event_type      STRING,
    session_id      STRING,
    user_id         STRING,
    namespace       STRING,
    source          STRING,
    url             STRING,
    referrer        STRING,
    user_agent      STRING,
    viewport        STRING,
    payload         STRING,
    quality_flags   STRING,
    ordinal         INT,
    batch_id        STRING,
    ingestion_time  STRING,
    quarantine_reason STRING NOT NULL
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id))
LOCATION 's3://cdp/warehouse/cdp.silver.demo_quarantine'
TBLPROPERTIES (
    'format-version' = '2'
);
