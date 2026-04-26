# HMLR CCOD Connector

**Source:** HM Land Registry Corporate and Commercial Ownership Data (CCOD)
**Cadence:** Monthly bulk release
**Volume:** ~5M rows
**Coverage:** Corporate freehold and leasehold titles in England & Wales

## Files

| File | Purpose |
|------|---------|
| `extract.py` | Stream-downloads the ZIP from HMLR and unpacks to `data/raw/ccod/` |
| `transform.py` | Renames columns, coerces types, drops nulls |
| `load.py` | Bulk-inserts into Postgres `titles` table |
| `tests.py` | Unit tests for transform (no I/O) |

## Usage

```bash
python -m etl.connectors.hmlr_ccod.extract
```
