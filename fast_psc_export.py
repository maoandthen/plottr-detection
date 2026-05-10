#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
import csv
import json
import time
from pathlib import Path
from etl.export_for_neo4j_admin import get_db
from etl.lib.normalise import normalise_name, person_id

EXPORT_DIR = Path("/Volumes/PlottrData/neo4j_import")
BATCH_SIZE = 5000  # Smaller batches for faster iteration

def fast_psc_export(conn):
    """Optimized PSC export with progress monitoring."""
    print(f"[{time.strftime('%H:%M:%S')}] Starting optimized PSC export...", flush=True)
    
    persons_out = EXPORT_DIR / "persons.csv"
    psc_out = EXPORT_DIR / "psc_of.csv"
    
    # Get total count first
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM stg_psc 
            WHERE raw_json->'data'->>'kind' LIKE 'individual-person%'
        """)
        total_count = cur.fetchone()[0]
        print(f"[{time.strftime('%H:%M:%S')}] Total PSC records to process: {total_count:,}", flush=True)
    
    seen_persons = set()
    with open(persons_out, "w", newline="", encoding="utf-8") as pf, \
         open(psc_out, "w", newline="", encoding="utf-8") as ef:
        
        pw = csv.writer(pf)
        ew = csv.writer(ef)
        
        # Write headers
        pw.writerow(["person_id:ID(Person)", "name", "name_normalised", "dob_year",
                     "dob_month", "country_of_residence", "nationality", ":LABEL"])
        ew.writerow([":START_ID(Person)", ":END_ID(Company)", "notified_on",
                     "nature_of_control", ":TYPE"])
        
        with conn.cursor("psc_cursor") as cur:
            cur.execute("""
                SELECT raw_json, company_number FROM stg_psc
                WHERE raw_json->'data'->>'kind' LIKE 'individual-person%'
            """)
            
            n_records = 0
            n_persons = 0 
            n_edges = 0
            last_report = time.time()
            
            print(f"[{time.strftime('%H:%M:%S')}] Starting batch processing...", flush=True)
            
            while True:
                rows = cur.fetchmany(BATCH_SIZE)
                if not rows:
                    break
                
                for raw_json, cn in rows:
                    try:
                        psc_wrapper = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                        psc = psc_wrapper.get("data", {}) if psc_wrapper else {}
                        
                        name_el = psc.get("name_elements", {}) or {}
                        name = " ".join([name_el.get("title", ""), name_el.get("forename", ""),
                                        name_el.get("middle_name", ""), name_el.get("surname", "")
                                        ]).strip()
                        if not name:
                            name = psc.get("name", "")
                        
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
                        
                        if pid not in seen_persons:
                            seen_persons.add(pid)
                            pw.writerow([pid, name, normalise_name(name),
                                        dy or "", dm or "", cor, nat, "Person"])
                            n_persons += 1
                        
                        notified = psc.get("notified_on", "") or ""
                        noc = psc.get("natures_of_control", []) or []
                        noc_str = ";".join(noc) if isinstance(noc, list) else str(noc)
                        ew.writerow([pid, cn, notified, noc_str, "PSC_OF"])
                        n_edges += 1
                        
                    except Exception as e:
                        print(f"[{time.strftime('%H:%M:%S')}] Error processing record: {e}", flush=True)
                        continue
                
                n_records += len(rows)
                
                # Progress report every 100k records or 30 seconds
                now = time.time()
                if n_records % 100000 == 0 or (now - last_report) > 30:
                    print(f"[{time.strftime('%H:%M:%S')}] Processed {n_records:,}/{total_count:,} "
                          f"({n_records/total_count*100:.1f}%) - {n_persons:,} persons, {n_edges:,} edges", flush=True)
                    last_report = now
            
            print(f"[{time.strftime('%H:%M:%S')}] PSC export complete: {n_records:,} records, "
                  f"{n_persons:,} unique persons, {n_edges:,} edges", flush=True)

if __name__ == "__main__":
    with get_db() as conn:
        fast_psc_export(conn)