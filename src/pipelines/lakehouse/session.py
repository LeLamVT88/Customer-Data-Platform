"""Shared Spark session factory for the Iceberg lakehouse.

Reads ``config/spark/lakehouse.conf`` and starts a local Spark session wired to
the JDBC catalog (PostgreSQL) and the S3-compatible object storage (MinIO).

The three jars Iceberg needs are shipped in ``tools/jars`` and added to the
classpath explicitly:

* ``iceberg-spark-runtime-3.5_2.12`` - the Iceberg engine for Spark 3.5
* ``iceberg-aws-bundle``              - ``S3FileIO`` for object storage
* ``postgresql``                      - JDBC driver for the catalog
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

import pyspark
from pyspark.sql import SparkSession

REPO_ROOT = Path(__file__).resolve().parents[3]
SPARK_CONF_PATH = REPO_ROOT / "config" / "spark" / "lakehouse.conf"
JARS_DIR = REPO_ROOT / "tools" / "jars"

#: Catalog name used in SQL, e.g. ``cdp.bronze.rees46_events``.
CATALOG = "cdp"


def load_properties(path: Path | None = None) -> dict[str, str]:
    """Parse a Spark properties file into a plain dict."""
    conf_path = path or SPARK_CONF_PATH
    if not conf_path.exists():
        raise FileNotFoundError(f"Spark properties file not found: {conf_path}")

    properties: dict[str, str] = {}
    for raw_line in conf_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        if not value:
            key, _, value = line.partition("=")
        properties[key.strip()] = value.strip()
    return properties


def install_jars() -> list[str]:
    """Copy the Iceberg/AWS/PostgreSQL jars into the PySpark jars directory.

    PySpark builds its classpath from ``pyspark/jars``. Putting the jars
    there avoids ``spark.jars``, which copies every jar into the session temp
    directory and then fails to delete it on Windows because the JVM still
    holds the files open.
    """
    target_dir = Path(pyspark.__file__).resolve().parent / "jars"
    installed: list[str] = []
    for source in _required_jars():
        destination = target_dir / source.name
        if not destination.exists() or destination.stat().st_size != source.stat().st_size:
            shutil.copy2(source, destination)
        installed.append(str(destination))
    return installed


def _required_jars() -> list[Path]:
    if not JARS_DIR.exists():
        raise FileNotFoundError(f"Jars directory not found: {JARS_DIR}")

    required = (
        "iceberg-spark-runtime-3.5_2.12",
        "iceberg-aws-bundle",
        "postgresql",
    )
    found: list[Path] = []
    for stem in required:
        matches = sorted(JARS_DIR.glob(f"{stem}*.jar"))
        if not matches:
            raise FileNotFoundError(f"Missing jar for {stem} in {JARS_DIR}")
        found.append(matches[-1])
    return found


def jar_paths() -> list[str]:
    """Return the Iceberg/AWS/PostgreSQL jars that must be on the classpath."""
    return [str(path) for path in _required_jars()]


def build_session(
    app_name: str = "cdp-lakehouse",
    extra: Mapping[str, Any] | None = None,
    master: str = "local[4]",
) -> SparkSession:
    """Create a Spark session configured for the lakehouse.

    ``extra`` overrides any property from ``lakehouse.conf`` and is the hook
    used by tests and by the ingestion jobs to tweak memory settings.
    """
    properties = load_properties()
    if extra:
        properties.update({str(k): str(v) for k, v in extra.items()})

    install_jars()

    builder = SparkSession.builder.appName(app_name).master(master)
    for key, value in properties.items():
        builder = builder.config(key, value)

    session = builder.getOrCreate()
    session.sparkContext.setLogLevel("WARN")
    return session
