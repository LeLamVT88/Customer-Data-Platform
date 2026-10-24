-- src/demo/lakehouse/sql/03_gold.sql
-- Iceberg DDL for Gold tables:
--   cdp.gold.demo_user_behavior — tổng hợp hành vi theo user
--   cdp.gold.demo_session_funnel — phễu hành vi theo session
--
-- Lưu ý: purchase_observed là sự kiện "quan sát được", không phải đơn hàng
-- đã xác nhận. Không suy ra doanh thu thực từ bảng này.

-- Gold: hành vi theo người dùng
CREATE TABLE IF NOT EXISTS cdp.gold.demo_user_behavior (
    batch_id        STRING    NOT NULL,
    event_date      DATE      NOT NULL,
    user_id         STRING    NOT NULL,
    session_count   BIGINT,
    event_count     BIGINT,
    page_views      BIGINT,
    product_views   BIGINT,
    searches        BIGINT,
    add_to_cart     BIGINT,
    remove_from_cart BIGINT,
    begin_checkout  BIGINT,
    purchases       BIGINT,
    cart_abandoned  BIGINT,
    wishlist_add    BIGINT,
    first_event_at  TIMESTAMP,
    last_event_at   TIMESTAMP
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id), days(event_date))
LOCATION 's3://cdp/warehouse/cdp.gold.demo_user_behavior'
TBLPROPERTIES (
    'format-version' = '2'
);


-- Gold: phễu hành vi theo session
-- Grain: batch_id / user_id / session_id
-- Mỗi bước chỉ tính 1 lần, và phải xảy ra sau bước trước (event_time tăng dần).
CREATE TABLE IF NOT EXISTS cdp.gold.demo_session_funnel (
    batch_id         STRING    NOT NULL,
    event_date       DATE      NOT NULL,
    user_id          STRING    NOT NULL,
    session_id       STRING    NOT NULL,
    step_view        BIGINT,   -- 1 nếu session có product_view
    step_cart        BIGINT,   -- 1 nếu có add_to_cart sau product_view
    step_checkout    BIGINT,   -- 1 nếu có begin_checkout sau add_to_cart
    step_purchase    BIGINT,   -- 1 nếu có purchase_observed sau checkout
    step_abandoned   BIGINT,   -- 1 nếu có cart_abandoned
    first_view_at    TIMESTAMP,
    first_cart_at    TIMESTAMP,
    first_checkout_at TIMESTAMP,
    first_purchase_at TIMESTAMP,
    first_abandoned_at TIMESTAMP
)
USING iceberg
PARTITIONED BY (bucket(16, batch_id), days(event_date))
LOCATION 's3://cdp/warehouse/cdp.gold.demo_session_funnel'
TBLPROPERTIES (
    'format-version' = '2'
);


-- Example aggregation query (read-only, for verification)
-- SELECT
--     batch_id,
--     SUM(step_view)      AS sessions_viewed,
--     SUM(step_cart)      AS sessions_cart,
--     SUM(step_checkout)  AS sessions_checkout,
--     SUM(step_purchase)  AS sessions_purchased,
--     ROUND(SUM(step_cart) * 100.0 / NULLIF(SUM(step_view), 0), 2) AS view_to_cart_pct,
--     ROUND(SUM(step_purchase) * 100.0 / NULLIF(SUM(step_cart), 0), 2) AS cart_to_purchase_pct
-- FROM cdp.gold.demo_session_funnel
-- GROUP BY batch_id
-- ORDER BY batch_id;
