from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from urllib.error import URLError

from .pipeline import (
    DEFAULT_RULES,
    ROOT,
    connect,
    export_client,
    fetch_records,
    initialize_database,
    upsert_records,
    validate,
)


def _queries(raw: str) -> list[dict]:
    """Accept one JSON object or a JSON array of objects (one search each)."""
    value = json.loads(raw)
    return value if isinstance(value, list) else [value]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Ingest, validate, and export NPI Registry records")
    parser.add_argument("--database", default="provider_data.db")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-db", help="create tables and the export view")
    init.add_argument("--schema", default=str(ROOT / "sql/schema.sql"))

    ingest = subparsers.add_parser("ingest", help="load records from the live API or a fixture")
    ingest.add_argument("--query", default="{}", help="JSON object, or array of objects, of API query parameters")
    ingest.add_argument("--fixture", help="JSON response file, for offline runs")
    ingest.add_argument("--delay", type=float, default=0.5, help="seconds to wait between API requests")

    validate_parser = subparsers.add_parser("validate", help="run the SQL rules in sql/validations.sql")
    validate_parser.add_argument("--rules", default=str(DEFAULT_RULES))
    validate_parser.add_argument("--fail-on-error", action="store_true", help="exit 1 if any error-severity rule fails")

    export = subparsers.add_parser("export", help="write a client's CSV/JSON files")
    export.add_argument("--config", default=str(ROOT / "configs/clients/example.json"))
    export.add_argument("--output-dir", default="exports")

    args = parser.parse_args()
    connection = connect(args.database)

    if args.command == "init-db":
        initialize_database(connection, args.schema)
    elif args.command == "ingest":
        records, truncated = [], []
        if args.fixture:
            records = json.loads(Path(args.fixture).read_text()).get("results", [])
            searches = 0
        else:
            queries = _queries(args.query)
            searches = len(queries)
            try:
                for query in queries:
                    found, was_truncated = fetch_records(query=query, delay=args.delay)
                    records.extend(found)
                    if was_truncated:
                        truncated.append(query)
            except (ValueError, URLError) as error:  # bad query, API rejection, or network failure
                print(f"ingest failed: {error}", file=sys.stderr)
                raise SystemExit(2) from error
        run_id, count = upsert_records(connection, records)
        print(json.dumps({"run_id": run_id, "records": count, "searches": searches, "truncated_searches": truncated}, indent=2))
    elif args.command == "validate":
        result = validate(connection, args.rules)
        print(json.dumps(result, indent=2))
        if args.fail_on_error and not result["valid"]:
            raise SystemExit(1)
    elif args.command == "export":
        print("\n".join(str(path) for path in export_client(connection, args.config, args.output_dir)))
