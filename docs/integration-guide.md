# Integration Guide

## Prerequisites

- Python 3.11 or newer
- A writable directory for the SQLite database and exports
- Network access to `https://npiregistry.cms.hhs.gov/api/` for live ingestion

Install the package with `pip install -e .`. The milestone uses SQLite so it can run without a separate database server. The tables and SQL are intentionally relational and can be migrated to PostgreSQL as a deployment step.

## Run the pipeline

Initialize the database, ingest a fixture or live API response, validate it, and export a client package:

```bash
provider-pipeline --database provider_data.db init-db
provider-pipeline --database provider_data.db ingest --fixture fixtures/npi-response.json
provider-pipeline --database provider_data.db validate --fail-on-error
provider-pipeline --database provider_data.db export --config configs/clients/example.json --output-dir exports
```

For a live request, replace the fixture argument with `--query`, whose value is a JSON object of NPI Registry API parameters. The ingestion client requests API version 2.1, paginates in batches of 200, and stops when a page is shorter than the requested batch size.

## Data model

- `providers` is keyed by NPI and is upserted on repeat runs.
- `addresses` and `taxonomies` are child tables replaced for an NPI during an upsert.
- `ingestion_runs` records the run identifier, count, and completion time.
- `provider_export` is a stable view used by client exports.

## Validation and exports

`sql/validations.sql` contains checks for malformed NPIs, missing names, missing location addresses, and duplicate NPIs. The CLI validation command currently enforces the missing-name and missing-address rules and emits JSON results.

Client definitions live under `configs/clients/`. Each definition specifies a name, output formats, a SQL filter, and selected view columns. Only records matching the client filter are exported. CSV includes a header row; JSON is an array of objects.

## Production integration considerations

Use PostgreSQL for shared or high-volume deployments, move credentials and configuration to environment variables or a secret manager, add durable raw-response storage, and schedule the commands with the organization’s job runner. Monitor run counts, validation failures, API errors, and export delivery. Keep the source run ID with downstream files for traceability.