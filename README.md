# Provider Data Pipeline

A small, runnable vertical slice for pulling provider records from the public NPI Registry API, loading them into a relational database, validating them with SQL, and exporting client-specific CSV/JSON files.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e . pytest

provider-pipeline --database provider_data.db init-db
provider-pipeline --database provider_data.db ingest --fixture fixtures/npi-response.json
provider-pipeline --database provider_data.db validate
provider-pipeline --database provider_data.db export --output-dir exports
pytest
```

Use the live API by omitting `--fixture` and passing JSON query parameters:

```bash
provider-pipeline --database provider_data.db ingest \
	--query '{"state":"MA","taxonomy_description":"Family Medicine"}'
```

See [docs/integration-guide.md](docs/integration-guide.md) for database, API, validation, and export details.
