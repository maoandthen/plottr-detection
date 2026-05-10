"""
plottr — search endpoint.

Single search endpoint serving:
  - autocomplete (small N, fast, type-grouped)
  - full search results page (larger N, paginated)

Endpoints:
  GET /api/search/autocomplete?q=...        → JSON, top 9 grouped 3+3+3
  GET /api/search/results?q=...&type=...    → JSON, paginated full results
  GET /search?q=...                         → HTML results page

Result types: company, person, address, title

Tier gating happens at the route layer:
  - autocomplete: open to all (deliberately generous, no real data leak from name+CRN)
  - results page detail links: free tier sees blur + upgrade CTA on click-through
  - full enterprise data: only on detail pages, gated by tier middleware
"""

import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates


router = APIRouter()


# -----------------------------------------------------------------------------
# Cypher queries
# -----------------------------------------------------------------------------

# Autocomplete — fast, indexed lookups, top 3 of each type.
# Uses CONTAINS on name_normalised which is indexed.
# All queries return at most 3 rows for snappy 3+3+3 dropdown.

CYPHER_AUTOCOMPLETE_COMPANIES = """
MATCH (c:Company)
WHERE c.name_normalised CONTAINS $q_normalised
WITH c
OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
WITH c, count(t) AS title_count
ORDER BY
  CASE WHEN c.name_normalised STARTS WITH $q_normalised THEN 0 ELSE 1 END,
  title_count DESC,
  c.name
LIMIT 3
RETURN c.company_number AS id,
       c.name AS name,
       c.status AS status,
       title_count
"""

CYPHER_AUTOCOMPLETE_PERSONS = """
MATCH (p:Person)
WHERE p.name_normalised CONTAINS $q_normalised
WITH p
OPTIONAL MATCH (p)-[:PSC_OF]->(c:Company)
WITH p, count(c) AS controlled_count
ORDER BY
  CASE WHEN p.name_normalised STARTS WITH $q_normalised THEN 0 ELSE 1 END,
  controlled_count DESC,
  p.name
LIMIT 3
RETURN p.person_id AS id,
       p.name AS name,
       p.country_of_residence AS country,
       p.dob_year AS dob_year,
       controlled_count
"""

CYPHER_AUTOCOMPLETE_ADDRESSES = """
MATCH (a:Address)
WHERE a.postcode = $q_postcode OR a.postcode STARTS WITH $q_postcode
WITH a
OPTIONAL MATCH (c:Company)-[:REGISTERED_AT]->(a)
WITH a, count(c) AS reg_count
ORDER BY reg_count DESC, a.postcode
LIMIT 3
RETURN a.address_id AS id,
       a.premises AS premises,
       a.postcode AS postcode,
       a.town AS town,
       reg_count
"""

CYPHER_AUTOCOMPLETE_TITLES = """
MATCH (t:Title)
WHERE t.title_number = $q_upper OR t.postcode = $q_postcode
RETURN t.title_number AS id,
       t.address AS address,
       t.postcode AS postcode,
       t.tenure AS tenure,
       t.source AS source
LIMIT 3
"""


# Full results — larger N, paginated.

CYPHER_RESULTS_COMPANIES = """
MATCH (c:Company)
WHERE c.name_normalised CONTAINS $q_normalised
WITH c
OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
WITH c, count(t) AS title_count
ORDER BY
  CASE WHEN c.name_normalised STARTS WITH $q_normalised THEN 0 ELSE 1 END,
  title_count DESC,
  c.name
SKIP $skip LIMIT $limit
OPTIONAL MATCH (c)-[:REGISTERED_AT]->(a:Address)
WITH c, title_count, a
LIMIT 1
RETURN c.company_number AS id,
       c.name AS name,
       c.status AS status,
       c.incorporation_date AS incorporated,
       c.category AS category,
       title_count,
       a.postcode AS reg_postcode,
       a.town AS reg_town
"""

CYPHER_RESULTS_PERSONS = """
MATCH (p:Person)
WHERE p.name_normalised CONTAINS $q_normalised
WITH p
OPTIONAL MATCH (p)-[:PSC_OF]->(c:Company)
WITH p, count(c) AS controlled_count, collect(c.name)[0..3] AS sample_companies
ORDER BY
  CASE WHEN p.name_normalised STARTS WITH $q_normalised THEN 0 ELSE 1 END,
  controlled_count DESC,
  p.name
SKIP $skip LIMIT $limit
RETURN p.person_id AS id,
       p.name AS name,
       p.country_of_residence AS country,
       p.dob_year AS dob_year,
       p.nationality AS nationality,
       controlled_count,
       sample_companies
"""

CYPHER_RESULT_COUNTS = """
CALL {
  MATCH (c:Company) WHERE c.name_normalised CONTAINS $q_normalised
  RETURN count(c) AS company_count
}
CALL {
  MATCH (p:Person) WHERE p.name_normalised CONTAINS $q_normalised
  RETURN count(p) AS person_count
}
CALL {
  MATCH (a:Address) WHERE a.postcode STARTS WITH $q_postcode
  RETURN count(a) AS address_count
}
CALL {
  MATCH (t:Title) WHERE t.title_number = $q_upper OR t.postcode = $q_postcode
  RETURN count(t) AS title_count
}
RETURN company_count, person_count, address_count, title_count
"""


# -----------------------------------------------------------------------------
# Query normalisation — same logic as etl/lib/normalise.py for consistency
# -----------------------------------------------------------------------------

UNICODE_HYPHENS = ['\u2010', '\u2011', '\u2012', '\u2013', '\u2014', '\u2015', '\u2212']
COMPANY_SUFFIXES = re.compile(r'\b(ltd|limited|plc|llp|llc|inc|co|company)\b\.?$', re.IGNORECASE)


def normalise_name(name: str) -> str:
    """Match the ETL normaliser exactly so search hits the same name_normalised values."""
    if not name:
        return ""
    n = name.lower().strip()
    for h in UNICODE_HYPHENS:
        n = n.replace(h, '-')
    n = re.sub(r'\s+', ' ', n)
    n = COMPANY_SUFFIXES.sub('', n).strip()
    return n


def normalise_postcode(pc: str) -> str:
    """Match the ETL postcode normaliser."""
    if not pc:
        return ""
    return re.sub(r'\s+', '', pc.upper())


def is_postcode_like(q: str) -> bool:
    """Quick heuristic: looks like a UK postcode prefix?"""
    return bool(re.match(r'^[A-Z]{1,2}[0-9]', q.upper().replace(' ', '')))


def is_title_number_like(q: str) -> bool:
    """HMLR title numbers are typically 2-3 letters + 5-7 digits."""
    return bool(re.match(r'^[A-Z]{2,3}\d{5,7}$', q.upper().replace(' ', '')))


# -----------------------------------------------------------------------------
# Helper: get the Neo4j driver from app state (set by main app on startup)
# -----------------------------------------------------------------------------

def get_driver(request: Request):
    """Read the Neo4j driver from the FastAPI app state."""
    if not hasattr(request.app.state, "neo4j_driver"):
        raise HTTPException(503, "Database connection not initialised")
    return request.app.state.neo4j_driver


# -----------------------------------------------------------------------------
# Autocomplete — JSON, fast, no auth required (deliberately generous)
# -----------------------------------------------------------------------------

@router.get("/api/search/autocomplete")
async def autocomplete(request: Request, q: str = Query(..., min_length=2, max_length=80)):
    """Autocomplete suggestions, top 3 of each type. Open to all visitors."""
    q = q.strip()
    if len(q) < 2:
        return {"groups": []}

    q_normalised = normalise_name(q)
    q_postcode = normalise_postcode(q)
    q_upper = q.upper().replace(' ', '')

    params = {
        "q_normalised": q_normalised,
        "q_postcode": q_postcode,
        "q_upper": q_upper,
    }

    driver = get_driver(request)
    try:
        with driver.session() as session:
            companies = session.run(CYPHER_AUTOCOMPLETE_COMPANIES, **params).data()
            persons = session.run(CYPHER_AUTOCOMPLETE_PERSONS, **params).data()
            addresses = session.run(CYPHER_AUTOCOMPLETE_ADDRESSES, **params).data() if is_postcode_like(q) else []
            titles = session.run(CYPHER_AUTOCOMPLETE_TITLES, **params).data() if is_title_number_like(q) or is_postcode_like(q) else []
    except Exception as e:
        # Don't surface internals; return empty results on infra issues.
        return JSONResponse({"groups": [], "error": "search_unavailable"}, status_code=503)

    groups = []
    if companies:
        groups.append({
            "type": "company",
            "label": "Companies",
            "results": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "status": r["status"],
                    "title_count": r["title_count"],
                    "url": f"/dashboard/ownership/estate/{r['id']}",
                }
                for r in companies
            ],
        })
    if persons:
        groups.append({
            "type": "person",
            "label": "Persons",
            "results": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "country": r["country"],
                    "dob_year": r["dob_year"],
                    "controlled_count": r["controlled_count"],
                    "url": f"/dashboard/ownership/person/{r['id']}",
                }
                for r in persons
            ],
        })
    if addresses:
        groups.append({
            "type": "address",
            "label": "Addresses",
            "results": [
                {
                    "id": r["id"],
                    "premises": r["premises"],
                    "postcode": r["postcode"],
                    "town": r["town"],
                    "reg_count": r["reg_count"],
                    "url": f"/dashboard/ownership/address/{r['id']}",
                }
                for r in addresses
            ],
        })
    if titles:
        groups.append({
            "type": "title",
            "label": "Titles",
            "results": [
                {
                    "id": r["id"],
                    "address": r["address"],
                    "postcode": r["postcode"],
                    "tenure": r["tenure"],
                    "source": r["source"],
                    "url": f"/dashboard/ownership/title/{r['id']}",
                }
                for r in titles
            ],
        })

    return {"q": q, "groups": groups}


# -----------------------------------------------------------------------------
# Full results JSON
# -----------------------------------------------------------------------------

@router.get("/api/search/results")
async def search_results_json(
    request: Request,
    q: str = Query(..., min_length=2, max_length=80),
    type: str = Query("all"),
    page: int = Query(1, ge=1, le=100),
    per_page: int = Query(25, ge=5, le=100),
):
    """Full search results, paginated, optionally filtered by type."""
    q = q.strip()
    q_normalised = normalise_name(q)
    q_postcode = normalise_postcode(q)
    q_upper = q.upper().replace(' ', '')
    skip = (page - 1) * per_page

    params = {
        "q_normalised": q_normalised,
        "q_postcode": q_postcode,
        "q_upper": q_upper,
        "skip": skip,
        "limit": per_page,
    }

    driver = get_driver(request)
    with driver.session() as session:
        counts = session.run(CYPHER_RESULT_COUNTS, **params).single()

        results = {}
        if type in ("all", "company"):
            results["companies"] = session.run(CYPHER_RESULTS_COMPANIES, **params).data()
        if type in ("all", "person"):
            results["persons"] = session.run(CYPHER_RESULTS_PERSONS, **params).data()
        # Address and title results: rely on autocomplete-style queries scaled up
        # (full results pagination not necessary for tonight's MVP)

    return {
        "q": q,
        "type": type,
        "page": page,
        "per_page": per_page,
        "counts": {
            "companies": counts["company_count"],
            "persons": counts["person_count"],
            "addresses": counts["address_count"],
            "titles": counts["title_count"],
        },
        "results": results,
    }


# -----------------------------------------------------------------------------
# Search results HTML page
# -----------------------------------------------------------------------------

# Rendered separately by the main app to keep templating central.
# This module exposes raw data; main app picks the template.
