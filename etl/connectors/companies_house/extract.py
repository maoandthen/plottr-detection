"""
Companies House ETL — Extract Layer
=====================================

Ingest strategy (IMPORTANT — read before modifying):
  - M1 bulk snapshot: download monthly flat files from CH bulk data S3 bucket.
    No API key required. No rate limiting. ~2-3GB compressed.
  - Delta updates (post-M1): use CH API with token-bucket rate limiting.
    Rate limit: 600 req / 5 min per key. A 429 response must trigger
    exponential backoff starting at 60s; three consecutive 429s = pause 15min.
    Never exceed the rate limit — CH will revoke the key.

Bulk snapshot files (updated monthly on the 1st):
  BASE = "https://download.companieshouse.data.s3-website-eu-west-1.amazonaws.com/"
  - BasicCompanyDataAsOneFile-{YYYY}-{MM}-01.zip         company profile snapshot
  - company-officers-{YYYY}-{MM}-01.zip                  officers (may be split parts)
  - persons-with-significant-control-snapshot-{YYYY}-{MM}-01.zip  PSC snapshot
"""

import os
import re
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

CH_BULK_BASE = "https://download.companieshouse.data.s3-website-eu-west-1.amazonaws.com/"
CH_API_BASE = "https://api.company-information.service.gov.uk"
RAW_DIR = Path(__file__).parents[4] / "data" / "raw" / "companies_house"

# Token bucket state (module-level, single-process)
_api_requests: list[float] = []
_API_WINDOW = 300  # 5 minutes in seconds
_API_LIMIT = 590   # stay safely below 600


def _get_api_key() -> str:
    key = os.getenv("COMPANIES_HOUSE_API_KEY", "")
    if not key or key == "REPLACE_ME":
        raise EnvironmentError(
            "COMPANIES_HOUSE_API_KEY not set in .env. "
            "Required for delta updates only — bulk snapshot does not need it."
        )
    return key


def _throttle_api():
    """Enforce 590 req / 5min token bucket. Block until a slot is available."""
    now = time.time()
    global _api_requests
    _api_requests = [t for t in _api_requests if now - t < _API_WINDOW]
    if len(_api_requests) >= _API_LIMIT:
        oldest = _api_requests[0]
        sleep_for = _API_WINDOW - (now - oldest) + 1
        logger.warning("CH API rate limit reached — sleeping %.1fs", sleep_for)
        time.sleep(sleep_for)
    _api_requests.append(time.time())


def _api_get(path: str, retries: int = 5) -> dict:
    """GET from CH API with token-bucket throttling and exponential backoff on 429."""
    import urllib.request as req
    import json
    key = _get_api_key()
    url = f"{CH_API_BASE}{path}"
    backoff = 60
    for attempt in range(retries):
        _throttle_api()
        try:
            request = req.Request(url)
            import base64
            creds = base64.b64encode(f"{key}:".encode()).decode()
            request.add_header("Authorization", f"Basic {creds}")
            with req.urlopen(request, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                consecutive = attempt + 1
                if consecutive >= 3:
                    backoff = 900  # 15 min pause after 3 consecutive 429s
                logger.warning("CH API 429 (attempt %d) — backing off %ds", attempt + 1, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 900)
            elif e.code == 404:
                return {}
            else:
                raise
    raise RuntimeError(f"CH API failed after {retries} retries: {path}")


# ─── BULK DOWNLOAD ────────────────────────────────────────────────────────────

def _current_bulk_month() -> tuple[str, str]:
    """Return (YYYY, MM) for the most recent bulk snapshot month."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y"), now.strftime("%m")


def _bulk_url(filename: str) -> str:
    return f"{CH_BULK_BASE}{filename}"


def download_company_snapshot(dest_dir: Path | None = None) -> Path:
    """
    Download the BasicCompanyDataAsOneFile bulk snapshot.
    Returns path to the downloaded .zip.
    Idempotent: skips download if file already exists.
    """
    dest_dir = dest_dir or (RAW_DIR / "snapshot")
    dest_dir.mkdir(parents=True, exist_ok=True)
    year, month = _current_bulk_month()
    filename = f"BasicCompanyDataAsOneFile-{year}-{month}-01.zip"
    dest = dest_dir / filename
    if dest.exists():
        logger.info("Company snapshot already downloaded: %s", dest)
        return dest
    url = _bulk_url(filename)
    logger.info("Downloading company snapshot from %s", url)
    urllib.request.urlretrieve(url, dest)
    logger.info("Saved to %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
    return dest


def download_officers_snapshot(dest_dir: Path | None = None) -> list[Path]:
    """
    Download all officer bulk snapshot parts.
    Returns list of downloaded .zip paths.
    Idempotent: skips files already present.
    """
    dest_dir = dest_dir or (RAW_DIR / "officers")
    dest_dir.mkdir(parents=True, exist_ok=True)
    year, month = _current_bulk_month()
    # Try parts 1-20; stop at first 404
    paths = []
    for part in range(1, 21):
        filename = f"company-officers-{year}-{month}-01-part{part}_{part}.zip"
        dest = dest_dir / filename
        if dest.exists():
            paths.append(dest)
            continue
        url = _bulk_url(filename)
        try:
            logger.info("Downloading officers part %d from %s", part, url)
            urllib.request.urlretrieve(url, dest)
            paths.append(dest)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.info("No more officer parts after part %d", part - 1)
                break
            raise
    if not paths:
        raise RuntimeError(
            f"No CH officer bulk files found for {year}-{month}. "
            "Check https://download.companieshouse.data.s3-website-eu-west-1.amazonaws.com/"
        )
    return paths


def download_psc_snapshot(dest_dir: Path | None = None) -> Path:
    """
    Download the PSC (persons with significant control) bulk snapshot.
    Returns path to downloaded .zip. Idempotent.
    """
    dest_dir = dest_dir or (RAW_DIR / "psc")
    dest_dir.mkdir(parents=True, exist_ok=True)
    year, month = _current_bulk_month()
    filename = f"persons-with-significant-control-snapshot-{year}-{month}-01.zip"
    dest = dest_dir / filename
    if dest.exists():
        logger.info("PSC snapshot already downloaded: %s", dest)
        return dest
    url = _bulk_url(filename)
    logger.info("Downloading PSC snapshot from %s", url)
    urllib.request.urlretrieve(url, dest)
    logger.info("Saved to %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
    return dest


def iter_company_csv(zip_path: Path) -> Iterator[dict]:
    """Stream rows from the company snapshot CSV inside the zip."""
    import zipfile
    import csv
    import io
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_names:
            raise ValueError(f"No CSV found in {zip_path}")
        with zf.open(csv_names[0]) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                yield row


def iter_officers_jsonl(zip_path: Path) -> Iterator[dict]:
    """Stream records from an officers bulk zip (JSONL format inside zip)."""
    import zipfile
    import json
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith(".json"):
                with zf.open(name) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            yield json.loads(line)


def iter_psc_jsonl(zip_path: Path) -> Iterator[dict]:
    """Stream records from the PSC bulk snapshot (JSONL format inside zip)."""
    import zipfile
    import json
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith(".json"):
                with zf.open(name) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            yield json.loads(line)


# ─── API DELTA UPDATES (post-M1 only) ─────────────────────────────────────────

def get_company_api(number: str) -> dict:
    """Fetch single company profile via API. Delta updates only."""
    return _api_get(f"/company/{number}")


def get_officers_api(number: str) -> list[dict]:
    """Fetch officers for a company via API. Delta updates only."""
    data = _api_get(f"/company/{number}/officers?items_per_page=100")
    return data.get("items", [])


def get_pscs_api(number: str) -> list[dict]:
    """Fetch PSCs for a company via API. Delta updates only."""
    data = _api_get(f"/company/{number}/persons-with-significant-control?items_per_page=100")
    return data.get("items", [])
