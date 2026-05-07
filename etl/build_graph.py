#!/usr/bin/env python3
"""
M1 Phase 3: Build Neo4j ownership graph from PostgreSQL staging tables.

Phases:
- 3a: Schema setup (constraints/indexes)
- 3b: Company nodes (~5.7M)
- 3c: Title nodes (~4.5M) 
- 3d: OWNED_BY edges (corporate ownership)
- 3e: Person nodes (PSC individuals)
- 3f: PSC_OF edges (person-company control)
- 3g: Address nodes + REGISTERED_AT edges

Uses batched UNWIND for Neo4j write performance.
Idempotent via MERGE operations.
"""

import json
import os
import time
from pathlib import Path
from typing import Iterator, Dict, Any

import psycopg
from neo4j import GraphDatabase

from etl.lib.normalise import normalise_name, normalise_postcode, person_id, address_id


def get_database_url() -> str:
    """Read DATABASE_URL from .env, swap postgres for localhost."""
    url = os.getenv("DATABASE_URL")
    if not url:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("@postgres:", "@localhost:")


def get_neo4j_config() -> tuple[str, str, str]:
    """Read Neo4j connection details from .env."""
    uri = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")  
    password = os.getenv("NEO4J_PASSWORD", "password")
    
    # Translate neo4j hostname to localhost 
    uri = uri.replace("neo4j://neo4j:", "neo4j://localhost:")
    
    return uri, user, password


def batched(iterator: Iterator, batch_size: int = 5000) -> Iterator[list]:
    """Yield successive batches from iterator."""
    batch = []
    for item in iterator:
        batch.append(item)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def phase_3a_schema_setup(neo4j_driver):
    """Phase 3a: Create Neo4j constraints and indexes."""
    print("=== PHASE 3a: Schema Setup ===")
    start_time = time.time()
    
    schema_path = Path(__file__).parent / "sql" / "graph_schema.cypher"
    cypher_commands = schema_path.read_text().strip()
    
    with neo4j_driver.session() as session:
        # Split by semicolon and execute each command
        for command in cypher_commands.split(';'):
            command = command.strip()
            if command and not command.startswith('//'):
                try:
                    session.run(command)
                    print(f"  ✓ {command.split()[0]} {command.split()[1]}")
                except Exception as e:
                    print(f"  ! {command.split()[0]} {command.split()[1]}: {e}")
    
    elapsed = time.time() - start_time
    print(f"  Schema setup complete in {elapsed:.1f}s")


def phase_3b_company_nodes(pg_conn, neo4j_driver):
    """Phase 3b: Create Company nodes from staging tables."""
    print("=== PHASE 3b: Company Nodes ===")
    start_time = time.time()
    
    query = """
    SELECT company_number, company_name, company_status, incorporation_date, 
           dissolution_date, company_category, sic_code_sic_text_1
    FROM stg_companies 
    WHERE company_number IS NOT NULL
    """
    
    total_processed = 0
    with pg_conn.cursor('company_cursor') as cursor:
        cursor.execute(query)
        
        with neo4j_driver.session() as session:
            for batch in batched(cursor, 5000):
                rows = [dict(zip(['company_number', 'company_name', 'company_status', 
                                'incorporation_date', 'dissolution_date', 'company_category', 
                                'sic_code_sic_text_1'], row)) for row in batch]
                
                session.run("""
                UNWIND $rows AS row
                MERGE (c:Company {company_number: row.company_number})
                SET c.name = row.company_name,
                    c.name_normalised = $normalise_name(row.company_name),
                    c.status = row.company_status,
                    c.incorporation_date = row.incorporation_date,
                    c.dissolution_date = row.dissolution_date,
                    c.category = row.company_category,
                    c.sic_text = row.sic_code_sic_text_1
                """, rows=rows, normalise_name=normalise_name)
                
                total_processed += len(batch)
                if total_processed % 100000 == 0:
                    print(f"  Progress: {total_processed:,} companies")
    
    elapsed = time.time() - start_time
    print(f"  Company nodes complete: {total_processed:,} in {elapsed:.1f}s")


def phase_3c_title_nodes(pg_conn, neo4j_driver):
    """Phase 3c: Create Title nodes from CCOD/OCOD."""
    print("=== PHASE 3c: Title Nodes ===")
    start_time = time.time()
    
    query = """
    SELECT title_number, tenure, property_address, district, county, 
           region, postcode, 'CCOD' as source
    FROM stg_ccod_titles
    WHERE title_number IS NOT NULL
    UNION ALL
    SELECT title_number, tenure, property_address, district, county,
           region, postcode, 'OCOD' as source  
    FROM stg_ocod_titles
    WHERE title_number IS NOT NULL
    """
    
    total_processed = 0
    with pg_conn.cursor('title_cursor') as cursor:
        cursor.execute(query)
        
        with neo4j_driver.session() as session:
            for batch in batched(cursor, 5000):
                rows = [dict(zip(['title_number', 'tenure', 'property_address', 
                                'district', 'county', 'region', 'postcode', 'source'], row)) 
                       for row in batch]
                
                session.run("""
                UNWIND $rows AS row
                MERGE (t:Title {title_number: row.title_number})
                SET t.tenure = row.tenure,
                    t.address = row.property_address,
                    t.district = row.district,
                    t.county = row.county,
                    t.region = row.region,
                    t.postcode = $normalise_postcode(row.postcode),
                    t.source = row.source
                """, rows=rows, normalise_postcode=normalise_postcode)
                
                total_processed += len(batch)
                if total_processed % 100000 == 0:
                    print(f"  Progress: {total_processed:,} titles")
    
    elapsed = time.time() - start_time
    print(f"  Title nodes complete: {total_processed:,} in {elapsed:.1f}s")


def phase_3d_owned_by_edges(pg_conn, neo4j_driver):
    """Phase 3d: Create OWNED_BY edges (Title -> Company)."""
    print("=== PHASE 3d: OWNED_BY Edges ===")
    start_time = time.time()
    
    # UNION all proprietor positions from CCOD and OCOD
    query = """
    SELECT title_number, proprietor_name_1 as proprietor_name, 
           company_registration_no_1 as company_number, proprietorship_category_1 as category
    FROM stg_ccod_titles 
    WHERE company_registration_no_1 IS NOT NULL AND company_registration_no_1 != ''
    UNION ALL
    SELECT title_number, proprietor_name_2, company_registration_no_2, proprietorship_category_2
    FROM stg_ccod_titles
    WHERE company_registration_no_2 IS NOT NULL AND company_registration_no_2 != ''
    UNION ALL  
    SELECT title_number, proprietor_name_3, company_registration_no_3, proprietorship_category_3
    FROM stg_ccod_titles
    WHERE company_registration_no_3 IS NOT NULL AND company_registration_no_3 != ''
    UNION ALL
    SELECT title_number, proprietor_name_4, company_registration_no_4, proprietorship_category_4
    FROM stg_ccod_titles
    WHERE company_registration_no_4 IS NOT NULL AND company_registration_no_4 != ''
    UNION ALL
    SELECT title_number, proprietor_name_1, company_registration_no_1, proprietorship_category_1
    FROM stg_ocod_titles
    WHERE company_registration_no_1 IS NOT NULL AND company_registration_no_1 != ''
    UNION ALL
    SELECT title_number, proprietor_name_2, company_registration_no_2, proprietorship_category_2
    FROM stg_ocod_titles
    WHERE company_registration_no_2 IS NOT NULL AND company_registration_no_2 != ''
    UNION ALL
    SELECT title_number, proprietor_name_3, company_registration_no_3, proprietorship_category_3
    FROM stg_ocod_titles
    WHERE company_registration_no_3 IS NOT NULL AND company_registration_no_3 != ''
    UNION ALL
    SELECT title_number, proprietor_name_4, company_registration_no_4, proprietorship_category_4
    FROM stg_ocod_titles
    WHERE company_registration_no_4 IS NOT NULL AND company_registration_no_4 != ''
    """
    
    total_processed = 0
    with pg_conn.cursor('owned_by_cursor') as cursor:
        cursor.execute(query)
        
        with neo4j_driver.session() as session:
            for batch in batched(cursor, 5000):
                rows = [dict(zip(['title_number', 'proprietor_name', 'company_number', 'category'], row)) 
                       for row in batch]
                
                session.run("""
                UNWIND $rows AS row
                MATCH (t:Title {title_number: row.title_number})
                MATCH (c:Company {company_number: row.company_number})
                MERGE (t)-[r:OWNED_BY]->(c)
                SET r.proprietor_name = row.proprietor_name,
                    r.proprietorship_category = row.category
                """, rows=rows)
                
                total_processed += len(batch)
                if total_processed % 50000 == 0:
                    print(f"  Progress: {total_processed:,} ownership edges")
    
    elapsed = time.time() - start_time
    print(f"  OWNED_BY edges complete: {total_processed:,} in {elapsed:.1f}s")


def phase_3e_person_nodes(pg_conn, neo4j_driver):
    """Phase 3e: Create Person nodes from PSC data."""
    print("=== PHASE 3e: Person Nodes ===")
    start_time = time.time()
    
    query = """
    SELECT raw_json, company_number
    FROM stg_psc
    WHERE raw_json->>'kind' = 'individual-person-with-significant-control'
    """
    
    total_processed = 0
    with pg_conn.cursor('person_cursor') as cursor:
        cursor.execute(query)
        
        with neo4j_driver.session() as session:
            for batch in batched(cursor, 5000):
                persons = []
                for raw_json, company_number in batch:
                    psc_data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                    
                    # Extract name from name_elements or fallback to name field
                    name_elements = psc_data.get('name_elements', {})
                    name = (name_elements.get('title', '') + ' ' + 
                           name_elements.get('forename', '') + ' ' + 
                           name_elements.get('middle_name', '') + ' ' + 
                           name_elements.get('surname', '')).strip()
                    if not name:
                        name = psc_data.get('name', '')
                    
                    # Extract date of birth
                    dob = psc_data.get('date_of_birth', {})
                    dob_year = dob.get('year', '')
                    dob_month = dob.get('month', '')
                    dob_year_month = f"{dob_year}-{dob_month:02d}" if dob_year and dob_month else ""
                    
                    # Extract other fields
                    country_of_residence = psc_data.get('country_of_residence', '')
                    nationality = psc_data.get('nationality', '')
                    
                    # Generate deterministic person_id
                    pid = person_id(name, dob_year_month, country_of_residence)
                    
                    persons.append({
                        'person_id': pid,
                        'name': name,
                        'name_normalised': normalise_name(name),
                        'dob_year': dob_year,
                        'dob_month': dob_month,
                        'country_of_residence': country_of_residence,
                        'nationality': nationality
                    })
                
                if persons:
                    session.run("""
                    UNWIND $persons AS p
                    MERGE (person:Person {person_id: p.person_id})
                    SET person.name = p.name,
                        person.name_normalised = p.name_normalised,
                        person.dob_year = p.dob_year,
                        person.dob_month = p.dob_month,
                        person.country_of_residence = p.country_of_residence,
                        person.nationality = p.nationality
                    """, persons=persons)
                
                total_processed += len(batch)
                if total_processed % 100000 == 0:
                    print(f"  Progress: {total_processed:,} PSC records")
    
    elapsed = time.time() - start_time
    print(f"  Person nodes complete: {total_processed:,} PSC records in {elapsed:.1f}s")


def phase_3f_psc_of_edges(pg_conn, neo4j_driver):
    """Phase 3f: Create PSC_OF edges (Person -> Company)."""
    print("=== PHASE 3f: PSC_OF Edges ===")
    start_time = time.time()
    
    query = """
    SELECT raw_json, company_number
    FROM stg_psc
    WHERE raw_json->>'kind' = 'individual-person-with-significant-control'
    """
    
    total_processed = 0
    with pg_conn.cursor('psc_edge_cursor') as cursor:
        cursor.execute(query)
        
        with neo4j_driver.session() as session:
            for batch in batched(cursor, 5000):
                psc_edges = []
                for raw_json, company_number in batch:
                    psc_data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                    
                    # Extract name and compute person_id (same logic as phase 3e)
                    name_elements = psc_data.get('name_elements', {})
                    name = (name_elements.get('title', '') + ' ' + 
                           name_elements.get('forename', '') + ' ' + 
                           name_elements.get('middle_name', '') + ' ' + 
                           name_elements.get('surname', '')).strip()
                    if not name:
                        name = psc_data.get('name', '')
                    
                    dob = psc_data.get('date_of_birth', {})
                    dob_year = dob.get('year', '')
                    dob_month = dob.get('month', '')
                    dob_year_month = f"{dob_year}-{dob_month:02d}" if dob_year and dob_month else ""
                    
                    country_of_residence = psc_data.get('country_of_residence', '')
                    pid = person_id(name, dob_year_month, country_of_residence)
                    
                    # Extract edge attributes
                    notified_on = psc_data.get('notified_on', '')
                    nature_of_control = psc_data.get('natures_of_control', [])
                    
                    psc_edges.append({
                        'person_id': pid,
                        'company_number': company_number,
                        'notified_on': notified_on,
                        'nature_of_control': nature_of_control
                    })
                
                if psc_edges:
                    session.run("""
                    UNWIND $edges AS e
                    MATCH (p:Person {person_id: e.person_id})
                    MATCH (c:Company {company_number: e.company_number})
                    MERGE (p)-[r:PSC_OF]->(c)
                    SET r.notified_on = e.notified_on,
                        r.nature_of_control = e.nature_of_control
                    """, edges=psc_edges)
                
                total_processed += len(batch)
                if total_processed % 50000 == 0:
                    print(f"  Progress: {total_processed:,} PSC edges")
    
    elapsed = time.time() - start_time
    print(f"  PSC_OF edges complete: {total_processed:,} in {elapsed:.1f}s")


def phase_3g_address_nodes(pg_conn, neo4j_driver):
    """Phase 3g: Create Address nodes and REGISTERED_AT edges."""
    print("=== PHASE 3g: Address Nodes ===")
    start_time = time.time()
    
    # Company registered addresses
    company_query = """
    SELECT company_number, 
           CONCAT(COALESCE(reg_address_address_line_1, ''), ' ', 
                  COALESCE(reg_address_address_line_2, '')) as premises,
           reg_address_post_code as postcode,
           reg_address_post_town as town,
           reg_address_county as county,
           'company' as address_type
    FROM stg_companies
    WHERE reg_address_post_code IS NOT NULL
    """
    
    total_processed = 0
    with pg_conn.cursor('address_cursor') as cursor:
        cursor.execute(company_query)
        
        with neo4j_driver.session() as session:
            for batch in batched(cursor, 5000):
                addresses = []
                edges = []
                
                for company_number, premises, postcode, town, county, addr_type in batch:
                    aid = address_id(postcode, premises)
                    
                    addresses.append({
                        'address_id': aid,
                        'premises': premises,
                        'postcode': normalise_postcode(postcode),
                        'town': town,
                        'county': county,
                        'address_type': addr_type
                    })
                    
                    edges.append({
                        'company_number': company_number,
                        'address_id': aid
                    })
                
                # Create address nodes
                session.run("""
                UNWIND $addresses AS a
                MERGE (addr:Address {address_id: a.address_id})
                SET addr.premises = a.premises,
                    addr.postcode = a.postcode,
                    addr.town = a.town,
                    addr.county = a.county,
                    addr.address_type = a.address_type
                """, addresses=addresses)
                
                # Create REGISTERED_AT edges
                session.run("""
                UNWIND $edges AS e
                MATCH (c:Company {company_number: e.company_number})
                MATCH (a:Address {address_id: e.address_id})
                MERGE (c)-[:REGISTERED_AT]->(a)
                """, edges=edges)
                
                total_processed += len(batch)
                if total_processed % 50000 == 0:
                    print(f"  Progress: {total_processed:,} addresses")
    
    elapsed = time.time() - start_time
    print(f"  Address nodes complete: {total_processed:,} in {elapsed:.1f}s")


def print_final_summary(neo4j_driver):
    """Print final node and edge counts."""
    print("=== FINAL SUMMARY ===")
    
    with neo4j_driver.session() as session:
        # Node counts
        for label in ['Company', 'Title', 'Person', 'Address']:
            result = session.run(f"MATCH (n:{label}) RETURN count(n) as count")
            count = result.single()['count']
            print(f"  {label} nodes: {count:,}")
        
        # Edge counts  
        for rel_type in ['OWNED_BY', 'PSC_OF', 'REGISTERED_AT']:
            result = session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as count")
            count = result.single()['count']
            print(f"  {rel_type} edges: {count:,}")


def main():
    """Execute all phases of graph building."""
    print("=== M1 PHASE 3: BUILD OWNERSHIP GRAPH ===")
    overall_start = time.time()
    
    # Connect to databases
    pg_url = get_database_url()
    neo4j_uri, neo4j_user, neo4j_password = get_neo4j_config()
    
    print(f"Postgres: {pg_url.split('@')[1]}")
    print(f"Neo4j: {neo4j_uri}")
    
    with psycopg.connect(pg_url) as pg_conn, \
         GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password)) as neo4j_driver:
        
        # Execute all phases
        phase_3a_schema_setup(neo4j_driver)
        phase_3b_company_nodes(pg_conn, neo4j_driver)
        phase_3c_title_nodes(pg_conn, neo4j_driver)
        phase_3d_owned_by_edges(pg_conn, neo4j_driver)
        phase_3e_person_nodes(pg_conn, neo4j_driver)
        phase_3f_psc_of_edges(pg_conn, neo4j_driver)
        phase_3g_address_nodes(pg_conn, neo4j_driver)
        
        print_final_summary(neo4j_driver)
    
    elapsed = time.time() - overall_start
    print(f"=== GRAPH BUILD COMPLETE in {elapsed/60:.1f} minutes ===")


if __name__ == "__main__":
    main()