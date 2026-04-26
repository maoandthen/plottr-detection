"""Transform raw Companies House data into normalised Company/Officer/PSC records."""
from typing import Any


def transform_company(raw: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")


def transform_officers(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")


def transform_pscs(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")
