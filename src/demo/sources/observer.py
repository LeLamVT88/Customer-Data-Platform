"""Read-only Kafka observer for the demo dashboard; not a Lakehouse layer.

Every transport record is retained before projecting good events. PostgreSQL
commits precede Kafka offset commits, so retries are safe by topic/partition/offset.
"""
import base64
import hashlib
import json
import logging
import os
import signal

from kafka import KafkaConsumer
from psycopg.types.json import Jsonb
from snowplow_analytics_sdk.event_transformer import transform

from src.demo.api.business import connect

BOOTSTRAP = os.getenv("CDP_KAFKA_BOOTSTRAP", "127.0.0.1:19092")
TOPICS = ["cdp.web.raw", "cdp.web.good", "cdp.web.bad", "cdp.web.failed", "cdp.web.collector_bad", "cdp.snapshot.public.products"] + [
    f"cdp.business.public.{t}" for t in ("customers", "products", "orders", "order_items", "identity_links")
]


def decode(topic, value):
    if value is None:
        return None
    if topic == "cdp.web.good":
        return transform(value.decode())
    if topic != "cdp.web.raw":
        return json.loads(value)
    return None


def context(event, name):
    return (event.get(f"contexts_com_cdp_demo_{name}_1") or [{}])[0]


def store_records(conn, records):
    for record in records:
        error = None
        try:
            decoded = decode(record.topic, record.value)
        except Exception as exc:
            decoded, error = None, str(exc)
        headers = [[key, base64.b64encode(value).decode() if value is not None else None]
                   for key, value in record.headers]
        inserted = conn.execute(
            "INSERT INTO observer.kafka_records(topic,partition,offset_id,kafka_timestamp,key_bytes,value_bytes,headers,decoded,decode_error) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING offset_id",
            (record.topic, record.partition, record.offset, record.timestamp, record.key, record.value,
             Jsonb(headers), Jsonb(decoded), error),
        ).fetchone()
        if not inserted:
            continue
        if record.topic == "cdp.web.good" and decoded:
            event = decoded
            source = context(event, "source")
            session = context(event, "session")
            conn.execute(
                "INSERT INTO observer.events(event_id,timestamp,event_json,failed,app_id,event_name,user_id,domain_userid,"
                "name_tracker,run_id,session_id,persona) VALUES(%s,%s,%s,false,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(event_id) DO NOTHING",
                (event["event_id"], event.get("collector_tstamp"), Jsonb(event), event.get("app_id"),
                 event.get("event_name"), event.get("user_id"), event.get("domain_userid"), event.get("name_tracker"),
                 source.get("run_id"), session.get("session_id"), source.get("persona")),
            )
        elif record.topic in ("cdp.web.bad", "cdp.web.collector_bad", "cdp.web.failed"):
            failed_id = hashlib.sha256(f"{record.topic}:{record.partition}:{record.offset}".encode()).hexdigest()
            conn.execute(
                "INSERT INTO observer.events(event_id,timestamp,event_json,failed,app_id,event_name) "
                "VALUES(%s,to_timestamp(%s/1000.0),%s,true,'cdp-demo','enrichment_failed') ON CONFLICT DO NOTHING",
                (failed_id, record.timestamp, Jsonb(decoded or {"decode_error": error})),
            )


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("kafka").setLevel(logging.WARNING)
    stop = False

    def halt(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, halt)
    signal.signal(signal.SIGINT, halt)
    # Pin protocol capabilities for the Kafka 4.x stack across reconnects.
    consumer = KafkaConsumer(*TOPICS, bootstrap_servers=BOOTSTRAP, api_version=(4, 0), group_id=os.getenv("CDP_OBSERVER_GROUP", "cdp-dashboard-observer-v1"),
                             enable_auto_commit=False, auto_offset_reset="earliest", max_poll_records=500)
    try:
        while not stop:
            batches = consumer.poll(timeout_ms=1000)
            records = [r for batch in batches.values() for r in batch]
            if not records:
                continue
            with connect() as conn:
                store_records(conn, records)
            consumer.commit()
            logging.info("Observed %d Kafka records", len(records))
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
