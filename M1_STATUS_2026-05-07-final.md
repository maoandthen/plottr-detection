# M1 Status — End of 2026-05-07

## Completed
- Phase 1 download (5.08GB on /Volumes/PlottrData)
- Phase 2 staging load (41,192,511 rows in Postgres)
- Phase 3 v2 export to CSV in neo4j-admin format:
 - companies.csv: 5,698,175 rows (887MB)
 - titles.csv: 4,504,682 rows (588MB) 
 - addresses.csv: 2,791,583 rows (367MB)
 - owned_by.csv: 3,483,696 edges (331MB)
 - registered_at.csv: 5,608,032 edges (499MB)
- Total: 22,086,548 records exported and ready

## Outstanding
- PSC export hangs on JSONB filter (26.9M rows). Fix tomorrow with index:
 CREATE INDEX idx_stg_psc_kind ON stg_psc ((raw_json->'data'->>'kind'));
 Then re-run export.
- LOAD CSV into Neo4j blocked tonight by Docker container startup issue on macOS. Containers stuck in "Created" state, never reach "Up". Likely volume mount permission. 
 Fix tomorrow morning:
 - Docker Desktop → Settings → Resources → File Sharing → ensure /Volumes/PlottrData listed
 - docker rm -f all zombie neo4j containers
 - docker compose up -d neo4j with fresh state

## Tomorrow's plan
1. Fix Docker file sharing
2. Run all 5 LOAD CSV operations (~50-90 min)
3. Add JSONB index, re-export PSC
4. Load Person nodes + PSC_OF edges
5. Verify M1 complete
6. Wire concentration page to live data

Total: ~3-4 hours fresh tomorrow.