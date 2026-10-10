-- One row per batch, source, UTC date and event name.
SELECT batch_id, source_namespace, cast(event_at AS DATE) AS event_date,
       event_name, count(*) AS event_count,
       count(DISTINCT source_user_id) AS user_count
FROM source_silver
GROUP BY batch_id, source_namespace, cast(event_at AS DATE), event_name
