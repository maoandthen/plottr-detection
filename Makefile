.PHONY: up down test verify-m0 verify-m1

up:
	docker compose up -d --wait

down:
	docker compose down

test:
	pytest tests/ -v

verify-m0:
	@echo "--- M0 verification ---"
	@docker compose exec postgres psql -U plottr -c "SELECT PostGIS_Version();" | grep -q "PostGIS" && echo "✓ PostGIS" || (echo "✗ PostGIS failed" && exit 1)
	@docker compose exec neo4j cypher-shell -u neo4j -p plottr_secret "RETURN 1 AS ping" | grep -q "ping" && echo "✓ Neo4j" || (echo "✗ Neo4j failed" && exit 1)
	@curl -sf http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d[\"status\"]==\"ok\" else 1)" && echo "✓ FastAPI /health" || (echo "✗ /health failed" && exit 1)
	@echo "M0 PASSED"

verify-m1:
	@echo "--- M1 verification ---"
	@python3 -m pytest tests/ -k "m1" -v
	@echo "M1 PASSED (schema and ETL skeleton verified)"
