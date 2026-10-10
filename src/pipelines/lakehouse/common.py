"""Infrastructure helpers shared by REES46 and future source jobs."""

from functools import reduce
import operator
import re
import time
from urllib.parse import urlparse
from pyspark.sql import functions as F


def ensure_bucket(spark):
    """Create the local warehouse bucket using Iceberg's bundled AWS SDK."""
    endpoint = spark.conf.get("spark.sql.catalog.cdp.s3.endpoint")
    bucket_name = urlparse(spark.conf.get("spark.sql.catalog.cdp.warehouse")).netloc
    jvm = spark._jvm
    client = (jvm.software.amazon.awssdk.services.s3.S3Client.builder()
              .endpointOverride(jvm.java.net.URI.create(endpoint))
              .region(jvm.software.amazon.awssdk.regions.Region.US_EAST_1)
              .forcePathStyle(True).build())
    try:
        for attempt in range(30):
            try:
                names = [bucket.name() for bucket in client.listBuckets().buckets()]
                if bucket_name not in names:
                    request = (jvm.software.amazon.awssdk.services.s3.model.CreateBucketRequest
                               .builder().bucket(bucket_name).build())
                    client.createBucket(request)
                return
            except Exception:
                if attempt == 29:
                    raise
                time.sleep(2)
    finally:
        client.close()


def write_batch(spark, frame, table, batch_id):
    """Replace just one batch atomically within one Iceberg table.

    One writer is required. Other batches remain untouched. Empty frames also
    delete old rows for this batch, which is important for quarantine/recovery.
    There is no transaction spanning Bronze, Silver and Gold tables.
    """
    if not re.fullmatch(r"cdp\.(bronze|silver|gold)\.[a-z][a-z0-9_]*", table):
        raise ValueError(f"Unsupported table name: {table}")
    date_column = "event_at" if "event_at" in frame.columns else (
        "event_date" if "event_date" in frame.columns else None)
    if not spark.catalog.tableExists(table):
        writer = (frame.writeTo(table).using("iceberg")
                  .tableProperty("format-version", "2")
                  .tableProperty("write.target-file-size-bytes", "67108864"))
        partitions = [F.col("batch_id")]
        if date_column:
            partitions.append(F.days(F.col(date_column)))
        writer.partitionedBy(*partitions).create()
    else:
        # Add a day transform once, retaining the batch partition and old files.
        # Iceberg transparently reads both old and new partition specifications.
        if date_column:
            iceberg_table = spark._jvm.org.apache.iceberg.spark.Spark3Util.loadIcebergTable(
                spark._jsparkSession, table)
            source_id = iceberg_table.schema().findField(date_column).fieldId()
            has_day = any(field.sourceId() == source_id and str(field.transform()) == "day"
                          for field in iceberg_table.spec().fields())
            if not has_day:
                spark.sql(f"ALTER TABLE {table} ADD PARTITION FIELD days({date_column})")
        spark.sql(f"ALTER TABLE {table} SET TBLPROPERTIES ('write.target-file-size-bytes'='67108864')")
        frame.writeTo(table).overwrite(F.col("batch_id") == F.lit(batch_id))


def assert_same_rows(actual, expected, description):
    """Compare exact values using stable keys; reject duplicate keys first.

    Grouping every wide payload column for EXCEPT ALL costs substantial memory.
    Keyed tables instead check key uniqueness, then compare all values with a
    full outer join and null-safe equality. Unkeyed frames retain EXCEPT ALL.
    """
    expected = expected.select(actual.columns)
    if "event_id" in actual.columns:
        keys = [column for column in ("batch_id", "event_id") if column in actual.columns]
    elif "event_date" in actual.columns:
        keys = ["batch_id", "source_namespace", "event_date", "event_name"]
    elif "source_user_id" in actual.columns:
        keys = ["batch_id", "source_namespace", "source_user_id"]
        if "source_session_id" in actual.columns:
            keys.append("source_session_id")
    else:
        if actual.exceptAll(expected).limit(1).count() or expected.exceptAll(actual).limit(1).count():
            raise AssertionError(f"Row/value mismatch: {description}")
        return
    for label, frame in (("actual", actual), ("expected", expected)):
        null_key = reduce(operator.or_, [F.col(key).isNull() for key in keys])
        if frame.filter(null_key).limit(1).count():
            raise AssertionError(f"Null key in {label}: {description}")
        if frame.groupBy(*keys).count().filter(F.col("count") > 1).limit(1).count():
            raise AssertionError(f"Duplicate key in {label}: {description}")
    left = actual.withColumn("_row_exists", F.lit(True)).alias("a")
    right = expected.withColumn("_row_exists", F.lit(True)).alias("e")
    joined = left.join(right, keys, "full_outer")
    mismatch = F.col("a._row_exists").isNull() | F.col("e._row_exists").isNull()
    for column in actual.columns:
        if column not in keys:
            mismatch = mismatch | ~F.col(f"a.`{column}`").eqNullSafe(F.col(f"e.`{column}`"))
    if joined.filter(mismatch).limit(1).count():
        raise AssertionError(f"Row/value mismatch: {description}")
