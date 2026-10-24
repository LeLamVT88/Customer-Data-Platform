# src/demo/bot/README.md

# CDP Demo Bot Driver

Synthetic user traffic generator for the Customer Data Platform demo pipeline.

The bot speaks **Snowplow Tracker Protocol 2 (TP2)** and posts directly to the
Snowplow Micro collector. It never calls the demo API — Snowplow owns event
collection, validation and enrichment end to end.

```
bot ──TP2 POST──▶ Snowplow Micro :9090 ──▶ Enrich ──▶ PostgreSQL `events`
```

## Quick start

```powershell
# Terminal 1 — start the Snowplow stack (collector + PostgreSQL storage)
docker compose -f config/docker/compose.snowplow.yml up -d --wait

# Terminal 2 — start the API (read layer, optional for the bot itself)
python -m src.demo.api.server

# Terminal 3 — run the bot
python -m src.demo.bot.driver --users 5            # smoke test
python -m src.demo.bot.driver --users 200          # full run (default)
python -m src.demo.bot.driver --users 200 --rate 10000  # 10k events/min target
```

## Options

| Flag | Default | Description |
|---|---|---|
| `--users N` | 200 | Number of synthetic users |
| `--rate N` | 5000 | Target events/minute across all workers |
| `--seed N` | 42 | Global seed for reproducible runs |
| `--profile NAME` | auto | Force all users to one profile (visitor / cart_abandoner / buyer) |
| `--workers N` | min(users, 50) | Thread pool size |

## Profile mix (default)

| Profile | Weight | Behaviour |
|---|---|---|
| `visitor` | 60% | Browse catalog, view products, no cart |
| `cart_abandoner` | 30% | View → add to cart → abandon at checkout |
| `buyer` | 10% | View → add to cart → checkout → purchase |

The mix is deterministic: the same `--seed` always produces the same profile assignment.

## Output

Each bot run writes run metadata to:

```
data/demo-events/bot-run-YYYYMMDDHHMMSS.json
```

Event payloads themselves are **not** written to local files. They live in the
Snowplow PostgreSQL `events` table, where validation failures are marked with
`failed = true` (the bad stream) instead of a separate quarantine file.

To inspect what a run produced:

```sql
-- events emitted by the bot in the last hour
SELECT event_name, count(*), count(*) FILTER (WHERE failed) AS failed
FROM events
WHERE name_tracker = 'cdpDemoBot'
  AND timestamp >= now() - interval '1 hour'
GROUP BY event_name;
```

## Scenario-based runs

For reproducible funnel tests, use the `scenarios.py` module directly:

```python
from bot.scenarios import get_scenario, list_scenarios
from bot.driver import assign_profiles, run_worker
from bot.profiles import build_profile

scenario = get_scenario("funnel_baseline")
print(scenario["expected"])
```

## Notes

- The bot uses a thread pool (not `asyncio`) to simplify compatibility with
  the existing `.venv` environment.
- Events are sent in micro-batches of TP2 payloads; rate limiting is approximate.
- No external network calls are made by the bot (self-contained).
- The Snowplow collector must be reachable at `http://127.0.0.1:9090`
  (override with `SNOWPLOW_COLLECTOR_URL`).
- The web app URL is only used to fill the `url` field of emitted events
  (override with `CDP_DEMO_WEB_URL`, default `http://localhost:8081/`).
