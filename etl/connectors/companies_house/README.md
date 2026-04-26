# Companies House Connector

## Ingest strategy

**M1 initial load: bulk snapshots (no API key needed)**

Monthly bulk files from the CH S3 bucket — no authentication, no rate limiting.

| File | Size | Format | Frequency |
|------|------|--------|-----------|
| BasicCompanyDataAsOneFile-YYYY-MM-01.zip | ~800MB | CSV | Monthly |
| company-officers-YYYY-MM-01-part*.zip | ~2GB total | JSONL | Monthly |
| persons-with-significant-control-snapshot-YYYY-MM-01.zip | ~600MB | JSONL | Monthly |

**Post-M1 delta updates: CH API**

API key required. Rate limit: 600 req / 5 min. The connector enforces a
590 req / 5 min token bucket with exponential backoff on 429 (60s → 120s → 900s).

**Never** use the API for bulk loads — at 600 req/5min it would take weeks.

## Running

```bash
# M1 bulk snapshot
python -m etl.connectors.companies_house.extract  # downloads to data/raw/companies_house/

# Delta update for a single company
from etl.connectors.companies_house.extract import get_company_api
data = get_company_api("12345678")
```

## Known schema quirks

- Officer bulk files are JSONL (one JSON object per line), not CSV
- PSC bulk file is JSONL
- Company CSV uses `CompanyNumber` not `company_number` — transform handles normalisation
- Some officer records have `date_of_birth` as `{month, year}` only — no day
- `nature_of_control` on PSC records is a JSON array of strings
