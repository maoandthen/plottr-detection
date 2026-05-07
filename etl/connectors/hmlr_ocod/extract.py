"""OCOD — overseas corporate ownership. ~100k rows. Refresh: monthly."""
import os
import zipfile
from pathlib import Path
import httpx

API_BASE = "https://use-land-property-data.service.gov.uk/api/v1/datasets"
DATASET_NAME = "ocod"
RAW_DIR = Path(os.getenv("DATA_DIR", "/Volumes/PlottrData")) / "raw" / "ocod"


def _auth_headers() -> dict:
    api_key = os.getenv("HMLR_API_KEY")
    if not api_key:
        raise RuntimeError("HMLR_API_KEY env var not set")
    return {
        "Authorization": api_key,
        "Accept": "application/json",
    }


def _resolve_full_file() -> tuple[str, str]:
    """Find the latest OCOD_FULL_*.zip resource and return (filename, download_url)."""
    headers = _auth_headers()
    # Step 1: list resources
    r = httpx.get(f"{API_BASE}/{DATASET_NAME}", headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    resources = data["result"]["resources"]
    # Pick the FULL file, not the COU (change-only) file
    full_files = [r for r in resources if r["file_name"].startswith("OCOD_FULL_")]
    if not full_files:
        raise RuntimeError(f"No OCOD_FULL_*.zip in resources: {resources}")
    filename = full_files[0]["file_name"]
    # Step 2: get pre-signed S3 URL
    r2 = httpx.get(
        f"{API_BASE}/{DATASET_NAME}/{filename}",
        headers=headers,
        timeout=30,
    )
    r2.raise_for_status()
    download_url = r2.json()["result"]["download_url"]
    return filename, download_url


def download() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    filename, download_url = _resolve_full_file()
    dest = RAW_DIR / filename
    # Resumability: skip if already exists
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  ✓ Skipping (already exists, {dest.stat().st_size / 1e6:.1f}MB): {dest}")
        return dest
    print(f"  Downloading {filename} from pre-signed URL...")
    with httpx.stream("GET", download_url, follow_redirects=True, timeout=300) as r:
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