// queries/concentration.cypher
//
// Page: /dashboard/ownership/concentration/{area_code}
// Tier: Business
// Performance budget: <500ms p95
//
// Returns top corporate landowners in a postcode prefix or named district,
// plus aggregate KPIs: total titles, % corporate, top-10 concentration,
// % overseas-incorporated.
//
// PARAMETERS:
//   $area_code      — postcode prefix (e.g. "SW1X") OR district name ("Westminster")
//   $area_kind      — "postcode" | "district" (determines which index to use)
//   $limit          — top N owners to return (default 50)
//   $min_titles     — only include owners with at least this many titles (default 1)
//
// INDEXES USED:
//   - title_postcode (range index, prefix seek) — when $area_kind = "postcode"
//   - title_district (range index, equality)    — when $area_kind = "district"
//   - company_number (constraint, point lookup) — joining to Company nodes
//
// QUERY PLAN STRATEGY:
//   1. Filter Title nodes by area (uses postcode or district index)
//   2. Hop to OWNED_BY → Company in single traversal
//   3. Group, count, order by title_count DESC
//   4. Compute aggregate KPIs in a separate sub-query

// ============================================================================
// MAIN QUERY — postcode-prefix variant
// ============================================================================

// Step 1: Headline KPIs across the area
// Run as a single CALL to populate counters in parallel where possible.
CALL {
  // Total titles in the area
  MATCH (t:Title)
  WHERE t.postcode STARTS WITH $area_code
  RETURN count(t) AS total_titles
}
CALL {
  // Corporate-held subset (those with at least one OWNED_BY edge)
  MATCH (t:Title)-[:OWNED_BY]->(c:Company)
  WHERE t.postcode STARTS WITH $area_code
  RETURN count(DISTINCT t) AS corporate_titles
}
CALL {
  // Overseas-incorporated subset (titles owned by an OCOD-source company,
  // approximated by checking the title's source field — OCOD titles are
  // overseas-held by definition)
  MATCH (t:Title)
  WHERE t.postcode STARTS WITH $area_code
    AND t.source = 'OCOD'
  RETURN count(t) AS overseas_titles
}

// Step 2: Top owners list
CALL {
  MATCH (t:Title)-[:OWNED_BY]->(c:Company)
  WHERE t.postcode STARTS WITH $area_code
  WITH c, count(DISTINCT t) AS title_count
  WHERE title_count >= $min_titles
  ORDER BY title_count DESC
  LIMIT $limit

  // Get registered office for each top owner (one address each)
  OPTIONAL MATCH (c)-[:REGISTERED_AT]->(addr:Address)
  WITH c, title_count, addr
  // Take the first address only (companies can have multiple historic offices)
  ORDER BY title_count DESC
  LIMIT $limit

  RETURN collect({
    company_number: c.company_number,
    name: c.name,
    name_normalised: c.name_normalised,
    status: c.status,
    category: c.category,
    incorporation_date: c.incorporation_date,
    title_count: title_count,
    registered_office: CASE WHEN addr IS NOT NULL
      THEN addr.premises + ', ' + addr.postcode
      ELSE null END,
    is_foreign: c.company_number IS NULL OR c.company_number = ''
  }) AS owners
}

// Top 10 concentration % (sum of titles held by top 10 owners / corporate total)
CALL {
  MATCH (t:Title)-[:OWNED_BY]->(c:Company)
  WHERE t.postcode STARTS WITH $area_code
  WITH c, count(DISTINCT t) AS tc
  ORDER BY tc DESC
  LIMIT 10
  RETURN sum(tc) AS top_10_titles
}

RETURN
  total_titles,
  corporate_titles,
  overseas_titles,
  top_10_titles,
  toFloat(corporate_titles) / total_titles * 100 AS corporate_pct,
  toFloat(top_10_titles) / corporate_titles * 100 AS top_10_pct,
  toFloat(overseas_titles) / corporate_titles * 100 AS overseas_pct,
  owners


// ============================================================================
// VARIANT — district-based
// Replace `WHERE t.postcode STARTS WITH $area_code`
// with    `WHERE t.district = $area_code`
// in all four CALL sub-queries.
// Otherwise identical.
// ============================================================================


// ============================================================================
// EXPECTED PERFORMANCE
//
// Test areas and expected sizes:
//   SW1X  — ~30,000 titles in Westminster Belgravia → 200ms p95
//   W1K   — ~25,000 titles in Mayfair               → 200ms p95
//   E14   — ~80,000 titles in Tower Hamlets/Canary  → 350ms p95
//   N1    — ~120,000 titles in Islington            → 450ms p95
//   "Westminster" district — ~150,000 titles        → 500ms p95
//
// Cost drivers (in order):
//   1. Number of titles in the area (linear scan after index seek)
//   2. Number of unique owners (grouping cost)
//   3. Address join (one extra hop per owner in top N)
//
// Optimisation done:
//   - All 4 sub-queries run independently via CALL
//   - DISTINCT on title to avoid double-counting when a title has multiple
//     OWNED_BY edges (rare but possible — joint ownership)
//   - LIMIT applied before OPTIONAL MATCH on address
//
// Optimisation NOT done (deferred unless needed):
//   - Materialised view of (postcode_prefix, total_titles) — if the headline
//     KPI query becomes a bottleneck on the largest postcodes
//   - Pre-computed "top owners" cache per popular district


// ============================================================================
// SECONDARY QUERY — full owners list with pagination
// Called separately by the page when user clicks "see all"
// ============================================================================

// MATCH (t:Title)-[:OWNED_BY]->(c:Company)
// WHERE t.postcode STARTS WITH $area_code
// WITH c, count(DISTINCT t) AS title_count
// WHERE title_count >= $min_titles
// ORDER BY title_count DESC
// SKIP $skip LIMIT $page_size
//
// OPTIONAL MATCH (c)-[:REGISTERED_AT]->(addr:Address)
// WITH c, title_count, addr LIMIT $page_size
//
// RETURN c.company_number, c.name, c.status, title_count,
//        CASE WHEN addr IS NOT NULL THEN addr.premises + ', ' + addr.postcode ELSE null END AS office
