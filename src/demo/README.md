# CDP Demo Website

A synthetic e-commerce demo site that generates typed behavioral events
(`page_view`, `product_view`, `add_to_cart`, `purchase_observed`, etc.) for the
Customer Data Platform pipeline.  Consists of:

| Milestone | Component | Description |
|---|---|---|
| M0 | Product catalog | 500 synthetic products in `config/demo/catalog.products.json` |
| M1 | Static SPA | HTML + ES module JS served via `http.server` |
| M2 | Demo API | FastAPI server: event ingestion, schema checks, idempotency |
| M3 | Bot driver | Python multi-threaded synthetic user generator |
| M4 | Lakehouse scaffold | Spark/Iceberg DDL + ingest script (NOT executed) |

---

## Prerequisites

- Python 3.10+ in `.venv`
- API dependencies installed:
  ```
  pip install -r src/demo/requirements.txt
  ```
- (Optional) Docker + Compose for Lakehouse (M4)

---

## Quick start

### 1 — Start the API

```powershell
# From repo root
python -m src.demo.api.server
```

The API listens on `http://127.0.0.1:8000`.  Endpoints:
- `GET /api/catalog`   — returns the product catalog JSON
- `POST /api/events`   — ingest a batch of events
- `GET /api/summary`   — dashboard counts (most recent batch)
- `GET /health`        — health check

---

### 2 — Start the web UI

```powershell
# In a second terminal
cd src/demo/web
python -m http.server 8080
```

Open `http://localhost:8080` in your browser.

What you can do:
- Browse the catalog (filter by category)
- Click a product → product detail page
- Add items to cart
- Checkout → fires `begin_checkout` + `purchase_observed` events
- Open **Dashboard** to see live event counts

Events are flushed to the API every 5 seconds or on page close.

---

### 3 — Run the bot (optional)

```powershell
# Smoke test (5 users)
python -m src.demo.bot.driver --users 5

# Full run (200 users, ~5000 events/min target)
python -m src.demo.bot.driver --users 200

# 10k events/min with fixed seed
python -m src.demo.bot.driver --users 200 --rate 10000 --seed 99
```

The bot POSTs events directly to the API.  Each run writes metadata to
`data/demo-events/bot-run-*.json`.

---

### 4 — Run API tests

```powershell
python -m unittest src.demo.api.tests.test_ingest -v
```

---

## File layout

```
src/demo/
├── web/
│   ├── index.html          # SPA entry (hash routing: #catalog, #cart, #dashboard…)
│   ├── css/main.css        # Minimal Tailwind-like styles
│   └── js/
│       ├── catalog.js      # Catalog loading, cart, event tracking, routing
│       └── dashboard.js    # Summary fetch + canvas bar chart
├── api/
│   ├── server.py           # FastAPI server (catalog, events, summary)
│   ├── ingest.py           # (logic embedded in server.py)
│   └── tests/
│       └── test_ingest.py  # Schema, idempotency, quarantine tests
├── bot/
│   ├── driver.py           # Multi-threaded user simulator
│   ├── profiles.py          # visitor / cart_abandoner / buyer profiles
│   └── scenarios.py        # Fixed seed scenarios for funnel testing
├── lakehouse/
│   ├── ingest_demo.py      # ⚠️ Scaffold only — requires Lakehouse stack
│   └── sql/
│       ├── 01_bronze.sql   # DDL: cdp.bronze.demo_events
│       ├── 02_silver.sql   # DDL: cdp.silver.demo_events / demo_quarantine
│       └── 03_gold.sql     # DDL: cdp.gold.demo_user_behavior / demo_session_funnel
├── requirements.txt        # API + bot Python deps

config/demo/
├── catalog.products.json    # 500 synthetic products
└── README.md               # Catalog source / seed documentation
```

---

## Dashboard

Open `http://localhost:8080` → click **Dashboard**.

The dashboard fetches `GET /api/summary` every 10 seconds and renders:
- Total event count
- Breakdown by `event_type`
- A bar chart of event volumes (pure canvas, no external library)

If the API is not running, it shows a "cannot connect" message with instructions.

---

## Data contract (demo)

Namespace: `cdp.demo.events`

| Field | Notes |
|---|---|
| `event_id` | `sha256(namespace + batch_checksum + ordinal)` — unique per row |
| `event_time` | ISO 8601 UTC, millisecond precision, client-generated |
| `event_type` | One of 10 supported types (see `server.py`) |
| `session_id` | Required; missing → quarantine |
| `user_id` | Required; missing in strict mode → quarantine |
| `price` | Decimal string; currency must accompany price |
| `currency` | Default `"USD"` |
| `batch_id` | Server-assigned UUID per POST request |
| `ingestion_time` | Server UTC timestamp |
| `quality_flags` | `missing_session`, `missing_user_id`, etc. |

Idempotency: the same POST body (same JSON bytes) always returns the same
`batch_id` and does NOT write new files.

---

## M4 note (Lakehouse)

The `src/demo/lakehouse/` directory is a **scaffold only**.
`ingest_demo.py` is structurally identical to `run_rees46.py` but requires the
Docker-based Lakehouse stack to execute:

```powershell
docker compose -f config/docker/compose.local-lakehouse.yml up -d
# Then run the Spark job pointing at data/demo-events/<batch-id>/
# sh src/tools/run_local_lakehouse.sh data/demo-events/<batch-id>/
```

Until then, events are stored as CSV in `data/demo-events/<batch-id>/`.

---

## Data not committed

`data/demo-events/` is already covered by the project's `.gitignore` (via `/data/`).
Do NOT commit it.  Run metadata files (`bot-run-*.json`) are also excluded.
