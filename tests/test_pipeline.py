import io
import json
import sqlite3
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from provider_pipeline.pipeline import (
    connect,
    export_client,
    fetch_records,
    initialize_database,
    npi_is_valid,
    upsert_records,
    validate,
)

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "fixtures/npi-response.json"


def make_db(tmp_path):
    connection = connect(tmp_path / "providers.db")
    initialize_database(connection, ROOT / "sql/schema.sql")
    return connection


def fixture_records():
    return json.loads(FIXTURE.read_text())["results"]


def fake_record(number, **overrides):
    record = {
        "number": str(number),
        "enumeration_type": "NPI-1",
        "basic": {"first_name": "TODD", "middle_name": "E", "last_name": "SMITH", "status": "A"},
        "addresses": [{"address_purpose": "LOCATION", "address_1": "1 A ST", "city": "DENVER",
                       "state": "CO", "postal_code": "802020000", "telephone_number": "3035550100"}],
        "taxonomies": [{"code": "207RC0000X", "desc": "Cardiovascular Disease", "primary": True}],
    }
    record.update(overrides)
    return record


def page_opener(total, requests_seen):
    """Fake API: serves `total` records, 200 per page, recording each requested skip."""
    def opener(request, timeout=30):
        params = parse_qs(urlparse(request.full_url).query)
        skip, limit = int(params["skip"][0]), int(params["limit"][0])
        requests_seen.append(skip)
        page = [fake_record(1000000000 + skip + i) for i in range(max(0, min(limit, total - skip)))]
        return io.BytesIO(json.dumps({"result_count": len(page), "results": page}).encode())
    return opener


# ---------------------------- ingestion / API client ----------------------------
def test_pagination_stops_on_short_page():
    seen = []
    records, truncated = fetch_records(query={"city": "DENVER"}, opener=page_opener(250, seen), sleep=lambda s: None)
    assert (len(records), truncated, seen) == (250, False, [0, 200])


def test_pagination_stops_at_api_ceiling_instead_of_looping():
    seen = []
    records, truncated = fetch_records(query={"city": "DENVER"}, opener=page_opener(5000, seen), sleep=lambda s: None)
    assert seen == [0, 200, 400, 600, 800, 1000]  # six requests, never past skip=1000
    assert len(records) == 1200 and truncated is True


def test_retries_rate_limit_with_backoff():
    calls, sleeps = [], []
    good = page_opener(3, [])

    def opener(request, timeout=30):
        calls.append(1)
        if len(calls) <= 2:
            raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
        return good(request, timeout)

    records, _ = fetch_records(query={"city": "DENVER"}, opener=opener, sleep=sleeps.append, backoff=1.0)
    assert len(records) == 3 and sleeps == [1.0, 2.0]


def test_gives_up_after_retries():
    def opener(request, timeout=30):
        raise HTTPError(request.full_url, 503, "Unavailable", {}, None)

    with pytest.raises(HTTPError):
        fetch_records(query={"city": "DENVER"}, opener=opener, sleep=lambda s: None, retries=1)


def test_api_error_payload_raises_readable_error():
    def opener(request, timeout=30):
        return io.BytesIO(json.dumps({"Errors": [{"description": "Field state requires another field"}]}).encode())

    with pytest.raises(ValueError, match="requires another field"):
        fetch_records(query={"city": "X"}, opener=opener, sleep=lambda s: None)


@pytest.mark.parametrize("query", [{}, {"state": "CO"}])
def test_rejects_queries_the_registry_will_refuse(query):
    with pytest.raises(ValueError):
        fetch_records(query=query, opener=page_opener(1, []), sleep=lambda s: None)


def test_live_shaped_records_are_normalized(tmp_path):
    connection = make_db(tmp_path)
    org = fake_record(1000000001, enumeration_type="NPI-2",
                      basic={"organization_name": "ACME HEART GROUP", "status": "A"})
    person = fake_record(1000000002)
    person["addresses"][0]["telephone_number"] = "--"
    upsert_records(connection, [org, person])

    names = dict(connection.execute("SELECT npi, provider_name FROM providers").fetchall())
    assert names == {"1000000001": "ACME HEART GROUP", "1000000002": "TODD E SMITH"}
    assert connection.execute("SELECT telephone FROM addresses WHERE npi='1000000002'").fetchone()[0] is None
    assert connection.execute("SELECT DISTINCT primary_flag FROM taxonomies").fetchall()[0][0] == "Y"


def test_upsert_deduplicates_overlapping_searches(tmp_path):
    connection = make_db(tmp_path)
    _, count = upsert_records(connection, [fake_record(1234567893), fake_record(1234567893)])
    assert count == 1
    assert connection.execute("SELECT count(*) FROM providers").fetchone()[0] == 1


def test_upsert_replaces_child_records(tmp_path):
    connection = make_db(tmp_path)
    record = fixture_records()[0]
    upsert_records(connection, [record])
    upsert_records(connection, [{**record, "addresses": [], "taxonomies": []}])
    assert connection.execute("SELECT count(*) FROM addresses").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM taxonomies").fetchone()[0] == 0


def test_schema_enforces_foreign_keys(tmp_path):
    connection = make_db(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO addresses (npi, address_purpose) VALUES ('missing', 'LOCATION')")


# ---------------------------------- validation ----------------------------------
def test_npi_check_digit():
    assert npi_is_valid("1234567893") == 1
    assert npi_is_valid("1234567898") == 0
    assert npi_is_valid("12345") == 0 and npi_is_valid(None) == 0 and npi_is_valid("12345abcde") == 0


def test_fixture_validation_reports_errors_and_warnings(tmp_path):
    connection = make_db(tmp_path)
    upsert_records(connection, fixture_records())
    result = validate(connection)

    assert result["valid"] is False and result["records_checked"] == 2
    by_rule = {(f["rule"], f["npi"]) for f in result["failures"]}
    assert ("missing_name", "1234567894") in by_rule
    assert ("missing_location_address", "1234567894") in by_rule
    assert ("no_primary_taxonomy", "1234567894") in by_rule
    assert not any(f["npi"] == "1234567893" for f in result["failures"])


def test_warning_rules_fire(tmp_path):
    connection = make_db(tmp_path)
    messy = fake_record(1234567898, basic={"first_name": "A", "last_name": "B", "status": "I"})  # bad check digit, inactive
    messy["addresses"] = [
        {"address_purpose": "LOCATION", "address_1": "9 X ST", "city": "DENVER", "state": "CO", "postal_code": "1234"},
        {"address_purpose": "LOCATION", "address_1": "9 X ST", "city": "DENVER", "state": "CO", "postal_code": "1234"},
    ]
    messy["taxonomies"] = [{"code": "1", "desc": "A", "primary": True}, {"code": "2", "desc": "B", "primary": True}]
    twin_a = fake_record(1000000010, basic={"organization_name": "SAME CLINIC"})
    twin_b = fake_record(1000000011, basic={"organization_name": "same clinic"})
    upsert_records(connection, [messy, twin_a, twin_b])

    flagged = {(f["rule"], f["npi"]) for f in validate(connection)["failures"]}
    assert ("invalid_npi_check_digit", "1234567898") in flagged
    assert ("inactive_status", "1234567898") in flagged
    assert ("bad_postal_format", "1234567898") in flagged
    assert ("duplicate_addresses", "1234567898") in flagged
    assert ("multiple_primary_taxonomies", "1234567898") in flagged
    assert ("missing_phone", "1234567898") in flagged
    assert ("possible_duplicate_providers", "1000000010") in flagged
    assert ("possible_duplicate_providers", "1000000011") in flagged


# ------------------------------------ exports -----------------------------------
def test_fixture_ingest_validate_and_export(tmp_path):
    connection = make_db(tmp_path)
    run_id, count = upsert_records(connection, fixture_records())
    assert run_id and count == 2

    paths = export_client(connection, ROOT / "configs/clients/example.json", tmp_path / "exports")
    assert {p.suffix for p in paths} == {".csv", ".json"}
    exported = json.loads((tmp_path / "exports/example-providers.json").read_text())
    assert [row["npi"] for row in exported] == ["1234567893"]


def test_export_view_returns_one_row_per_provider(tmp_path):
    connection = make_db(tmp_path)
    record = fake_record(1234567893)
    record["addresses"].append({**record["addresses"][0], "address_1": "2 B ST"})
    record["taxonomies"].append({"code": "X", "desc": "Second", "primary": True})
    upsert_records(connection, [record])
    assert connection.execute("SELECT count(*) FROM provider_export").fetchone()[0] == 1


def test_export_rejects_unknown_columns(tmp_path):
    connection = make_db(tmp_path)
    config = tmp_path / "bad.json"
    config.write_text(json.dumps({"name": "bad", "columns": ["npi", "nope"]}))
    with pytest.raises(ValueError, match="nope"):
        export_client(connection, config, tmp_path / "out")
