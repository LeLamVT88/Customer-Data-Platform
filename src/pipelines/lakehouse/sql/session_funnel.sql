-- One row per batch/source/user/session. Strict timestamps establish order.
-- Earliest qualifying step is sufficient to find any valid view -> cart -> purchase chain.
WITH sessions AS (
    SELECT batch_id, source_namespace, source_user_id, source_session_id,
           min(CASE WHEN event_name = 'product_view' THEN event_at END) AS first_view_at
    FROM source_silver
    WHERE source_session_id IS NOT NULL AND trim(source_session_id) <> ''
    GROUP BY batch_id, source_namespace, source_user_id, source_session_id
), carts AS (
    SELECT s.*, min(e.event_at) AS first_cart_after_view_at
    FROM sessions s
    LEFT JOIN source_silver e
      ON s.batch_id = e.batch_id AND s.source_namespace = e.source_namespace
     AND s.source_user_id = e.source_user_id AND s.source_session_id = e.source_session_id
     AND e.event_name = 'add_to_cart' AND e.event_at > s.first_view_at
    GROUP BY s.batch_id, s.source_namespace, s.source_user_id, s.source_session_id, s.first_view_at
), purchases AS (
    SELECT c.*, min(e.event_at) AS first_purchase_after_cart_at
    FROM carts c
    LEFT JOIN source_silver e
      ON c.batch_id = e.batch_id AND c.source_namespace = e.source_namespace
     AND c.source_user_id = e.source_user_id AND c.source_session_id = e.source_session_id
     AND e.event_name = 'purchase_observed' AND e.event_at > c.first_cart_after_view_at
    GROUP BY c.batch_id, c.source_namespace, c.source_user_id, c.source_session_id,
             c.first_view_at, c.first_cart_after_view_at
)
SELECT *, first_view_at IS NOT NULL AS has_view,
          first_cart_after_view_at IS NOT NULL AS has_cart_after_view,
          first_purchase_after_cart_at IS NOT NULL AS has_purchase_after_cart
FROM purchases
