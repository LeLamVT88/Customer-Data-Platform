"""End-to-end source acceptance; requires runtime up. Artifacts go to data/source-runs/."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

import httpx
from kafka import KafkaConsumer, TopicPartition

from src.demo.api.business import connect
from src.demo.sources.generate import generate
from src.demo.sources.runtime import COMPOSE, connector_ready
from src.demo.snowplow.tp2 import SnowplowCollector, build_event

ROOT = Path(__file__).resolve().parents[3]


def eventually(probe, description, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(1)
    raise AssertionError(f'Timeout: {description}')


def query(sql, params=()):
    with connect() as conn:
        return conn.execute(sql, params or None).fetchall()


def cdc_rows(table, field, value):
    # Table/field are fixed test constants; value is parameterized.
    return query("SELECT decoded FROM observer.kafka_records WHERE topic=%s AND "
                 "(decoded->'after'->>%s=%s OR decoded->'before'->>%s=%s) ORDER BY partition,offset_id",
                 (f'cdp.business.public.{table}', field, value, field, value))


def cdc_until(table, field, value, predicate):
    rows = cdc_rows(table, field, value)
    return rows if predicate(rows) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart-kafka', action='store_true', help='Also prove persisted Kafka bytes survive restart')
    args = parser.parse_args()
    run_id = f'acceptance-{uuid.uuid4()}'
    output = ROOT / 'data/source-runs' / run_id
    output.mkdir(parents=True, exist_ok=True)
    report = {'run_id': run_id, 'started_at': datetime.now(timezone.utc).isoformat(), 'checks': {}, 'passed': False}

    def check(name, condition, evidence):
        report['checks'][name] = {'passed': bool(condition), 'evidence': evidence}
        if not condition:
            raise AssertionError(name)

    try:
        check('connector_running', connector_ready(), 'Debezium connector and task RUNNING')
        # A dedicated initial-only connector proves snapshots even on a reused database.
        # It never resets the main connector's WAL offsets or replication slot.
        snapshot_name = 'proof-' + uuid.uuid4().hex
        snapshot_start = int(time.time() * 1000)
        config = json.loads((ROOT / 'config/kafka/business-connector.json').read_text())
        config.update({'topic.prefix': 'cdp.snapshot', 'snapshot.mode': 'initial_only',
                       'slot.name': snapshot_name.replace('-', '_'), 'slot.drop.on.stop': 'true',
                       'publication.name': 'cdp_snapshot_proof', 'table.include.list': 'public.products',
                       'heartbeat.interval.ms': '0'})
        response = httpx.post('http://127.0.0.1:8083/connectors',
                              json={'name': snapshot_name, 'config': config}, timeout=30)
        response.raise_for_status()
        try:
            expected_products = query("SELECT product_id,price::text AS price FROM products ORDER BY product_id")
            def read_snapshot():
                rows = query("SELECT decoded->'after' AS product FROM observer.kafka_records "
                             "WHERE topic='cdp.snapshot.public.products' AND decoded->>'op'='r' "
                             "AND (decoded->'source'->>'ts_ms')::bigint >= %s", (snapshot_start,))
                return rows if len(rows) >= len(expected_products) else None
            snapshot = eventually(read_snapshot, 'initial product snapshot')
            actual_products = {r['product']['product_id']: r['product']['price'] for r in snapshot}
            check('initial_snapshot', actual_products == {r['product_id']: r['price'] for r in expected_products},
                  {'expected': len(expected_products), 'actual': len(actual_products), 'mode': 'initial_only'})
        finally:
            httpx.delete(f'http://127.0.0.1:8083/connectors/{snapshot_name}', timeout=30).raise_for_status()
        manifest = generate(users=4, seed=42, run_id=run_id)
        expected = {e['event_id'] for e in manifest['events']}
        events = eventually(lambda: (rows if len(rows := query(
            'SELECT event_id,event_name,event_json,session_id,user_id FROM observer.events WHERE run_id=%s AND NOT failed',
            (run_id,))) >= len(expected) else None), 'all journey events enriched')
        check('good_event_ids', {e['event_id'] for e in events} == expected,
              {'expected': len(expected), 'actual': len(events)})
        observed = {e['event_id']: e for e in events}
        check('identity_on_events', all(observed[e['event_id']]['session_id'] == e['session_id'] and
                                       observed[e['event_id']]['user_id'] == e['customer_id'] for e in manifest['events']),
              'anonymous events have no authenticated user; login binds subsequent events')
        for order in manifest['orders']:
            rows = eventually(lambda: cdc_until('orders', 'order_id', order['order_id'], lambda rows: any(
                r['decoded']['op'] == 'u' and r['decoded']['after']['status'] == 'PAID' for r in rows)), 'order CDC PAID')
            check('order_insert_update', {'c', 'u'} <= {r['decoded']['op'] for r in rows}, [r['decoded']['op'] for r in rows])
            db = query('SELECT status,total_price::text AS total_price,currency FROM orders WHERE order_id=%s', (order['order_id'],))[0]
            check('authoritative_order', all(db[k] == order[k] for k in db), db)
            items = eventually(lambda: cdc_rows('order_items', 'order_id', order['order_id']), 'order items CDC')
            check('order_items', len(items) == len(order['items']), {'expected': len(order['items']), 'actual': len(items)})
        customer = manifest['customers'][0]
        links = eventually(lambda: cdc_rows('identity_links', 'link_id', customer['link_id']), 'identity CDC')
        link = links[0]['decoded']['after']
        check('authenticated_link', all(link[k] == customer[k] for k in ('customer_id', 'session_id', 'anonymous_id')) and
              link['evidence'] == 'authenticated_login', link)
        customers = eventually(lambda: cdc_rows('customers', 'customer_id', customer['customer_id']), 'customer CDC')
        check('no_auth_secrets_in_cdc', all('password_hash' not in str(r['decoded']) for r in customers) and
              not query("SELECT topic FROM observer.kafka_records WHERE topic LIKE '%auth_sessions%'"),
              'password_hash excluded; auth_sessions absent')

        # API invariants against the real database, with an isolated HTTP cookie jar.
        with httpx.Client(base_url='http://127.0.0.1:8000', timeout=30) as client:
            check('auth_required', client.get('/api/orders').status_code == 401, 'GET /api/orders without cookie -> 401')
            credentials = {'email': customer['email'], 'password': 'Local-demo-password-42',
                           'anonymous_id': customer['anonymous_id'], 'session_id': customer['session_id'], 'run_id': run_id}
            response = client.post('/api/auth/login', json={**credentials, 'password': 'wrong-password'})
            check('wrong_password', response.status_code == 401, response.status_code)
            client.post('/api/auth/login', json=credentials).raise_for_status()
            order = manifest['orders'][0]
            retry_body = {'items': [{'product_id': i['product_id'], 'quantity': i['quantity']} for i in order['items']],
                          'run_id': run_id}
            def retry_order(_):
                response = client.post('/api/orders', json=retry_body, headers={'Idempotency-Key': f'{run_id}:1'})
                response.raise_for_status()
                return response.json()['order_id']
            with ThreadPoolExecutor(max_workers=4) as pool:
                retried_ids = list(pool.map(retry_order, range(4)))
            check('concurrent_idempotent_retries', set(retried_ids) == {order['order_id']} and
                  query('SELECT count(*) AS n FROM orders WHERE run_id=%s', (run_id,))[0]['n'] == 1,
                  {'requests': 4, 'distinct_order_ids': len(set(retried_ids))})
            response = client.patch(f'/api/orders/{order["order_id"]}/status', json={'status': 'CANCELLED'})
            check('invalid_status_transition', response.status_code == 409, 'PAID -> CANCELLED rejected')
            response = client.post('/api/orders', json={'items': [{'product_id': order['items'][0]['product_id'], 'quantity': 99}],
                                                      'run_id': run_id}, headers={'Idempotency-Key': f'{run_id}:1'})
            check('idempotency_conflict', response.status_code == 409, response.status_code)
            client.post('/api/auth/logout').raise_for_status()
            check('logout_revokes_session', client.get('/api/auth/me').status_code == 401, 'old session revoked')

        # Isolated row exercises all WAL operations; no catalog product is modified.
        product_id = f'probe-{uuid.uuid4()}'
        with connect() as conn:
            conn.execute("INSERT INTO products VALUES(%s,'probe','probe',1.00,'USD',NULL,true)", (product_id,))
        with connect() as conn:
            conn.execute('UPDATE products SET price=2.00 WHERE product_id=%s', (product_id,))
        with connect() as conn:
            conn.execute('DELETE FROM products WHERE product_id=%s', (product_id,))
        rows = eventually(lambda: cdc_until('products', 'product_id', product_id,
                                  lambda rows: {'c','u','d'} <= {r['decoded']['op'] for r in rows}), 'CDC insert/update/delete')
        check('wal_operations', True, [r['decoded']['op'] for r in rows])
        tombstone = eventually(lambda: query("SELECT offset_id FROM observer.kafka_records WHERE "
                                            "topic='cdp.business.public.products' AND value_bytes IS NULL "
                                            "AND convert_from(key_bytes,'UTF8')::jsonb->>'product_id'=%s", (product_id,)), 'delete tombstone')
        check('delete_tombstone', True, tombstone)
        check('delete_before_image', any(r['decoded']['op']=='d' and r['decoded']['before']['price']=='2.00' for r in rows),
              'delete before image retained')
        invalid = build_event('product_view', {'unexpected_field': 'invalid'}, session_id=str(uuid.uuid4()), run_id=run_id)
        with SnowplowCollector() as collector:
            check('invalid_transport_accepted', collector.send_one(invalid), invalid['eid'])
        bad = eventually(lambda: query("SELECT topic,decoded FROM observer.kafka_records WHERE topic='cdp.web.bad' "
                                      "AND decoded::text LIKE %s", (f'%{invalid["eid"]}%',)), 'invalid event in bad stream with reason')
        (output / 'bad-event.json').write_text(json.dumps(bad, indent=2, default=str))
        check('bad_event_preserved', bool(bad[0]['decoded']), 'bad-event.json contains original payload and failure reason')
        check('invalid_not_good', not query('SELECT event_id FROM observer.events WHERE event_id=%s AND NOT failed',
                                          (invalid['eid'],)), 'invalid event absent from good projection')
        check('dashboard', httpx.get('http://127.0.0.1:8000/api/summary').json()['snowplow_available'], 'observer available')
        if args.restart_kafka:
            record = query("SELECT topic,partition,offset_id,key_bytes,value_bytes FROM observer.kafka_records "
                           "WHERE topic='cdp.web.good' ORDER BY observed_at DESC LIMIT 1")[0]
            subprocess.run([*COMPOSE, 'restart', 'kafka'], check=True)
            consumer = KafkaConsumer(bootstrap_servers='127.0.0.1:19092', api_version=(4, 0), enable_auto_commit=False,
                                     group_id=None, request_timeout_ms=30000, api_version_auto_timeout_ms=60000)
            try:
                partition = TopicPartition(record['topic'], record['partition'])
                consumer.assign([partition])
                consumer.seek(partition, record['offset_id'])
                actual = eventually(lambda: next((r for batch in consumer.poll(timeout_ms=1000).values() for r in batch
                                                  if r.offset == record['offset_id']), None), 'persisted record after restart')
                check('kafka_restart_persistence', actual.value == bytes(record['value_bytes']) and actual.key == record['key_bytes'],
                      {'topic': record['topic'], 'partition': record['partition'], 'offset': record['offset_id'],
                       'sha256': hashlib.sha256(actual.value).hexdigest()})
            finally:
                consumer.close()
            eventually(connector_ready, 'connector recovers after broker restart')
            # Verify producers and Enrich can process new messages after reconnecting.
            with SnowplowCollector() as collector:
                event = build_event('page_view', {'path': '/recovered'}, run_id=run_id)
                if not collector.send_one(event):
                    raise AssertionError('collector after restart')
            eventually(lambda: query('SELECT event_id FROM observer.events WHERE event_id=%s', (event['eid'],)), 'pipeline after restart')
            check('pipeline_recovers', True, event['eid'])
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        (output / 'acceptance.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        print(f'Acceptance {"PASS" if report["passed"] else "FAIL"}: {output / "acceptance.json"}')


if __name__ == '__main__':
    main()
