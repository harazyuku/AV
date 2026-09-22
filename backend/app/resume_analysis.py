import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.main import (
    AutoImport,
    SessionLocal,
    analyze_video_api,
    extract_video_frames,
    register_analyzed_product,
    safe_error_message,
)


def main(import_id: int) -> None:
    media_dir = Path(os.getenv("MEDIA_DIR", "/data/missav"))
    job_dirs = sorted(media_dir.glob(f"auto-{import_id}-*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not job_dirs:
        raise RuntimeError(f"import {import_id} の作業ディレクトリがありません")
    job_dir = job_dirs[0]
    metadata_files = list(job_dir.glob("*.normalized.json"))
    video_files = [path for path in job_dir.glob("*") if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
    if not metadata_files or not video_files:
        raise RuntimeError(f"import {import_id} の解析元ファイルが不足しています")
    source = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    video_path = video_files[0]
    with SessionLocal() as session:
        row = session.get(AutoImport, import_id)
        if not row:
            raise RuntimeError(f"import {import_id} がDBにありません")
        row.status = "splitting"
        row.error = None
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
    try:
        frames = extract_video_frames(video_path)
        with SessionLocal() as session:
            row = session.get(AutoImport, import_id)
            row.status = "json_building"
            row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
        analysis = analyze_video_api(video_path, source["title"], source.get("source_metadata", {}), frames)
        analysis_path = video_path.with_suffix(".analysis.json")
        analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        product_id = register_analyzed_product(source, analysis, video_path)
        with SessionLocal() as session:
            row = session.get(AutoImport, import_id)
            row.status = "completed"
            row.title = source["title"]
            row.product_id = product_id
            row.error = None
            row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            row.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
        if os.getenv("KEEP_SOURCE_VIDEO", "false").lower() != "true":
            shutil.rmtree(job_dir, ignore_errors=True)
        print(f"import {import_id} resumed and completed: product_id={product_id}", flush=True)
    except Exception as exc:
        with SessionLocal() as session:
            row = session.get(AutoImport, import_id)
            row.status = "failed"
            row.error = safe_error_message(exc)
            row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            row.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
        raise


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.resume_analysis IMPORT_ID")
    main(int(sys.argv[1]))
