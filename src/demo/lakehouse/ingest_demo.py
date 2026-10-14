"""
src/demo/lakehouse/ingest_demo.py

⚠️  NOT EXECUTED — requires the existing Lakehouse stack (Spark + Iceberg + S3).

This file mirrors the structure of src/pipelines/lakehouse/run_rees46.py to
ingest demo events from data/demo-events/<batch-id>/ into Iceberg.

Namespaces / tables written:
  cdp.bronze.demo_events
  cdp.silver.demo_events
  cdp.silver.demo_quarantine
  cdp.gold.demo_user_behavior
  cdp.gold.demo_session_funnel

To execute this, the Lakehouse must be running:
    docker compose -f config/docker/compose.local-lakehouse.yml up -d
    sh src/tools/run_local_lakehouse.sh data/demo-events/<batch-id>

After running, export Gold with:
    docker compose -f config/docker/compose.local-lakehouse.yml run --rm spark \\
      /workspace/src/pipelines/lakehouse/export_gold.py --batch-id <batch-id>
"""

from __future__ import annotations

import json
from pathlib import Path

# ── Batch metadata ──────────────────────────────────────────────────────────────

BATCH_ROOT = Path(__file__).resolve().parents[2] / "data" / "demo-events"


def load_manifest(batch_id: str) -> dict:
    path = BATCH_ROOT / batch_id / "manifest.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Spark ingestion (copy-paste from run_rees46.py, adapted) ──────────────────

# NOTE: This is a scaffold.  The actual Spark code follows the same pattern as
# run_rees46.py (Bronze → Silver → Quarantine → Gold).  Key differences:
#
#   - Source path:  data/demo-events/<batch_id>/events.csv
#   - Partition by:  batch_id  (Bronze),  batch_id + days(event_at)  (Silver/Gold)
#   - Column names:  match the demo event schema (product_view, add_to_cart, etc.)
#   - No brand/category_code normalisation needed (catalog is pre-loaded JSON)
#
# The Bronze writer should:
#   • Read CSV with all columns from events.csv
#   • Add ordinal (already in CSV), batch_id, namespace
#   • Write to cdp.bronze.demo_events  partitioned by batch_id
#
# The Silver writer should:
#   • Read Bronze
#   • Validate: event_type in SUPPORTED, event_time valid ISO, session_id present
#   • Map event_type (already normalised in demo events)
#   • Flag: missing_session, zero_price, etc.
#   • Write to cdp.silver.demo_events
#
# The Quarantine writer:
#   • Route: bad event_type, missing session_id, bad timestamp
#   • Write to cdp.silver.demo_quarantine
#
# The Gold writers:
#   • cdp.gold.demo_user_behavior   — one row per user, counts by event_type
#   • cdp.gold.demo_session_funnel  — funnel view → cart → purchase per session
#       Funnel grain: batch_id / namespace / user_id / session_id
#       Steps require event_time strictly increasing (no ordinal trick)
#       Count each session once per step


def run_ingestion(batch_id: str) -> dict:
    """
    Main entry-point for the Spark job.
    Returns a dict with counts matching the pattern of run_rees46.py.
    """
    manifest = load_manifest(batch_id)
    events_csv = BATCH_ROOT / batch_id / "events.csv"
    q_csv = BATCH_ROOT / batch_id / "quarantine.csv"

    if not events_csv.exists():
        raise FileNotFoundError(f"Events CSV not found: {events_csv}")

    # TODO (requires Spark):
    #   1. spark.read.csv(events_csv)  → bronze
    #   2. bronze.write.to_iceberg("cdp.bronze.demo_events", partition_by="batch_id")
    #   3. Read bronze, normalise → silver
    #   4. silver.write.to_iceberg("cdp.silver.demo_events", partition_by=["batch_id", "event_date"])
    #   5. Route quarantine rows → cdp.silver.demo_quarantine
    #   6. Aggregate → cdp.gold.demo_user_behavior
    #   7. Aggregate → cdp.gold.demo_session_funnel
    #   8. Return manifest-style dict with counts

    raise NotImplementedError(
        "M4 scaffold: run Spark + Iceberg locally to execute. "
        "See src/pipelines/lakehouse/run_rees46.py for the exact pattern to replicate."
    )


# ── Stub for CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest demo events into Iceberg")
    parser.add_argument("--batch-id", required=True, help="Demo batch ID (folder name under data/demo-events/)")
    args = parser.parse_args()
    result = run_ingestion(args.batch_id)
    print(json.dumps(result, indent=2, default=str))
