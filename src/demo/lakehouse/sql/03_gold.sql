-- src/demo/lakehouse/sql/03_gold.sql
-- Iceberg DDL for Gold tables: cdp.gold.demo_user_behavior, cdp.gold.demo_session_funnel

-- Gold: per-user behaviour summary
CREATE TABLE IF NOT EXISTS cdp.gold.demo_user_behavior (
    batch_id        STRING  NOT NULL,
    event_date      DATE    NOT NULL,
    user_id         STRING  NOT NULL,
    page_views      BIGINT  DEFAULT 0,
    product_views   BIGINT  DEFAULT 0,
    add_to_cart     BIGINT  DEFAULT 0,
    remove_from_cart BIGINT DEFAULT 0,
    begin_checkout  BIGINT  DEFAULT 0,
    purchases       BIGINT  DEFAULT 0,
    unique_sessions BIGINT  DEFAULT 0,
    last_event_at   TIMESTAMP
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id), days(event_date))
LOCATION 's3://cdp/warehouse/cdp.gold.demo_user_behavior'
TBLPROPERTIES (
    'format-version' = '2'
);


-- Gold: session funnel  (grain: batch_id / namespace / user_id / session_id)
-- Steps must have event_time strictly increasing; count sessions once per step.
CREATE TABLE IF NOT EXISTS cdp.gold.demo_session_funnel (
    batch_id        STRING  NOT NULL,
    event_date      DATE    NOT NULL,
    namespace       STRING  NOT NULL,
    user_id         STRING  NOT NULL,
    session_id      STRING  NOT NULL,
    step_view       BIGINT  DEFAULT 0,   -- 1 if session has at least 1 product_view
    step_cart       BIGINT  DEFAULT 0,   -- 1 if session has add_to_cart after step_view
    step_purchase   BIGINT  DEFAULT 0,   -- 1 if session has purchase_observed after step_cart
    first_view_at   TIMESTAMP,
    first_cart_at   TIMESTAMP,
    first_purchase_at TIMESTAMP
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id), days(event_date))
LOCATION 's3://cdp/warehouse/cdp.gold.demo_session_funnel'
TBLPROPERTIES (
    'format-version' = '2'
;


-- Example aggregation query (read-only, for verification)
-- SELECT
--     batch_id,
--     SUM(step_view)  AS sessions_viewed,
--     SUM(step_cart)  AS sessions_cart,
--     SUM(step_purchase) AS sessions_purchased,
--     ROUND(SUM(step_cart) * 100.0 / NULLIF(SUM(step_view), 0), 2) AS view_to_cart_pct,
--     ROUND(SUM(step_purchase) * 100.0 / NULLIF(SUM(step_cart), 0), 2) AS cart_to_purchase_pct
-- FROM cdp.gold.demo_session_funnel
-- GROUP BY batch_id
-- ORDER BY batch_id;
