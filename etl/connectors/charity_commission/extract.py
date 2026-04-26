"""Charity Commission public register. Refresh: weekly."""
import zipfile
from pathlib import Path

import httpx

SOURCE_URL = "https://ccewuksprdoneregsadata1.blob.core.windows.net/data/json/publicextract.charity.zip"
RAW_DIR = Path("data/raw/charity_commission")


def download() -> Path:
    raise NotImplementedError("Charity Commission download not yet implemented (M2+)")


def extract_zip(zip_path: Path) -> Path:
    raise NotImplementedError("Charity Commission extract not yet implemented (M2+)")


def main():
    zip_path = download()
    extract_zip(zip_path)
    print(f"Charity Commission data downloaded to {RAW_DIR}")


if __name__ == "__main__":
    main()
