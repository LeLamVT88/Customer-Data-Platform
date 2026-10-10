#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"
if [ "$#" -ne 1 ]; then
    printf '%s\n' 'Usage: sh src/tools/run_local_lakehouse.sh data/local-batches/rees46/<batch-id>' >&2
    exit 1
fi
# Accept only a project-relative batch path. No automatic selection of a batch.
case "$1" in
    data/*) batch_path="$1" ;;
    *) printf '%s\n' 'Batch must be a project-relative path under data/.' >&2; exit 1 ;;
esac
if [ ! -f "$batch_path/manifest.json" ]; then
    printf '%s\n' 'Batch manifest not found.' >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    printf '%s\n' 'Docker chưa chạy. Mở Docker Desktop rồi chạy lại.' >&2
    exit 1
fi
docker compose -f config/docker/compose.local-lakehouse.yml up -d --wait catalog storage
docker compose -f config/docker/compose.local-lakehouse.yml run --build --rm spark \
    /workspace/src/pipelines/lakehouse/run_rees46.py --batch "/workspace/$batch_path"
