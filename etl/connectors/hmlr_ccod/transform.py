"""Transform raw CCOD CSV into normalised Title records."""
from pathlib import Path

import pandas as pd

COLUMN_MAP = {
    "Title Number": "title_number",
    "Tenure": "tenure",
    "Proprietor Name (1)": "proprietor_name",
    "Company Registration No. (1)": "company_registration",
    "Proprietorship Category (1)": "proprietor_category",
    "Property Address": "address",
    "Postcode": "postcode",
    "Price Paid": "price_paid",
    "Date Proprietor Added": "date_registered",
}


def transform(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    df = df.rename(columns=COLUMN_MAP)
    keep = [c for c in COLUMN_MAP.values() if c in df.columns]
    df = df[keep].copy()
    df["price_paid"] = pd.to_numeric(df.get("price_paid"), errors="coerce")
    df["date_registered"] = pd.to_datetime(df.get("date_registered"), errors="coerce").dt.date
    df = df.dropna(subset=["title_number", "proprietor_name"])
    return df
