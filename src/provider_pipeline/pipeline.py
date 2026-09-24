from __future__ import annotations

import csv
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://npiregistry.cms.hhs.gov/api/"


def connect(database: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection, schema_path: str | Path) -> None:
    connection.executescript(Path(schema_path).read_text())
    connection.commit()


def fetch_records(
    *,
    query: dict[str, str],
    page_size: int = 200,
    opener=urlopen,
) -> list[dict[str, Any]]:
    """Fetch all pages from the NPI Registry API."""
    records: list[dict[str, Any]] = []
    skip = 0
    while True:
        params = {"version": "2.1", **query, "limit": str(page_size), "skip": str(skip)}
        request = Request(f"{API_URL}?{urlencode(params)}", headers={"Accept": "application/json"})
        with opener(request, timeout=30) as response:
            payload = json.load(response)
        page = payload.get("results", [])
        records.extend(page)
        if len(page) < page_size:
            return records
        skip += page_size


def _first(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return next(iter(items), {})


def upsert_records(connection: sqlite3.Connection, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
    run_id = datetime.now(UTC).isoformat()
    inserted = 0
    for record in records:
        npi = str(record["number"])
        basic = record.get("basic", {})
        connection.execute(
            """INSERT INTO providers
               (npi, entity_type_code, provider_name, credential, enumeration_date,
                last_updated_date, status, source_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(npi) DO UPDATE SET
                 entity_type_code=excluded.entity_type_code,
                 provider_name=excluded.provider_name,
                 credential=excluded.credential,
                 enumeration_date=excluded.enumeration_date,
                 last_updated_date=excluded.last_updated_date,
                 status=excluded.status,
                 source_run_id=excluded.source_run_id""",
            (npi, record.get("enumeration_type"), basic.get("name"), basic.get("credential"),
             basic.get("enumeration_date"), basic.get("last_updated"), basic.get("status"), run_id),
        )
        connection.execute("DELETE FROM addresses WHERE npi = ?", (npi,))
        for address in record.get("addresses", []):
            connection.execute(
                """INSERT INTO addresses
                   (npi, address_purpose, address_1, address_2, city, state, postal_code, telephone)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (npi, address.get("address_purpose"), address.get("address_1"), address.get("address_2"),
                 address.get("city"), address.get("state"), address.get("postal_code"), address.get("telephone_number")),
            )
        connection.execute("DELETE FROM taxonomies WHERE npi = ?", (npi,))
        for taxonomy in record.get("taxonomies", []):
            connection.execute(
                "INSERT INTO taxonomies (npi, code, description, primary_flag) VALUES (?, ?, ?, ?)",
                (npi, taxonomy.get("code"), taxonomy.get("desc"), taxonomy.get("primary")),
            )
        inserted += 1
    connection.execute(
        "INSERT INTO ingestion_runs (run_id, record_count, completed_at) VALUES (?, ?, ?)",
        (run_id, inserted, datetime.now(UTC).isoformat()),
    )
    connection.commit()
    return run_id, inserted


def validate(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in connection.execute(
        """SELECT npi, 'missing_name' AS rule FROM providers
           WHERE provider_name IS NULL OR trim(provider_name) = ''
           UNION ALL
           SELECT npi, 'missing_address' FROM providers p
           WHERE NOT EXISTS (SELECT 1 FROM addresses a WHERE a.npi = p.npi)"""
    ):
        failures.append(dict(row))
    return failures


def export_client(connection: sqlite3.Connection, config_path: str | Path, output_dir: str | Path) -> list[Path]:
    config = json.loads(Path(config_path).read_text())
    columns = config["columns"]
    where = config.get("where", "1 = 1")
    rows = connection.execute(f"SELECT {', '.join(columns)} FROM provider_export WHERE {where}").fetchall()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for format_name in config.get("formats", ["csv"]):
        path = output / f"{config['name']}.{format_name}"
        if format_name == "csv":
            with path.open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(columns)
                writer.writerows(rows)
        elif format_name == "json":
            path.write_text(json.dumps([dict(row) for row in rows], indent=2) + "\n")
        else:
            raise ValueError(f"Unsupported export format: {format_name}")
        written.append(path)
    return written
