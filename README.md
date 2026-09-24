# Provider Data Pipeline

A small, runnable pipeline that pulls provider records from the public
[NPI Registry API](https://npiregistry.cms.hhs.gov/api-page) (REST, JSON), loads them into a relational
SQLite database, validates them with SQL rules, and writes client-specific CSV/JSON exports.

```
NPI Registry API ──► ingest ──► SQLite (providers, addresses, taxonomies)
                                   │
                         validate (sql/validations.sql)
                                   │
                    export (configs/clients/*.json) ──► CSV / JSON
```

## Quick start (offline, uses a fixture)

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e . pytest

provider-pipeline --database provider_data.db init-db
provider-pipeline --database provider_data.db ingest --fixture fixtures/npi-response.json
provider-pipeline --database provider_data.db validate
provider-pipeline --database provider_data.db export --output-dir exports
pytest
```

## Live data

Pass one search, or an array of searches, as JSON. The registry needs at least one criterion besides
`state`, and a single search returns at most 1,200 records, so split large areas by city, ZIP prefix or specialty:

```bash
provider-pipeline --database provider_data.db ingest --query '[
  {"state":"CO","city":"DENVER","taxonomy_description":"Cardiology"},
  {"state":"CO","city":"BOULDER","taxonomy_description":"Cardiology"}
]'
```

The ingest summary lists any `truncated_searches` that hit the ceiling. Then run `validate` and `export` as above.

## What the checks do

`validate` runs every rule in [`sql/validations.sql`](sql/validations.sql) and prints a count per rule.
Error rules (bad NPI, missing name or location address) fail `--fail-on-error`; warning rules (missing phone,
odd ZIP format, duplicate addresses, possible duplicate providers, and more) are reported only.

See [docs/integration-guide.md](docs/integration-guide.md) for the data model, field dictionary,
troubleshooting table, and known limitations.

## Limitations

The registry is self-reported. An NPI existing does not mean a provider is licensed or in good standing.
