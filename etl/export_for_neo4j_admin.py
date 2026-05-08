#!/usr/bin/env python3
"""Export Postgres staging data to CSV in neo4j-admin import format.

neo4j-admin needs:
- one CSV per node label, with header row in special format
- one CSV per relationship type, with :START_ID and :END_ID columns
"""
import csv
import json
import os
import time
from pathlib import Path
import psycopg
from etl.lib.normalise import normalise_name, normalise_postcode, person_id, address_id

EXPORT_DIR = Path("/Volumes/PlottrData/neo4j_import")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    url = os.getenv("DATABASE_URL")
    if not url:
        env = Path(".env")
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    return psycopg.connect(url.replace("@postgres:", "@localhost:"))


def export_companies(conn):
    """Export Company nodes."""
    print(f"[{time.strftime('%H:%M:%S')}] Exporting companies...", flush=True)
    out = EXPORT_DIR / "companies.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company_number:ID(Company)", "name", "name_normalised", "status",
                    "incorporation_date", "dissolution_date", "category", "sic_text", ":LABEL"])
        with conn.cursor() as cur:
            cur.execute("""
                SELECT company_number, company_name, company_status, incorporation_date,
                       dissolution_date, company_category, sic_code_sic_text_1
                FROM stg_companies WHERE company_number IS NOT NULL
            """)
            n = 0
            while True:
                rows = cur.fetchmany(10000)
                if not rows:
                    break
                for r in rows:
                    cn, name, status, inc, diss, cat, sic = r
                    w.writerow([cn, name or "", normalise_name(name or ""),
                               status or "", inc or "", diss or "", cat or "", sic or "", "Company"])
                n += len(rows)
                if n % 500000 == 0:
                    print(f"[{time.strftime('%H:%M:%S')}] {n:,} companies", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] Companies done: {n:,}", flush=True)


def export_titles(conn):
    """Export Title nodes (CCOD + OCOD)."""
    print(f"[{time.strftime('%H:%M:%S')}] Exporting titles...", flush=True)
    out = EXPORT_DIR / "titles.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title_number:ID(Title)", "tenure", "address", "district", "county",
                    "region", "postcode", "source", ":LABEL"])
        for table, source in [("stg_ccod_titles", "CCOD"), ("stg_ocod_titles", "OCOD")]:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT title_number, tenure, property_address, district, county,
                           region, postcode FROM {table} WHERE title_number IS NOT NULL
                """)
                n = 0
                while True:
                    rows = cur.fetchmany(10000)
                    if not rows:
                        break
                    for r in rows:
                        tn, ten, addr, dist, county, region, pc = r
                        w.writerow([tn, ten or "", addr or "", dist or "", county or "",
                                   region or "", normalise_postcode(pc or ""), source, "Title"])
                    n += len(rows)
            print(f"[{time.strftime('%H:%M:%S')}] {table}: {n:,}", flush=True)


def export_owned_by(conn):
    """Export OWNED_BY edges (Title -> Company)."""
    print(f"[{time.strftime('%H:%M:%S')}] Exporting OWNED_BY edges...", flush=True)
    out = EXPORT_DIR / "owned_by.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([":START_ID(Title)", ":END_ID(Company)", "proprietor_name",
                    "proprietorship_category", ":TYPE"])
        union_parts = []
        for table in ["stg_ccod_titles", "stg_ocod_titles"]:
            for i in [1, 2, 3, 4]:
                union_parts.append(f"""
                    SELECT title_number, proprietor_name_{i} AS pn,
                           company_registration_no_{i} AS cn, proprietorship_category_{i} AS cat
                    FROM {table}
                    WHERE company_registration_no_{i} IS NOT NULL AND company_registration_no_{i} != ''
                """)
        query = " UNION ALL ".join(union_parts)
        with conn.cursor() as cur:
            cur.execute(query)
            n = 0
            while True:
                rows = cur.fetchmany(10000)
                if not rows:
                    break
                for r in rows:
                    tn, pn, cn, cat = r
                    w.writerow([tn, cn, pn or "", cat or "", "OWNED_BY"])
                n += len(rows)
                if n % 500000 == 0:
                    print(f"[{time.strftime('%H:%M:%S')}] {n:,} ownership edges", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] OWNED_BY done: {n:,}", flush=True)


def export_persons_and_psc(conn):
    """Export Person nodes and PSC_OF edges - streaming version without memory dedup."""
    print(f"[{time.strftime('%H:%M:%S')}] Exporting persons + PSC_OF...", flush=True)
    persons_out = EXPORT_DIR / "persons.csv"
    psc_out = EXPORT_DIR / "psc_of.csv"
    
    with open(persons_out, "w", newline="", encoding="utf-8") as pf, \
         open(psc_out, "w", newline="", encoding="utf-8") as ef:
        pw = csv.writer(pf)
        ew = csv.writer(ef)
        pw.writerow(["person_id:ID(Person)", "name", "name_normalised", "dob_year",
                     "dob_month", "country_of_residence", "nationality", ":LABEL"])
        ew.writerow([":START_ID(Person)", ":END_ID(Company)", "notified_on",
                     "nature_of_control", ":TYPE"])
        
        with conn.cursor() as cur:
            cur.execute("""
                SELECT raw_json, company_number FROM stg_psc
                WHERE raw_json->'data'->>'kind' LIKE 'individual-person%'
            """)
            n_records = 0
            n_persons = 0
            n_edges = 0
            while True:
                rows = cur.fetchmany(5000)
                if not rows:
                    break
                for raw_json, cn in rows:
                    psc_outer = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                    psc = psc_outer.get("data", {}) or {}
                    
                    name_el = psc.get("name_elements", {}) or {}
                    name = " ".join([
                        name_el.get("title", "") or "", name_el.get("forename", "") or "",
                        name_el.get("middle_name", "") or "", name_el.get("surname", "") or ""
                    ]).strip()
                    if not name:
                        name = psc.get("name", "") or ""
                    
                    dob = psc.get("date_of_birth", {}) or {}
                    try:
                        dy = int(dob.get("year")) if dob.get("year") else None
                        dm = int(dob.get("month")) if dob.get("month") else None
                        dym = f"{dy}-{dm:02d}" if dy and dm else ""
                    except (ValueError, TypeError):
                        dym = ""
                        dy = dm = None
                    
                    cor = psc.get("country_of_residence", "") or ""
                    nat = psc.get("nationality", "") or ""
                    
                    pid = person_id(name, dym, cor)
                    
                    # Write person row - duplicates OK, will dedupe via sort -u after
                    pw.writerow([pid, name, normalise_name(name),
                                dy or "", dm or "", cor, nat, "Person"])
                    n_persons += 1
                    
                    notified = psc.get("notified_on", "") or ""
                    noc = psc.get("natures_of_control", []) or []
                    noc_str = ";".join(noc) if isinstance(noc, list) else str(noc)
                    ew.writerow([pid, cn, notified, noc_str, "PSC_OF"])
                    n_edges += 1
                
                n_records += len(rows)
                if n_records % 100000 == 0:
                    print(f"[{time.strftime('%H:%M:%S')}] {n_records:,} PSC records processed", flush=True)
        
        print(f"[{time.strftime('%H:%M:%S')}] PSC raw export done: {n_records:,} records, {n_persons:,} person rows (with duplicates), {n_edges:,} edges", flush=True)
        print(f"[{time.strftime('%H:%M:%S')}] Deduplicating persons.csv via sort -u...", flush=True)
        
        # Dedupe persons.csv: keep header, sort+unique the rest
        import subprocess
        persons_path = str(persons_out)
        persons_dedup = persons_path + ".dedup"
        subprocess.run(
            f"head -1 {persons_path} > {persons_dedup} && tail -n +2 {persons_path} | sort -u >> {persons_dedup}",
            shell=True, check=True
        )
        subprocess.run(f"mv {persons_dedup} {persons_path}", shell=True, check=True)
        
        # Count deduped lines
        result = subprocess.run(["wc", "-l", persons_path], capture_output=True, text=True)
        final_count = int(result.stdout.split()[0]) - 1 # minus header
        print(f"[{time.strftime('%H:%M:%S')}] Persons deduped: {final_count:,} unique persons", flush=True)


def export_addresses_and_registered_at(conn):
    """Export Address nodes and REGISTERED_AT edges from Company registered offices."""
    print(f"[{time.strftime('%H:%M:%S')}] Exporting addresses + REGISTERED_AT...", flush=True)
    addr_out = EXPORT_DIR / "addresses.csv"
    edge_out = EXPORT_DIR / "registered_at.csv"
    
    seen_addresses = set()
    with open(addr_out, "w", newline="", encoding="utf-8") as af, \
         open(edge_out, "w", newline="", encoding="utf-8") as ef:
        aw = csv.writer(af)
        ew = csv.writer(ef)
        aw.writerow(["address_id:ID(Address)", "premises", "postcode", "town",
                     "county", "address_type", ":LABEL"])
        ew.writerow([":START_ID(Company)", ":END_ID(Address)", ":TYPE"])
        
        with conn.cursor() as cur:
            cur.execute("""
                SELECT company_number,
                       CONCAT(COALESCE(reg_address_address_line_1, ''), ' ',
                              COALESCE(reg_address_address_line_2, '')),
                       reg_address_post_code, reg_address_post_town, reg_address_county
                FROM stg_companies
                WHERE reg_address_post_code IS NOT NULL AND reg_address_post_code != ''
            """)
            n = 0
            while True:
                rows = cur.fetchmany(10000)
                if not rows:
                    break
                for cn, premises, pc, town, county in rows:
                    aid = address_id(pc or "", premises or "")
                    if aid not in seen_addresses:
                        seen_addresses.add(aid)
                        aw.writerow([aid, (premises or "").strip(), normalise_postcode(pc or ""),
                                    town or "", county or "", "company", "Address"])
                    ew.writerow([cn, aid, "REGISTERED_AT"])
                n += len(rows)
                if n % 500000 == 0:
                    print(f"[{time.strftime('%H:%M:%S')}] {n:,} company addresses", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] Addresses done", flush=True)


def main():
    print(f"[{time.strftime('%H:%M:%S')}] === Phase 3 v2 CSV export ===", flush=True)
    start = time.time()
    with get_db() as conn:
        export_companies(conn)
        export_titles(conn)
        export_owned_by(conn)
        export_persons_and_psc(conn)
        export_addresses_and_registered_at(conn)
    print(f"[{time.strftime('%H:%M:%S')}] Total: {(time.time()-start)/60:.1f} min", flush=True)
    print(f"\nFiles in {EXPORT_DIR}:")
    for f in sorted(EXPORT_DIR.glob("*.csv")):
        print(f"  {f.name}: {f.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()