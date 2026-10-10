SELECT event_id, batch_id, source_namespace, source_sha256, source_row_number,
       ingested_at, event_at, event_name, event_type AS source_event_type,
       '1-0-0' AS contract_version,
       user_id AS source_user_id, user_session AS source_session_id,
       cast(NULL AS STRING) AS verified_customer_id,
       product_id, category_id, category_code, brand,
       price_decimal AS price, cast(NULL AS STRING) AS currency, quality_flags
FROM checked_events
WHERE size(error_reasons) = 0
