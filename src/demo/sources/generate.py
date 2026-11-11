"""Generate linked behavior/customer/order journeys through the public source APIs."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import random
import uuid

import httpx

from src.demo.snowplow.tp2 import COLLECTOR_URL, SnowplowCollector, build_event

ROOT = Path(__file__).resolve().parents[3]
PERSONAS = ('lina', 'minh', 'hoa', 'quang')


def generate(users=4, seed=42, api_url='http://127.0.0.1:8000', collector_url=COLLECTOR_URL, run_id=None):
    if users < 1:
        raise ValueError('users must be positive')
    run_id = run_id or f'journey-{uuid.uuid4()}'
    rng = random.Random(seed)
    manifest = {'run_id': run_id, 'seed': seed, 'created_at': datetime.now(timezone.utc).isoformat(),
                'events': [], 'customers': [], 'orders': [], 'sessions': []}
    with httpx.Client(base_url=api_url, timeout=30) as catalog_client:
        response = catalog_client.get('/api/catalog')
        response.raise_for_status()
        catalog = sorted(response.json(), key=lambda p: p['product_id'])
    if not catalog:
        raise RuntimeError('Catalog is empty')
    for index in range(users):
        persona = PERSONAS[index % len(PERSONAS)]
        anonymous = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{run_id}:anonymous:{index}'))
        session = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{run_id}:session:{index}'))
        product = rng.choice(catalog)
        customer_id = None
        manifest['sessions'].append({'session_id': session, 'anonymous_id': anonymous, 'persona': persona})
        with httpx.Client(base_url=api_url, timeout=30) as api, SnowplowCollector(collector_url) as collector:
            def call(method, path, **kwargs):
                response = api.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            def emit(name, data, entity=None):
                event = build_event(name, data, user_id=customer_id, anonymous_id=anonymous, customer_id=customer_id,
                                    session_id=session, run_id=run_id, persona=persona, product=entity)
                if not collector.send_one(event):
                    raise RuntimeError(f'Collector rejected {name}')
                manifest['events'].append({'event_id': event['eid'], 'event_name': name, 'session_id': session,
                                           'customer_id': customer_id, 'persona': persona})

            emit('page_view', {'path': '/', 'title': 'Source journey'})
            emit('product_view', {'product_id': product['product_id'], 'category_id': product['category_id']}, product)
            if persona == 'hoa':
                emit('search', {'query': product['brand'], 'results_count': 1, 'type': 'catalog_search'})
                emit('wishlist_add', {k: product[k] for k in ('product_id', 'price', 'currency')}, product)
            if persona in ('minh', 'quang'):
                item = {k: product[k] for k in ('product_id', 'price', 'currency')}
                item['quantity'] = rng.randint(1, 3)
                emit('add_to_cart', item, product)
                total = str((Decimal(item['price']) * item['quantity']).quantize(Decimal('.01')))
                if persona == 'quang':
                    emit('cart_abandoned', {'items': [item], 'total_price': total, 'currency': product['currency']})
                else:
                    credentials = {'email': f'{anonymous}@example.test', 'password': 'Local-demo-password-42'}
                    customer = call('POST', '/api/auth/register', json={**credentials, 'name': f'Minh {index}', 'run_id': run_id})
                    auth = call('POST', '/api/auth/login', json={**credentials, 'anonymous_id': anonymous,
                                                              'session_id': session, 'run_id': run_id})
                    customer_id = auth['customer_id']
                    manifest['customers'].append({**customer, 'link_id': auth['link_id'], 'anonymous_id': anonymous,
                                                  'session_id': session})
                    emit('identity_authenticated', {'customer_id': customer_id, 'link_id': auth['link_id']})
                    body = {'items': [{'product_id': item['product_id'], 'quantity': item['quantity']}], 'run_id': run_id}
                    headers = {'Idempotency-Key': f'{run_id}:{index}'}
                    order = call('POST', '/api/orders', json=body, headers=headers)
                    retry = call('POST', '/api/orders', json=body, headers=headers)
                    if retry['order_id'] != order['order_id']:
                        raise AssertionError('Idempotent retry created a second order')
                    payload = {k: order[k] for k in ('order_id', 'items', 'total_price', 'currency')}
                    payload['cart_id'] = order['order_id']
                    emit('begin_checkout', payload)
                    paid = call('PATCH', f'/api/orders/{order["order_id"]}/status', json={'status': 'PAID'})
                    emit('purchase_observed', payload)
                    manifest['orders'].append(paid)
                    call('POST', '/api/auth/logout')
    manifest['counts'] = dict(Counter(e['event_name'] for e in manifest['events']))
    path = ROOT / 'data/source-runs' / run_id / 'ground-truth.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Generated {len(manifest["events"])} events, {len(manifest["orders"])} orders: {path}')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users', type=int, default=4)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--collector', default=COLLECTOR_URL)
    args = parser.parse_args()
    generate(args.users, args.seed, args.api, args.collector)


if __name__ == '__main__':
    main()
