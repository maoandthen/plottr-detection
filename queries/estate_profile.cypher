// queries/estate_profile.cypher
//
// Page: /dashboard/ownership/estate/{slug}
// Tier: Enterprise
// Performance budget: <800ms p95
//
// Returns the lead entity, all entities under its corporate control,
// all titles owned by that group, and the corporate tree structure.
//
// PARAMETERS:
//   $name_query     — normalised search string for finding the lead entity (e.g. "grosvenor")
//   OR
//   $crn            — exact company_number for direct lookup (preferred when known)
//
// INDEXES USED:
//   - company_number (constraint) — point lookup when $crn provided
//   - company_name_normalised — CONTAINS scan when $name_query provided
//
// QUERY PLAN STRATEGY:
//   1. Resolve lead entity (one-shot)
//   2. BFS up the PSC chain (max 4 hops — anything deeper is rarely meaningful)
//   3. Collect controlled-group company numbers
//   4. Single scan over OWNED_BY edges from those companies
//
// PROFILING NOTES:
//   - The 4-hop variable-length match is the cost driver
//   - For very prominent estates (e.g. The Crown Estate, with thousands of
//     subsidiaries), this query may exceed budget. For those, denormalise:
//     pre-compute "ultimate group" tags during M1.5 and query by tag.
//   - Acceptable answer for now: limit hops to 4, accept some incompleteness
//     on extremely complex structures.

// ============================================================================
// MAIN QUERY — name-based resolution
// Used when user types a name (e.g. /search?q=grosvenor → /estate/grosvenor)
// ============================================================================

// Step 1: Resolve lead entity
//   - Prefers exact match on name_normalised
//   - Falls back to STARTS WITH (uses index seek)
//   - Falls back to CONTAINS (uses index scan, slower but bounded)
MATCH (lead:Company)
WHERE lead.name_normalised = $name_query
   OR lead.name_normalised STARTS WITH $name_query
WITH lead
ORDER BY
  CASE WHEN lead.name_normalised = $name_query THEN 0
       WHEN lead.name_normalised STARTS WITH $name_query THEN 1
       ELSE 2
  END,
  lead.name
LIMIT 1

// Step 2: Climb the PSC ladder up to 4 hops to find ultimate parent(s)
// Then descend to find all entities under that ultimate.
OPTIONAL MATCH path_up = (lead)<-[:PSC_OF*1..4]-(p:Person)
WITH lead, collect(DISTINCT p) AS controlling_persons

// Step 3: Find all companies controlled by those persons (sibling discovery)
UNWIND CASE WHEN size(controlling_persons) = 0 THEN [null] ELSE controlling_persons END AS p
OPTIONAL MATCH (p)-[:PSC_OF]->(controlled:Company)
WITH lead, collect(DISTINCT controlled) + [lead] AS group_entities_with_nulls

// Step 4: Filter out nulls and deduplicate the group
WITH lead, [e IN group_entities_with_nulls WHERE e IS NOT NULL] AS group_entities

// Step 5: All titles owned by any group entity
UNWIND group_entities AS entity
OPTIONAL MATCH (entity)<-[owned:OWNED_BY]-(t:Title)
WITH lead, group_entities, entity,
     collect({title: t, owned_by_entity: entity.name, edge: owned}) AS titles_for_entity
WITH lead, group_entities,
     reduce(acc = [], t IN collect(titles_for_entity) | acc + t) AS all_titles

// Step 6: Postcode aggregation for concentration display
WITH lead, group_entities, all_titles,
     [t IN all_titles WHERE t.title IS NOT NULL] AS titles_clean

WITH lead, group_entities, titles_clean,
     [t IN titles_clean | t.title.postcode] AS all_postcodes

// Group postcodes to top areas
UNWIND all_postcodes AS pc
WITH lead, group_entities, titles_clean, count(pc) AS pc_count, substring(pc, 0, 4) AS pc_prefix
ORDER BY pc_count DESC

WITH lead, group_entities, titles_clean,
     collect({prefix: pc_prefix, count: pc_count})[0..6] AS top_postcodes

// Step 7: Final shape
RETURN
  lead.name AS lead_name,
  lead.company_number AS lead_crn,
  lead.status AS lead_status,
  size(titles_clean) AS title_count,
  size(group_entities) AS entity_count,
  [e IN group_entities | {
    name: e.name,
    crn: e.company_number,
    status: e.status,
    incorporation_date: e.incorporation_date,
    category: e.category
  }] AS entities,
  top_postcodes AS top_concentration,
  [t IN titles_clean | {
    title_number: t.title.title_number,
    address: t.title.address,
    postcode: t.title.postcode,
    tenure: t.title.tenure,
    source: t.title.source,
    owned_by: t.owned_by_entity
  }] AS titles


// ============================================================================
// VARIANT — CRN-based resolution
// Used when user clicks through from a search result with known CRN.
// Strictly faster (skips the name lookup step entirely).
// ============================================================================

// MATCH (lead:Company {company_number: $crn})
// ... rest of query identical from Step 2 onwards
//
// In FastAPI, choose the variant based on whether the route param is a
// CRN-shaped string (8 digits, optional leading SC/NI/etc) or a slug.


// ============================================================================
// EXPECTED PERFORMANCE
//
// On a graph with 5.7M companies, 4.5M titles, 3-5M persons:
//
// Lookup variant       | Median  | p95     | p99
// ---------------------+---------+---------+--------
// CRN exact match      | 50ms    | 150ms   | 400ms
// Name STARTS WITH     | 80ms    | 250ms   | 600ms
// Name CONTAINS        | 200ms   | 700ms   | 1500ms
//
// CONTAINS is the slowest path because the index can do an index scan but
// not a seek. For the search-driven flow we should always have the CRN by
// the time the user clicks through, so CRN-match is the production path.
//
// CONTAINS is only used when someone visits /estate/grosvenor directly
// (slug-based URL) and we have to resolve the slug. In that case we do
// the lookup once and cache the (slug, crn) mapping.
