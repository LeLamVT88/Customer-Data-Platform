-- REES46 source values remain untouched in Bronze.
WITH parsed AS (
    SELECT *,
        try_cast(event_time AS TIMESTAMP) AS event_at,
        try_cast(price AS DECIMAL(18, 2)) AS price_decimal,
        CASE event_type
            WHEN 'view' THEN 'product_view'
            WHEN 'cart' THEN 'add_to_cart'
            WHEN 'purchase' THEN 'purchase_observed'
        END AS event_name
    FROM source_bronze
)
SELECT *,
    filter(array(
        CASE WHEN event_at IS NULL THEN 'invalid_event_time' END,
        CASE WHEN event_type IS NULL OR event_name IS NULL THEN 'unsupported_event_type' END,
        CASE WHEN product_id IS NULL OR trim(product_id) = '' THEN 'missing_product_id' END,
        CASE WHEN user_id IS NULL OR trim(user_id) = '' THEN 'missing_source_user_id' END,
        CASE WHEN price IS NULL OR NOT (price RLIKE '^-?[0-9]+([.][0-9]{1,2})?$')
                  OR price_decimal IS NULL THEN 'invalid_price' END,
        CASE WHEN price_decimal < 0 THEN 'negative_price' END
    ), reason -> reason IS NOT NULL) AS error_reasons,
    filter(array(
        CASE WHEN category_code IS NULL OR trim(category_code) = '' THEN 'missing_category_code' END,
        CASE WHEN brand IS NULL OR trim(brand) = '' THEN 'missing_brand' END,
        CASE WHEN user_session IS NULL OR trim(user_session) = '' THEN 'missing_session' END,
        CASE WHEN price_decimal = 0 THEN 'zero_price' END
    ), flag -> flag IS NOT NULL) AS quality_flags
FROM parsed
