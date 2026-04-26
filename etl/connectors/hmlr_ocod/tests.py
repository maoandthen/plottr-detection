"""Unit tests for OCOD transform."""
import io

import pandas as pd
import pytest

from etl.connectors.hmlr_ocod.transform import transform


def _make_csv() -> io.StringIO:
    rows = [
        {
            "Title Number": "LN12345",
            "Tenure": "Leasehold",
            "Proprietor Name (1)": "OVERSEAS CORP SA",
            "Company Registration No. (1)": "",
            "Proprietorship Category (1)": "Overseas Company",
            "Property Address": "5 Park Lane, London",
            "Postcode": "W1K 1AA",
            "Price Paid": "2500000",
            "Date Proprietor Added": "2019-06-01",
            "Country Incorporated (1)": "British Virgin Islands",
        }
    ]
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return buf


def test_transform_columns():
    result = transform(_make_csv())
    assert "title_number" in result.columns
    assert "country_incorporated" in result.columns


def test_transform_price_paid_numeric():
    result = transform(_make_csv())
    assert result["price_paid"].iloc[0] == 2500000.0
