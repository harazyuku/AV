#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$project_dir/.runtime"
pg_bin="/usr/lib/postgresql/18/bin"
pg_data="$runtime_dir/postgres-data"
pg_socket="$runtime_dir/postgres-socket"
pg_log="$runtime_dir/postgres.log"
pgvector_root="$runtime_dir/packages/pgvector-root"
extension_dir="$pgvector_root/usr/share/postgresql/18"
library_dir="$pgvector_root/usr/lib/postgresql/18/lib"

mkdir -p "$runtime_dir/logs" "$runtime_dir/pids" "$pg_socket"
chmod 700 "$runtime_dir" "$pg_socket"

if [[ ! -s "$pg_data/PG_VERSION" ]]; then
  "$pg_bin/initdb" -D "$pg_data" --auth-local=peer --auth-host=scram-sha-256
fi

if ! "$pg_bin/pg_ctl" -D "$pg_data" status >/dev/null 2>&1; then
  "$pg_bin/pg_ctl" -D "$pg_data" -l "$pg_log" -o \
    "-p 5433 -k '$pg_socket' -c listen_addresses='' -c dynamic_library_path='$library_dir' -c extension_control_path='$extension_dir'" start
fi

if ! "$pg_bin/psql" -h "$pg_socket" -p 5433 -d postgres -Atc \
  "select 1 from pg_database where datname='av_search'" | grep -qx 1; then
  "$pg_bin/createdb" -h "$pg_socket" -p 5433 av_search
fi
"$pg_bin/psql" -h "$pg_socket" -p 5433 -d av_search -v ON_ERROR_STOP=1 \
  -c "create extension if not exists vector" >/dev/null

export DATABASE_URL="postgresql+psycopg://$USER@/av_search?host=$pg_socket&port=5433"
export CORS_ALLOW_ORIGINS="https://av-search.tailc7d85e.ts.net,http://127.0.0.1:3100"
export AUTO_IMPORT_ENABLED="${AUTO_IMPORT_ENABLED:-false}"

if [[ -f "$project_dir/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$project_dir/.env"
  set +a
  export DATABASE_URL="postgresql+psycopg://$USER@/av_search?host=$pg_socket&port=5433"
  export CORS_ALLOW_ORIGINS="https://av-search.tailc7d85e.ts.net,http://127.0.0.1:3100"
fi

start_process() {
  local name="$1"
  shift
  local pid_file="$runtime_dir/pids/$name.pid"
  if [[ -s "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    return
  fi
  nohup "$@" >"$runtime_dir/logs/$name.log" 2>&1 &
  echo "$!" >"$pid_file"
}

cd "$project_dir/backend"
start_process backend "$project_dir/backend/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
    break
  fi
  sleep 1
done
if ! curl -fsS http://127.0.0.1:8000/health >/dev/null; then
  echo "Backend startup health check failed" >&2
  exit 1
fi

start_process worker "$project_dir/backend/.venv/bin/python" -m app.worker
cd "$project_dir/frontend"
start_process frontend npm run start -- --hostname 127.0.0.1 --port 3100

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:3100/ >/dev/null; then
    echo "AV AI Search is running"
    exit 0
  fi
  sleep 1
done

echo "Startup health check failed" >&2
exit 1
