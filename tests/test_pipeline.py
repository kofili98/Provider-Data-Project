import json
import sqlite3
from pathlib import Path

from provider_pipeline.pipeline import connect, export_client, initialize_database, upsert_records, validate


ROOT = Path(__file__).parents[1]


def test_fixture_ingest_validate_and_export(tmp_path):
    database = tmp_path / "providers.db"
    connection = connect(database)
    initialize_database(connection, ROOT / "sql/schema.sql")
    records = json.loads((ROOT / "fixtures/npi-response.json").read_text())["results"]

    run_id, count = upsert_records(connection, records)

    assert run_id
    assert count == 2
    assert connection.execute("SELECT count(*) FROM providers").fetchone()[0] == 2
    failures = validate(connection)
    assert {failure["npi"] for failure in failures} == {"1234567894"}

    output_paths = export_client(
        connection,
        ROOT / "configs/clients/example.json",
        tmp_path / "exports",
    )

    assert {path.suffix for path in output_paths} == {".csv", ".json"}
    exported = json.loads((tmp_path / "exports/example-providers.json").read_text())
    assert len(exported) == 1
    assert exported[0]["npi"] == "1234567893"


def test_upsert_replaces_child_records(tmp_path):
    connection = connect(tmp_path / "providers.db")
    initialize_database(connection, ROOT / "sql/schema.sql")
    record = json.loads((ROOT / "fixtures/npi-response.json").read_text())["results"][0]

    upsert_records(connection, [record])
    upsert_records(connection, [{**record, "addresses": [], "taxonomies": []}])

    assert connection.execute("SELECT count(*) FROM addresses").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM taxonomies").fetchone()[0] == 0


def test_schema_enforces_foreign_keys(tmp_path):
    connection = connect(tmp_path / "providers.db")
    initialize_database(connection, ROOT / "sql/schema.sql")

    try:
        connection.execute("INSERT INTO addresses (npi, address_purpose) VALUES ('missing', 'LOCATION')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("foreign key constraint was not enforced")