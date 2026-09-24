# Integration Guide

## Prerequisites

- Python 3.11 or newer
- A writable directory for the SQLite database and exports
- Network access to `https://npiregistry.cms.hhs.gov/api/` for live ingestion (not needed for the fixture)

Install with `pip install -e .`. SQLite keeps setup simple; the schema is standard relational SQL and can move to PostgreSQL for shared deployments.

## Run the pipeline

```bash
provider-pipeline --database provider_data.db init-db
provider-pipeline --database provider_data.db ingest --query '{"state":"CO","city":"DENVER","taxonomy_description":"Cardiology"}'
provider-pipeline --database provider_data.db validate --fail-on-error
provider-pipeline --database provider_data.db export --config configs/clients/colorado-cardiology.json --output-dir exports
```

`init-db` is safe to re-run: tables use `IF NOT EXISTS` and the export view is recreated, so it also upgrades an older database.

### How ingestion behaves

- Requests API version 2.1 in pages of 200 with a delay between requests (`--delay`, default 0.5 s).
- Retries HTTP 429/5xx and network errors with exponential backoff.
- The API allows skipping at most 1,000 records, so one search returns at most 1,200. The pipeline stops there and reports the search under `truncated_searches`.
- Empty values (`--` in the registry) are stored as NULL. Individuals are named from first/middle/last name; organizations from `organization_name`. Taxonomy `primary` is normalized to `Y`/`N`.
- Overlapping searches are de-duplicated by NPI, and repeat runs upsert.

## Data model

- `providers`: one row per NPI (primary key), upserted on repeat runs.
- `addresses`, `taxonomies`: child tables, replaced for an NPI on each upsert.
- `ingestion_runs`: run id, record count, completion time.
- `provider_export`: view with one row per provider (first LOCATION address, first primary taxonomy).

### Field dictionary (`provider_export`)

| Column | Meaning |
|---|---|
| `npi` | 10-digit National Provider Identifier |
| `provider_name` | Organization name, or first, middle and last name for individuals |
| `credential` | Credential text as reported (e.g. MD) |
| `status` | `A` = active |
| `address_1`, `city`, `state`, `postal_code`, `telephone` | First LOCATION (practice) address |
| `taxonomy_code`, `taxonomy_description` | Primary taxonomy (specialty) |

## Validation rules

| Rule | Severity | Flags |
|---|---|---|
| `malformed_npi` | error | NPI not exactly 10 digits |
| `invalid_npi_check_digit` | error | Fails the NPI check digit (Luhn with prefix 80840) |
| `missing_name` | error | No name |
| `missing_location_address` | error | No LOCATION address |
| `no_primary_taxonomy` / `multiple_primary_taxonomies` | warning | Zero, or more than one, primary specialty |
| `missing_phone` | warning | LOCATION address without a phone |
| `bad_postal_format` | warning | ZIP not 5 digits, 9 digits or ZIP+4 |
| `inactive_status` | warning | Status other than `A` |
| `duplicate_addresses` | warning | Same address repeated for one NPI |
| `possible_duplicate_providers` | warning | Different NPIs with the same name and address |

Add a rule by appending a `-- rule: name | error|warning` header and a query that returns `npi`.

## Client exports

Each file in `configs/clients/` defines `name`, `formats` (csv, json), a SQL `where` filter, and `columns` from the view. Unknown columns are rejected. The `where` value is trusted SQL, so only maintainers should edit configs.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ingest failed: ... requires another criterion` | Searching by `state` alone | Add `city`, `postal_code` or `taxonomy_description` |
| `truncated_searches` is not empty | Search hit the 1,200-result ceiling | Split by city, ZIP prefix (`"postal_code":"802*"`) or specialty |
| Filter seems ignored, results too broad | Misspelled parameter; the API ignores unknown ones | Check parameter names against the API docs |
| HTTP 429 or 5xx | Rate limiting or an API outage | The pipeline retries; raise `--delay` and re-run |
| Export has 0 rows | Client `where` too strict, or no data for that area | Query `provider_export` directly and loosen the filter |
| `taxonomy_code` is empty | Provider has no primary taxonomy | Check the `no_primary_taxonomy` warning |
| `Unknown export column` | Column not in `provider_export` | Use the field dictionary above |
| Old database missing new behavior | Schema predates an upgrade | Re-run `init-db` |

## Known limitations

- The registry is self-reported. An NPI does not verify licensure or good standing.
- The export view keeps one address and one taxonomy per provider.
- SQLite allows a single writer; use PostgreSQL for concurrent jobs.

## Production considerations

Move configuration to environment variables or a secret manager, store raw API responses for replay, schedule runs with the organization's job runner, monitor run counts, validation failures and API errors, and keep the source run ID with downstream files for traceability.
