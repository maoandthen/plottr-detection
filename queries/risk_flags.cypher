// ── RISK FLAG QUERIES ────────────────────────────────────────────────────────
// Automated detection of structural red flags in the ownership graph.
// Flags are additive — an entity can carry multiple flags.
//
// Flag taxonomy:
//   NOMINEE_ADDRESS    — registered address shared by 50+ companies
//   NO_UBO             — overseas title with no PSC person traceable
//   LAYERED_STRUCTURE  — PSC chain is corporate, not individual
//   HIGH_TURNOVER      — title transferred frequently (needs delta data)
//   DORMANT_HOLDER     — dissolved/inactive company still holding titles
//   CONCENTRATION_HUB  — company holds titles in 5+ distinct districts
// ────────────────────────────────────────────────────────────────────────────


// ── 1. NOMINEE ADDRESS DETECTION ────────────────────────────────────────────
// Registered addresses shared by an unusually large number of companies.
// Classic signal for nominee director services and shell company factories.
// Flag threshold: 50 companies. Serious concern: 200+.

MATCH (c:Company)-[:REGISTERED_AT]->(a:Address)
WITH a,
     count(DISTINCT c)           AS company_count,
     collect(DISTINCT c.name)[0..8] AS sample_companies
WHERE company_count >= 50
RETURN
  a.address_id            AS address_id,
  a.full_address          AS address,
  a.postcode              AS postcode,
  company_count,
  sample_companies,
  CASE
    WHEN company_count >= 500 THEN 'CRITICAL'
    WHEN company_count >= 200 THEN 'HIGH'
    WHEN company_count >= 50  THEN 'MEDIUM'
  END AS risk_level
ORDER BY company_count DESC
LIMIT 200;


// ── 2. OVERSEAS TITLES WITH NO TRACEABLE UBO ────────────────────────────────
// OCOD titles where no PSC person can be found in the graph.
// These are the "undisclosed" holdings flagged in the foreign ownership page.
// Note: absence of PSC may mean pre-Aug-2022 filing, not necessarily evasion.

MATCH (t:Title {source: 'OCOD'})-[r:OWNED_BY]->(c:Company)
WHERE NOT EXISTS {
  MATCH (p:Person)-[:PSC_OF]->(c)
}
WITH c,
     count(DISTINCT t)              AS overseas_titles,
     collect(DISTINCT t.postcode)[0..5] AS postcodes,
     collect(DISTINCT t.district)[0..3] AS districts,
     r.country_incorporated_in      AS jurisdiction
RETURN
  c.company_number     AS crn,
  c.name               AS company_name,
  c.status             AS status,
  jurisdiction,
  overseas_titles,
  postcodes,
  districts,
  'NO_UBO'             AS flag
ORDER BY overseas_titles DESC
LIMIT 500;


// ── 3. DORMANT COMPANIES HOLDING TITLES ─────────────────────────────────────
// Dissolved or inactive companies that still appear as OWNED_BY on live titles.
// HMLR doesn't automatically update proprietor records on dissolution.

MATCH (t:Title)-[:OWNED_BY]->(c:Company)
WHERE c.status IN ['Dissolved', 'Liquidation', 'Administration',
                   'Receivership', 'Converted/Closed']
WITH c,
     count(DISTINCT t)                  AS titles_held,
     collect(DISTINCT t.title_number)[0..5] AS sample_titles,
     collect(DISTINCT t.postcode)[0..5]    AS postcodes
RETURN
  c.company_number      AS crn,
  c.name                AS company_name,
  c.status              AS status,
  c.dissolution_date    AS dissolution_date,
  titles_held,
  sample_titles,
  postcodes,
  'DORMANT_HOLDER'      AS flag
ORDER BY titles_held DESC
LIMIT 200;


// ── 4. CONCENTRATION HUBS ────────────────────────────────────────────────────
// Single companies owning titles spread across many districts.
// Can indicate portfolio landlords, institutional investors, or complex
// structures obscuring the true geographic reach of a single owner.

MATCH (t:Title)-[:OWNED_BY]->(c:Company)
WITH c,
     count(DISTINCT t)           AS total_titles,
     count(DISTINCT t.district)  AS district_count,
     collect(DISTINCT t.district)[0..8] AS districts,
     collect(DISTINCT t.postcode)[0..5] AS sample_postcodes
WHERE district_count >= 5
  AND total_titles >= 10
RETURN
  c.company_number      AS crn,
  c.name                AS company_name,
  c.status              AS status,
  total_titles,
  district_count,
  districts,
  sample_postcodes,
  'CONCENTRATION_HUB'   AS flag
ORDER BY district_count DESC, total_titles DESC
LIMIT 200;


// ── 5. COMBINED RISK SCORE PER COMPANY ──────────────────────────────────────
// Aggregate all flags for a single company lookup.
// Used on the estate profile page risk score widget.
// p95 budget: 400ms  |  pass $crn

MATCH (c:Company {company_number: $crn})

// Flag 1: nominee address
OPTIONAL MATCH (c)-[:REGISTERED_AT]->(a:Address)
WITH c, a
OPTIONAL MATCH (a)<-[:REGISTERED_AT]-(peer:Company)
WITH c, a, count(DISTINCT peer) AS address_peers

// Flag 2: overseas titles without UBO
OPTIONAL MATCH (t_o:Title {source: 'OCOD'})-[:OWNED_BY]->(c)
WITH c, address_peers, count(DISTINCT t_o) AS overseas_no_ubo_titles

// Flag 3: dormant status
WITH c, address_peers, overseas_no_ubo_titles,
     CASE WHEN c.status IN ['Dissolved','Liquidation','Administration',
                             'Receivership','Converted/Closed']
          THEN 1 ELSE 0 END AS is_dormant

// Flag 4: total titles for concentration check
OPTIONAL MATCH (t_all:Title)-[:OWNED_BY]->(c)
WITH c, address_peers, overseas_no_ubo_titles, is_dormant,
     count(DISTINCT t_all.district) AS district_count

// Compute risk score 0-10
WITH c, address_peers, overseas_no_ubo_titles, is_dormant, district_count,
     (
       CASE WHEN address_peers >= 200 THEN 3
            WHEN address_peers >= 50  THEN 1 ELSE 0 END
     + CASE WHEN overseas_no_ubo_titles >= 5 THEN 3
            WHEN overseas_no_ubo_titles >= 1 THEN 1 ELSE 0 END
     + is_dormant * 4
     + CASE WHEN district_count >= 10 THEN 1 ELSE 0 END
     ) AS raw_score

RETURN
  c.company_number          AS crn,
  c.name                    AS company_name,
  c.status                  AS status,
  address_peers             AS address_shared_with,
  overseas_no_ubo_titles    AS overseas_undisclosed_titles,
  is_dormant = 1            AS is_dormant,
  district_count            AS districts_present_in,
  CASE WHEN raw_score > 10 THEN 10 ELSE raw_score END AS risk_score,
  CASE
    WHEN raw_score >= 7 THEN 'HIGH'
    WHEN raw_score >= 4 THEN 'MEDIUM'
    WHEN raw_score >= 1 THEN 'LOW'
    ELSE 'CLEAN'
  END AS risk_level,
  [
    x IN [
      CASE WHEN address_peers >= 50    THEN 'NOMINEE_ADDRESS'    ELSE null END,
      CASE WHEN overseas_no_ubo_titles >= 1 THEN 'NO_UBO'        ELSE null END,
      CASE WHEN is_dormant = 1         THEN 'DORMANT_HOLDER'      ELSE null END,
      CASE WHEN district_count >= 10   THEN 'CONCENTRATION_HUB'  ELSE null END
    ] WHERE x IS NOT NULL
  ] AS active_flags;
