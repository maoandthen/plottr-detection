#!/usr/bin/env python3
"""
benchmark_queries.py — measure production query latency.

Runs each Plottr production Cypher query against the live Neo4j graph N times
and reports p50/p95/p99 latency. Writes a CSV report and prints a console table.

Run after M1 graph is loaded:
  PYTHONPATH=. python3 etl/benchmark_queries.py [--iterations N] [--query QUERY_NAME]

Output:
  - Console table with p50/p95/p99 per query
  - benchmark_results_<timestamp>.csv with raw timings
  - Verdict: each query against its budget (PASS / WARN / FAIL)

Performance budgets enforced:
  estate_profile (CRN lookup)        : p95 < 200ms
  estate_profile (name lookup)       : p95 < 800ms
  concentration (small postcode)     : p95 < 250ms
  concentration (large postcode)     : p95 < 500ms
  concentration (district)           : p95 < 600ms
  foreign_ownership (district)       : p95 < 600ms
  search_autocomplete (companies)    : p95 < 30ms
  search_autocomplete (persons)      : p95 < 30ms
  search_autocomplete (full request) : p95 < 100ms
"""

import argparse
import csv
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from neo4j import GraphDatabase


# -----------------------------------------------------------------------------
# Connection
# -----------------------------------------------------------------------------

def get_driver():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "plottr_secret")
    
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("NEO4J_URI=") and uri == "bolt://localhost:7687":
                uri = line.split("=", 1)[1].strip()
            elif line.startswith("NEO4J_PASSWORD=") and password == "plottr_secret":
                password = line.split("=", 1)[1].strip()
    
    uri = uri.replace("://neo4j:", "://localhost:")
    if uri.startswith("neo4j://"):
        uri = uri.replace("neo4j://", "bolt://", 1)
    
    return GraphDatabase.driver(uri, auth=(user, password))


# -----------------------------------------------------------------------------
# Benchmark cases
# -----------------------------------------------------------------------------

# Each benchmark is (name, query, params_fn, p95_budget_ms)
# params_fn returns the params dict; called fresh each iteration to avoid cache effects

BENCHMARKS = [
    # ------ Estate Profile ------
    {
        "name": "estate_profile.crn_lookup",
        "description": "Estate profile resolution by company_number (the production hot path)",
        "p95_budget_ms": 200,
        "query": """
            MATCH (lead:Company {company_number: $crn})
            OPTIONAL MATCH (lead)<-[:PSC_OF*1..2]-(p:Person)-[:PSC_OF]->(controlled:Company)
            WITH lead, collect(DISTINCT controlled) + [lead] AS group_entities
            UNWIND group_entities AS entity
            OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(entity)
            WITH lead, group_entities, count(DISTINCT t) AS title_count
            RETURN lead.name, lead.company_number, title_count, size(group_entities) AS entity_count
        """,
        "params": [
            {"crn": "00099912"},  # Grosvenor (Mayfair) Estate Ltd
            {"crn": "00094378"},  # Crown Estate Commissioners
            {"crn": "00104822"},  # Cadogan Estates Limited
            {"crn": "00099913"},  # Grosvenor (Belgravia)
            {"crn": "03219112"},  # Grosvenor Group Limited
        ],
    },
    {
        "name": "estate_profile.name_lookup_starts_with",
        "description": "Estate profile resolution by name STARTS WITH (slug-based URL fallback)",
        "p95_budget_ms": 400,
        "query": """
            MATCH (c:Company)
            WHERE c.name_normalised STARTS WITH $name_query
            WITH c
            ORDER BY
              CASE WHEN c.name_normalised = $name_query THEN 0 ELSE 1 END,
              c.name
            LIMIT 1
            RETURN c.name, c.company_number
        """,
        "params": [
            {"name_query": "grosvenor"},
            {"name_query": "cadogan"},
            {"name_query": "berkeley"},
            {"name_query": "british land"},
            {"name_query": "norges"},
        ],
    },
    {
        "name": "estate_profile.name_lookup_contains",
        "description": "Estate profile resolution by name CONTAINS (worst case fallback)",
        "p95_budget_ms": 800,
        "query": """
            MATCH (c:Company)
            WHERE c.name_normalised CONTAINS $name_query
            WITH c
            ORDER BY c.name
            LIMIT 1
            RETURN c.name, c.company_number
        """,
        "params": [
            {"name_query": "trust"},
            {"name_query": "estates"},
            {"name_query": "holdings"},
            {"name_query": "investment"},
            {"name_query": "properties"},
        ],
    },

    # ------ Concentration ------
    {
        "name": "concentration.small_postcode",
        "description": "Concentration analysis on small postcode prefix (~1k titles)",
        "p95_budget_ms": 250,
        "query": """
            MATCH (t:Title)-[:OWNED_BY]->(c:Company)
            WHERE t.postcode STARTS WITH $area_code
            WITH c, count(DISTINCT t) AS title_count
            ORDER BY title_count DESC
            LIMIT 50
            RETURN c.name, c.company_number, title_count
        """,
        "params": [
            {"area_code": "SW1X"},
            {"area_code": "W1K"},
            {"area_code": "W1J"},
            {"area_code": "SW1Y"},
            {"area_code": "SW1A"},
        ],
    },
    {
        "name": "concentration.large_postcode",
        "description": "Concentration analysis on larger postcode area (~50k titles)",
        "p95_budget_ms": 500,
        "query": """
            MATCH (t:Title)-[:OWNED_BY]->(c:Company)
            WHERE t.postcode STARTS WITH $area_code
            WITH c, count(DISTINCT t) AS title_count
            ORDER BY title_count DESC
            LIMIT 50
            RETURN c.name, c.company_number, title_count
        """,
        "params": [
            {"area_code": "SW"},
            {"area_code": "W1"},
            {"area_code": "E14"},
            {"area_code": "EC2"},
            {"area_code": "N1"},
        ],
    },
    {
        "name": "concentration.district",
        "description": "Concentration analysis by named district",
        "p95_budget_ms": 600,
        "query": """
            MATCH (t:Title)-[:OWNED_BY]->(c:Company)
            WHERE t.district = $district
            WITH c, count(DISTINCT t) AS title_count
            ORDER BY title_count DESC
            LIMIT 50
            RETURN c.name, c.company_number, title_count
        """,
        "params": [
            {"district": "WESTMINSTER"},
            {"district": "KENSINGTON AND CHELSEA"},
            {"district": "CITY OF LONDON"},
            {"district": "TOWER HAMLETS"},
            {"district": "CAMDEN"},
        ],
    },

    # ------ Foreign Ownership ------
    {
        "name": "foreign_ownership.district_kpis",
        "description": "Foreign ownership headline KPIs for a district",
        "p95_budget_ms": 600,
        "query": """
            CALL {
              MATCH (t:Title)-[:OWNED_BY]->(c:Company)
              WHERE t.district = $district
              RETURN count(DISTINCT t) AS corporate_titles
            }
            CALL {
              MATCH (t:Title)
              WHERE t.district = $district AND t.source = 'OCOD'
              RETURN count(t) AS overseas_titles
            }
            CALL {
              MATCH (t:Title {source: 'OCOD'})-[:OWNED_BY]->(c:Company)
              WHERE t.district = $district
              RETURN count(DISTINCT c) AS overseas_entity_count
            }
            RETURN corporate_titles, overseas_titles, overseas_entity_count
        """,
        "params": [
            {"district": "WESTMINSTER"},
            {"district": "KENSINGTON AND CHELSEA"},
            {"district": "CITY OF LONDON"},
            {"district": "CAMDEN"},
            {"district": "TOWER HAMLETS"},
        ],
    },

    # ------ Search Autocomplete ------
    {
        "name": "search.autocomplete_companies_prefix",
        "description": "Autocomplete companies — STARTS WITH (the fast path)",
        "p95_budget_ms": 30,
        "query": """
            MATCH (c:Company)
            WHERE c.name_normalised STARTS WITH $q
            WITH c
            OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
            WITH c, count(t) AS title_count
            ORDER BY title_count DESC, c.name
            LIMIT 3
            RETURN c.company_number, c.name, c.status, title_count
        """,
        "params": [
            {"q": "gros"},
            {"q": "cad"},
            {"q": "berk"},
            {"q": "qatar"},
            {"q": "norge"},
        ],
    },
    {
        "name": "search.autocomplete_companies_contains",
        "description": "Autocomplete companies — CONTAINS (the slow path)",
        "p95_budget_ms": 60,
        "query": """
            MATCH (c:Company)
            WHERE c.name_normalised CONTAINS $q
            WITH c
            OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
            WITH c, count(t) AS title_count
            ORDER BY title_count DESC, c.name
            LIMIT 3
            RETURN c.company_number, c.name, c.status, title_count
        """,
        "params": [
            {"q": "estate"},
            {"q": "holdings"},
            {"q": "trust"},
            {"q": "property"},
            {"q": "investment"},
        ],
    },
    {
        "name": "search.autocomplete_address_postcode",
        "description": "Autocomplete addresses by postcode prefix",
        "p95_budget_ms": 30,
        "query": """
            MATCH (a:Address)
            WHERE a.postcode STARTS WITH $q
            WITH a
            OPTIONAL MATCH (c:Company)-[:REGISTERED_AT]->(a)
            WITH a, count(c) AS reg_count
            ORDER BY reg_count DESC
            LIMIT 3
            RETURN a.address_id, a.premises, a.postcode, a.town, reg_count
        """,
        "params": [
            {"q": "SW1X"},
            {"q": "W1K"},
            {"q": "EC2"},
            {"q": "E14"},
            {"q": "N1"},
        ],
    },
]


# -----------------------------------------------------------------------------
# Benchmark runner
# -----------------------------------------------------------------------------

def run_benchmark(driver, bench, iterations: int) -> dict:
    """Run one benchmark N times. Returns timing stats."""
    timings_ms = []
    errors = 0
    
    # Warm-up (5 iterations, not counted) to warm Neo4j page cache
    with driver.session() as session:
        for i in range(min(5, iterations // 4)):
            params = bench["params"][i % len(bench["params"])]
            try:
                list(session.run(bench["query"], **params))
            except Exception:
                pass
    
    # Measured iterations
    with driver.session() as session:
        for i in range(iterations):
            params = bench["params"][i % len(bench["params"])]
            start = time.perf_counter()
            try:
                # consume() forces full result fetch including cursor close
                session.run(bench["query"], **params).consume()
                elapsed_ms = (time.perf_counter() - start) * 1000
                timings_ms.append(elapsed_ms)
            except Exception as e:
                errors += 1
                if errors == 1:
                    print(f"    ! First error on {bench['name']}: {type(e).__name__}: {e}")
    
    if not timings_ms:
        return {
            "name": bench["name"],
            "iterations": 0,
            "errors": errors,
            "p50": None, "p95": None, "p99": None, "mean": None,
            "min": None, "max": None,
            "budget_ms": bench["p95_budget_ms"],
            "verdict": "FAIL",
        }
    
    sorted_t = sorted(timings_ms)
    p50 = sorted_t[len(sorted_t) // 2]
    p95 = sorted_t[int(len(sorted_t) * 0.95)] if len(sorted_t) >= 20 else sorted_t[-1]
    p99 = sorted_t[int(len(sorted_t) * 0.99)] if len(sorted_t) >= 100 else sorted_t[-1]
    
    budget = bench["p95_budget_ms"]
    if p95 < budget * 0.7:
        verdict = "PASS"
    elif p95 < budget:
        verdict = "WARN"
    else:
        verdict = "FAIL"
    
    return {
        "name": bench["name"],
        "iterations": len(timings_ms),
        "errors": errors,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "mean": statistics.mean(timings_ms),
        "min": min(timings_ms),
        "max": max(timings_ms),
        "budget_ms": budget,
        "verdict": verdict,
    }


def print_report(results: list):
    print()
    print("=" * 100)
    print(f"{'Query':<48} {'p50':>8} {'p95':>8} {'p99':>8} {'Budget':>8} {'Verdict':>8}")
    print("=" * 100)
    
    for r in results:
        if r["p50"] is None:
            print(f"{r['name']:<48} {'—':>8} {'—':>8} {'—':>8} {r['budget_ms']:>7}ms {r['verdict']:>8}")
        else:
            print(
                f"{r['name']:<48} "
                f"{r['p50']:>7.1f}ms "
                f"{r['p95']:>7.1f}ms "
                f"{r['p99']:>7.1f}ms "
                f"{r['budget_ms']:>7}ms "
                f"{r['verdict']:>8}"
            )
    
    print("=" * 100)
    
    failures = [r for r in results if r["verdict"] == "FAIL"]
    warnings = [r for r in results if r["verdict"] == "WARN"]
    
    print(f"\n{len(results) - len(failures) - len(warnings)} PASS · "
          f"{len(warnings)} WARN · {len(failures)} FAIL\n")
    
    if failures:
        print("FAILURES (p95 over budget) — investigation needed:")
        for r in failures:
            print(f"  {r['name']}: p95 = {r['p95']:.1f}ms vs {r['budget_ms']}ms budget")
        print()


def write_csv(results: list, path: Path):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "name", "iterations", "errors",
            "p50", "p95", "p99", "mean", "min", "max",
            "budget_ms", "verdict",
        ])
        writer.writeheader()
        for r in results:
            writer.writerow(r)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100,
                        help="Iterations per benchmark (default: 100)")
    parser.add_argument("--query", type=str, default=None,
                        help="Run only the named query (default: all)")
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark_output"),
                        help="Where to write CSV reports")
    args = parser.parse_args()
    
    args.output_dir.mkdir(exist_ok=True, parents=True)
    
    # Filter benchmarks
    benchmarks = BENCHMARKS
    if args.query:
        benchmarks = [b for b in BENCHMARKS if args.query in b["name"]]
        if not benchmarks:
            print(f"No benchmarks matching '{args.query}'")
            print(f"Available: {[b['name'] for b in BENCHMARKS]}")
            sys.exit(1)
    
    print(f"Plottr query benchmark — {datetime.now().isoformat()}")
    print(f"Iterations: {args.iterations} per query")
    print(f"Benchmarks: {len(benchmarks)}")
    print()
    
    driver = get_driver()
    
    # Verify connection and graph state
    try:
        with driver.session() as session:
            counts = session.run("""
                MATCH (n) RETURN labels(n)[0] AS label, count(n) AS c ORDER BY c DESC
            """).data()
            print("Graph state:")
            for row in counts:
                print(f"  {row['label']}: {row['c']:,}")
            print()
    except Exception as e:
        print(f"FATAL: cannot connect to Neo4j: {e}")
        sys.exit(1)
    
    results = []
    for bench in benchmarks:
        print(f"  Running {bench['name']}... ", end="", flush=True)
        result = run_benchmark(driver, bench, args.iterations)
        results.append(result)
        if result["p50"] is not None:
            print(f"p50={result['p50']:.0f}ms p95={result['p95']:.0f}ms [{result['verdict']}]")
        else:
            print(f"FAILED ({result['errors']} errors)")
    
    print_report(results)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.output_dir / f"benchmark_{timestamp}.csv"
    write_csv(results, csv_path)
    print(f"Results written to {csv_path}")
    
    failures = [r for r in results if r["verdict"] == "FAIL"]
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
