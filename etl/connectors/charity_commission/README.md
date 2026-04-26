# Charity Commission Connector

**Source:** Charity Commission for England and Wales — public data extract
**Cadence:** Weekly
**Format:** JSON ZIP
**URL:** https://ccewuksprdoneregsadata1.blob.core.windows.net/data/json/publicextract.charity.zip

## Files

| File | Purpose |
|------|---------|
| `extract.py` | Download and unpack JSON ZIP to `data/raw/charity_commission/` |
| `transform.py` | Normalise JSON records to flat charity dicts |
| `load.py` | Upsert into Postgres `charities` table |
| `tests.py` | Skipped (M2+) |
