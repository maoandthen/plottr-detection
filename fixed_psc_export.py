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

def export_persons_and_psc_fixed(conn):
    """Export Person nodes and PSC_OF edges - FIXED VERSION."""
    print(f"[{time.strftime('%H:%M:%S')}] Exporting persons + PSC_OF (fixed)...", flush=True)
    persons_out = EXPORT_DIR / "persons.csv"
    psc_out = EXPORT_DIR / "psc_of.csv"
    
    seen_persons = set()
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
            
            print(f"[{time.strftime('%H:%M:%S')}] Query started...", flush=True)
            
            while True:
                rows = cur.fetchmany(10000)
                if not rows:
                    break
                    
                for raw_json, cn in rows:
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
                
                n_records += len(rows)
                if n_records % 500000 == 0:
                    print(f"[{time.strftime('%H:%M:%S')}] {n_records:,} PSC records, "
                          f"{n_persons:,} unique persons, {n_edges:,} edges", flush=True)
        
        print(f"[{time.strftime('%H:%M:%S')}] PSC done: {n_records:,} records, "
              f"{n_persons:,} persons, {n_edges:,} edges", flush=True)

if __name__ == "__main__":
    with get_db() as conn:
        export_persons_and_psc_fixed(conn)