#!/usr/bin/env bash
set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$project_dir/deploy/configure-gemini-key.py"

systemctl --user restart av-backend.service av-worker.service

for _ in {1..30}; do
  health="$(curl -fsS http://127.0.0.1:8000/health 2>/dev/null || true)"
  if [[ "$health" == *'"query_ai_configured":true'* ]] && \
     [[ "$health" == *'"import_ai_configured":true'* ]] && \
     [[ "$health" == *'"description_ai_configured":true'* ]]; then
    echo "Gemini設定を反映し、APIとワーカーを再起動しました。"
    exit 0
  fi
  sleep 1
done

echo "再起動後のGemini設定確認に失敗しました。" >&2
exit 1
