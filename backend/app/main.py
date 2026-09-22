import asyncio, base64, json, os, random, re, shutil, subprocess, tempfile, threading, time, unicodedata, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import httpx
import yt_dlp
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, create_engine, delete, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from pgvector.sqlalchemy import Vector
from app.sources.missav import discover_feed_urls, resolve_page
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://av:av@localhost:5432/av_search")
DEFAULT_MEDIA_DIR = Path(__file__).resolve().parents[2] / "data" / "missav"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
def query_ai_key() -> str: return os.getenv("QUERY_AI_API_KEY") or os.getenv("GEMINI_API_KEY", "")
def import_ai_keys() -> list[str]:
    keys = [
        os.getenv("IMPORT_AI_API_KEY", ""),
        os.getenv("IMPORT_AI_API_KEY_2", ""),
        os.getenv("IMPORT_AI_API_KEY_3", ""),
        os.getenv("IMPORT_AI_API_KEY_4", ""),
        os.getenv("IMPORT_AI_API_KEY_5", ""),
    ]
    configured = list(dict.fromkeys(key.strip() for key in keys if key.strip()))
    fallback = os.getenv("GEMINI_API_KEY", "").strip()
    if not configured and fallback:
        configured.append(fallback)
    return configured
def description_ai_key() -> str: return os.getenv("DESCRIPTION_AI_API_KEY", "") or (import_ai_keys()[0] if import_ai_keys() else "")
def query_ai_model() -> str: return os.getenv("QUERY_AI_MODEL", "gemini-3.5-flash")
def import_ai_model() -> str: return os.getenv("IMPORT_AI_MODEL", "gemini-3.5-flash")
def description_ai_model() -> str: return os.getenv("DESCRIPTION_AI_MODEL", import_ai_model())
def query_embedding_model() -> str: return os.getenv("QUERY_AI_EMBEDDING_MODEL", "gemini-embedding-2")
VISUAL_ANALYSIS_DEFAULTS: dict[str, Any] = {
    "summary": "",
    "people": 0,
    "performers": [],
    "clothing": [],
    "locations": [],
    "mood": [],
    "keywords": [],
}
ANALYSIS_SCHEMA_VERSION = 3 + len(VISUAL_ANALYSIS_DEFAULTS)
FANZA_GENRES_PATH = Path(__file__).with_name("data") / "fanza_genres.json"
try:
    FANZA_GENRES = json.loads(FANZA_GENRES_PATH.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    FANZA_GENRES = []
class Base(DeclarativeBase): pass
class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    fanza_url: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    performers: Mapped[list["Performer"]] = relationship(cascade="all, delete-orphan")
class Performer(Base):
    __tablename__ = "performers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200)); type: Mapped[str] = mapped_column(String(100), default="")
    hair_color: Mapped[str] = mapped_column(String(100), default=""); hair_style: Mapped[str] = mapped_column(String(100), default="")
    glasses: Mapped[bool] = mapped_column(Boolean, default=False)
class ClickLog(Base):
    __tablename__ = "click_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
class AutoImport(Base):
    __tablename__ = "auto_imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_url: Mapped[str] = mapped_column(Text, unique=True, index=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

def purge_expired_failed_imports(session: Session) -> int:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    result = session.execute(delete(AutoImport).where(
        AutoImport.status == "failed",
        AutoImport.processed_at.is_not(None),
        AutoImport.processed_at < cutoff,
    ))
    if result.rowcount:
        session.commit()
    return result.rowcount or 0
class PerformerIn(BaseModel):
    name: str; type: str = ""; hair_color: str = ""; hair_style: str = ""; glasses: bool = False
    model_config = {"from_attributes": True}
class ProductIn(BaseModel):
    external_id: str; title: str; description: str = ""; release_date: date | None = None; fanza_url: str
    performers: list[PerformerIn] = []; attributes: dict[str, Any] = {}
class ProductOut(ProductIn):
    id: int
    model_config = {"from_attributes": True}
class SelectedSearchTag(BaseModel):
    type: str
    value: str

class SearchFilters(BaseModel):
    query: str = ""; people: int | None = None; performer_type: str | None = None; hair_color: str | None = None
    hair_style: str | None = None; glasses: bool | None = None; clothing: str | None = None; location: str | None = None; release_year: int | None = None
    genre: str | None = None; keyword: str | None = None; maker: str | None = None; label: str | None = None
    director: str | None = None; performer: str | None = None; product_code: str | None = None
    selected_tags: list[SelectedSearchTag] = []
class ImportRequest(BaseModel):
    url: str; analyze: bool = True
class AutoImportEnqueueRequest(BaseModel):
    urls: list[str]
class AutoImportControlRequest(BaseModel):
    enabled: bool
class ImportJob(BaseModel):
    id: str; status: str; url: str; title: str | None = None; video_path: str | None = None
    metadata_path: str | None = None; analysis_path: str | None = None
    product_id: int | None = None; error: str | None = None
import_jobs: dict[str, dict[str, Any]] = {}
import_jobs_lock = threading.Lock()
app = FastAPI(title="AV AI Search API", version="0.2.0")

# Production nginx forwards same-origin API requests as /api/*.  Keep the
# application's route declarations unchanged while accepting that prefix.
@app.middleware("http")
async def strip_api_prefix(request, call_next):
    if request.scope["path"] == "/api":
        request.scope["path"] = "/"
    elif request.scope["path"].startswith("/api/"):
        request.scope["path"] = request.scope["path"][4:]
    return await call_next(request)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
def db():
    with SessionLocal() as s: yield s
def init_db():
    with engine.begin() as c: c.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql("ALTER TABLE auto_imports ADD COLUMN IF NOT EXISTS is_manual BOOLEAN NOT NULL DEFAULT FALSE")
        c.exec_driver_sql("ALTER TABLE auto_imports ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()")
def auto_import_enabled(session: Session | None = None) -> bool:
    fallback = os.getenv("AUTO_IMPORT_ENABLED", "false").lower() == "true"
    if session is not None:
        setting = session.get(AppSetting, "auto_import_enabled")
        return setting.value == "true" if setting else fallback
    try:
        with SessionLocal() as local_session:
            setting = local_session.get(AppSetting, "auto_import_enabled")
            return setting.value == "true" if setting else fallback
    except Exception:
        return fallback
@app.on_event("startup")
def startup(): init_db()
def validate_missav_url(url: str):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not re.fullmatch(r"(?:www\.)?missav\.[a-z]{2,}", host):
        raise HTTPException(400, "MissAVの公開作品URLを指定してください")
    if parsed.username or parsed.password: raise HTTPException(400, "認証情報を含むURLは使えません")
def update_import_job(job_id: str, **values):
    with import_jobs_lock: import_jobs[job_id].update(values)
def safe_error_message(exc: Exception) -> str:
    message = re.sub(r"([?&]key=)[^&\s'\"]+", r"\1[redacted]", str(exc), flags=re.I)
    return message[:500]
def parse_gemini_json(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        candidate = response.json()["candidates"][0]
        parts = candidate["content"]["parts"]
        finish_reason = candidate.get("finishReason", "unknown")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{label}の応答に本文がありません") from exc
    texts = [str(part.get("text", "")).strip() for part in parts if isinstance(part, dict) and part.get("text") and not part.get("thought")]
    if not texts:
        texts = [str(part.get("text", "")).strip() for part in parts if isinstance(part, dict) and part.get("text")]
    for text in reversed(texts):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        candidates = [cleaned]
        if "{" in cleaned and "}" in cleaned:
            candidates.append(cleaned[cleaned.find("{"):cleaned.rfind("}") + 1])
        for candidate_text in candidates:
            try:
                parsed = json.loads(candidate_text)
                if isinstance(parsed, dict): return parsed
            except json.JSONDecodeError:
                continue
    raise RuntimeError(f"{label}のJSON応答を解釈できません（終了理由: {finish_reason}）")
def post_gemini_generate(model: str, key: str, payload: dict[str, Any], timeout: int, label: str) -> httpx.Response:
    transient_statuses = {429, 500, 502, 503, 504}
    last_error: Exception | None = None
    with httpx.Client(timeout=timeout) as client:
        for attempt in range(4):
            try:
                response = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}", json=payload)
                if response.status_code not in transient_statuses:
                    response.raise_for_status()
                    return response
                last_error = RuntimeError(f"{label}が一時エラーを返しました（HTTP {response.status_code}）")
            except httpx.RequestError as exc:
                last_error = exc
            if attempt < 3: time.sleep(2 ** attempt)
    raise RuntimeError(f"{label}への接続が再試行後も失敗しました: {last_error}") from last_error
def extract_video_frames(video_path: Path, count: int | None = None) -> list[bytes]:
    if count is None:
        count = max(3, min(60, int(os.getenv("IMPORT_FRAME_COUNT", "30"))))
    width = max(256, min(1280, int(os.getenv("IMPORT_FRAME_WIDTH", "448"))))
    jpeg_quality = max(2, min(15, int(os.getenv("IMPORT_FRAME_JPEG_QUALITY", "8"))))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video_path)], capture_output=True, text=True, timeout=30)
    try: duration = float(probe.stdout.strip())
    except ValueError: raise RuntimeError("動画の長さを読み取れません")
    frames: list[bytes] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for index in range(count):
            position = duration * (index + 1) / (count + 1)
            output = Path(temp_dir) / f"frame-{index}.jpg"
            result = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(position), "-i", str(video_path), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", str(jpeg_quality), str(output)], capture_output=True, timeout=60)
            if result.returncode == 0 and output.exists(): frames.append(output.read_bytes())
    if len(frames) < 3: raise RuntimeError("解析用フレームを十分に抽出できません")
    return frames
def analyze_frame_batch(key: str, model: str, prompt: str, frames: list[bytes], batch_number: int) -> dict[str, Any]:
    batch_prompt = prompt + f"\nこれは全5区間中の第{batch_number}区間です。segmentには{batch_number}を設定してください。"
    parts: list[dict[str, Any]] = [{"text": batch_prompt}]
    for frame in frames:
        parts.append({"inline_data":{"mime_type":"image/jpeg","data":base64.b64encode(frame).decode("ascii")}})
    payload = {"contents":[{"parts":parts}],"generationConfig":{"responseMimeType":"application/json","temperature":0.1}}
    last_error: RuntimeError | None = None
    for _ in range(2):
        response = post_gemini_generate(model, key, payload, 180, f"動画解析APIの第{batch_number}区間")
        try:
            return parse_gemini_json(response, f"動画解析APIの第{batch_number}区間")
        except RuntimeError as exc:
            last_error = exc
    print(f"frame batch {batch_number} returned no usable JSON: {last_error}", flush=True)
    return {
        "segment": batch_number,
        "analysis_status": "unavailable",
        "visual_description": "",
        "people": 0,
        "performers": [],
        "clothing": [],
        "locations": [],
        "mood": [],
        "keywords": [],
    }

def synthesize_video_analysis(source_title: str, source_metadata: dict[str, Any], partials: list[dict[str, Any]]) -> dict[str, Any]:
    key = description_ai_key()
    if not key: raise RuntimeError("画像解析の統合にはDESCRIPTION_AI_API_KEYまたはIMPORT_AI_API_KEYが必要です")
    prompt = """あなたは動画の視覚解析の統合担当です。時系列順の5体の画像解析AIによる観察報告だけを統合してください。
タイトル、取得元の概要、品番、ジャンル、メーカー、監督、レーベル、配信日は扱わず、推測もしないでください。
人物数、人物の外見、衣装、場所、雰囲気、検索キーワードをまとめ、同一人物や同義語を重複させないでください。
summaryは画像から確認できる動画全体の簡単な説明を、日本語1〜2文・120文字以内で作ってください。
露骨な行為の説明、個人の特定、年齢推測は不要です。不明な値は空文字・false・空配列にしてください。
次の形式のJSONだけを返してください。
{"summary":"","people":0,"performers":[{"type":"","hair_color":"","hair_style":"","glasses":false}],"clothing":[],"locations":[],"mood":[],"keywords":[]}
5体の画像解析報告: """ + json.dumps(partials, ensure_ascii=False)
    payload = {"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","temperature":0.1}}
    response = post_gemini_generate(description_ai_model(), key, payload, 120, "画像解析統合AI")
    raw_analysis = parse_gemini_json(response, "画像解析統合AI")
    analysis = {
        field: raw_analysis.get(field, default)
        for field, default in VISUAL_ANALYSIS_DEFAULTS.items()
    }
    analysis["summary"] = str(analysis.get("summary") or "").strip()
    try: analysis["people"] = max(0, int(analysis.get("people", 0)))
    except (TypeError, ValueError): analysis["people"] = 0
    performers: list[dict[str, Any]] = []
    for performer in analysis.get("performers", []) if isinstance(analysis.get("performers"), list) else []:
        if not isinstance(performer, dict): continue
        performers.append({
            "type": str(performer.get("type", "")).strip(),
            "hair_color": str(performer.get("hair_color", "")).strip(),
            "hair_style": str(performer.get("hair_style", "")).strip(),
            "glasses": bool(performer.get("glasses", False)),
        })
    analysis["performers"] = performers
    if analysis["people"] > 0:
        analysis["performers"] = analysis["performers"][:analysis["people"]]
    elif analysis["performers"]:
        analysis["people"] = len(analysis["performers"])
    for field in ("clothing", "locations", "mood", "keywords"):
        values = analysis.get(field, [])
        analysis[field] = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip())) if isinstance(values, list) else []
    return analysis

def fallback_video_analysis(source_title: str, source_metadata: dict[str, Any], partials: list[dict[str, Any]]) -> dict[str, Any]:
    def unique_strings(field: str) -> list[str]:
        values: list[str] = []
        for partial in partials:
            items = partial.get(field, [])
            if not isinstance(items, list): continue
            for item in items:
                value = str(item).strip()
                if value and value not in values: values.append(value)
        return values
    performers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for partial in partials:
        items = partial.get("performers", [])
        if not isinstance(items, list): continue
        for performer in items:
            if not isinstance(performer, dict): continue
            normalized = {
                "type": str(performer.get("type", "")).strip(),
                "hair_color": str(performer.get("hair_color", "")).strip(),
                "hair_style": str(performer.get("hair_style", "")).strip(),
                "glasses": bool(performer.get("glasses", False)),
            }
            signature = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
            if signature not in seen:
                seen.add(signature); performers.append(normalized)
    people = [partial.get("people", 0) for partial in partials]
    people_count = max((value for value in people if isinstance(value, int)), default=0)
    if people_count > 0: performers = performers[:people_count]
    elif performers: people_count = len(performers)
    descriptions = [str(partial.get("visual_description", "")).strip() for partial in partials]
    return {
        "summary": " ".join(value for value in descriptions if value)[:240],
        "people": people_count,
        "performers": performers,
        "clothing": unique_strings("clothing"),
        "locations": unique_strings("locations"),
        "mood": unique_strings("mood"),
        "keywords": unique_strings("keywords"),
    }

def build_analysis_document(source_title: str, source_metadata: dict[str, Any], visual_analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "source": {
            "title": source_title,
            "description": str(source_metadata.get("description", "")).strip(),
            "metadata": source_metadata,
        },
        "visual_analysis": visual_analysis,
    }

def analyze_video_api(video_path: Path, source_title: str, source_metadata: dict[str, Any], frames: list[bytes] | None = None) -> dict[str, Any]:
    keys = import_ai_keys()
    if not keys: raise RuntimeError("IMPORT_AI_API_KEYが未設定です")
    prompt = """この6枚は1本の動画から時間順に抽出された1区間です。後段の統合AIへ渡す観察報告を日本語のJSONだけで返してください。
この段階ではタイトルや取得元情報を推測せず、画像から確認できる人物数、人物の外見、衣装、場所、雰囲気、検索キーワード、区間の簡潔な視覚説明だけを報告してください。
露骨な行為の説明、個人の特定、年齢推測は不要です。不明な値は空文字・false・空配列にしてください。
JSON形式: {"segment":1,"visual_description":"","people":0,"performers":[{"type":"","hair_color":"","hair_style":"","glasses":false}],"clothing":[],"locations":[],"mood":[],"keywords":[]}"""
    selected_frames = frames if frames is not None else extract_video_frames(video_path)
    images_per_key = max(1, min(30, int(os.getenv("IMPORT_IMAGES_PER_KEY", "6"))))
    batches = [selected_frames[index:index + images_per_key] for index in range(0, len(selected_frames), images_per_key)]
    model = import_ai_model()
    with ThreadPoolExecutor(max_workers=min(len(batches), len(keys))) as executor:
        futures = [
            executor.submit(analyze_frame_batch, keys[index % len(keys)], model, prompt, batch, index + 1)
            for index, batch in enumerate(batches)
        ]
        partials = [future.result() for future in futures]
    try:
        visual_analysis = synthesize_video_analysis(source_title, source_metadata, partials)
    except RuntimeError as exc:
        print(f"final synthesis unavailable; using deterministic fallback: {exc}", flush=True)
        visual_analysis = fallback_video_analysis(source_title, source_metadata, partials)
    return build_analysis_document(source_title, source_metadata, visual_analysis)
def register_analyzed_product(source: dict[str, Any], analysis: dict[str, Any], video_path: Path) -> int:
    external_id = f"missav-{source.get('source_id') or video_path.stem}"
    source_analysis = analysis.get("source", {}) if isinstance(analysis.get("source"), dict) else {}
    visual_analysis = analysis.get("visual_analysis", {}) if isinstance(analysis.get("visual_analysis"), dict) else {}
    title = str(source_analysis.get("title") or source.get("title") or external_id)
    description = str(source_analysis.get("description") or source.get("description") or "")
    source_metadata = source_analysis.get("metadata") if isinstance(source_analysis.get("metadata"), dict) else source.get("source_metadata", {})
    text = build_search_text(title, description, source_metadata, visual_analysis)
    vector = asyncio.run(embedding(text))
    release_date_value = None
    try:
        if source.get("source_metadata", {}).get("release_date"):
            release_date_value = date.fromisoformat(source["source_metadata"]["release_date"])
    except ValueError:
        pass
    with SessionLocal() as session:
        product = session.scalar(select(Product).where(Product.external_id == external_id))
        values = {"title":title,"description":description,"release_date":release_date_value,"fanza_url":source["source_url"],"attributes":{"schema_version":analysis.get("schema_version",ANALYSIS_SCHEMA_VERSION),"source_title":title,"source_metadata":source_metadata,"visual_analysis":visual_analysis,"summary":visual_analysis.get("summary",""),"人数":visual_analysis.get("people",0),"衣装":visual_analysis.get("clothing",[]),"場所":visual_analysis.get("locations",[]),"雰囲気":visual_analysis.get("mood",[]),"キーワード":visual_analysis.get("keywords",[]),"source":"missav","source_url":source["source_url"],"source_id":source.get("source_id"),"duration":source.get("duration"),"thumbnail":source.get("thumbnail"),"upload_date":source.get("upload_date")},"embedding":vector}
        if product:
            for key, value in values.items(): setattr(product, key, value)
            product.performers.clear()
        else:
            product = Product(external_id=external_id, **values); session.add(product)
        product.performers = [Performer(name=f"出演者{index+1}", type=item.get("type", ""), hair_color=item.get("hair_color", ""), hair_style=item.get("hair_style", ""), glasses=bool(item.get("glasses", False))) for index, item in enumerate(visual_analysis.get("performers", []))]
        session.commit(); session.refresh(product); return product.id
def run_missav_import(job_id: str, url: str, should_analyze: bool, on_progress=None):
    media_dir = Path(os.getenv("MEDIA_DIR", str(DEFAULT_MEDIA_DIR))); media_dir.mkdir(parents=True, exist_ok=True)
    job_dir = media_dir / job_id; job_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(os.getenv("MAX_VIDEO_BYTES", "2147483648"))
    keep_video = os.getenv("KEEP_SOURCE_VIDEO", "false").lower() == "true"
    options = {
        "outtmpl": str(job_dir / "%(id)s-%(title).120B.%(ext)s"),
        "format": "bestvideo*+bestaudio/best", "merge_output_format": "mp4",
        "noplaylist": True, "restrictfilenames": True, "writeinfojson": True,
        "extractor_args": {"generic": {"impersonate": [""]}},
        "http_headers": {"Referer": url},
        "max_filesize": max_bytes, "socket_timeout": 30, "retries": 3,
        "quiet": True, "no_warnings": True,
    }
    last_download_heartbeat = 0.0
    def progress(**values):
        update_import_job(job_id, **values)
        if on_progress: on_progress(**values)
    def download_heartbeat(event: dict[str, Any]):
        nonlocal last_download_heartbeat
        if event.get("status") != "downloading": return
        now = time.monotonic()
        if now - last_download_heartbeat < 15: return
        last_download_heartbeat = now
        progress(status="downloading")
    options["progress_hooks"] = [download_heartbeat]
    progress(status="downloading")
    try:
        page_title, media_url, source_metadata = resolve_page(url)
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(media_url, download=True)
            if info.get("_type") == "playlist": raise RuntimeError("プレイリスト取得は無効です")
            prepared = Path(downloader.prepare_filename(info))
            candidates = list(job_dir.glob(f"{info.get('id', '')}-*"))
            videos = [p for p in candidates if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
            video_path = videos[0] if videos else prepared
            metadata = video_path.with_suffix(".normalized.json")
            source_id = Path(urlparse(url).path.rstrip("/")).name or info.get("id")
            normalized = {"source":"missav","source_url":url,"source_id":source_id,"title":page_title or info.get("title") or "","description":source_metadata.get("description") or info.get("description") or "","source_metadata":source_metadata,"duration":info.get("duration"),"thumbnail":info.get("thumbnail"),"upload_date":info.get("upload_date"),"video_path":str(video_path)}
            metadata.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
            if should_analyze:
                progress(status="splitting", title=normalized["title"], video_path=str(video_path), metadata_path=str(metadata))
                frames = extract_video_frames(video_path)
                progress(status="json_building", title=normalized["title"])
                analysis = analyze_video_api(video_path, normalized["title"], normalized["source_metadata"], frames)
                analysis_path = video_path.with_suffix(".analysis.json")
                analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
                product_id = register_analyzed_product(normalized, analysis, video_path)
                progress(status="completed", title=analysis.get("source", {}).get("title") or normalized["title"], video_path=str(video_path) if keep_video else None, metadata_path=str(metadata) if keep_video else None, analysis_path=str(analysis_path) if keep_video else None, product_id=product_id)
            else:
                progress(status="completed", title=normalized["title"], video_path=str(video_path), metadata_path=str(metadata))
    except Exception as exc:
        progress(status="failed", error=safe_error_message(exc))
    finally:
        if should_analyze and not keep_video:
            shutil.rmtree(job_dir, ignore_errors=True)
@app.post("/admin/imports/missav", response_model=ImportJob, status_code=202)
def import_missav(payload: ImportRequest, background: BackgroundTasks):
    validate_missav_url(payload.url)
    if payload.analyze and not import_ai_keys(): raise HTTPException(503, "動画解析にはIMPORT_AI_API_KEYが必要です")
    job_id = uuid.uuid4().hex
    job = ImportJob(id=job_id, status="queued", url=payload.url).model_dump()
    with import_jobs_lock: import_jobs[job_id] = job
    background.add_task(run_missav_import, job_id, payload.url, payload.analyze)
    return job
@app.get("/admin/imports/{job_id}", response_model=ImportJob)
def import_status(job_id: str):
    with import_jobs_lock: job = import_jobs.get(job_id)
    if not job: raise HTTPException(404, "import job not found")
    return job
@app.get("/admin/auto-import/status")
def auto_import_status(s: Session = Depends(db)):
    purge_expired_failed_imports(s)
    zone = ZoneInfo(os.getenv("AUTO_IMPORT_TIMEZONE", "Asia/Tokyo"))
    start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    counts = dict(s.execute(select(AutoImport.status, func.count(AutoImport.id)).group_by(AutoImport.status)).all())
    used_today = s.scalar(select(func.count(AutoImport.id)).where(AutoImport.status == "completed", AutoImport.processed_at >= start, AutoImport.is_manual.is_(False))) or 0
    stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)
    active_statuses = ("processing", "downloading", "splitting", "json_building")
    ghost_count = s.scalar(select(func.count(AutoImport.id)).where(AutoImport.status.in_(active_statuses), AutoImport.updated_at < stale_before)) or 0
    recent = s.scalars(select(AutoImport).order_by(AutoImport.id.desc()).limit(10)).all()
    return {"enabled":auto_import_enabled(s),"daily_limit":max(1,min(int(os.getenv("AUTO_IMPORT_DAILY_LIMIT", "3")),30)),"used_today":used_today,"feed_configured":bool(os.getenv("MISSAV_FEED_URL")),"ghost_count":ghost_count,"counts":counts,"recent":[{"id":x.id,"url":x.source_url,"status":x.status,"title":x.title,"product_id":x.product_id,"attempts":x.attempts,"error":x.error} for x in recent]}
@app.post("/admin/auto-import/control")
def auto_import_control(payload: AutoImportControlRequest, s: Session = Depends(db)):
    setting = s.get(AppSetting, "auto_import_enabled")
    if setting: setting.value = "true" if payload.enabled else "false"
    else: s.add(AppSetting(key="auto_import_enabled", value="true" if payload.enabled else "false"))
    s.commit()
    return {"enabled":payload.enabled}
@app.delete("/admin/auto-import/pending")
def delete_pending_auto_imports(s: Session = Depends(db)):
    stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)
    active_statuses = ("processing", "downloading", "splitting", "json_building")
    targets = s.scalars(select(AutoImport).where(
        (AutoImport.status == "pending") |
        (AutoImport.status.in_(active_statuses) & (AutoImport.updated_at < stale_before))
    )).all()
    pending_count = sum(item.status == "pending" for item in targets)
    ghost_ids = [item.id for item in targets if item.status != "pending"]
    target_ids = [item.id for item in targets]
    if target_ids:
        s.execute(delete(AutoImport).where(AutoImport.id.in_(target_ids)))
    s.commit()
    media_dir = Path(os.getenv("MEDIA_DIR", str(DEFAULT_MEDIA_DIR)))
    for import_id in ghost_ids:
        for job_dir in media_dir.glob(f"auto-{import_id}-*"):
            shutil.rmtree(job_dir, ignore_errors=True)
    return {"deleted":len(target_ids),"deleted_pending":pending_count,"deleted_ghosts":len(ghost_ids),"deleted_ids":target_ids}
@app.post("/admin/auto-import/run-now")
def auto_import_run_now(s: Session = Depends(db)):
    if not import_ai_keys(): return {"accepted":False,"message":"IMPORT_AI_API_KEYが未設定です"}
    saved_urls = {attrs.get("source_url") for attrs in s.scalars(select(Product.attributes)).all() if isinstance(attrs, dict) and attrs.get("source_url")}
    pending = s.scalars(select(AutoImport).where(AutoImport.status == "pending", AutoImport.attempts == 0)).all()
    pending = [item for item in pending if item.source_url not in saved_urls]
    if pending:
        selected_item = random.choice(pending)
        selected_item.is_manual = True
        selected = selected_item.source_url
    else:
        selected_item = None
        selected = None
    feed_url = os.getenv("MISSAV_FEED_URL", "").strip()
    if selected is None:
        if not feed_url: return {"accepted":False,"message":"未処理の待機作品がなく、MISSAV_FEED_URLも未設定です"}
        try:
            candidates = discover_feed_urls(feed_url)
        except Exception as exc:
            return {"accepted":False,"message":f"作品一覧を取得できませんでした: {str(exc)[:240]}"}
        known = set(s.scalars(select(AutoImport.source_url).where(AutoImport.source_url.in_(candidates))))
        fresh = [url for url in candidates if url not in known and url not in saved_urls]
        if not fresh: return {"accepted":False,"message":"未取得・未登録の新しい作品がありません"}
        selected = random.choice(fresh)
        s.add(AutoImport(source_url=selected, is_manual=True))
    setting = s.get(AppSetting, "auto_import_run_now")
    if setting: setting.value = "true"
    else: s.add(AppSetting(key="auto_import_run_now", value="true"))
    s.commit()
    return {"accepted":True,"message":f"新しい作品を選びました: {selected}"}
@app.post("/admin/auto-import/enqueue", status_code=202)
def auto_import_enqueue(payload: AutoImportEnqueueRequest, s: Session = Depends(db)):
    urls = list(dict.fromkeys(url.strip() for url in payload.urls if url.strip()))
    if not urls or len(urls) > 10: raise HTTPException(400, "1〜10件のURLを指定してください")
    for url in urls: validate_missav_url(url)
    existing = set(s.scalars(select(AutoImport.source_url).where(AutoImport.source_url.in_(urls))))
    queued = [url for url in urls if url not in existing]
    s.add_all([AutoImport(source_url=url, is_manual=True) for url in queued]); s.commit()
    return {"queued":queued,"duplicates":[url for url in urls if url in existing]}
def local_filters(q: str) -> SearchFilters:
    f = SearchFilters(query=q); m = re.search(r"(\d+)\s*人", q)
    if m: f.people = int(m.group(1))
    for field, words in {"hair_color":["黒髪","金髪","茶髪","赤髪","銀髪"], "hair_style":["ロング","ショート","ボブ","ポニーテール","ウェーブ"], "clothing":["制服","スーツ","ワンピース","スポーツウェア","私服","水着"], "location":["ホテル","学校","オフィス","屋外","自宅"]}.items():
        for w in words:
            if w in q: setattr(f, field, w.replace("髪", "") if field == "hair_color" else w)
    if re.search(r"(?:メガネ|眼鏡)(?:は)?(?:なし|無し|かけていない|不要)", q): f.glasses = False
    elif "メガネ" in q or "眼鏡" in q: f.glasses = True
    for performer_type in ("清楚系", "クール系", "お姉さん系", "かわいい系", "ギャル系"):
        if performer_type in q or performer_type.removesuffix("系") in q: f.performer_type = performer_type
    m = re.search(r"(20\d{2})年", q)
    if m: f.release_year = int(m.group(1))
    product_code = re.search(r"\b([A-Za-z]{2,12})[-_\s]?(\d{2,6})\b", q)
    if product_code: f.product_code = f"{product_code.group(1)}-{product_code.group(2)}"
    return f
async def ai_filters(q: str) -> SearchFilters:
    key = query_ai_key()
    if not key: return local_filters(q)
    try:
        prompt = """日本語の作品検索文をJSONだけに変換してください。
キー: people, performer_type, hair_color, hair_style, glasses, clothing, location, release_year, genre, keyword, maker, label, director, performer, product_code。指定がない値はnull。
hair_colorは「黒」「茶」「金」「赤」「銀」の形にし、「髪」を付けないでください。
performer_typeは「清楚系」「クール系」「お姉さん系」「かわいい系」「ギャル系」のいずれかです。
「メガネなし」「眼鏡をかけていない」はglasses=false、着用を求める場合だけtrueです。
genre、maker、label、director、performer、product_codeは検索文で明示された場合だけ抽出してください。
検索文: """ + q
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{query_ai_model()}:generateContent?key={key}", json={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json"}})
            r.raise_for_status(); raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            parsed = SearchFilters(query=q, **json.loads(raw))
            local = local_filters(q)
            for field in ("people", "performer_type", "hair_color", "hair_style", "glasses", "clothing", "location", "release_year", "product_code"):
                local_value = getattr(local, field)
                if local_value is not None: setattr(parsed, field, local_value)
            return parsed
    except Exception: return local_filters(q)

def text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [text for item in value for text in text_values(item)]
    return []

def build_search_text(title: str, description: str, metadata: dict[str, Any], visual: dict[str, Any], performers: list[Performer] | None = None) -> str:
    values = [title, description]
    for field in ("product_code", "maker", "label", "director", "genres", "actresses"):
        values.extend(text_values(metadata.get(field)))
    for field in ("summary", "keywords", "clothing", "locations", "mood"):
        values.extend(text_values(visual.get(field)))
    if performers:
        for performer in performers:
            values.extend([performer.name, performer.type, performer.hair_color, performer.hair_style])
    return " ".join(dict.fromkeys(value.strip() for value in values if value and value.strip()))

def normalized_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    hiragana = "".join(
        chr(ord(character) - 0x60)
        if "ァ" <= character <= "ヶ"
        else character
        for character in normalized
    )
    return re.sub(r"\s+", "", hiragana)

def product_lexical_score(product: Product, query: str, parsed: SearchFilters) -> int:
    attributes = product.attributes or {}
    metadata = attributes.get("source_metadata") if isinstance(attributes.get("source_metadata"), dict) else {}
    visual = attributes.get("visual_analysis") if isinstance(attributes.get("visual_analysis"), dict) else {}
    requested = [query]
    for field in ("genre", "keyword", "maker", "label", "director", "performer", "product_code"):
        value = getattr(parsed, field)
        if value: requested.append(value)
    needle = normalized_search_text(" ".join(requested))
    if not needle: return 0
    groups = [
        (100, text_values(metadata.get("product_code")) + [attributes.get("source_id", "")]),
        (40, [product.title]),
        (30, text_values(metadata.get("maker")) + text_values(metadata.get("label")) + text_values(metadata.get("director"))),
        (30, text_values(metadata.get("actresses")) + [performer.name for performer in product.performers]),
        (25, text_values(metadata.get("genres"))),
        (18, text_values(visual.get("keywords")) + text_values(visual.get("clothing")) + text_values(visual.get("locations")) + text_values(visual.get("mood"))),
        (6, [product.description, str(visual.get("summary", ""))]),
    ]
    score = 0
    compact_code_query = re.sub(r"[^a-z0-9]", "", needle)
    for weight, values in groups:
        for value in values:
            normalized = normalized_search_text(str(value))
            if len(normalized) < 2: continue
            if normalized in needle or needle in normalized:
                score += weight
            elif weight == 100 and re.sub(r"[^a-z0-9]", "", normalized) in compact_code_query:
                score += weight
    return score
async def embedding(text: str):
    key = query_ai_key()
    if not key: return None
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{query_embedding_model()}:embedContent?key={key}", json={"content":{"parts":[{"text":text}]}})
            r.raise_for_status(); return r.json()["embedding"]["values"]
    except Exception: return None
@app.get("/health")
def health(): return {"ok": True, "query_ai_configured": bool(query_ai_key()), "import_ai_configured": bool(import_ai_keys()), "description_ai_configured": bool(description_ai_key())}
FANZA_CONTENT_ID_PREFIXES = {
    "VNDS": "h_254",
    "IRO": "h_086",
    "NHDTC": "1",
    "SW": "1",
}
def fanza_content_id(attributes: dict[str, Any]) -> str | None:
    stored_content_id = str(attributes.get("fanza_content_id") or "").strip()
    if stored_content_id:
        return stored_content_id
    source_metadata = attributes.get("source_metadata")
    metadata = source_metadata if isinstance(source_metadata, dict) else {}
    product_code = str(metadata.get("product_code") or attributes.get("source_id") or "")
    match = re.search(r"([a-z0-9]+)[-_](\d+)", product_code.lower())
    if not match:
        return None
    product_prefix = match.group(1)
    base_content_id = f"{product_prefix}{int(match.group(2)):05d}"
    internal_prefix = FANZA_CONTENT_ID_PREFIXES.get(product_prefix.upper(), "")
    return f"{internal_prefix}{base_content_id}"
def fanza_image_url(attributes: dict[str, Any], size: str = "pl") -> str | None:
    stored_url = str(attributes.get("fanza_image_url") or "").strip()
    if stored_url:
        return re.sub(r"pl\.jpg(?:\?.*)?$", f"{size}.jpg", stored_url) if size == "ps" else stored_url
    content_id = fanza_content_id(attributes)
    if not content_id:
        return None
    return f"https://pics.dmm.co.jp/digital/video/{content_id}/{content_id}{size}.jpg"
@app.get("/media/thumbnail/{external_id}")
def proxy_thumbnail(external_id: str, s: Session = Depends(db)):
    product = s.scalar(select(Product).where(or_(
        Product.external_id == external_id,
        Product.external_id == f"missav-{external_id}",
        Product.attributes["source_id"].astext == external_id,
    )))
    if not product: raise HTTPException(404, "product not found")
    image_url = fanza_image_url(product.attributes or {})
    if not image_url: raise HTTPException(404, "thumbnail not found")
    try:
        image = httpx.get(image_url, timeout=15, follow_redirects=True)
        image.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "thumbnail provider unavailable") from exc
    return Response(content=image.content, media_type=image.headers.get("content-type", "image/jpeg"), headers={"Cache-Control": "public, max-age=86400"})
def product_json(p: Product) -> dict[str, Any]:
    attributes = p.attributes or {}
    stored_visual = attributes.get("visual_analysis")
    visual_analysis = stored_visual if isinstance(stored_visual, dict) else {
        "summary": attributes.get("summary", ""),
        "people": attributes.get("人数", 0),
        "performers": [
            {
                "name": x.name,
                "type": x.type,
                "hair_color": x.hair_color,
                "hair_style": x.hair_style,
                "glasses": x.glasses,
            }
            for x in p.performers
        ],
        "clothing": attributes.get("衣装", []),
        "locations": attributes.get("場所", []),
        "mood": attributes.get("雰囲気", []),
        "keywords": attributes.get("キーワード", []),
    }
    return {
        "schema_version": attributes.get("schema_version", ANALYSIS_SCHEMA_VERSION),
        "id": p.id,
        "external_id": p.external_id,
        "title": attributes.get("source_title") or p.title,
        "description": p.description,
        "release_date": p.release_date.isoformat() if p.release_date else None,
        "fanza_url": p.fanza_url,
        "performers": [
            {
                "name": performer.name,
                "type": performer.type,
                "hair_color": performer.hair_color,
                "hair_style": performer.hair_style,
                "glasses": performer.glasses,
            }
            for performer in p.performers
        ],
        "attributes": attributes,
        "source": {
            "title": attributes.get("source_title") or p.title,
            "description": p.description,
            "metadata": attributes.get("source_metadata", {}),
            "release_date": p.release_date.isoformat() if p.release_date else None,
            "url": p.fanza_url,
            "source_id": attributes.get("source_id"),
        },
        "visual_analysis": visual_analysis,
        "media": {
            "fanza_content_id": fanza_content_id(attributes),
            "thumbnail_url": f"/api/media/thumbnail/{attributes.get('source_id')}" if fanza_image_url(attributes) and attributes.get("source_id") else None,
            "thumbnail_small_url": f"/api/media/thumbnail/{attributes.get('source_id')}?size=small" if fanza_image_url(attributes) and attributes.get("source_id") else None,
            "provider": "FANZA",
        },
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
@app.get("/products/recommended")
def recommended_products(limit: int = 6, s: Session = Depends(db)):
    safe_limit = max(1, min(limit, 12))
    products = s.scalars(
        select(Product)
        .where(Product.attributes["source"].astext == "missav")
        .order_by(Product.created_at.desc(), Product.id.desc())
        .limit(safe_limit)
    ).unique().all()
    return {"items": [product_json(p) for p in products]}
@app.get("/products/popular")
def popular_products(limit: int = 6, s: Session = Depends(db)):
    safe_limit = max(1, min(limit, 12))
    view_count = func.count(ClickLog.id)
    products = s.scalars(
        select(Product)
        .outerjoin(ClickLog, ClickLog.product_id == Product.id)
        .where(Product.attributes["source"].astext == "missav")
        .group_by(Product.id)
        .order_by(view_count.desc(), Product.created_at.desc(), Product.id.desc())
        .limit(safe_limit)
    ).unique().all()
    return {"items": [product_json(p) for p in products]}
@app.get("/products/imported")
def imported_products(s: Session = Depends(db)):
    products = s.scalars(
        select(Product)
        .where(Product.attributes["source"].astext == "missav")
        .order_by(Product.created_at.desc(), Product.id.desc())
    ).unique().all()
    return {"items": [product_json(p) for p in products]}

@app.get("/search/suggestions")
def search_suggestions(q: str = "", limit: int = 12, s: Session = Depends(db)):
    needle = normalized_search_text(q)
    if not needle:
        return {"items": []}
    counts: dict[tuple[str, str], int] = {}

    def add(kind: str, values: Any) -> None:
        for value in text_values(values):
            if len(value) < 1:
                continue
            key = (kind, value)
            counts[key] = counts.get(key, 0) + 1

    for genre in FANZA_GENRES:
        counts[("FANZAジャンル", genre)] = 0

    products = s.scalars(select(Product)).unique().all()
    for product in products:
        attributes = product.attributes or {}
        metadata = attributes.get("source_metadata") if isinstance(attributes.get("source_metadata"), dict) else {}
        visual = attributes.get("visual_analysis") if isinstance(attributes.get("visual_analysis"), dict) else {}
        add("FANZAジャンル", metadata.get("genres"))
        add("タグ", visual.get("keywords"))
        add("タグ", visual.get("clothing"))
        add("タグ", visual.get("locations"))
        add("タグ", visual.get("mood"))
        add("女優", metadata.get("actresses"))
        for performer in product.performers:
            if performer.name and not re.match(r"^(?:出演者|モック出演者)\d", performer.name):
                add("女優", performer.name)
        add("メーカー", metadata.get("maker"))
        add("レーベル", metadata.get("label"))
        add("監督", metadata.get("director"))
        add("品番", metadata.get("product_code"))
        add("作品", product.title)

    category_order = {"女優": 0, "FANZAジャンル": 1, "タグ": 2, "メーカー": 3, "レーベル": 4, "監督": 5, "品番": 6, "作品": 7}
    matches = [
        (kind, value, count)
        for (kind, value), count in counts.items()
        if needle in normalized_search_text(value)
    ]
    matches.sort(key=lambda item: (
        0 if normalized_search_text(item[1]).startswith(needle) else 1,
        category_order.get(item[0], 99),
        -item[2],
        len(item[1]),
        item[1],
    ))
    safe_limit = max(1, min(limit, 30))
    return {
        "items": [
            {"type": kind, "value": value, "count": count}
            for kind, value, count in matches[:safe_limit]
        ]
    }

@app.get("/products/{product_id}/json")
def product_json_detail(product_id: int, s: Session = Depends(db)):
    product = s.get(Product, product_id)
    if not product: raise HTTPException(404, "product not found")
    return product_json(product)
@app.get("/products/by-external/{external_id}/json")
def product_json_external_detail(external_id: str, s: Session = Depends(db)):
    product = s.scalar(select(Product).where(or_(
        Product.external_id == external_id,
        Product.external_id == f"missav-{external_id}",
        Product.attributes["source_id"].astext == external_id,
    )))
    if not product: raise HTTPException(404, "product not found")
    return product_json(product)
@app.post("/products/{product_id}/view", status_code=201)
def record_product_view(product_id: int, s: Session = Depends(db)):
    if not s.get(Product, product_id):
        raise HTTPException(404, "product not found")
    s.add(ClickLog(product_id=product_id))
    s.commit()
    return {"recorded": True}
@app.post("/products/by-external/{external_id}/view", status_code=201)
def record_external_product_view(external_id: str, s: Session = Depends(db)):
    product = s.scalar(select(Product).where(or_(
        Product.external_id == external_id,
        Product.external_id == f"missav-{external_id}",
        Product.attributes["source_id"].astext == external_id,
    )))
    if not product: raise HTTPException(404, "product not found")
    s.add(ClickLog(product_id=product.id)); s.commit()
    return {"recorded": True}
@app.post("/admin/products", response_model=ProductOut)
async def create_product(payload: ProductIn, s: Session = Depends(db)):
    metadata = payload.attributes.get("source_metadata", {}) if isinstance(payload.attributes, dict) else {}
    visual = payload.attributes.get("visual_analysis", {}) if isinstance(payload.attributes, dict) else {}
    search_text = build_search_text(payload.title, payload.description, metadata, visual)
    p = Product(**payload.model_dump(exclude={"performers"}), embedding=await embedding(search_text))
    p.performers = [Performer(**x.model_dump()) for x in payload.performers]; s.add(p); s.commit(); s.refresh(p); return p
@app.post("/admin/products/seed")
def seed(s: Session = Depends(db)):
    if s.scalar(select(func.count(Product.id))): return {"message":"already seeded"}
    samples = [ProductIn(external_id="sample-001", title="黒髪清楚系 スーツのホテル", description="清楚系の女性。ホテルが舞台。", release_date=date(2024,6,1), fanza_url="https://www.dmm.co.jp/", performers=[PerformerIn(name="サンプル花子", type="清楚系", hair_color="黒", hair_style="ロング")], attributes={"人数":1,"衣装":["スーツ"],"場所":["ホテル"]}), ProductIn(external_id="sample-002", title="金髪ボブ 制服", description="制服と学校のシーン。", release_date=date(2023,3,1), fanza_url="https://www.dmm.co.jp/", performers=[PerformerIn(name="サンプル美咲", hair_color="金", hair_style="ボブ")], attributes={"人数":1,"衣装":["制服"],"場所":["学校"]})]
    for x in samples:
        p=Product(**x.model_dump(exclude={"performers"})); p.performers=[Performer(**z.model_dump()) for z in x.performers]; s.add(p)
    s.commit(); return {"message":"seeded", "count":len(samples)}
@app.post("/search")
async def search(filters: SearchFilters, s: Session = Depends(db)):
    f = await ai_filters(filters.query) if filters.query else filters
    f.selected_tags = filters.selected_tags
    query_vector = await embedding(filters.query) if filters.query else None
    stmt = select(Product).order_by(Product.release_date.desc().nullslast())
    if query_vector: stmt = select(Product).order_by(Product.embedding.cosine_distance(query_vector).asc().nullslast())
    if f.release_year: stmt=stmt.where(func.extract("year", Product.release_date)==f.release_year)
    products=list(s.scalars(stmt).unique())
    def match(p):
        attrs=p.attributes or {}; ps=p.performers
        metadata = attrs.get("source_metadata") if isinstance(attrs.get("source_metadata"), dict) else {}
        visual = attrs.get("visual_analysis") if isinstance(attrs.get("visual_analysis"), dict) else {}
        def contains_value(expected: str, values: Any) -> bool:
            normalized_expected = normalized_search_text(expected)
            return any(
                normalized_expected in normalized_search_text(value)
                or normalized_search_text(value) in normalized_expected
                for value in text_values(values)
            )
        if f.people is not None and attrs.get("人数") != f.people: return False
        for value, attr in [(f.performer_type,"type"),(f.hair_color,"hair_color"),(f.hair_style,"hair_style"),(f.glasses,"glasses")]:
            if value is not None and not any(getattr(x,attr)==value for x in ps): return False
        if f.clothing and not contains_value(f.clothing, [
            *text_values(attrs.get("衣装")),
            *text_values(visual.get("clothing")),
            *text_values(visual.get("keywords")),
            *text_values(metadata.get("genres")),
        ]): return False
        if f.location and not contains_value(f.location, [
            *text_values(attrs.get("場所")),
            *text_values(visual.get("locations")),
            *text_values(visual.get("keywords")),
        ]): return False
        selected_values = {
            "FANZAジャンル": metadata.get("genres"),
            "タグ": [
                *text_values(visual.get("keywords")),
                *text_values(visual.get("clothing")),
                *text_values(visual.get("locations")),
                *text_values(visual.get("mood")),
            ],
            "女優": [*text_values(metadata.get("actresses")), *[performer.name for performer in ps], p.title],
            "メーカー": metadata.get("maker"),
            "レーベル": metadata.get("label"),
            "監督": metadata.get("director"),
            "品番": [metadata.get("product_code", ""), attrs.get("source_id", "")],
            "作品": p.title,
        }
        for selected in f.selected_tags:
            if not contains_value(selected.value, selected_values.get(selected.type, [])):
                return False
        return True
    matched = [product for product in products if match(product)]
    semantic_order = {product.id: index for index, product in enumerate(matched)}
    matched.sort(key=lambda product: (-product_lexical_score(product, filters.query, f), semantic_order[product.id]))
    return {
        "filters": f.model_dump(),
        "results": [product_json(product) for product in matched],
    }
@app.get("/go/{product_id}")
def go(product_id:int, s:Session=Depends(db)):
    p=s.get(Product,product_id)
    if not p: raise HTTPException(404,"product not found")
    s.add(ClickLog(product_id=product_id)); s.commit(); url=p.fanza_url; aid=os.getenv("FANZA_AFFILIATE_ID")
    if aid: url += ("&" if "?" in url else "?") + "affiliate_id=" + aid
    return RedirectResponse(url=url, status_code=307)
