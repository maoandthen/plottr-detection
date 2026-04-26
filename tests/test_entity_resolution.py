"""Tests for deterministic entity resolution rules."""
import pytest

from etl.entity_resolution import (
    deterministic_person_id,
    normalise_name,
    normalise_postcode,
    should_merge_addresses,
    should_merge_persons,
)


def test_same_ch_person_number_merges():
    a = {"ch_person_number": "12345678", "full_name": "Alice Smith", "date_of_birth": "1980-01", "postcode": "SW1A 1AA"}
    b = {"ch_person_number": "12345678", "full_name": "Alicia Smith", "date_of_birth": "1980-01", "postcode": "EC1A 1BB"}
    merged, rule = should_merge_persons(a, b)
    assert merged is True
    assert rule == "ch_person_number_match"


def test_same_name_dob_postcode_merges():
    a = {"full_name": "John O'Brien", "date_of_birth": "1975-06-15", "postcode": "SW7 1HY"}
    b = {"full_name": "John O'Brien", "date_of_birth": "1975-06", "postcode": "sw7 1hy"}
    merged, rule = should_merge_persons(a, b)
    assert merged is True
    assert rule == "name_dob_postcode_match"


def test_different_postcode_no_merge():
    a = {"full_name": "Jane Doe", "date_of_birth": "1990-03", "postcode": "SW1A 1AA"}
    b = {"full_name": "Jane Doe", "date_of_birth": "1990-03", "postcode": "EC2A 1BB"}
    merged, reason = should_merge_persons(a, b)
    assert merged is False
    assert reason == "postcode_mismatch_no_ch_number"


def test_name_mismatch_no_merge():
    a = {"full_name": "John Smith", "date_of_birth": "1985-01", "postcode": "SW1A 1AA"}
    b = {"full_name": "James Smith", "date_of_birth": "1985-01", "postcode": "SW1A 1AA"}
    merged, reason = should_merge_persons(a, b)
    assert merged is False
    assert reason == "name_mismatch"


def test_missing_dob_no_merge():
    a = {"full_name": "Jane Doe", "date_of_birth": "", "postcode": "SW1A 1AA"}
    b = {"full_name": "Jane Doe", "date_of_birth": "1990-03", "postcode": "SW1A 1AA"}
    merged, reason = should_merge_persons(a, b)
    assert merged is False
    assert reason == "dob_mismatch_or_missing"


def test_normalise_name_handles_unicode():
    assert normalise_name("Müller") == "muller"
    assert normalise_name("  O'BRIEN  ") == "obrien"
    assert normalise_name("Smith-Jones") == "smith-jones"
    assert normalise_name("JEAN\u2010PAUL") == "jean-paul"  # non-breaking hyphen normalised


def test_normalise_postcode():
    assert normalise_postcode("sw1a 1aa") == "SW1A1AA"
    assert normalise_postcode("SW7 1HY") == "SW71HY"
    assert normalise_postcode("  EC1A 1BB  ") == "EC1A1BB"
    assert normalise_postcode("") == ""


def test_deterministic_person_id_stable():
    id1 = deterministic_person_id("John Smith", "1980-01-15", "SW1A 1AA", None)
    id2 = deterministic_person_id("John Smith", "1980-01-15", "SW1A 1AA", None)
    assert id1 == id2
    assert len(id1) == 32

    # Different DOB month → different ID
    id3 = deterministic_person_id("John Smith", "1980-02-15", "SW1A 1AA", None)
    assert id1 != id3

    # CH person number takes precedence
    id4 = deterministic_person_id("John Smith", "1980-01-15", "SW1A 1AA", "ABC123")
    id5 = deterministic_person_id("Different Name", "2000-01", "EC1A 1BB", "ABC123")
    assert id4 == id5


def test_address_uprn_merge():
    a = {"uprn": "100021343562", "address_string": "1 High Street", "postcode": "SW1A 1AA"}
    b = {"uprn": "100021343562", "address_string": "1 High St", "postcode": "SW1A 1AA"}
    merged, rule = should_merge_addresses(a, b)
    assert merged is True
    assert rule == "uprn_match"


def test_address_string_match():
    a = {"uprn": "", "address_string": "Flat 2, 10 Baker Street", "postcode": "NW1 6XE"}
    b = {"uprn": None, "address_string": "flat 2, 10 baker street", "postcode": "nw1 6xe"}
    merged, rule = should_merge_addresses(a, b)
    assert merged is True
    assert rule == "address_string_postcode_match"

    # Different postcode → no merge
    c = {"uprn": None, "address_string": "flat 2, 10 baker street", "postcode": "NW1 6XF"}
    merged2, reason2 = should_merge_addresses(a, c)
    assert merged2 is False
