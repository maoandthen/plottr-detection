#!/usr/bin/env python3
"""
M1 Phase 2 staging loader.
Loads raw bulk files into Postgres staging tables using COPY for speed.

Reads DATABASE_URL from .env. Connects via localhost (script runs outside Docker).
Idempotent: TRUNCATE + COPY each table.
"""

import csv
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import psycopg


def get_database_url() -> str:
    """Read DATABASE_URL from .env, swap 'postgres' host for 'localhost' since we run outside Docker."""
    url = os.getenv("DATABASE_URL")
    if not url:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    if not url:
        raise RuntimeError("DATABASE_URL not set in env or .env")
    # Translate Docker-internal hostname to host-side localhost
    url = url.replace("@postgres:", "@localhost:")
    return url


def get_data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "/Volumes/PlottrData"))


def init_schema(conn):
    """Run staging_schema.sql to create tables."""
    schema_path = Path(__file__).parent / "sql" / "staging_schema.sql"
    print(f"Running schema: {schema_path}")
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text())
    conn.commit()
    print("Schema initialised.")


def load_companies_house_snapshot(conn):
    """Stream CH company snapshot CSV directly into stg_companies via COPY."""
    snapshot_dir = get_data_dir() / "raw" / "companies_house" / "snapshot"
    zip_files = list(snapshot_dir.glob("BasicCompanyDataAsOneFile-*.zip"))
    if not zip_files:
        print(f"No CH snapshot ZIP in {snapshot_dir}, skipping")
        return
    zip_path = zip_files[0]
    print(f"Loading CH snapshot from {zip_path.name}...")
    start = time.time()

    with conn.cursor() as cur:
        cur.execute("TRUNCATE stg_companies")
        with zipfile.ZipFile(zip_path) as zf:
            csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
            with zf.open(csv_name) as csv_stream:
                # Stream CSV directly into COPY
                reader = io.TextIOWrapper(csv_stream, encoding="utf-8")
                header = reader.readline()  # skip header
                with cur.copy("COPY stg_companies FROM STDIN WITH (FORMAT csv, HEADER false, QUOTE '\"', ESCAPE '\"')") as copy:
                    for line in reader:
                        if line.strip():
                            copy.write(line.encode("utf-8") if isinstance(line, str) else line)
        conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM stg_companies")
        rows = cur.fetchone()[0]
        elapsed = time.time() - start
        print(f"  stg_companies: {rows:,} rows loaded in {elapsed:.1f}s")


def load_psc(conn):
    """Stream all PSC NDJSON parts into stg_psc via COPY."""
    psc_dir = get_data_dir() / "raw" / "companies_house" / "psc"
    zip_files = sorted(psc_dir.glob("persons-with-significant-control-snapshot-*.zip"))
    if not zip_files:
        # Try ungzipped or pre-extracted
        zip_files = sorted(psc_dir.glob("*.zip"))
    if not zip_files:
        print(f"No PSC files in {psc_dir}, skipping")
        return

    print(f"Loading {len(zip_files)} PSC parts...")
    start = time.time()
    total_rows = 0

    with conn.cursor() as cur:
        cur.execute("TRUNCATE stg_psc RESTART IDENTITY")
        with cur.copy("COPY stg_psc (company_number, raw_json) FROM STDIN") as copy:
            for zip_path in zip_files:
                with zipfile.ZipFile(zip_path) as zf:
                    for name in zf.namelist():
                        if not (name.endswith(".txt") or name.endswith(".json")):
                            continue
                        with zf.open(name) as fh:
                            for raw_line in io.TextIOWrapper(fh, encoding="utf-8"):
                                line = raw_line.strip()
                                if not line:
                                    continue
                                try:
                                    rec = json.loads(line)
                                except json.JSONDecodeError:
                                    continue
                                company_number = rec.get("company_number") or ""
                                # Tab-separated row for default COPY format. Escape special chars.
                                json_str = json.dumps(rec).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
                                row = f"{company_number}\t{json_str}\n"
                                copy.write(row.encode("utf-8"))
                                total_rows += 1
        conn.commit()
    elapsed = time.time() - start
    print(f"  stg_psc: {total_rows:,} rows loaded in {elapsed:.1f}s")


CCOD_COLUMNS = [
    "title_number", "tenure", "property_address", "district", "county",
    "region", "postcode", "multiple_address_indicator", "price_paid",
    "proprietor_name_1", "company_registration_no_1", "proprietorship_category_1",
    "proprietor_1_address_1", "proprietor_1_address_2", "proprietor_1_address_3",
    "proprietor_name_2", "company_registration_no_2", "proprietorship_category_2",
    "proprietor_2_address_1", "proprietor_2_address_2", "proprietor_2_address_3",
    "proprietor_name_3", "company_registration_no_3", "proprietorship_category_3",
    "proprietor_3_address_1", "proprietor_3_address_2", "proprietor_3_address_3",
    "proprietor_name_4", "company_registration_no_4", "proprietorship_category_4",
    "proprietor_4_address_1", "proprietor_4_address_2", "proprietor_4_address_3",
    "date_proprietor_added", "additional_proprietor_indicator",
]

OCOD_COLUMNS = [
    "title_number", "tenure", "property_address", "district", "county",
    "region", "postcode", "multiple_address_indicator", "price_paid",
    "proprietor_name_1", "company_registration_no_1", "proprietorship_category_1",
    "country_incorporated_1",
    "proprietor_1_address_1", "proprietor_1_address_2", "proprietor_1_address_3",
    "proprietor_name_2", "company_registration_no_2", "proprietorship_category_2",
    "country_incorporated_2",
    "proprietor_2_address_1", "proprietor_2_address_2", "proprietor_2_address_3",
    "proprietor_name_3", "company_registration_no_3", "proprietorship_category_3",
    "country_incorporated_3",
    "proprietor_3_address_1", "proprietor_3_address_2", "proprietor_3_address_3",
    "proprietor_name_4", "company_registration_no_4", "proprietorship_category_4",
    "country_incorporated_4",
    "proprietor_4_address_1", "proprietor_4_address_2", "proprietor_4_address_3",
    "date_proprietor_added", "additional_proprietor_indicator",
]


def load_hmlr_csv(conn, dataset: str, table: str):
    """Generic HMLR CSV loader for CCOD/OCOD with hardcoded column list."""
    raw_dir = get_data_dir() / "raw" / dataset
    zip_files = list(raw_dir.glob(f"{dataset.upper()}_FULL_*.zip"))
    if not zip_files:
        print(f"No {dataset.upper()}_FULL_*.zip in {raw_dir}, skipping")
        return
    zip_path = zip_files[0]
    print(f"Loading {dataset.upper()} from {zip_path.name}...")
    start = time.time()

    columns = CCOD_COLUMNS if dataset == "ccod" else OCOD_COLUMNS
    column_list = ",".join(columns)

    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {table} RESTART IDENTITY")
        with zipfile.ZipFile(zip_path) as zf:
            csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
            with zf.open(csv_name) as csv_stream:
                reader = io.TextIOWrapper(csv_stream, encoding="utf-8")
                header_line = reader.readline()
                # Header consumed; skip it
                with cur.copy(
                    f"COPY {table} ({column_list}) "
                    f"FROM STDIN WITH (FORMAT csv, HEADER false, QUOTE '\"', ESCAPE '\"')"
                ) as copy:
                    for line in reader:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        # Skip HMLR footer row: "Row Count:","NNNN" — only 2 columns
                        if stripped.startswith('"Row Count:"') or stripped.startswith("Row Count:"):
                            continue
                        copy.write(line.encode("utf-8") if isinstance(line, str) else line)
        conn.commit()

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        rows = cur.fetchone()[0]
        elapsed = time.time() - start
        print(f"  {table}: {rows:,} rows loaded in {elapsed:.1f}s")


def main():
    print("=== M1 PHASE 2 — STAGING LOAD ===")
    db_url = get_database_url()
    print(f"Connecting to {db_url.split('@')[1]}...")

    with psycopg.connect(db_url) as conn:
        init_schema(conn)
        load_companies_house_snapshot(conn)
        load_psc(conn)
        load_hmlr_csv(conn, "ccod", "stg_ccod_titles")
        load_hmlr_csv(conn, "ocod", "stg_ocod_titles")

        # Final summary
        with conn.cursor() as cur:
            for t in ["stg_companies", "stg_psc", "stg_ccod_titles", "stg_ocod_titles"]:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                count = cur.fetchone()[0]
                print(f"  {t}: {count:,}")

    print("=== STAGING LOAD COMPLETE ===")


if __name__ == "__main__":
    main()