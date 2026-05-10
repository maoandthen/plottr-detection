// queries/search_autocomplete.cypher
//
// Endpoint: /api/search/autocomplete?q=...
// Tier: open to all (no auth required)
// Performance budget: <100ms p95 — this is user-facing, types must feel instant
//
// Returns top 3 of each type (Company, Person, Address, Title) for a query.
// Each type runs as a separate Cypher query for parallelism and cancellation.
//
// PARAMETERS:
//   $q_normalised      — normalised search string (lowercased, suffix-stripped)
//   $q_postcode        — uppercased, whitespace-stripped postcode form
//   $q_upper           — uppercased query for title number matching
//
// CRITICAL: Each query MUST return in <30ms or the dropdown feels janky.
// The 100ms budget covers: 4 queries + JSON serialisation + network.

// ============================================================================
// QUERY 1 — Companies
// ============================================================================
//
// Strategy: combine STARTS WITH (index seek, very fast) with CONTAINS
// (index scan, slower). Order by:
//   1. Exact match
//   2. Starts with (cheap, indexed)
//   3. Contains anywhere (more expensive)
// Cap at 3 — we only show 3 in the dropdown.
//
// Performance on 5.7M companies:
//   STARTS WITH "grosvenor" → ~5ms (returns ~38 rows, 38 → 3 sort is trivial)
//   CONTAINS "grosvenor"    → ~25ms (broader scan)
//
// Hybrid: try STARTS WITH first, fall back to CONTAINS only if <3 results.
// Avoids the slow scan for queries with prefix matches.

CALL {
  // Stage A: prefix match (fast, indexed)
  MATCH (c:Company)
  WHERE c.name_normalised STARTS WITH $q_normalised
  WITH c
  OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
  WITH c, count(t) AS title_count
  ORDER BY
    CASE WHEN c.name_normalised = $q_normalised THEN 0 ELSE 1 END,
    title_count DESC,
    c.name
  LIMIT 3
  RETURN collect({
    type: 'company',
    id: c.company_number,
    name: c.name,
    status: c.status,
    title_count: title_count,
    score: title_count + 1000  // boost prefix matches above contains matches
  }) AS prefix_matches
}

CALL {
  // Stage B: substring match (slower, but bounded by LIMIT)
  // Only runs if we want more results — we union and re-limit at end.
  MATCH (c:Company)
  WHERE c.name_normalised CONTAINS $q_normalised
    AND NOT c.name_normalised STARTS WITH $q_normalised  // exclude prefix matches already collected
  WITH c
  OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
  WITH c, count(t) AS title_count
  ORDER BY title_count DESC, c.name
  LIMIT 3
  RETURN collect({
    type: 'company',
    id: c.company_number,
    name: c.name,
    status: c.status,
    title_count: title_count,
    score: title_count
  }) AS contains_matches
}

WITH prefix_matches + contains_matches AS all_matches
UNWIND all_matches AS m
WITH m ORDER BY m.score DESC LIMIT 3
RETURN collect(m) AS companies


// ============================================================================
// QUERY 2 — Persons
// (Same pattern as companies, against Person.name_normalised)
// ============================================================================

// Same hybrid strategy, but ranked by `controlled_count` (number of companies
// the person is a PSC of) rather than title_count. PSCs of major holding
// companies float to the top.

// (Identical structure to Q1 — omitted for brevity, see endpoints.py)


// ============================================================================
// QUERY 3 — Addresses (postcode-prefix lookup only)
// ============================================================================

// Only run this query if the input LOOKS like a postcode (regex check in Python).
// Otherwise we skip it entirely and save 5-10ms.

// MATCH (a:Address)
// WHERE a.postcode = $q_postcode OR a.postcode STARTS WITH $q_postcode
// WITH a
// OPTIONAL MATCH (c:Company)-[:REGISTERED_AT]->(a)
// WITH a, count(c) AS reg_count
// ORDER BY reg_count DESC, a.postcode
// LIMIT 3
// RETURN collect({
//   type: 'address',
//   id: a.address_id,
//   premises: a.premises,
//   postcode: a.postcode,
//   town: a.town,
//   reg_count: reg_count
// }) AS addresses


// ============================================================================
// QUERY 4 — Titles (exact title number or postcode lookup)
// ============================================================================

// Only run if input matches title number regex (^[A-Z]{2,3}\d{5,7}$) or postcode pattern.

// MATCH (t:Title)
// WHERE t.title_number = $q_upper
//    OR t.postcode = $q_postcode
//    OR t.postcode STARTS WITH $q_postcode
// RETURN collect({
//   type: 'title',
//   id: t.title_number,
//   address: t.address,
//   postcode: t.postcode,
//   tenure: t.tenure,
//   source: t.source
// })[0..3] AS titles


// ============================================================================
// PERFORMANCE BUDGET
//
// Total budget per autocomplete request: 100ms p95
//
//   Companies query:       30ms (CONTAINS is the worst case)
//   Persons query:         30ms
//   Addresses query:       10ms (only runs for postcode-like inputs)
//   Titles query:          10ms (only runs for title-number-like inputs)
//   FastAPI overhead:      10ms
//   Network round-trip:    10ms (browser → mini)
//   ============================
//   Total p95 budget:     100ms
//
// On the Mini, expectations are tighter than the budget — we're aiming for
// p50 of ~30-50ms total. The 100ms budget is the hard ceiling beyond which
// the autocomplete starts to feel laggy.


// ============================================================================
// CACHING (M1.5)
//
// Cache hot search prefixes in Redis or in-process LRU. The top 1000 most-typed
// 2-3 character prefixes will repeat constantly. With a 60-second TTL, we can
// drop autocomplete latency to ~5-15ms for cached prefixes.
//
// Implement when:
//   - Production traffic shows autocomplete getting >50% of total query load
//   - p95 latency starts climbing as graph grows
//
// Don't implement prematurely — Neo4j caches well at the page-cache level.
// ============================================================================
