"""Tests for CH connector — skipped until API key is configured."""
import pytest


@pytest.mark.skip(reason="Requires COMPANIES_HOUSE_API_KEY in .env")
def test_get_company_stub():
    from etl.connectors.companies_house.extract import get_company
    get_company("00000006")


@pytest.mark.skip(reason="Requires COMPANIES_HOUSE_API_KEY in .env")
def test_get_officers_stub():
    from etl.connectors.companies_house.extract import get_officers
    get_officers("00000006")
