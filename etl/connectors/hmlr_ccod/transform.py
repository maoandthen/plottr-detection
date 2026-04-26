"""Transform raw CCOD CSV rows into (title_dict, [company_dict], [owned_by_dict]) tuples."""
from pathlib import Path
from typing import Generator

import csv
import re

PROPRIETORSHIP_CATEGORY_MAP = {
    "UK Company": "UK Company",
    "Overseas Company": "Overseas Company",
    "Corporate Body": "Corporate Body",
    "Limited Liability Partnership": "Limited Liability Partnership",
    "Registered Society": "Registered Society",
    "Government": "Government",
}

_PROPRIETOR_COLUMNS = [
    (
        "Proprietor Name ({n})",
        "Company Registration No. ({n})",
        "Proprietorship Category ({n})",
        "Proprietor ({n}) Address (1)",
        "Proprietor ({n}) Address (2)",
        "Proprietor ({n}) Address (3)",
    )
    for n in range(1, 5)
]


def _normalise_postcode(postcode: str) -> str:
    """Normalise to uppercase spaced format e.g. SW7 1HY."""
    if not postcode:
        return ""
    pc = postcode.upper().replace(" ", "")
    if len(pc) >= 3:
        return f"{pc[:-3]} {pc[-3:]}".strip()
    return pc


def _map_category(raw: str) -> str:
    return PROPRIETORSHIP_CATEGORY_MAP.get((raw or "").strip(), "Unknown")


def _address_string(a1: str, a2: str, a3: str) -> str:
    parts = [p.strip() for p in (a1, a2, a3) if p and p.strip()]
    return ", ".join(parts)


def transform(csv_path: Path) -> Generator[tuple[dict, list[dict], list[dict]], None, None]:
    """
    Yields (title_dict, company_dicts, owned_by_dicts) for each valid CCOD row.
    Skips rows where title_number is blank.
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            title_number = (row.get("Title Number") or "").strip()
            if not title_number:
                continue

            postcode = _normalise_postcode(row.get("Postcode") or "")

            title_dict = {
                "title_number": title_number,
                "tenure": (row.get("Tenure") or "").strip(),
                "address": (row.get("Property Address") or "").strip(),
                "postcode": postcode,
                "price_paid": _parse_price(row.get("Price Paid")),
                "date_registered": (row.get("Date Proprietor Added") or "").strip() or None,
                "source": "ccod",
            }

            company_dicts: list[dict] = []
            owned_by_dicts: list[dict] = []

            for n in range(1, 5):
                name_col = f"Proprietor Name ({n})"
                reg_col = f"Company Registration No. ({n})"
                cat_col = f"Proprietorship Category ({n})"
                addr1_col = f"Proprietor ({n}) Address (1)"
                addr2_col = f"Proprietor ({n}) Address (2)"
                addr3_col = f"Proprietor ({n}) Address (3)"

                prop_name = (row.get(name_col) or "").strip()
                if not prop_name:
                    continue

                company_reg = (row.get(reg_col) or "").strip()
                category = _map_category(row.get(cat_col) or "")
                prop_addr = _address_string(
                    row.get(addr1_col) or "",
                    row.get(addr2_col) or "",
                    row.get(addr3_col) or "",
                )

                if company_reg:
                    company_dicts.append({
                        "company_number": company_reg,
                        "company_name": prop_name,
                        "company_status": "",
                        "company_type": category,
                        "incorporated_on": None,
                        "sic_codes": [],
                        "registered_address": prop_addr,
                    })
                    owned_by_dicts.append({
                        "title_number": title_number,
                        "owner_id": company_reg,
                        "proprietor_category": category,
                        "date_from": title_dict["date_registered"],
                    })

            yield title_dict, company_dicts, owned_by_dicts


def _parse_price(value) -> float | None:
    if not value:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
