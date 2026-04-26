"""
Companies House ETL — Extract Layer
=====================================

Ingest strategy (IMPORTANT — read before modifying):
  - M1 bulk snapshot: download monthly flat files from canonical CH domain.
    No authentication. No rate limiting. ~26GB compressed / ~80GB uncompressed.
    Canonical index: https://download.companieshouse.gov.uk/en_output.html
  - Delta updates (post-M1): use CH API with Redis-backed token-bucket rate limiting.
    Rate limit: 600 req / 5 min per key. A 429 response triggers exponential backoff
    starting at 60s; three consecutive 429s = 15-minute pause.
    NEVER use the API for bulk loads — it would take weeks.

PSC snapshot note:
  The PSC bulk file is sometimes published as a single file and sometimes as
  multiple parts (e.g. psc-snapshot-YYYY-MM-DD_1of3.txt.gz). This connector
  handles both formats by reading the live index before downloading.
"""

import gzip
import hashlib
import io
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

CH_INDEX_URL = "https://download.companieshouse.gov.uk/en_output.html"
CH_BULK_BASE = "https://download.companieshouse.gov.uk/"
CH_API_BASE  = "https://api.company-information.service.gov.uk"
RAW_DIR      = Path(__file__).parents[4] / "data" / "raw" / "companies_house"

# ─── Index parsing ─────────────────────────────────────────────────────────────

class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, val in attrs:
                if name == "href" and val:
                    self.links.append(val)


def _fetch_bulk_index() -> list[str]:
    """Return list of filenames available on the CH bulk download index page."""
    with urllib.request.urlopen(CH_INDEX_URL, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    parser = _LinkParser()
    parser.feed(html)
    # Keep only links that look like bulk data files
    files = []
    for link in parser.links:
        # Strip any directory prefix, keep filename
        fname = link.split("/")[-1].split("?")[0]
        if fname and "." in fname:
            files.append(fname)
    return files


def print_bulk_manifest():
    """Fetch the CH download index and print all available bulk files."""
    print(f"Fetching index: {CH_INDEX_URL}")
    files = _fetch_bulk_index()
    print(f"\n{'Filename':<70} URL")
    print("-" * 120)
    for f in sorted(files):
        print(f"{f:<70} {CH_BULK_BASE}{f}")
    print(f"\n{len(files)} files listed.")


def _find_bulk_files(pattern: str) -> list[str]:
    """
    Return filenames from the live CH index matching a regex pattern.
    Raises RuntimeError if no matches found.
    """
    files = _fetch_bulk_index()
    matches = [f for f in files if re.search(pattern, f, re.IGNORECASE)]
    if not matches:
        raise RuntimeError(
            f"No CH bulk files matching '{pattern}' found at {CH_INDEX_URL}. "
            "Check the index manually for the current filename format."
        )
    return sorted(matches)


def _download_file(filename: str, dest_dir: Path) -> Path:
    """
    Download a single bulk file from the CH domain.
    Prints the resolved URL before fetching.
    Idempotent: skips if file already exists and is non-empty.
    Raises RuntimeError on 404 or empty file.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    url  = f"{CH_BULK_BASE}{filename}"

    print(f"  URL: {url}")

    if dest.exists() and dest.stat().st_size > 0:
        logger.info("Already downloaded (skipping): %s", dest)
        return dest

    try:
        urllib.request.urlretrieve(url, dest)
    except urllib.error.HTTPError as e:
        if dest.exists():
            dest.unlink()
        raise RuntimeError(f"CH bulk download failed {e.code}: {url}") from e

    if dest.stat().st_size == 0:
        dest.unlink()
        raise RuntimeError(f"CH bulk download produced empty file: {url}")

    logger.info("Downloaded %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
    return dest


# ─── Bulk download entry points ────────────────────────────────────────────────

def download_company_snapshot(dest_dir: Path | None = None) -> Path:
    """
    Download the BasicCompanyData snapshot.
    Resolves the current filename from the live index before downloading.
    Returns path to .zip file.
    """
    dest_dir = dest_dir or (RAW_DIR / "snapshot")
    print("Resolving company snapshot filename from CH index...")
    matches = _find_bulk_files(r"BasicCompanyDataAsOneFile.*\.zip")
    filename = matches[-1]  # most recent
    print(f"  Found: {filename}")
    return _download_file(filename, dest_dir)


def download_officers_snapshot(dest_dir: Path | None = None) -> list[Path]:
    """
    Download all officer bulk snapshot parts.
    Resolves current filenames from the live index.
    Returns list of downloaded file paths.
    """
    dest_dir = dest_dir or (RAW_DIR / "officers")
    print("Resolving officer snapshot filenames from CH index...")
    matches = _find_bulk_files(r"company-officers.*\.(zip|gz)")
    print(f"  Found {len(matches)} officer file(s)")
    paths = []
    for filename in matches:
        paths.append(_download_file(filename, dest_dir))
    return paths


def download_psc_snapshot(dest_dir: Path | None = None) -> list[Path]:
    """
    Download all PSC snapshot parts (handles single file and multi-part sets).
    Resolves current filenames from the live index.
    Returns list of downloaded file paths in part order.
    """
    dest_dir = dest_dir or (RAW_DIR / "psc")
    print("Resolving PSC snapshot filenames from CH index...")
    # Match both common formats:
    #   persons-with-significant-control-snapshot-YYYY-MM-DD.zip
    #   psc-snapshot-YYYY-MM-DD_1of3.txt.gz
    matches = _find_bulk_files(
        r"(persons-with-significant-control|psc-snapshot).*\.(zip|gz|txt\.gz)"
    )
    print(f"  Found {len(matches)} PSC file(s)")
    paths = []
    for filename in matches:
        paths.append(_download_file(filename, dest_dir))
    return paths


# ─── Streaming iterators ───────────────────────────────────────────────────────

def iter_company_csv(zip_path: Path) -> Iterator[dict]:
    """Stream rows from the company snapshot CSV inside the .zip."""
    import csv
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_names:
            raise ValueError(f"No CSV found inside {zip_path}")
        with zf.open(csv_names[0]) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                yield row


def _iter_jsonl_from_file(path: Path) -> Iterator[dict]:
    """Stream JSONL from a .zip or .gz file."""
    name = path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for member in zf.namelist():
                with zf.open(member) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            yield json.loads(line)
    elif name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
    else:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def iter_officers_jsonl(paths: list[Path] | Path) -> Iterator[dict]:
    """Stream officer records across all downloaded parts."""
    if isinstance(paths, Path):
        paths = [paths]
    for p in paths:
        yield from _iter_jsonl_from_file(p)


def iter_psc_jsonl(paths: list[Path] | Path) -> Iterator[dict]:
    """Stream PSC records across all downloaded parts (single or multi-part)."""
    if isinstance(paths, Path):
        paths = [paths]
    for p in sorted(paths):  # sort ensures _1of3, _2of3, _3of3 order
        yield from _iter_jsonl_from_file(p)


# ─── Redis-backed token bucket (API delta use only) ───────────────────────────

def _api_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _get_redis():
    """Return a Redis client or None if unavailable."""
    try:
        import redis
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(url, socket_connect_timeout=2)
        r.ping()
        return r
    except Exception:
        return None


_redis_client = None
_redis_warned  = False
_in_process_requests: list[float] = []
_API_WINDOW = 300
_API_LIMIT  = 590


def _throttle_api(api_key: str):
    """
    Enforce 590 req / 5 min. Redis-backed so multiple workers sharing one key
    collectively respect the ceiling. Falls back to in-process if Redis is down.
    """
    global _redis_client, _redis_warned, _in_process_requests

    if _redis_client is None:
        _redis_client = _get_redis()

    if _redis_client is not None:
        bucket_key = f"ch_api_token_bucket:{_api_key_hash(api_key)}"
        now = time.time()
        pipe = _redis_client.pipeline()
        pipe.zremrangebyscore(bucket_key, 0, now - _API_WINDOW)
        pipe.zcard(bucket_key)
        _, count = pipe.execute()
        if count >= _API_LIMIT:
            # Find oldest entry to compute sleep time
            oldest = _redis_client.zrange(bucket_key, 0, 0, withscores=True)
            sleep_for = _API_WINDOW - (now - oldest[0][1]) + 1 if oldest else 60
            logger.warning("CH API rate limit reached — sleeping %.1fs", sleep_for)
            time.sleep(sleep_for)
            now = time.time()
        _redis_client.zadd(bucket_key, {str(now): now})
        _redis_client.expire(bucket_key, _API_WINDOW + 10)
    else:
        if not _redis_warned:
            logger.warning(
                "Redis unavailable — using in-process rate limiter. "
                "Do NOT run multiple workers sharing one CH API key without Redis."
            )
            _redis_warned = True
        now = time.time()
        _in_process_requests[:] = [t for t in _in_process_requests if now - t < _API_WINDOW]
        if len(_in_process_requests) >= _API_LIMIT:
            sleep_for = _API_WINDOW - (now - _in_process_requests[0]) + 1
            logger.warning("CH API rate limit reached — sleeping %.1fs", sleep_for)
            time.sleep(sleep_for)
        _in_process_requests.append(time.time())


def _api_get(path: str, api_key: str, retries: int = 5) -> dict:
    """GET from CH API with per-key token-bucket throttling and 429 backoff."""
    import base64
    url     = f"{CH_API_BASE}{path}"
    backoff = 60
    consecutive_429 = 0
    for attempt in range(retries):
        _throttle_api(api_key)
        try:
            req = urllib.request.Request(url)
            creds = base64.b64encode(f"{api_key}:".encode()).decode()
            req.add_header("Authorization", f"Basic {creds}")
            with urllib.request.urlopen(req, timeout=30) as r:
                consecutive_429 = 0
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                consecutive_429 += 1
                if consecutive_429 >= 3:
                    backoff = 900
                logger.warning("CH API 429 (attempt %d) — backing off %ds", attempt + 1, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 900)
            elif e.code == 404:
                return {}
            else:
                raise
    raise RuntimeError(f"CH API failed after {retries} retries: {path}")


def _get_api_key() -> str:
    key = os.getenv("COMPANIES_HOUSE_API_KEY", "")
    if not key or key == "REPLACE_ME":
        raise EnvironmentError(
            "COMPANIES_HOUSE_API_KEY not set in .env. "
            "Only needed for delta updates — bulk M1 snapshot does not require it."
        )
    return key


# ─── API delta-update functions (post-M1 only) ────────────────────────────────

def get_company_api(number: str) -> dict:
    """Fetch single company profile via API. For delta updates only."""
    return _api_get(f"/company/{number}", _get_api_key())


def get_officers_api(number: str) -> list[dict]:
    """Fetch officers for a company via API. For delta updates only."""
    data = _api_get(f"/company/{number}/officers?items_per_page=100", _get_api_key())
    return data.get("items", [])


def get_pscs_api(number: str) -> list[dict]:
    """Fetch PSCs for a company via API. For delta updates only."""
    data = _api_get(
        f"/company/{number}/persons-with-significant-control?items_per_page=100",
        _get_api_key(),
    )
    return data.get("items", [])


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print_bulk_manifest()
