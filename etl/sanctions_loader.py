"""
sanctions_loader.py
───────────────────
Downloads OFAC SDN and EU consolidated sanctions lists, normalises names,
and matches against Person nodes in the Neo4j graph. Creates a
stg_sanctions_matches table in Postgres and a :SANCTIONS_MATCH label
on matched Person nodes.

Usage:
    PYTHONPATH=. python3 etl/sanctions_loader.py

Runtime: ~10-20 minutes (bulk download + fuzzy match across 9.5M persons).
"""

import os
import re
import csv
import json
import hashlib
import logging
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path
from datetime import datetime, date

# ── deps ─────────────────────────────────────────────────────────────────────
try:
    import psycopg
    from neo4j import GraphDatabase
except ImportError:
    raise SystemExit("pip3 install psycopg neo4j --break-system-packages")

# ── config ────────────────────────────────────────────────────────────────────
DATABASE_URL   = os.environ.get("DATABASE_URL",
                                "postgresql://plottr:plottr@localhost:5432/plottr")
NEO4J_URI      = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.environ.get("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "plottr_secret")

OFAC_SDN_URL = (
    "https://www.treasury.gov/ofac/downloads/sdn.xml"
)
EU_SANCTIONS_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList/content"
)
ELECTORAL_COMMISSION_URL = (
    "https://search.electoralcommission.org.uk/api/csv/Donations"
    "?start=2010-01-01&end=2026-12-31&register=gb&entity=individual"
)

FUZZY_THRESHOLD = 0.85   # minimum similarity to call a match
BATCH_SIZE      = 1000

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ── normalisation ─────────────────────────────────────────────────────────────

def normalise_name(raw: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace, strip punctuation."""
    if not raw:
        return ""
    s = unicodedata.normalize("NFD", raw)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def name_tokens(normalised: str) -> frozenset:
    return frozenset(normalised.split())


def token_similarity(a: str, b: str) -> float:
    """Jaccard similarity on name tokens. Fast approximation for bulk matching."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ── OFAC SDN parser ───────────────────────────────────────────────────────────

def fetch_ofac_sdn() -> list[dict]:
    """
    Downloads OFAC SDN XML and extracts individual (not entity) entries.
    Returns list of dicts with: id, name, name_normalised, dob_year, programs.
    """
    log.info("Downloading OFAC SDN list …")
    try:
        with urllib.request.urlopen(OFAC_SDN_URL, timeout=60) as r:
            xml_bytes = r.read()
    except Exception as e:
        log.warning(f"OFAC download failed: {e}. Using cached file if present.")
        cache = Path("/tmp/plottr-intelligence/sdn.xml")
        if cache.exists():
            xml_bytes = cache.read_bytes()
        else:
            log.error("No cached SDN file. Skipping OFAC.")
            return []

    Path("/tmp/plottr-intelligence/sdn.xml").write_bytes(xml_bytes)

    ns = {"sdn": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN"}
    root = ET.fromstring(xml_bytes)

    entries = []
    for entry in root.findall(".//sdn:sdnEntry", ns):
        sdn_type = entry.findtext("sdn:sdnType", namespaces=ns)
        if sdn_type != "Individual":
            continue

        last  = entry.findtext("sdn:lastName",  namespaces=ns) or ""
        first = entry.findtext("sdn:firstName", namespaces=ns) or ""
        full  = f"{first} {last}".strip() if first else last

        dob_year = None
        for dob_el in entry.findall(".//sdn:dateOfBirthItem/sdn:dateOfBirth", ns):
            raw = dob_el.text or ""
            m = re.search(r"\b(19|20)\d{2}\b", raw)
            if m:
                dob_year = int(m.group())
                break

        programs = [
            p.text for p in entry.findall(".//sdn:program", ns)
            if p.text
        ]

        entries.append({
            "source":          "OFAC_SDN",
            "source_id":       entry.findtext("sdn:uid", namespaces=ns),
            "name":            full,
            "name_normalised": normalise_name(full),
            "dob_year":        dob_year,
            "programs":        json.dumps(programs),
            "raw":             json.dumps({"last": last, "first": first}),
        })

    log.info(f"  OFAC: {len(entries):,} individual entries")
    return entries


# ── EU consolidated sanctions parser ──────────────────────────────────────────

def fetch_eu_sanctions() -> list[dict]:
    """
    Downloads EU consolidated sanctions CSV. Extracts individual persons.
    """
    log.info("Downloading EU consolidated sanctions list …")
    try:
        with urllib.request.urlopen(EU_SANCTIONS_URL, timeout=60) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning(f"EU sanctions download failed: {e}. Skipping EU list.")
        return []

    entries = []
    reader = csv.DictReader(StringIO(raw), delimiter=";")
    for row in reader:
        if row.get("Entity_SubjectType", "").lower() != "person":
            continue

        name_alias = row.get("NameAlias_WholeName") or row.get("Entity_LogicalId") or ""
        dob_str    = row.get("BirthDate_BirthDate", "")
        dob_year   = None
        m = re.search(r"\b(19|20)\d{2}\b", dob_str)
        if m:
            dob_year = int(m.group())

        entries.append({
            "source":          "EU_SANCTIONS",
            "source_id":       row.get("Entity_LogicalId", ""),
            "name":            name_alias,
            "name_normalised": normalise_name(name_alias),
            "dob_year":        dob_year,
            "programs":        json.dumps([row.get("Regulation_Programme", "")]),
            "raw":             json.dumps(dict(list(row.items())[:10])),
        })

    log.info(f"  EU:   {len(entries):,} individual entries")
    return entries


# ── Postgres staging ──────────────────────────────────────────────────────────

def init_staging(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stg_sanctions_list (
            id               SERIAL PRIMARY KEY,
            source           TEXT NOT NULL,
            source_id        TEXT,
            name             TEXT,
            name_normalised  TEXT,
            dob_year         INTEGER,
            programs         JSONB,
            raw              JSONB,
            loaded_at        TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sanctions_name
            ON stg_sanctions_list (name_normalised);

        CREATE TABLE IF NOT EXISTS stg_sanctions_matches (
            id               SERIAL PRIMARY KEY,
            person_id        TEXT NOT NULL,
            person_name      TEXT,
            person_dob_year  INTEGER,
            sanction_source  TEXT,
            sanction_id      TEXT,
            sanction_name    TEXT,
            sanction_dob     INTEGER,
            similarity       REAL,
            dob_match        BOOLEAN,
            confidence       TEXT,
            flagged_at       TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_matches_person
            ON stg_sanctions_matches (person_id);
    """)
    conn.commit()
    log.info("Staging tables ready.")


def load_sanctions_list(conn, entries: list[dict]):
    conn.execute("TRUNCATE stg_sanctions_list;")
    with conn.cursor() as cur:
        for i in range(0, len(entries), BATCH_SIZE):
            batch = entries[i:i + BATCH_SIZE]
            cur.executemany("""
                INSERT INTO stg_sanctions_list
                  (source, source_id, name, name_normalised, dob_year, programs, raw)
                VALUES
                  (%(source)s, %(source_id)s, %(name)s, %(name_normalised)s,
                   %(dob_year)s, %(programs)s::jsonb, %(raw)s::jsonb)
            """, batch)
    conn.commit()
    log.info(f"  Loaded {len(entries):,} sanctions entries to Postgres.")


# ── Neo4j matching ────────────────────────────────────────────────────────────

def match_against_graph(conn, driver):
    """
    Iterates Person nodes in Neo4j in batches, scores against sanctions list.
    Writes confirmed matches to stg_sanctions_matches and tags Neo4j nodes.
    """
    log.info("Loading sanctions list into memory for matching …")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT source, source_id, name_normalised, dob_year, programs
            FROM stg_sanctions_list
        """)
        sanctions = cur.fetchall()

    log.info(f"  {len(sanctions):,} sanctions entries in memory.")

    skip = 0
    matched_total = 0

    with driver.session() as session:
        while True:
            result = session.run("""
                MATCH (p:Person)
                WHERE p.name_normalised IS NOT NULL
                RETURN p.person_id AS pid,
                       p.name_normalised AS name,
                       p.name AS raw_name,
                       toInteger(p.dob_year) AS dob_year
                SKIP $skip LIMIT $limit
            """, skip=skip, limit=BATCH_SIZE)

            persons = result.data()
            if not persons:
                break

            matches = []
            for person in persons:
                p_name = person["name"] or ""
                p_dob  = person["dob_year"]

                for (src, src_id, s_name, s_dob, programs) in sanctions:
                    sim = token_similarity(p_name, s_name)
                    if sim < FUZZY_THRESHOLD:
                        continue

                    dob_match = (
                        p_dob is not None
                        and s_dob is not None
                        and p_dob == s_dob
                    )

                    # Confidence: HIGH needs both name sim ≥0.9 and DOB match
                    if sim >= 0.9 and dob_match:
                        confidence = "HIGH"
                    elif sim >= 0.9:
                        confidence = "MEDIUM"
                    else:
                        confidence = "LOW"

                    matches.append({
                        "person_id":       person["pid"],
                        "person_name":     person["raw_name"],
                        "person_dob_year": p_dob,
                        "sanction_source": src,
                        "sanction_id":     src_id,
                        "sanction_name":   s_name,
                        "sanction_dob":    s_dob,
                        "similarity":      round(sim, 4),
                        "dob_match":       dob_match,
                        "confidence":      confidence,
                    })

            if matches:
                with conn.cursor() as cur:
                    cur.executemany("""
                        INSERT INTO stg_sanctions_matches
                          (person_id, person_name, person_dob_year,
                           sanction_source, sanction_id, sanction_name,
                           sanction_dob, similarity, dob_match, confidence)
                        VALUES
                          (%(person_id)s, %(person_name)s, %(person_dob_year)s,
                           %(sanction_source)s, %(sanction_id)s, %(sanction_name)s,
                           %(sanction_dob)s, %(similarity)s, %(dob_match)s,
                           %(confidence)s)
                        ON CONFLICT DO NOTHING
                    """, matches)
                conn.commit()

                # Tag HIGH-confidence matches in Neo4j
                high_conf = [m["person_id"] for m in matches
                             if m["confidence"] == "HIGH"]
                if high_conf:
                    session.run("""
                        UNWIND $pids AS pid
                        MATCH (p:Person {person_id: pid})
                        SET p.sanctions_flag = true,
                            p.sanctions_confidence = 'HIGH'
                    """, pids=high_conf)

                matched_total += len(matches)

            skip += BATCH_SIZE
            if skip % 100_000 == 0:
                log.info(f"  Processed {skip:,} persons … {matched_total:,} matches so far")

    log.info(f"Matching complete. {matched_total:,} total matches written.")
    return matched_total


# ── PEP: Electoral Commission donations ───────────────────────────────────────

def fetch_electoral_commission_donors() -> list[dict]:
    """
    Pulls individual donors from Electoral Commission API.
    Used to flag persons who appear in PSC data AND have made political donations.
    Note: name matching only — no unique ID between registers.
    """
    log.info("Downloading Electoral Commission donor data …")
    try:
        with urllib.request.urlopen(ELECTORAL_COMMISSION_URL, timeout=60) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning(f"Electoral Commission download failed: {e}. Skipping.")
        return []

    donors = []
    reader = csv.DictReader(StringIO(raw))
    for row in reader:
        name = row.get("DonorName", "").strip()
        if not name:
            continue
        donors.append({
            "source":          "ELECTORAL_COMMISSION",
            "source_id":       row.get("ECRef", ""),
            "name":            name,
            "name_normalised": normalise_name(name),
            "dob_year":        None,
            "programs":        json.dumps([
                row.get("ReportingPeriodName", ""),
                row.get("RecipientName", ""),
            ]),
            "raw":             json.dumps({
                "value":     row.get("Value", ""),
                "recipient": row.get("RecipientName", ""),
                "date":      row.get("ReceivedDate", ""),
            }),
        })

    log.info(f"  Electoral Commission: {len(donors):,} individual donors")
    return donors


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Plottr Sanctions & PEP Loader ===")

    # 1. Fetch lists
    ofac    = fetch_ofac_sdn()
    eu      = fetch_eu_sanctions()
    donors  = fetch_electoral_commission_donors()
    all_entries = ofac + eu + donors
    log.info(f"Total entries to screen against: {len(all_entries):,}")

    # 2. Postgres staging
    with psycopg.connect(DATABASE_URL) as conn:
        init_staging(conn)
        load_sanctions_list(conn, all_entries)

        # 3. Neo4j matching
        driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
        try:
            matched = match_against_graph(conn, driver)
        finally:
            driver.close()

    log.info(f"=== Done. {matched:,} matches. ===")
    log.info("Review matches in Postgres: SELECT * FROM stg_sanctions_matches ORDER BY confidence, similarity DESC;")
    log.info("HIGH confidence matches are tagged on Person nodes in Neo4j (p.sanctions_flag = true).")
    log.info("MEDIUM/LOW require manual review before surfacing in the product.")


if __name__ == "__main__":
    main()
