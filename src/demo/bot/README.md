# src/demo/bot/README.md

# CDP Demo Bot Driver

Synthetic user traffic generator for the Customer Data Platform demo pipeline.

## Quick start

```powershell
# Terminal 1 — start the API
python -m src.demo.api.server

# Terminal 2 — start the web (optional, bot doesn't need it)
cd src/demo/web
python -m http.server 8080

# Terminal 3 — run the bot
python -m src.demo.bot.driver --users 5          # smoke test
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

Each bot run writes metadata to:
```
data/demo-events/bot-run-YYYYMMDDHHMMSS.json
```

Individual event batches are stored by the API at:
```
data/demo-events/<batch-id>/events.csv
data/demo-events/<batch-id>/quarantine.csv
data/demo-events/<batch-id>/manifest.json
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
- Events are sent in micro-batches to the API; rate limiting is approximate.
- No external network calls are made by the bot (self-contained).
- The API must be running at `http://127.0.0.1:8000` (override with
  `CDP_DEMO_API` env var).
