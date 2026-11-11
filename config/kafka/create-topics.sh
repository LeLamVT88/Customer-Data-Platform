#!/bin/bash
set -eu
topics=(cdp.web.raw cdp.web.good cdp.web.bad cdp.web.collector_bad cdp.web.failed
  cdp.business.public.customers cdp.business.public.products cdp.business.public.orders
  cdp.business.public.order_items cdp.business.public.identity_links
  __debezium-heartbeat.cdp.business cdp.snapshot.public.products)
for topic in "${topics[@]}"; do
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists \
    --topic "$topic" --partitions 3 --replication-factor 1 \
    --config retention.ms=604800000 --config cleanup.policy=delete
done
for topic in cdp.connect.configs cdp.connect.offsets cdp.connect.status; do
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists \
    --topic "$topic" --partitions 1 --replication-factor 1 --config cleanup.policy=compact
done
