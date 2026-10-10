-- Observed behavior only: purchase events are not confirmed orders.
SELECT batch_id, source_namespace, source_user_id,
       min(event_at) AS first_seen_at, max(event_at) AS last_seen_at,
       count(*) AS event_count,
       count(DISTINCT CASE WHEN trim(source_session_id) <> '' THEN source_session_id END) AS session_count,
       sum(CASE WHEN event_name = 'product_view' THEN 1 ELSE 0 END) AS view_count,
       sum(CASE WHEN event_name = 'add_to_cart' THEN 1 ELSE 0 END) AS cart_count,
       sum(CASE WHEN event_name = 'purchase_observed' THEN 1 ELSE 0 END) AS purchase_event_count
FROM source_silver
GROUP BY batch_id, source_namespace, source_user_id
