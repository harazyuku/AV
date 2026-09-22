#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
from pathlib import Path


project_dir = Path(__file__).resolve().parent.parent
env_path = project_dir / ".env"

key = getpass.getpass("Gemini API key（入力は表示されません）: ").strip()
if not key:
    raise SystemExit("APIキーが空なので変更しませんでした。")

lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
updated: list[str] = []
replaced = False
for line in lines:
    if line.startswith("GEMINI_API_KEY="):
        updated.append(f"GEMINI_API_KEY={key}")
        replaced = True
    else:
        updated.append(line)
if not replaced:
    updated.append(f"GEMINI_API_KEY={key}")

temp_path = env_path.with_suffix(".tmp")
temp_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
os.chmod(temp_path, 0o600)
temp_path.replace(env_path)
print("Gemini APIキーを設定しました。")
