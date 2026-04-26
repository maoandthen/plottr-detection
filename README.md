# Plottr Detection & Enrichment Layer

Automated detection of corporate land ownership patterns in England & Wales, linking Land Registry titles to Companies House, PSC registers, and the Charity Commission.

## Stack

| Layer | Technology |
|-------|-----------|
| Relational store | PostgreSQL 16 + PostGIS 3.4 |
| Graph store | Neo4j 5 Community + APOC |
| API | FastAPI 0.111 + Uvicorn |
| ORM / migrations | SQLAlchemy 2 + Alembic |
| ETL orchestration | Prefect 3 |
| Data processing | pandas + DuckDB + PyArrow |

## Quick start

```bash
cp .env.example .env
make up
make verify-m0
```

## Milestone status

| Milestone | Description | Status |
|-----------|-------------|--------|
| M0 | Docker infra: PostGIS + Neo4j + FastAPI /health | pending |
| M1 | ETL connector skeletons, graph schema, Alembic migrations | pending |
| M2 | CCOD + OCOD full ingest → Postgres + Neo4j | pending |
| M3 | Companies House live API ingest (requires API key) | pending |
| M4 | PSC graph traversal + ownership chain API | pending |
| M5 | Charity Commission ingest + trustee graph | pending |
| M6 | Geospatial enrichment (postcode → centroid) | pending |
| M7 | Risk scoring engine | pending |
| M8 | Search API + frontend scaffold | pending |
| M9 | Scheduled ETL via Prefect + alerting | pending |

## Project structure

```
etl/connectors/   — per-source extract/transform/load + tests
etl/flows/        — Prefect orchestration flows
graph/            — Neo4j schema definitions + Cypher helpers
api/              — FastAPI app + routers
models/           — SQLAlchemy ORM models
migrations/       — Alembic migrations
docker/           — Dockerfile + init scripts
tests/            — Integration tests
```
