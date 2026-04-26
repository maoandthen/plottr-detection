# Companies House Connector

**Source:** Companies House API + bulk data snapshots
**Cadence:** Daily (API); monthly (bulk snapshot)
**Bulk snapshot:** https://download.companieshouse.data.s3-website-eu-west-1.amazonaws.com/

## Setup

1. Register at https://developer.company-information.service.gov.uk/
2. Add `COMPANIES_HOUSE_API_KEY=your_key` to `.env`

## Files

| File | Purpose |
|------|---------|
| `extract.py` | Live API calls: `get_company`, `get_officers`, `get_pscs` |
| `transform.py` | Normalise API responses to flat dicts |
| `load.py` | Upsert into Postgres companies/officers/pscs tables |
| `tests.py` | Skipped until API key is set |
