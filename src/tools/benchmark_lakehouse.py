#!/usr/bin/env python3
"""Run one local Lakehouse batch and sample Java/Python memory in its container."""
import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ['docker', 'compose', '-f', str(ROOT / 'config/docker/compose.local-lakehouse.yml')]
PROBE = '''
import json, os
from pathlib import Path
result = {'java_rss_bytes': 0, 'java_hwm_bytes': 0, 'python_rss_bytes': 0}
for path in Path('/proc').glob('[0-9]*'):
    if int(path.name) == os.getpid(): continue
    try:
        name = (path/'comm').read_text().strip()
        fields = dict(line.split(':', 1) for line in (path/'status').read_text().splitlines() if ':' in line)
        rss = int(fields.get('VmRSS', '0 kB').split()[0])*1024
        if name == 'java':
            result['java_rss_bytes'] += rss
            result['java_hwm_bytes'] = max(result['java_hwm_bytes'], int(fields.get('VmHWM', '0 kB').split()[0])*1024)
        elif name.startswith('python'):
            result['python_rss_bytes'] += rss
    except (FileNotFoundError, ProcessLookupError): pass
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True, type=Path)
    args = parser.parse_args()
    batch = args.batch.resolve(strict=True)
    relative = batch.relative_to(ROOT / 'data')
    manifest = json.loads((batch/'manifest.json').read_text())
    batch_id = manifest['batch_id']
    run_id = uuid.uuid4().hex
    output = ROOT / 'data/reports/lakehouse'
    output.mkdir(parents=True, exist_ok=True)
    name = 'cdp-benchmark-' + run_id[:12]
    log_path = output / f'{batch_id}-{run_id}.log'
    subprocess.run(COMPOSE + ['up', '-d', '--wait', 'catalog', 'storage'], check=True)
    command = COMPOSE + ['run', '--rm', '--name', name, 'spark',
                         '/workspace/src/pipelines/lakehouse/run_rees46.py', '--batch',
                         '/workspace/data/' + str(relative)]
    started = time.monotonic()
    samples = []
    with log_path.open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                probe = subprocess.run(['docker', 'exec', name, 'python3', '-c', PROBE], capture_output=True, text=True)
                if probe.returncode == 0:
                    sample = json.loads(probe.stdout)
                    sample['elapsed_seconds'] = round(time.monotonic() - started, 3)
                    samples.append(sample)
                time.sleep(2)
            code = process.wait()
        except KeyboardInterrupt:
            subprocess.run(['docker', 'stop', name], check=False)
            process.wait()
            raise
    report = {
        'batch_id': batch_id, 'exit_code': code, 'log': str(log_path.relative_to(ROOT)),
        'launch_to_exit_seconds': round(time.monotonic() - started, 3),
        'peak_java_rss_observed_bytes': max((s['java_rss_bytes'] for s in samples), default=0),
        'peak_java_hwm_observed_bytes': max((s['java_hwm_bytes'] for s in samples), default=0),
        'peak_python_rss_observed_bytes': max((s['python_rss_bytes'] for s in samples), default=0),
        'samples': samples,
        'limits': 'About 2-second sampling; may miss final peak. Python RSS sums processes and may double-count shared pages. No storage/catalog memory, no heap-only metric.',
    }
    path = output / f'{batch_id}-{run_id}-memory.json'
    path.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key != 'samples'}, indent=2))
    print(f'Memory report: {path}')
    raise SystemExit(code)


if __name__ == '__main__':
    main()
