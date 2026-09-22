import html
import json
import re
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests


MEDIA_URL_RE = re.compile(
    r"https?://[^\"'<>\\\s]+?\.(?:m3u8|mp4)(?:\?[^\"'<>\\\s]*)?",
    re.IGNORECASE,
)
BLOCKED_PATHS = {"genres", "makers", "actresses", "series", "new", "release", "search", "login", "signup", "dm18"}


def _clean_url(value: str, page_url: str) -> str:
    value = html.unescape(value).replace("\\/", "/").replace("\\u0026", "&")
    return urljoin(page_url, value.strip())


def _media_candidates(soup: BeautifulSoup, page_url: str, raw_html: str) -> list[str]:
    candidates: list[str] = []

    for tag in soup.select("video[src], video source[src], source[src]"):
        candidates.append(_clean_url(tag.get("src", ""), page_url))

    for tag in soup.select('meta[property="og:video"], meta[property="og:video:url"], meta[name="twitter:player:stream"]'):
        candidates.append(_clean_url(tag.get("content", ""), page_url))

    normalized_html = raw_html.replace("\\/", "/").replace("\\u0026", "&")
    candidates.extend(_clean_url(match, page_url) for match in MEDIA_URL_RE.findall(normalized_html))
    candidates.extend(_packed_media_candidates(raw_html, page_url))

    # Some pages place the player configuration in a JSON script block.
    for script in soup.select('script[type="application/json"], script#__NEXT_DATA__'):
        text = script.string or script.get_text()
        candidates.extend(_clean_url(match, page_url) for match in MEDIA_URL_RE.findall(text))
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            continue
        candidates.extend(_walk_media_values(payload, page_url))

    return list(dict.fromkeys(url for url in candidates if urlparse(url).scheme in {"http", "https"}))


def _walk_media_values(value, page_url: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            found.extend(_walk_media_values(child, page_url))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_media_values(child, page_url))
    elif isinstance(value, str) and re.search(r"\.(?:m3u8|mp4)(?:\?|$)", value, re.I):
        found.append(_clean_url(value, page_url))
    return found


def _packed_media_candidates(raw_html: str, page_url: str) -> list[str]:
    """Decode the small packed player snippet used by MissAV."""
    found: list[str] = []
    packed_re = re.compile(r"\('(?P<program>.*?)',\s*\d+,\s*\d+,\s*'(?P<tokens>[^']*)'\.split\('\|\'\)", re.S)
    assignment_re = re.compile(r"(?P<key>[A-Za-z0-9]+)=\\?'(?P<value>[^']*)")
    for match in packed_re.finditer(raw_html):
        program = match.group("program").replace("\\'", "'")
        tokens = match.group("tokens").split("|")
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
        values = {}
        for index, value in enumerate(tokens):
            values[str(index)] = value
            if index < len(alphabet): values[alphabet[index]] = value
        for template in re.findall(r"[A-Za-z0-9]+='([^']+)'", program):
            decoded = re.sub(r"[A-Za-z0-9]+", lambda item: values.get(item.group(0), item.group(0)), template)
            if re.search(r"\.(?:m3u8|mp4)(?:\?|$)", decoded, re.I):
                found.append(_clean_url(decoded, page_url))
    return found


def _page_metadata(soup: BeautifulSoup) -> dict:
    description_tag = soup.select_one('meta[name="description"], meta[property="og:description"]')
    metadata = {
        "description": description_tag.get("content", "").strip() if description_tag else "",
        "release_date": "",
        "product_code": "",
        "genres": [],
        "maker": "",
        "director": "",
        "label": "",
        "actresses": [],
    }
    labels = {
        "配信開始日": "release_date",
        "品番": "product_code",
        "ジャンル": "genres",
        "メーカー": "maker",
        "監督": "director",
        "レーベル": "label",
        "出演者": "actresses",
        "女優": "actresses",
    }
    for row in soup.select("div.text-secondary"):
        label_tag = row.find("span")
        if not label_tag:
            continue
        label = label_tag.get_text(" ", strip=True).rstrip(":：")
        field = labels.get(label)
        if not field:
            continue
        if field in {"genres", "actresses"}:
            metadata[field] = list(dict.fromkeys(a.get_text(" ", strip=True) for a in row.select("a[href]") if a.get_text(" ", strip=True)))
        elif field == "release_date":
            time_tag = row.find("time")
            metadata[field] = ((time_tag.get("datetime", "").split("T", 1)[0] or time_tag.get_text(" ", strip=True)) if time_tag else "")
        else:
            value_tag = row.select_one("a.font-medium, span.font-medium")
            metadata[field] = value_tag.get_text(" ", strip=True) if value_tag else ""
    return metadata


def resolve_page(url: str) -> tuple[str, str, dict]:
    """Return (page title, direct media URL, source metadata) from a public MissAV page."""
    response = curl_requests.get(url, impersonate="chrome", timeout=30, allow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = ""
    title_tag = soup.select_one('meta[property="og:title"]')
    if title_tag:
        title = title_tag.get("content", "").strip()
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    candidates = _media_candidates(soup, str(response.url), response.text)
    if not candidates:
        raise RuntimeError(
            "MissAVページから直接動画URLを抽出できませんでした。"
            "ページ構造が変わったか、動画URLがJavaScript実行後にしか提供されていません。"
        )
    return title, candidates[0], _page_metadata(soup)


def discover_feed_urls(feed_url: str) -> list[str]:
    """Find public work URLs from a MissAV listing page."""
    host = (urlparse(feed_url).hostname or "").lower()
    if not re.fullmatch(r"(?:www\.)?missav\.[a-z]{2,}", host):
        raise RuntimeError("MISSAV_FEED_URL must be a MissAV URL")
    response = curl_requests.get(feed_url, impersonate="chrome", timeout=30, allow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    found: list[str] = []
    for anchor in soup.select("a[href]"):
        absolute = urljoin(str(response.url), anchor.get("href", ""))
        parsed = urlparse(absolute)
        if (parsed.hostname or "").lower() != host:
            continue
        segments = [segment.lower() for segment in parsed.path.split("/") if segment]
        if not segments or any(segment in BLOCKED_PATHS for segment in segments):
            continue
        if len(segments) > 2 or (len(segments) == 2 and len(segments[0]) != 2):
            continue
        slug = segments[-1]
        if len(slug) < 3 or not re.search(r"\d", slug) or not re.fullmatch(r"[a-z0-9-]+", slug):
            continue
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        if clean not in found:
            found.append(clean)
    return found
