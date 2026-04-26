"""CCOD refresh cadence: monthly. ~5M rows. Corporate freehold/leasehold titles."""
import os
import zipfile
from pathlib import Path

import httpx

SOURCE_URL = "https://use-land-property-data.service.gov.uk/datasets/ccod/download"
RAW_DIR = Path("data/raw/ccod")


def download() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / "ccod_latest.zip"
    with httpx.stream("GET", SOURCE_URL, follow_redirects=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=1024 * 64):
                f.write(chunk)
    return dest


def extract_zip(zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(RAW_DIR)
    return RAW_DIR


def main():
    zip_path = download()
    extract_zip(zip_path)
    print(f"CCOD downloaded and extracted to {RAW_DIR}")


if __name__ == "__main__":
    main()
