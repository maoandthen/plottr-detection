"""Load Companies House records into Postgres."""
from typing import Any


def load_company(record: dict[str, Any]) -> None:
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")


def load_officers(records: list[dict[str, Any]]) -> None:
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")


def load_pscs(records: list[dict[str, Any]]) -> None:
    raise NotImplementedError("Requires COMPANIES_HOUSE_API_KEY in .env")
