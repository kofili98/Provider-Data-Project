# Sample run (September 24, 2026)

A real end-to-end run against the live NPI Registry API. Python 3.14 on Windows, SQLite.

## Ingest

Six searches (Colorado; Denver, Aurora, Boulder; cardiovascular disease and dermatology), one per city and specialty so each stays under the API's 1,200-result ceiling.

| Search | Records returned |
|---|---|
| Denver, Cardiovascular Disease | 206 |
| Aurora, Cardiovascular Disease | 157 |
| Boulder, Cardiovascular Disease | 29 |
| Denver, Dermatology | 145 |
| Aurora, Dermatology | 89 |
| Boulder, Dermatology | 39 |
| **Raw total** | **665** |
| **Unique providers loaded** | **601** |

No search was truncated. The 64 duplicates are providers who matched more than one search (for example, practicing in both Denver and Aurora); ingestion de-duplicates on NPI.

## Validation

14 SQL rules, run with `provider-pipeline validate`. Result: `valid: true`; all four error-level rules (malformed NPI, invalid check digit, missing name, missing location address) found 0 problems across 601 records.

| Warning rule | Providers flagged | Share |
|---|---|---|
| `stale_record` (registry entry last updated 5+ years ago) | 292 | 49% |
| `missing_credential` (individual providers) | 18 | 3% |
| `possible_duplicate_providers` (same name and address, different NPI) | 2 | 0.3% |
| `no_primary_taxonomy`, `multiple_primary_taxonomies`, `missing_phone`, `bad_postal_format`, `inactive_status`, `duplicate_addresses`, `po_box_location` | 0 | 0% |

Stale records are a freshness risk, not proof of wrong data.

## Issue found and fixed

An early run searched for specialty `Cardiology`. The registry stores this specialty as `Cardiovascular Disease`, so those searches returned nothing and the Colorado cardiology export came back with 0 rows. Adding a per-search record count to the ingest summary made this visible, and correcting the search term produced 392 raw cardiovascular results. See the troubleshooting table in [integration-guide.md](integration-guide.md).

## Reproduce

```bash
provider-pipeline --database provider_data.db init-db
provider-pipeline --database provider_data.db ingest --query-file searches.json
provider-pipeline --database provider_data.db profile
provider-pipeline --database provider_data.db validate
provider-pipeline --database provider_data.db export --config configs/clients/colorado-cardiology.json --output-dir exports
```

Counts change as the registry is updated.
