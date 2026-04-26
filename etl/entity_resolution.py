"""
Entity Resolution — Deterministic Rules
========================================
Two Person records refer to the same person if and only if ALL of:
  1. Normalised full name matches exactly (after strip, lower, collapse whitespace,
     remove punctuation except hyphens in surnames)
  2. Date of birth matches at month precision (YYYY-MM) — day may be absent
  3. Correspondence address postcode matches (after normalising to uppercase, no space)
     OR Companies House person_number matches (where both records have one)

Two Company records refer to the same company if and only if:
  company_number matches exactly (Companies House registration number is the canonical key)

Two Address records refer to the same address if and only if:
  uprn matches (where present), otherwise normalised address_string + postcode matches.

Merge policy:
  - The record with the most complete data wins field-by-field.
  - If a merge would create a cycle in the graph, reject and log — do not merge.
  - All merges are logged to entity_resolution_log table with: record_a_id, record_b_id,
    rule_applied, merged_at, merged_by (etl job name).

If any rule is ambiguous (e.g. same name + DOB but different postcodes and no person_number),
do NOT merge — create separate records and log to entity_resolution_conflicts table for
human review.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


def normalise_name(name: str) -> str:
    """Lowercase, strip, collapse whitespace, remove punctuation except hyphens."""
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", name)
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s\-]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def normalise_postcode(postcode: str) -> str:
    """Uppercase, remove spaces."""
    if not postcode:
        return ""
    return postcode.upper().replace(" ", "")


def normalise_dob(dob: str) -> str:
    """Return YYYY-MM from any YYYY-MM-DD or YYYY-MM input. Returns '' if unparseable."""
    if not dob:
        return ""
    parts = dob.strip().split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return ""


def deterministic_person_id(
    full_name: str,
    date_of_birth: str,
    postcode: Optional[str],
    ch_person_number: Optional[str],
) -> str:
    """
    Generate a stable UUID-like hex ID for a person.
    Uses SHA-256 of (normalised_name + dob_month + normalised_postcode).
    If ch_person_number is present, it is the canonical key (prefix with ch:).
    """
    if ch_person_number:
        canonical = f"ch:{ch_person_number.strip()}"
    else:
        name = normalise_name(full_name)
        dob = normalise_dob(date_of_birth)
        pc = normalise_postcode(postcode or "")
        canonical = f"{name}|{dob}|{pc}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def should_merge_persons(a: dict, b: dict) -> tuple[bool, str]:
    """
    Returns (True, rule_name) if records should merge, (False, reason) otherwise.

    Rule 1: same ch_person_number → always merge
    Rule 2: same normalised name + same YYYY-MM DOB + same normalised postcode → merge
    Anything else → do NOT merge
    """
    # Rule 1: CH person number match
    a_num = (a.get("ch_person_number") or "").strip()
    b_num = (b.get("ch_person_number") or "").strip()
    if a_num and b_num and a_num == b_num:
        return True, "ch_person_number_match"

    # Rule 2: name + DOB(month) + postcode
    a_name = normalise_name(a.get("full_name", ""))
    b_name = normalise_name(b.get("full_name", ""))
    a_dob = normalise_dob(a.get("date_of_birth", ""))
    b_dob = normalise_dob(b.get("date_of_birth", ""))
    a_pc = normalise_postcode(a.get("postcode", ""))
    b_pc = normalise_postcode(b.get("postcode", ""))

    if not a_name or not b_name:
        return False, "missing_name"
    if a_name != b_name:
        return False, "name_mismatch"
    if not a_dob or not b_dob or a_dob != b_dob:
        return False, "dob_mismatch_or_missing"
    if not a_pc or not b_pc:
        return False, "missing_postcode_no_ch_number"
    if a_pc != b_pc:
        return False, "postcode_mismatch_no_ch_number"

    return True, "name_dob_postcode_match"


def should_merge_addresses(a: dict, b: dict) -> tuple[bool, str]:
    """UPRN match → merge. Else normalised string + postcode match → merge."""
    a_uprn = (a.get("uprn") or "").strip()
    b_uprn = (b.get("uprn") or "").strip()
    if a_uprn and b_uprn and a_uprn == b_uprn:
        return True, "uprn_match"

    a_str = (a.get("address_string") or "").lower().strip()
    b_str = (b.get("address_string") or "").lower().strip()
    a_pc = normalise_postcode(a.get("postcode", ""))
    b_pc = normalise_postcode(b.get("postcode", ""))

    if a_str and b_str and a_str == b_str and a_pc and b_pc and a_pc == b_pc:
        return True, "address_string_postcode_match"

    return False, "no_match"
