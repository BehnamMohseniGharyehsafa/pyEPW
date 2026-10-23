"""Public-endpoint HTTP transport, retries, and a local response cache."""

from __future__ import annotations

import hashlib
import gzip
import io
import json
import logging
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ._files import atomic_text, atomic_bytes, default_cache_dir
from ._version import __version__
from .exceptions import APIError

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
logger = logging.getLogger(__name__)


class APIClient:
    """Internal HTTP client; imports and construction do not contact the network."""

    def __init__(self, cache_dir: str | Path | None = None, refresh: bool = False):
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
        self.refresh = refresh
        self.urls: list[str] = []
        self.text_sources: list[dict[str, Any]] = []

    def get_text(self, url: str, *, expected_start: str | None = None) -> str:
        """Fetch a bounded public text dataset with caching and format checking.

        Used for NOAA's station list / station-year PSV files. No authentication
        or paid endpoints. The original text is retained for audit/reproduction.
        """
        self.urls.append(url)
        cached = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".txt")

        def valid(value):
            return (
                bool(value.strip())
                and not value.lstrip().lower().startswith(("<!doctype", "<html"))
                and (expected_start is None or value.startswith(expected_start))
            )

        result = None
        if cached.exists() and not self.refresh:
            try:
                with cached.open(encoding="utf-8", newline="") as source_stream:
                    candidate = source_stream.read()
                if valid(candidate):
                    result = candidate
            except (OSError, UnicodeError):
                pass
        if result is None:
            compressed_payload = None
            request = Request(url, headers={"User-Agent": f"pyEPW/{__version__}", "Accept": "text/plain,text/csv"})
            for attempt in range(3):
                try:
                    with urlopen(request, timeout=90) as response:
                        raw = response.read(64 * 1024 * 1024 + 1)
                    if len(raw) > 64 * 1024 * 1024:
                        raise APIError("Station dataset exceeds the 64 MiB safety limit.")
                    if url.endswith(".gz"):
                        if not raw.startswith(b"\x1f\x8b"):
                            raise APIError("Public dataset is not the expected gzip archive.")
                        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as archive:
                            decoded = archive.read(64 * 1024 * 1024 + 1)
                        if len(decoded) > 64 * 1024 * 1024:
                            raise APIError("Decoded station dataset exceeds the 64 MiB safety limit.")
                        compressed_payload = raw
                    else:
                        decoded = raw
                    result = decoded.decode("utf-8-sig")
                    if not valid(result):
                        raise APIError(f"Unexpected public dataset format: {url}")
                    break
                except HTTPError as exc:
                    if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                        time.sleep(2 ** (attempt + 1))
                        continue
                    raise APIError(f"Public dataset HTTP {exc.code}: {url}") from exc
                except (URLError, TimeoutError, OSError) as exc:
                    if attempt < 2:
                        time.sleep(2 ** (attempt + 1))
                        continue
                    raise APIError(f"Cannot download public station dataset: {url}: {exc}") from exc
                except UnicodeError as exc:
                    raise APIError(f"Station dataset is not valid UTF-8: {url}") from exc
                except EOFError as exc:
                    raise APIError(f"Truncated gzip station dataset: {url}") from exc
            if compressed_payload is not None:
                atomic_bytes(cached.with_suffix(".gz"), compressed_payload)
            atomic_text(cached, result)
        self.text_sources.append(
            {"url": url, "sha256_utf8": hashlib.sha256(result.encode("utf-8")).hexdigest(), "cached_file": cached.name}
        )
        compressed = cached.with_suffix(".gz")
        if url.endswith(".gz") and compressed.exists():
            self.text_sources[-1].update(
                compressed_cached_file=compressed.name,
                compressed_sha256=hashlib.sha256(compressed.read_bytes()).hexdigest(),
            )
        return result

    def get(self, endpoint: str, parameters: dict[str, Any]) -> dict[str, Any]:
        url = endpoint + "?" + urlencode(parameters)
        self.urls.append(url)
        cached = self.cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if cached.exists() and not self.refresh:
            try:
                result = json.loads(cached.read_text(encoding="utf-8"))
                if isinstance(result, dict) and not result.get("error"):
                    logger.debug("Cache hit: %s", url)
                    return result
            except (OSError, ValueError):
                logger.debug("Ignoring an unreadable cache entry: %s", cached)
        request = Request(
            url,
            headers={
                "User-Agent": f"pyEPW/{__version__}",
                "Accept": "application/json",
            },
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=60) as response:
                    result = json.load(response)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    retry_after = exc.headers.get("Retry-After", "")
                    delay = min(30, int(retry_after)) if retry_after.isdigit() else 2 ** (attempt + 1)
                    logger.warning("HTTP %s; retrying in %ss", exc.code, delay)
                    time.sleep(delay)
                    continue
                raise APIError(f"Open-Meteo HTTP {exc.code}: {detail}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise APIError(f"Cannot reach Open-Meteo: {exc}. Check your internet connection.") from exc
            except (ValueError, UnicodeError) as exc:
                raise APIError("Open-Meteo did not return valid JSON.") from exc
            if not isinstance(result, dict) or result.get("error"):
                reason = (
                    result.get("reason", "Unexpected response") if isinstance(result, dict) else "Unexpected response"
                )
                raise APIError(str(reason))
            # Cache failures are local I/O failures, not network failures. Do not
            # retry successful downloads or conceal permission errors.
            atomic_text(cached, json.dumps(result, ensure_ascii=False))
            return result
        raise APIError("Open-Meteo request failed.")
