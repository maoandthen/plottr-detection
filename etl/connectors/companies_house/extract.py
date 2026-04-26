"""
Companies House connector.

Bulk snapshot URL:
  https://download.companieshouse.data.s3-website-eu-west-1.amazonaws.com/

Live API requires COMPANIES_HOUSE_API_KEY in .env.
"""
import os

CH_BASE = "https://api.company-information.service.gov.uk"


def _get_api_key() -> str:
    key = os.getenv("COMPANIES_HOUSE_API_KEY", "")
    if not key or key == "REPLACE_ME":
        raise EnvironmentError("Requires COMPANIES_HOUSE_API_KEY in .env")
    return key


def get_company(number: str) -> dict:
    """Fetch company profile from CH API."""
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")


def get_officers(number: str) -> list[dict]:
    """Fetch officer list for a company from CH API."""
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")


def get_pscs(number: str) -> list[dict]:
    """Fetch persons with significant control for a company from CH API."""
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")
