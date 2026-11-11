"""Local source stack lifecycle. Run from the repository with python -m ...runtime up."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import httpx

from src.demo.api import business
from src.demo.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / '.cache' / 'sources'
COMPOSE = ['docker', 'compose', '-f', str(ROOT / 'config/docker/compose.sources.yml')]
CONNECT = 'http://127.0.0.1:8083'
PROCESSES = {
    'api': ['-m', 'src.demo.api.server'],
    'observer': ['-m', 'src.demo.sources.observer'],
    'web': ['src/demo/web/serve.py'],
}


def wait_for(description, probe, timeout=180):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            result = probe()
            if result:
                return result
        except (httpx.HTTPError, OSError) as exc:
            last = exc
        time.sleep(1)
    raise RuntimeError(f'Timeout waiting for {description}: {last or "not ready"}')


def connector_ready():
    response = httpx.get(f'{CONNECT}/connectors/cdp-business/status', timeout=5)
    if response.status_code != 200:
        return False
    state = response.json()
    tasks = state.get('tasks', [])
    if any(t['state'] == 'FAILED' for t in tasks):
        raise RuntimeError(json.dumps(state, indent=2))
    return state['connector']['state'] == 'RUNNING' and tasks and all(t['state'] == 'RUNNING' for t in tasks)


def alive(pid):
    try:
        os.kill(pid, 0)
        # Check identity as PID files can outlive processes or be reused.
        command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True)
        return any(' '.join(args) in command for args in PROCESSES.values())
    except (OSError, subprocess.CalledProcessError):
        return False


def start_process(name, args):
    pidfile = STATE / f'{name}.pid'
    if pidfile.exists() and alive(int(pidfile.read_text())):
        return
    with (STATE / f'{name}.log').open('a') as log:
        process = subprocess.Popen([sys.executable, *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    pidfile.write_text(str(process.pid))


def stop_processes():
    for name in PROCESSES:
        pidfile = STATE / f'{name}.pid'
        if not pidfile.exists():
            continue
        pid = int(pidfile.read_text())
        if alive(pid):
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 15
            while alive(pid) and time.monotonic() < deadline:
                time.sleep(.2)
            if alive(pid):
                raise RuntimeError(f'{name} did not stop; inspect {STATE / (name + ".log")}')
        pidfile.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['up', 'down', 'status'])
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    if args.action == 'up':
        subprocess.run([*COMPOSE, 'up', '-d', '--wait', '--wait-timeout', '180',
                        'kafka', 'topics', 'schemas', 'collector', 'enrich', 'business-db'], check=True)
        # Seed before registering CDC so a new connector can prove its initial snapshot.
        business.seed_catalog(load_catalog())
        subprocess.run([*COMPOSE, 'up', '-d', 'connect'], check=True)
        wait_for('Kafka Connect', lambda: httpx.get(f'{CONNECT}/connector-plugins', timeout=5).is_success)
        config = json.loads((ROOT / 'config/kafka/business-connector.json').read_text())
        response = httpx.put(f'{CONNECT}/connectors/cdp-business/config', json=config, timeout=30)
        response.raise_for_status()
        wait_for('Debezium task', connector_ready)
        for name, command in PROCESSES.items():
            start_process(name, command)
        wait_for('API', lambda: httpx.get('http://127.0.0.1:8000/health', timeout=3).is_success)
        wait_for('web', lambda: httpx.get('http://127.0.0.1:8081/', timeout=3).is_success)
        wait_for('Collector', lambda: httpx.get('http://127.0.0.1:9091/health', timeout=3).is_success)
        for name in PROCESSES:
            if not alive(int((STATE / f'{name}.pid').read_text())):
                raise RuntimeError(f'{name} exited; inspect {STATE / (name + ".log")}')
        print('Web: http://127.0.0.1:8081/ | API: http://127.0.0.1:8000/docs')
        print(f'Logs: {STATE}')
    elif args.action == 'down':
        stop_processes()
        subprocess.run([*COMPOSE, 'down'], check=True)  # Keep named volumes.
    else:
        subprocess.run([*COMPOSE, 'ps', '-a'], check=True)
        for name in PROCESSES:
            file = STATE / f'{name}.pid'
            print(f'{name}: {"running" if file.exists() and alive(int(file.read_text())) else "stopped"}')


if __name__ == '__main__':
    main()
