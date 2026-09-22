import os, re, time, uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, or_, select, update
from app.main import AppSetting, AutoImport, SessionLocal, auto_import_enabled, import_ai_keys, import_jobs, import_jobs_lock, init_db, purge_expired_failed_imports, run_missav_import
from app.sources.missav import discover_feed_urls

BLOCKED_PATHS = {"genres", "makers", "actresses", "series", "new", "release", "search", "login", "signup", "dm18"}

def enqueue_discovered(urls: list[str]):
    with SessionLocal() as session:
        purge_expired_failed_imports(session)
        existing = set(session.scalars(select(AutoImport.source_url).where(AutoImport.source_url.in_(urls)))) if urls else set()
        session.add_all([AutoImport(source_url=url) for url in urls if url not in existing]); session.commit()

def today_start_utc() -> datetime:
    zone = ZoneInfo(os.getenv("AUTO_IMPORT_TIMEZONE", "Asia/Tokyo")); now = datetime.now(zone)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)

def processed_today() -> int:
    with SessionLocal() as session:
        return session.scalar(select(func.count(AutoImport.id)).where(
            AutoImport.status == "completed",
            AutoImport.processed_at >= today_start_utc(),
            AutoImport.is_manual.is_(False),
        )) or 0

def run_now_requested() -> bool:
    with SessionLocal() as session:
        setting = session.get(AppSetting, "auto_import_run_now")
        return bool(setting and setting.value == "true")

def consume_run_now() -> bool:
    with SessionLocal() as session:
        setting = session.get(AppSetting, "auto_import_run_now")
        if not setting or setting.value != "true": return False
        setting.value = "false"; session.commit(); return True

def wait_for_even_hour_slot() -> None:
    zone = ZoneInfo(os.getenv("AUTO_IMPORT_TIMEZONE", "Asia/Tokyo"))
    now = datetime.now(zone)
    next_hour = ((now.hour // 2) + 1) * 2
    target = ((now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
              if next_hour >= 24 else now.replace(hour=next_hour, minute=0, second=0, microsecond=0))
    delay = max(0, (target - now).total_seconds())
    if delay > 0:
        print(f"next auto-import slot: {target.isoformat()}", flush=True)
        time.sleep(delay)

def next_item(max_attempts: int, is_manual: bool | None = False, promote_to_manual: bool = False) -> AutoImport | None:
    with SessionLocal() as session:
        retryable = AutoImport.status == "failed"
        conditions = [AutoImport.attempts < max_attempts, or_(AutoImport.status == "pending", retryable)]
        if is_manual is not None: conditions.append(AutoImport.is_manual.is_(is_manual))
        item = session.scalar(select(AutoImport).where(*conditions).order_by(AutoImport.discovered_at.asc()).with_for_update(skip_locked=True))
        if not item: return None
        if promote_to_manual: item.is_manual = True
        item.status = "processing"; item.attempts += 1; item.error = None; item.updated_at = datetime.now(timezone.utc).replace(tzinfo=None); session.commit(); session.refresh(item); session.expunge(item); return item

def recover_interrupted_items():
    with SessionLocal() as session:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        session.execute(
            update(AutoImport)
            .where(AutoImport.status.in_(("processing", "downloading", "splitting", "json_building")))
            .values(status="failed", error="worker stopped during processing", updated_at=now_utc, processed_at=now_utc)
        )
        session.commit()

def process_item(item: AutoImport):
    job_id = f"auto-{item.id}-{uuid.uuid4().hex[:8]}"
    with import_jobs_lock: import_jobs[job_id] = {"id":job_id,"status":"queued","url":item.source_url,"title":None,"video_path":None,"metadata_path":None,"analysis_path":None,"product_id":None,"error":None}
    def save_progress(**values):
        with SessionLocal() as session:
            row = session.get(AutoImport, item.id)
            if not row: return
            row.status = values.get("status", row.status)
            row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if values.get("title"): row.title = values["title"]
            if values.get("product_id"): row.product_id = values["product_id"]
            if values.get("error"): row.error = values["error"]
            if row.status in {"completed", "failed"}: row.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
    run_missav_import(job_id, item.source_url, True, save_progress)
    with import_jobs_lock: result = dict(import_jobs.pop(job_id))
    with SessionLocal() as session:
        row = session.get(AutoImport, item.id)
        if not row: return
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        row.status = result["status"]; row.title = result.get("title"); row.product_id = result.get("product_id"); row.error = result.get("error"); row.updated_at = now_utc; row.processed_at = now_utc; session.commit()

def main():
    init_db(); recover_interrupted_items(); print("auto-import worker started", flush=True)
    while True:
        enabled = auto_import_enabled(); feed = os.getenv("MISSAV_FEED_URL", "").strip()
        interval = max(900, int(os.getenv("AUTO_IMPORT_POLL_SECONDS", "21600"))); limit = max(1, min(int(os.getenv("AUTO_IMPORT_DAILY_LIMIT", "3")), 30)); max_attempts = max(1, min(int(os.getenv("AUTO_IMPORT_MAX_ATTEMPTS", "3")), 5))
        manual_run = consume_run_now()
        if (not enabled or not import_ai_keys()) and not manual_run: time.sleep(5); continue
        try:
            if manual_run:
                item = next_item(max_attempts, is_manual=True)
                if item: process_item(item)
            elif feed:
                try: enqueue_discovered(discover_feed_urls(feed))
                except Exception as exc: print(f"discovery error: {exc}", flush=True)
            if not manual_run:
                while processed_today() < limit:
                    wait_for_even_hour_slot()
                    item = next_item(max_attempts, is_manual=False)
                    if not item: break
                    process_item(item)
        except Exception as exc: print(f"worker error: {exc}", flush=True)
        for _ in range(max(1, interval // 5)):
            if run_now_requested(): break
            time.sleep(5)

if __name__ == "__main__": main()
