#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from etl.export_for_neo4j_admin import get_db
import json

# Test the PSC query directly
print("Testing PSC query...")
with get_db() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT raw_json, company_number FROM stg_psc
            WHERE raw_json->'data'->>'kind' LIKE 'individual-person%'
            LIMIT 3
        """)
        rows = cur.fetchall()
        print(f"Query returned {len(rows)} rows")
        
        for i, (raw_json, cn) in enumerate(rows):
            print(f"\nRow {i+1}:")
            print(f"Company: {cn}")
            
            psc_wrapper = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            psc = psc_wrapper.get("data", {}) if psc_wrapper else {}
            
            print(f"Kind: {psc.get('kind', 'MISSING')}")
            print(f"Name: {psc.get('name', 'MISSING')}")
            
            name_el = psc.get("name_elements", {}) or {}
            if name_el:
                full_name = " ".join([
                    name_el.get("title", ""), 
                    name_el.get("forename", ""),
                    name_el.get("middle_name", ""), 
                    name_el.get("surname", "")
                ]).strip()
                print(f"Constructed name: '{full_name}'")