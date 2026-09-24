from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import connect, export_client, fetch_records, initialize_database, upsert_records, validate


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest and export NPI Registry records")
    parser.add_argument("--database", default="provider_data.db")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init-db")
    init.add_argument("--schema", default=str(ROOT / "sql/schema.sql"))
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--query", default="{}", help="JSON API query parameters")
    ingest.add_argument("--fixture", help="JSON response file, for local runs")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--fail-on-error", action="store_true")
    export = subparsers.add_parser("export")
    export.add_argument("--config", default=str(ROOT / "configs/clients/example.json"))
    export.add_argument("--output-dir", default="exports")
    args = parser.parse_args()
    connection = connect(args.database)
    if args.command == "init-db":
        initialize_database(connection, args.schema)
    elif args.command == "ingest":
        records = (json.loads(Path(args.fixture).read_text()).get("results", []) if args.fixture
                   else fetch_records(query=json.loads(args.query)))
        run_id, count = upsert_records(connection, records)
        print(json.dumps({"run_id": run_id, "records": count}))
    elif args.command == "validate":
        failures = validate(connection)
        print(json.dumps({"valid": not failures, "failures": failures}, indent=2))
        if failures and args.fail_on_error:
            raise SystemExit(1)
    elif args.command == "export":
        print("\n".join(str(path) for path in export_client(connection, args.config, args.output_dir)))
