"""OCOD — overseas corporate ownership. ~100k rows. Refresh: monthly."""
import zipfile
from pathlib import Path

import httpx

SOURCE_URL = "https://use-land-property-data.service.gov.uk/datasets/ocod/download"
RAW_DIR = Path("data/raw/ocod")


def download() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / "ocod_latest.zip"
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
    print(f"OCOD downloaded and extracted to {RAW_DIR}")


if __name__ == "__main__":
    main()
