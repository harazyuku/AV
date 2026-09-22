#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


ALLOWED_KEYS = {
    "GEMINI_API_KEY",
    "QUERY_AI_API_KEY",
    "QUERY_AI_MODEL",
    "QUERY_AI_EMBEDDING_MODEL",
    "IMPORT_AI_API_KEY",
    "IMPORT_AI_API_KEY_2",
    "IMPORT_AI_API_KEY_3",
    "IMPORT_AI_API_KEY_4",
    "IMPORT_AI_API_KEY_5",
    "IMPORT_AI_MODEL",
    "IMPORT_FRAME_COUNT",
    "IMPORT_FRAME_WIDTH",
    "IMPORT_FRAME_JPEG_QUALITY",
    "IMPORT_IMAGES_PER_KEY",
    "DESCRIPTION_AI_API_KEY",
    "DESCRIPTION_AI_MODEL",
    "FANZA_API_ID",
    "FANZA_AFFILIATE_ID",
    "MAX_VIDEO_BYTES",
    "AUTO_IMPORT_ENABLED",
    "MISSAV_FEED_URL",
    "AUTO_IMPORT_DAILY_LIMIT",
    "AUTO_IMPORT_POLL_SECONDS",
    "AUTO_IMPORT_BETWEEN_ITEMS_SECONDS",
    "AUTO_IMPORT_MAX_ATTEMPTS",
    "AUTO_IMPORT_TIMEZONE",
    "KEEP_SOURCE_VIDEO",
}


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key in ALLOWED_KEYS and value.strip():
            values[key] = value.strip()
    return values


project_dir = Path(__file__).resolve().parent.parent
env_path = project_dir / ".env"
incoming = parse_env(sys.stdin.read())
if not incoming:
    raise SystemExit("対応するAI・取込設定が入力に見つかりませんでした。")

lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
seen: set[str] = set()
updated: list[str] = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in incoming:
        updated.append(f"{key}={incoming[key]}")
        seen.add(key)
    else:
        updated.append(line)
for key in sorted(incoming.keys() - seen):
    updated.append(f"{key}={incoming[key]}")

temp_path = env_path.with_suffix(".tmp")
temp_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
os.chmod(temp_path, 0o600)
temp_path.replace(env_path)
print("取り込んだ設定: " + ", ".join(sorted(incoming)))
