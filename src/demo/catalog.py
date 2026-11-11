"""Load the seed catalog independently of the HTTP application."""
import json
import threading
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[2] / "config/demo/catalog.products.json"
_catalog: list[dict] = []
_catalog_lock = threading.Lock()


def load_catalog() -> list[dict]:
    with _catalog_lock:
        if not _catalog and CATALOG_PATH.exists():
            with CATALOG_PATH.open(encoding="utf-8") as source:
                _catalog.extend(json.load(source))
        return _catalog
