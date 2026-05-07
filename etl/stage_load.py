#!/usr/bin/env python3
"""
M1 Phase 2: Staging Load Orchestration
Loads raw data files into Postgres staging tables for transformation.
"""

import json
import os
import csv
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterator, TextIO
import psycopg


def get_db_connection():
    """Get database connection from DATABASE_URL env var."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL env var not set")
    return psycopg.connect(db_url)


def get_data_dir() -> Path:
    """Get DATA_DIR from environment."""
    data_dir = os.getenv("DATA_DIR", "/Volumes/PlottrData")
    return Path(data_dir)


def log_timing(table_name: str, start_time: datetime, row_count: int):
    """Log load timing and row count."""
    duration = datetime.now() - start_time
    print(f"  ✓ {table_name}: {row_count:,} rows loaded in {duration.total_seconds():.1f}s")


def stream_companies_csv() -> Iterator[str]:
    """Stream Companies House snapshot CSV from ZIP file."""
    data_dir = get_data_dir()
    snapshot_files = list((data_dir / "raw" / "companies_house" / "snapshot").glob("BasicCompanyDataAsOneFile-*.zip"))
    
    if not snapshot_files:
        raise FileNotFoundError("No Companies House snapshot ZIP found")
    
    zip_path = snapshot_files[0]
    print(f"  Reading: {zip_path}")
    
    with zipfile.ZipFile(zip_path) as zf:
        csv_files = [name for name in zf.namelist() if name.endswith('.csv')]
        if not csv_files:
            raise FileNotFoundError("No CSV file found in Companies House ZIP")
        
        with zf.open(csv_files[0], 'r') as f:
            text_stream = TextIO(f, encoding='utf-8')
            # Skip header row
            next(text_stream)
            for line in text_stream:
                yield line.rstrip('\n\r')


def stream_psc_json() -> Iterator[dict]:
    """Stream PSC JSON records from all ZIP files."""
    data_dir = get_data_dir()
    psc_dir = data_dir / "raw" / "companies_house" / "psc"
    
    if not psc_dir.exists():
        raise FileNotFoundError("PSC directory not found")
    
    zip_files = list(psc_dir.glob("*.zip"))
    if not zip_files:
        raise FileNotFoundError("No PSC ZIP files found")
    
    print(f"  Reading: {len(zip_files)} PSC ZIP files")
    
    for zip_path in sorted(zip_files):
        with zipfile.ZipFile(zip_path) as zf:
            json_files = [name for name in zf.namelist() if name.endswith(('.jsonl', '.json', '.txt'))]
            
            for json_file in json_files:
                with zf.open(json_file, 'r') as f:
                    for line_bytes in f:
                        line = line_bytes.decode('utf-8').strip()
                        if line:
                            try:
                                record = json.loads(line)
                                yield record
                            except json.JSONDecodeError as e:
                                print(f"  Warning: Skipping invalid JSON line: {e}")
                                continue


def stream_ccod_csv() -> Iterator[str]:
    """Stream CCOD CSV from ZIP file.""" 
    # Use CCOD connector's RAW_DIR path
    ccod_dir = Path("data/raw/ccod")
    ccod_files = list(ccod_dir.glob("CCOD_FULL_*.zip"))
    
    if not ccod_files:
        raise FileNotFoundError(f"No CCOD ZIP found in {ccod_dir}")
    
    ccod_zip = ccod_files[0]
    print(f"  Reading: {ccod_zip}")
    
    with zipfile.ZipFile(ccod_zip) as zf:
        csv_files = [name for name in zf.namelist() if name.endswith('.csv')]
        if not csv_files:
            raise FileNotFoundError("No CSV file found in CCOD ZIP")
        
        with zf.open(csv_files[0], 'r') as f:
            text_stream = TextIO(f, encoding='utf-8')
            # Skip header row
            next(text_stream)
            for line in text_stream:
                yield line.rstrip('\n\r')


def stream_ocod_csv() -> Iterator[str]:
    """Stream OCOD CSV from ZIP file."""
    # Use OCOD connector's RAW_DIR path
    ocod_dir = Path("data/raw/ocod")
    ocod_files = list(ocod_dir.glob("OCOD_FULL_*.zip"))
    
    if not ocod_files:
        raise FileNotFoundError(f"No OCOD ZIP found in {ocod_dir}")
    
    ocod_zip = ocod_files[0]
    print(f"  Reading: {ocod_zip}")
    
    with zipfile.ZipFile(ocod_zip) as zf:
        csv_files = [name for name in zf.namelist() if name.endswith('.csv')]
        if not csv_files:
            raise FileNotFoundError("No CSV file found in OCOD ZIP")
        
        with zf.open(csv_files[0], 'r') as f:
            text_stream = TextIO(f, encoding='utf-8')
            # Skip header row
            next(text_stream)
            for line in text_stream:
                yield line.rstrip('\n\r')


def load_companies(conn):
    """Load Companies House snapshot into stg_companies."""
    print("Loading Companies House snapshot...")
    start_time = datetime.now()
    
    with conn.cursor() as cur:
        # Truncate existing data
        cur.execute("TRUNCATE stg_companies")
        
        # Stream COPY from CSV
        with cur.copy("COPY stg_companies FROM STDIN WITH CSV") as copy:
            row_count = 0
            for line in stream_companies_csv():
                copy.write_row(line.split(',', 53))  # 54 columns expected
                row_count += 1
                
                if row_count % 100000 == 0:
                    print(f"    {row_count:,} rows...")
        
        conn.commit()
    
    log_timing("stg_companies", start_time, row_count)
    
    # Sanity check
    if row_count < 4000000:
        print(f"  ⚠ Warning: Only {row_count:,} companies loaded - expected ~5.2M")
    
    return row_count


def load_psc(conn):
    """Load PSC data into stg_psc."""
    print("Loading PSC data...")
    start_time = datetime.now()
    
    with conn.cursor() as cur:
        # Truncate existing data
        cur.execute("TRUNCATE stg_psc")
        
        # Batch insert PSC records
        batch = []
        row_count = 0
        batch_size = 5000
        
        for record in stream_psc_json():
            company_number = record.get('company_number', '')
            batch.append((company_number, json.dumps(record)))
            row_count += 1
            
            if len(batch) >= batch_size:
                cur.executemany(
                    "INSERT INTO stg_psc (company_number, raw_json) VALUES (%s, %s)",
                    batch
                )
                batch = []
                
                if row_count % 100000 == 0:
                    print(f"    {row_count:,} rows...")
        
        # Insert final batch
        if batch:
            cur.executemany(
                "INSERT INTO stg_psc (company_number, raw_json) VALUES (%s, %s)",
                batch
            )
        
        conn.commit()
    
    log_timing("stg_psc", start_time, row_count)
    
    # Sanity check
    if row_count < 5000000:
        print(f"  ⚠ Warning: Only {row_count:,} PSC records loaded - expected ~7M+")
    
    return row_count


def load_ccod(conn):
    """Load CCOD data into stg_ccod_titles."""
    print("Loading CCOD titles...")
    start_time = datetime.now()
    
    with conn.cursor() as cur:
        # Truncate existing data
        cur.execute("TRUNCATE stg_ccod_titles")
        
        # Stream COPY from CSV
        with cur.copy("COPY stg_ccod_titles (title_number, tenure, property_address, district, county, region, postcode, multiple_address_indicator, price_paid, proprietor_name_1, company_registration_no_1, proprietorship_category_1, proprietor_1_address_1, proprietor_1_address_2, proprietor_1_address_3, proprietor_name_2, company_registration_no_2, proprietorship_category_2, proprietor_2_address_1, proprietor_2_address_2, proprietor_2_address_3, proprietor_name_3, company_registration_no_3, proprietorship_category_3, proprietor_3_address_1, proprietor_3_address_2, proprietor_3_address_3, proprietor_name_4, company_registration_no_4, proprietorship_category_4, proprietor_4_address_1, proprietor_4_address_2, proprietor_4_address_3, date_proprietor_added, additional_proprietor_indicator) FROM STDIN WITH CSV") as copy:
            row_count = 0
            for line in stream_ccod_csv():
                copy.write_row(line.split(',', 35))  # 36 columns expected
                row_count += 1
                
                if row_count % 100000 == 0:
                    print(f"    {row_count:,} rows...")
        
        conn.commit()
    
    log_timing("stg_ccod_titles", start_time, row_count)
    
    # Sanity check - flag if we got change-only file by mistake
    if row_count < 2000000:
        print(f"  ⚠ WARNING: Only {row_count:,} CCOD titles loaded - expected ~5M")
        print(f"    This suggests we downloaded the COU (change-only) file instead of FULL file!")
    
    return row_count


def load_ocod(conn):
    """Load OCOD data into stg_ocod_titles."""
    print("Loading OCOD titles...")
    start_time = datetime.now()
    
    with conn.cursor() as cur:
        # Truncate existing data  
        cur.execute("TRUNCATE stg_ocod_titles")
        
        # Stream COPY from CSV
        with cur.copy("COPY stg_ocod_titles (title_number, tenure, property_address, district, county, region, postcode, multiple_address_indicator, price_paid, proprietor_name_1, company_registration_no_1, proprietorship_category_1, country_incorporated_1, proprietor_1_address_1, proprietor_1_address_2, proprietor_1_address_3, proprietor_name_2, company_registration_no_2, proprietorship_category_2, country_incorporated_2, proprietor_2_address_1, proprietor_2_address_2, proprietor_2_address_3, proprietor_name_3, company_registration_no_3, proprietorship_category_3, country_incorporated_3, proprietor_3_address_1, proprietor_3_address_2, proprietor_3_address_3, proprietor_name_4, company_registration_no_4, proprietorship_category_4, country_incorporated_4, proprietor_4_address_1, proprietor_4_address_2, proprietor_4_address_3, date_proprietor_added, additional_proprietor_indicator) FROM STDIN WITH CSV") as copy:
            row_count = 0
            for line in stream_ocod_csv():
                copy.write_row(line.split(',', 39))  # 40 columns expected 
                row_count += 1
                
                if row_count % 10000 == 0:
                    print(f"    {row_count:,} rows...")
        
        conn.commit()
    
    log_timing("stg_ocod_titles", start_time, row_count)
    
    # Sanity check
    if row_count < 50000 or row_count > 200000:
        print(f"  ⚠ Warning: {row_count:,} OCOD titles loaded - expected ~120K")
    
    return row_count


def add_indexes(conn):
    """Add indexes after all loads complete."""
    print("Adding indexes...")
    start_time = datetime.now()
    
    with conn.cursor() as cur:
        indexes = [
            "CREATE INDEX idx_stg_psc_company_number ON stg_psc (company_number)",
            "CREATE INDEX idx_stg_ccod_title_number ON stg_ccod_titles (title_number)",
            "CREATE INDEX idx_stg_ccod_company_reg_1 ON stg_ccod_titles (company_registration_no_1) WHERE company_registration_no_1 IS NOT NULL",
            "CREATE INDEX idx_stg_ccod_company_reg_2 ON stg_ccod_titles (company_registration_no_2) WHERE company_registration_no_2 IS NOT NULL",
            "CREATE INDEX idx_stg_ocod_title_number ON stg_ocod_titles (title_number)",
            "CREATE INDEX idx_stg_ocod_company_reg_1 ON stg_ocod_titles (company_registration_no_1) WHERE company_registration_no_1 IS NOT NULL",
            "CREATE INDEX idx_stg_ocod_company_reg_2 ON stg_ocod_titles (company_registration_no_2) WHERE company_registration_no_2 IS NOT NULL"
        ]
        
        for idx_sql in indexes:
            cur.execute(idx_sql)
    
    conn.commit()
    
    duration = datetime.now() - start_time
    print(f"  ✓ {len(indexes)} indexes created in {duration.total_seconds():.1f}s")


def main():
    """Main staging load orchestration."""
    print("=== M1 PHASE 2: STAGING LOAD ORCHESTRATION ===")
    
    total_start_time = datetime.now()
    
    try:
        with get_db_connection() as conn:
            # Load each source into staging tables
            companies_count = load_companies(conn)
            psc_count = load_psc(conn)
            ccod_count = load_ccod(conn)
            ocod_count = load_ocod(conn)
            
            # Add indexes for performance
            add_indexes(conn)
            
            total_duration = datetime.now() - total_start_time
            total_rows = companies_count + psc_count + ccod_count + ocod_count
            
            print("\n" + "="*60)
            print("STAGING LOAD COMPLETE")
            print("="*60)
            print(f"Total time: {total_duration.total_seconds():.1f} seconds")
            print(f"Total rows: {total_rows:,}")
            print(f"Companies: {companies_count:,}")
            print(f"PSC: {psc_count:,}")
            print(f"CCOD: {ccod_count:,}")
            print(f"OCOD: {ocod_count:,}")
            print("\nStaging tables ready for M1 Phase 3 (graph build) ✓")
            
    except Exception as e:
        print(f"\nSTAGING LOAD FAILED: {e}")
        raise


if __name__ == "__main__":
    main()