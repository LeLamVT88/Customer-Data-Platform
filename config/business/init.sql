CREATE TABLE customers (
  customer_id UUID PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  run_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE products (
  product_id TEXT PRIMARY KEY,
  category_id TEXT NOT NULL,
  brand TEXT NOT NULL,
  price NUMERIC(18,2) NOT NULL CHECK (price >= 0),
  currency TEXT NOT NULL,
  image_url TEXT,
  active BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE auth_sessions (
  token_hash TEXT PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customers,
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE identity_links (
  link_id UUID PRIMARY KEY,
  anonymous_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  customer_id UUID NOT NULL REFERENCES customers,
  run_id TEXT NOT NULL,
  evidence TEXT NOT NULL CHECK (evidence = 'authenticated_login'),
  linked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE orders (
  order_id UUID PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customers,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('CREATED','PAID','CANCELLED','REFUNDED')),
  total_price NUMERIC(18,2) NOT NULL CHECK (total_price >= 0),
  currency TEXT NOT NULL,
  run_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (customer_id, idempotency_key)
);
CREATE TABLE order_items (
  order_id UUID NOT NULL REFERENCES orders,
  product_id TEXT NOT NULL REFERENCES products,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(18,2) NOT NULL,
  currency TEXT NOT NULL,
  PRIMARY KEY (order_id, product_id)
);
-- CDC deliberately excludes password hashes and auth_sessions.
ALTER TABLE customers REPLICA IDENTITY FULL;
ALTER TABLE products REPLICA IDENTITY FULL;
ALTER TABLE orders REPLICA IDENTITY FULL;
ALTER TABLE order_items REPLICA IDENTITY FULL;
ALTER TABLE identity_links REPLICA IDENTITY FULL;
CREATE SCHEMA observer;
CREATE TABLE observer.kafka_records (
  topic TEXT NOT NULL, partition INTEGER NOT NULL, offset_id BIGINT NOT NULL,
  kafka_timestamp BIGINT, key_bytes BYTEA, value_bytes BYTEA, headers JSONB NOT NULL,
  decoded JSONB, decode_error TEXT, observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (topic, partition, offset_id)
);
CREATE TABLE observer.events (
  event_id TEXT PRIMARY KEY,
  timestamp TIMESTAMPTZ NOT NULL,
  event_json JSONB NOT NULL,
  failed BOOLEAN NOT NULL,
  app_id TEXT,
  event_name TEXT,
  user_id TEXT,
  domain_userid TEXT,
  name_tracker TEXT,
  run_id TEXT,
  session_id TEXT,
  persona TEXT
);
CREATE INDEX ON observer.events (timestamp);
CREATE INDEX ON observer.events (run_id);
