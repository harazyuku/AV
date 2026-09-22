#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$project_dir/.runtime"

for name in frontend worker backend; do
  pid_file="$runtime_dir/pids/$name.pid"
  if [[ -s "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      for _ in {1..20}; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.25
      done
    fi
    rm -f "$pid_file"
  fi
done

pg_data="$runtime_dir/postgres-data"
if [[ -s "$pg_data/PG_VERSION" ]] && /usr/lib/postgresql/18/bin/pg_ctl -D "$pg_data" status >/dev/null 2>&1; then
  /usr/lib/postgresql/18/bin/pg_ctl -D "$pg_data" stop -m fast
fi
