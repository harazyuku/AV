# Codex implementation notes

FastAPI backend is in `backend/app/main.py`; the frontend is in `frontend/app`.

The bounded auto-import worker is `backend/app/worker.py` and runs as the Compose `worker` service. It discovers URLs from `MISSAV_FEED_URL`, persists its queue in `auto_imports`, attempts at most `AUTO_IMPORT_DAILY_LIMIT` items per local day, and retries failed items on later days up to `AUTO_IMPORT_MAX_ATTEMPTS`. Keep the hard 1–10 daily clamp and URL allowlist when changing it.

With the default `KEEP_SOURCE_VIDEO=false`, analyzed source video and sidecar JSON are temporary. Durable metadata belongs in PostgreSQL. Do not add authentication bypass, DRM circumvention, or unbounded crawling.

For production, add migrations, ingestion authentication, rate limiting, and a background FANZA sync job.
