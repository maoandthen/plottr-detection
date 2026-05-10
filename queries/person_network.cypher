// ── PERSON NETWORK QUERIES ──────────────────────────────────────────────────
// Surfaces individuals who appear as PSC across many companies,
// family office structures (surname clustering), and network hubs.
//
// Indexes required: person_name_normalised, company_name_normalised
// All queries are parameterised — pass $min_companies to tune sensitivity.
// ────────────────────────────────────────────────────────────────────────────


// ── 1. TOP NETWORK HUBS ─────────────────────────────────────────────────────
// Persons controlling the most companies. The raw leaderboard.
// p95 budget: 200ms  |  index: person_name_normalised

MATCH (p:Person)-[r:PSC_OF]->(c:Company)
WITH p,
     count(DISTINCT c) AS controlled_companies,
     collect(DISTINCT c.name)[0..10] AS sample_companies,
     collect(DISTINCT r.nature_of_control)[0..5] AS control_types
WHERE controlled_companies >= $min_companies   // default: 3
RETURN
  p.person_id                AS person_id,
  p.name                     AS name,
  p.name_normalised          AS name_normalised,
  p.dob_year                 AS dob_year,
  p.nationality              AS nationality,
  p.country_of_residence     AS country_of_residence,
  controlled_companies,
  sample_companies,
  control_types
ORDER BY controlled_companies DESC
LIMIT 100;


// ── 2. FAMILY OFFICE SURNAME CLUSTERS ───────────────────────────────────────
// Groups persons by normalised surname. Where 2+ persons share a surname
// and collectively control 3+ companies, flags as a likely family structure.
// This surfaces Grosvenors, Cadogans, etc. without knowing the names upfront.

MATCH (p:Person)-[:PSC_OF]->(c:Company)
WITH
  // Extract surname as last word of normalised name
  toLower(trim(last(split(p.name_normalised, ' ')))) AS surname,
  collect(DISTINCT {
    person_id: p.person_id,
    name: p.name,
    dob_year: p.dob_year,
    nationality: p.nationality
  }) AS persons,
  collect(DISTINCT c.company_number) AS company_numbers,
  collect(DISTINCT c.name)[0..8]     AS sample_companies
WHERE size(persons) >= 2
  AND size(company_numbers) >= $min_companies   // default: 3
  AND size(surname) >= 3                        // filter noise
RETURN
  surname,
  size(persons)          AS family_members,
  size(company_numbers)  AS companies_controlled,
  persons,
  sample_companies
ORDER BY companies_controlled DESC
LIMIT 100;


// ── 3. FAMILY OFFICE WITH TITLE HOLDINGS ───────────────────────────────────
// Extends query 2 to include property titles held by the cluster's companies.
// Heavier query — use for deep-dive on a specific surname, not for bulk scan.
// p95 budget: 800ms  |  pass $surname as parameter

MATCH (p:Person)-[:PSC_OF]->(c:Company)<-[:OWNED_BY]-(t:Title)
WHERE toLower(trim(last(split(p.name_normalised, ' ')))) = $surname
WITH
  p, c, t,
  t.postcode  AS postcode,
  t.district  AS district
RETURN
  p.name                            AS person,
  p.dob_year                        AS dob_year,
  c.name                            AS company,
  c.company_number                  AS crn,
  count(DISTINCT t)                 AS titles_held,
  collect(DISTINCT postcode)[0..5]  AS postcodes,
  collect(DISTINCT district)[0..3]  AS districts
ORDER BY titles_held DESC;


// ── 4. PERSON FULL PROFILE ──────────────────────────────────────────────────
// All companies a named person controls, plus titles those companies hold.
// Used for the person detail page. CRN-equivalent path for persons.
// p95 budget: 400ms

MATCH (p:Person {person_id: $person_id})-[psc:PSC_OF]->(c:Company)
OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
OPTIONAL MATCH (c)-[:REGISTERED_AT]->(a:Address)
WITH p, c, psc,
     count(DISTINCT t)           AS titles,
     collect(DISTINCT t.postcode)[0..5] AS postcodes,
     a.full_address              AS registered_address
RETURN
  p.name                    AS person_name,
  p.dob_year                AS dob_year,
  p.nationality             AS nationality,
  p.country_of_residence    AS country_of_residence,
  c.company_number          AS crn,
  c.name                    AS company_name,
  c.status                  AS company_status,
  c.incorporation_date      AS incorporated,
  psc.nature_of_control     AS nature_of_control,
  psc.notified_on           AS psc_since,
  titles,
  postcodes,
  registered_address
ORDER BY titles DESC;


// ── 5. SHARED PERSONS BETWEEN ESTATES ──────────────────────────────────────
// Finds persons who are PSC of companies in two different named estates.
// Surface hidden connections between ostensibly separate landowners.
// p95 budget: 600ms

MATCH (p:Person)-[:PSC_OF]->(c1:Company)<-[:OWNED_BY]-(t1:Title)
MATCH (p)-[:PSC_OF]->(c2:Company)<-[:OWNED_BY]-(t2:Title)
WHERE c1 <> c2
  AND toLower(c1.name_normalised) CONTAINS $estate_a
  AND toLower(c2.name_normalised) CONTAINS $estate_b
RETURN DISTINCT
  p.name             AS shared_person,
  p.dob_year         AS dob_year,
  c1.name            AS company_in_estate_a,
  c2.name            AS company_in_estate_b;
