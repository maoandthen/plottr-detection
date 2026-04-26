# HMLR OCOD Connector

**Source:** HM Land Registry Overseas Companies Ownership Data (OCOD)
**Cadence:** Monthly bulk release
**Volume:** ~100k rows
**Coverage:** Titles in England & Wales owned by overseas-incorporated companies

## Files

| File | Purpose |
|------|---------|
| `extract.py` | Stream-downloads the ZIP from HMLR and unpacks to `data/raw/ocod/` |
| `transform.py` | Renames columns, coerces types, adds `country_incorporated` |
| `load.py` | Bulk-inserts into Postgres `titles` table |
| `tests.py` | Unit tests for transform |

## Usage

```bash
python -m etl.connectors.hmlr_ocod.extract
```
