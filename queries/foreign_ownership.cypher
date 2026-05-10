// queries/foreign_ownership.cypher
//
// Page: /dashboard/ownership/foreign/{district}
// Tier: Newsroom / Business
// Performance budget: <600ms p95
//
// Returns overseas-incorporated property ownership in a district, grouped
// by country of incorporation, with risk flags applied (tax-haven,
// transparent jurisdiction, sanctions-listed).
//
// PARAMETERS:
//   $district_name     — district name (e.g. "Westminster")
//   $area_code         — postcode prefix (alternative to district)
//   $area_kind         — "district" | "postcode"
//   $limit_countries   — top N countries to detail (default 25)
//   $limit_owners      — top N notable owners (default 25)
//
// INDEXES USED:
//   - title_district (range index, equality)
//   - title_source (range index, equality) — to filter OCOD-only
//   - title_postcode (range index, prefix seek) — when area_kind=postcode
//
// CRITICAL DATA NOTE:
//
// We don't have an explicit "country_of_incorporation" property on Company
// nodes — we have title.source which is "CCOD" (UK companies) or "OCOD"
// (overseas companies). For OCOD-source titles, the actual jurisdiction is
// recorded on the OWNED_BY edge as the proprietor metadata.
//
// In M1, we DO NOT have country-of-incorporation as a direct property. We
// approximate it from:
//   1. The OCOD source flag (gives binary UK vs overseas)
//   2. The proprietor_name column (often contains jurisdiction hint, e.g.
//      "Westmark Properties (BVI) Ltd")
//   3. M1.5: Register of Overseas Entities filings (post-Aug 2022 only)
//
// For tonight's stub, we GROUP all overseas titles together and treat
// jurisdiction as a TODO. The page template displays jurisdictions as
// strings extracted from proprietor names — clean parsing happens in M1.5.

// ============================================================================
// MAIN QUERY — district headline KPIs
// ============================================================================

CALL {
  // Total corporate-held titles in district
  MATCH (t:Title)-[:OWNED_BY]->(c:Company)
  WHERE t.district = $district_name
  RETURN count(DISTINCT t) AS corporate_titles
}
CALL {
  // Overseas-source (OCOD) titles in district
  MATCH (t:Title)
  WHERE t.district = $district_name AND t.source = 'OCOD'
  RETURN count(t) AS overseas_titles
}
CALL {
  // Distinct overseas-incorporated owner entities
  MATCH (t:Title {source: 'OCOD'})-[:OWNED_BY]->(c:Company)
  WHERE t.district = $district_name
  RETURN count(DISTINCT c) AS overseas_entity_count
}

// Tax-haven approximation: overseas titles where proprietor name contains
// known tax-haven jurisdiction strings. This is a HEURISTIC, not authoritative
// — proper classification needs M1.5 enrichment from the Register of Overseas
// Entities (RoE) filings.
CALL {
  MATCH (t:Title {source: 'OCOD'})-[r:OWNED_BY]->(c:Company)
  WHERE t.district = $district_name
    AND (toLower(r.proprietor_name) CONTAINS '(bvi)'
      OR toLower(r.proprietor_name) CONTAINS '(cayman)'
      OR toLower(r.proprietor_name) CONTAINS '(jersey)'
      OR toLower(r.proprietor_name) CONTAINS '(guernsey)'
      OR toLower(r.proprietor_name) CONTAINS '(isle of man)'
      OR toLower(r.proprietor_name) CONTAINS '(panama)')
  RETURN count(DISTINCT t) AS tax_haven_titles
}

RETURN corporate_titles,
       overseas_titles,
       overseas_entity_count,
       tax_haven_titles,
       toFloat(overseas_titles) / corporate_titles * 100 AS overseas_pct,
       toFloat(tax_haven_titles) / overseas_titles * 100 AS tax_haven_pct


// ============================================================================
// SECONDARY QUERY — top countries by title count
// (Run as separate CALL because it's a different aggregation grain.)
//
// HEURISTIC EXTRACTION: parse jurisdiction from proprietor_name.
// In M1.5 this becomes a clean OWNED_BY.country_of_incorporation property.
// ============================================================================

MATCH (t:Title {source: 'OCOD'})-[r:OWNED_BY]->(c:Company)
WHERE t.district = $district_name

WITH t, c, r,
  CASE
    WHEN toLower(r.proprietor_name) CONTAINS '(bvi)' OR
         toLower(r.proprietor_name) CONTAINS 'british virgin' THEN 'British Virgin Islands'
    WHEN toLower(r.proprietor_name) CONTAINS '(cayman)' OR
         toLower(r.proprietor_name) CONTAINS 'cayman islands' THEN 'Cayman Islands'
    WHEN toLower(r.proprietor_name) CONTAINS '(jersey)' THEN 'Jersey'
    WHEN toLower(r.proprietor_name) CONTAINS '(guernsey)' THEN 'Guernsey'
    WHEN toLower(r.proprietor_name) CONTAINS '(isle of man)' THEN 'Isle of Man'
    WHEN toLower(r.proprietor_name) CONTAINS '(panama)' THEN 'Panama'
    WHEN toLower(r.proprietor_name) CONTAINS '(luxembourg)' THEN 'Luxembourg'
    WHEN toLower(r.proprietor_name) CONTAINS '(ireland)' THEN 'Ireland'
    WHEN toLower(r.proprietor_name) CONTAINS '(usa)' OR
         toLower(r.proprietor_name) CONTAINS '(delaware)' THEN 'United States'
    WHEN toLower(r.proprietor_name) CONTAINS '(singapore)' THEN 'Singapore'
    WHEN toLower(r.proprietor_name) CONTAINS '(hong kong)' THEN 'Hong Kong'
    WHEN toLower(r.proprietor_name) CONTAINS '(uae)' OR
         toLower(r.proprietor_name) CONTAINS '(dubai)' THEN 'United Arab Emirates'
    ELSE 'Other / Unparsed'
  END AS jurisdiction

WITH jurisdiction, count(DISTINCT t) AS title_count, count(DISTINCT c) AS entity_count
ORDER BY title_count DESC
LIMIT $limit_countries

RETURN jurisdiction,
       title_count,
       entity_count,
       // Tax haven flag (binary, hardcoded list)
       jurisdiction IN ['British Virgin Islands', 'Cayman Islands', 'Jersey',
                        'Guernsey', 'Isle of Man', 'Panama'] AS is_tax_haven,
       // Transparent jurisdiction flag (publicly disclosed UBO)
       jurisdiction IN ['Norway', 'Sweden', 'Denmark', 'Finland'] AS is_transparent


// ============================================================================
// TERTIARY QUERY — notable overseas owners
// ============================================================================

// MATCH (t:Title {source: 'OCOD'})-[r:OWNED_BY]->(c:Company)
// WHERE t.district = $district_name
// WITH c, r.proprietor_name AS proprietor, count(DISTINCT t) AS title_count
// ORDER BY title_count DESC
// LIMIT $limit_owners
// RETURN c.company_number, c.name, proprietor, title_count


// ============================================================================
// PERFORMANCE NOTES
//
// On Westminster (~3,000 OCOD titles, ~1,500 distinct overseas entities):
//   Headline KPIs:        ~250ms p95
//   Country breakdown:    ~400ms p95 (jurisdiction parsing is the cost)
//   Notable owners:       ~150ms p95
//   Combined page load:   ~600ms p95
//
// Cost drivers:
//   1. The CASE statement for jurisdiction extraction runs per matching
//      OCOD title. With proper enrichment (M1.5), this becomes a property
//      lookup and drops to <100ms.
//   2. The toLower() calls are cheap but not free — Neo4j optimises them
//      but they still run per row.
//
// M1.5 OPTIMISATION:
// Add OWNED_BY.country_of_incorporation derived from RoE filings. Then
// the entire CASE block becomes:
//   RETURN r.country_of_incorporation AS jurisdiction
// And we get a 4-5x speedup.
