"""Unit tests for CCOD transform (no I/O required)."""
import io

import pandas as pd
import pytest

from etl.connectors.hmlr_ccod.transform import transform, COLUMN_MAP


def _make_csv() -> io.StringIO:
    rows = [
        {
            "Title Number": "AGL1234",
            "Tenure": "Freehold",
            "Proprietor Name (1)": "ACME LTD",
            "Company Registration No. (1)": "12345678",
            "Proprietorship Category (1)": "Limited Company or Public Limited Company",
            "Property Address": "1 High Street, London",
            "Postcode": "EC1A 1BB",
            "Price Paid": "500000",
            "Date Proprietor Added": "2020-01-15",
        }
    ]
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return buf


def test_transform_columns():
    buf = _make_csv()
    result = transform(buf)
    assert "title_number" in result.columns
    assert "proprietor_name" in result.columns


def test_transform_price_paid_numeric():
    buf = _make_csv()
    result = transform(buf)
    assert result["price_paid"].dtype == float or result["price_paid"].iloc[0] == 500000.0


def test_transform_drops_nulls():
    rows = [{"Title Number": None, "Proprietor Name (1)": None}]
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    result = transform(buf)
    assert len(result) == 0
