"""Shared HTTP plumbing for ATS fetchers: retries, per-host rate limiting, response caching."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from pipeline.settings import REPO_ROOT, is_ci

USER_AGENT = "appollo/0.1 (+https://github.com/Sanket0412/appollo)"
REQUEST_TIMEOUT = 20
MIN_HOST_INTERVAL = 1.0
CACHE_TTL_SECONDS = 6 * 3600
CACHE_DIR = REPO_ROOT / "data" / "cache" / "http"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = USER_AGENT

_last_request_at: dict[str, float] = {}


def _rate_limit(host: str) -> None:
    wait = MIN_HOST_INTERVAL - (time.monotonic() - _last_request_at.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, requests.ConnectionError | requests.Timeout):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


def _wait_for_retry_after(retry_state):
    exc = retry_state.outcome.exception()
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        header = exc.response.headers.get("Retry-After")
        if header and header.isdigit():
            return float(header)
    return wait_exponential(multiplier=1, min=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception(_should_retry),
    stop=stop_after_attempt(4),
    wait=_wait_for_retry_after,
    reraise=True,
)
def _request(method: str, url: str, **kwargs) -> requests.Response:
    host = urlparse(url).netloc
    _rate_limit(host)
    try:
        resp = SESSION.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
    finally:
        _last_request_at[host] = time.monotonic()
    if resp.status_code == 429 or resp.status_code >= 500:
        resp.raise_for_status()
    return resp


def _cache_path(method: str, url: str, body: dict | None) -> Path:
    key_raw = f"{method}:{url}:{json.dumps(body, sort_keys=True) if body else ''}"
    key = hashlib.sha1(key_raw.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.json"


def _read_cache(path: Path):
    if is_ci() or not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_cache(path: Path, payload) -> None:
    if is_ci():
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f)


def get_json(url: str, use_cache: bool = True):
    cache_path = _cache_path("GET", url, None)
    if use_cache:
        cached = _read_cache(cache_path)
        if cached is not None:
            return cached

    resp = _request("GET", url)
    resp.raise_for_status()
    payload = resp.json()
    if use_cache:
        _write_cache(cache_path, payload)
    return payload


def post_json(url: str, body: dict, use_cache: bool = True):
    cache_path = _cache_path("POST", url, body)
    if use_cache:
        cached = _read_cache(cache_path)
        if cached is not None:
            return cached

    resp = _request("POST", url, json=body)
    resp.raise_for_status()
    payload = resp.json()
    if use_cache:
        _write_cache(cache_path, payload)
    return payload
