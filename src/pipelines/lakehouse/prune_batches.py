#!/usr/bin/env python3
"""Delete specified REES46 batches and expire historical snapshots.

Run with no other writers or readers relying on historical snapshots. This is
explicit maintenance: only the current snapshot is retained in each table.
"""
import argparse
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import SparkSession, functions as F
from run_rees46 import ROOT, TABLES


def counts_by_batch(spark, table):
    return {row.batch_id: row['count'] for row in
            spark.table(table).groupBy('batch_id').count().collect()}


def retained_files(spark, table, removed_ids):
    # Compare the actual file identities, not just counts, for all retained batches.
    files = spark.table(f'{table}.files')
    return {row.file_path for row in files.filter(
        ~F.col('partition.batch_id').isin(removed_ids)).select('file_path').collect()}


def prune(spark, removed_ids, keep_report):
    reference = json.loads(keep_report.read_text())
    keep_id = reference['batch_id']
    if reference['status'] != 'passed' or keep_id in removed_ids:
        raise ValueError('A passed, retained batch report is required')
    for batch_id in [keep_id, *removed_ids]:
        if not re.fullmatch(r'[a-f0-9]{64}', batch_id):
            raise ValueError('Invalid batch ID')
    expected_counts = {**{'bronze': reference['counts']['bronze_rows'],
                         'silver': reference['counts']['silver_rows'],
                         'quarantine': reference['counts']['quarantine_rows']},
                       **reference['gold_rows']}
    report = {'status': 'started', 'removed_batch_ids': removed_ids,
              'retained_batch_id': keep_id, 'tables': {}}
    path = ROOT / 'data/reports/lakehouse' / f'cleanup-{uuid.uuid4().hex}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    before = {}
    # Validate every table before the first DELETE.
    for name, table in TABLES.items():
        counts = counts_by_batch(spark, table)
        if counts.get(keep_id, 0) != expected_counts[name]:
            raise AssertionError(f'Unexpected retained row count: {table}')
        refs = spark.table(f'{table}.refs').select('name').collect()
        if any(row.name != 'main' for row in refs):
            raise ValueError(f'Historical branches/tags exist: {table}')
        before[name] = (counts, retained_files(spark, table, removed_ids))
    predicate = ', '.join(f"'{batch_id}'" for batch_id in removed_ids)
    try:
        # Delete rows first, then verify all retained rows/files before expiration.
        for name, table in TABLES.items():
            print(f'Deleting specified batches: {table}', flush=True)
            spark.sql(f'DELETE FROM {table} WHERE batch_id IN ({predicate})')
            counts, files = before[name]
            expected = {bid: count for bid, count in counts.items() if bid not in removed_ids}
            after = counts_by_batch(spark, table)
            if after != expected or retained_files(spark, table, removed_ids) != files:
                raise AssertionError(f'Retained rows/files changed: {table}')
            report['tables'][name] = {'table': table, 'before_counts': counts,
                                     'after_counts': after,
                                     'retained_files_unchanged': True}
        cutoff = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
        for name, table in TABLES.items():
            print(f'Expiring historical snapshots: {table}', flush=True)
            snapshots_before = spark.table(f'{table}.snapshots').count()
            result = spark.sql(
                "CALL cdp.system.expire_snapshots("
                f"table => '{table.removeprefix('cdp.')}', "
                f"older_than => TIMESTAMP '{cutoff}', retain_last => 1, "
                "stream_results => true)"
            ).first().asDict()
            # Read again after physical file cleanup; detect missing/corrupt files.
            if counts_by_batch(spark, table) != report['tables'][name]['after_counts']:
                raise AssertionError(f'Row counts changed after expiration: {table}')
            if retained_files(spark, table, removed_ids) != before[name][1]:
                raise AssertionError(f'Retained file identities changed: {table}')
            report['tables'][name].update({
                'snapshots_before': snapshots_before,
                'snapshots_after': spark.table(f'{table}.snapshots').count(),
                'expiration': result})
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        raise
    finally:
        report['completed_at_utc'] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(f'Cleanup report: {path}', flush=True)
    print(json.dumps(report, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-id', action='append', required=True)
    parser.add_argument('--keep-report', type=Path, required=True)
    args = parser.parse_args()
    spark = SparkSession.builder.appName('cdp-prune-batches').getOrCreate()
    spark.sparkContext.setLogLevel('WARN')
    try:
        prune(spark, list(dict.fromkeys(args.batch_id)), args.keep_report)
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
