from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

API_URL = "https://npiregistry.cms.hhs.gov/api/"
PAGE_SIZE = 200  # the API returns at most 200 results per request
MAX_SKIP = 1000  # the API skips at most 1,000 records -> 1,200 results per search
RETRY_STATUSES = {429, 500, 502, 503, 504}
PLACEHOLDERS = {"", "--"}  # the registry uses "--" for empty values

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = ROOT / "sql/validations.sql"


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def npi_is_valid(npi: Any) -> int:
    """Return 1 if `npi` is 10 digits with a valid check digit, else 0.

    NPIs use the Luhn algorithm with the constant prefix 80840.
    """
    if npi is None:
        return 0
    text = str(npi)
    if len(text) != 10 or not (text.isascii() and text.isdigit()):
        return 0
    total = 0
    for index, char in enumerate(reversed("80840" + text)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return int(total % 10 == 0)


def connect(database: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.create_function("npi_is_valid", 1, npi_is_valid, deterministic=True)
    return connection


def initialize_database(connection: sqlite3.Connection, schema_path: str | Path) -> None:
    connection.executescript(Path(schema_path).read_text())
    connection.commit()


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
def _check_query(query: dict[str, Any]) -> None:
    criteria = {key for key in query if key not in {"version", "limit", "skip", "pretty"}}
    if not criteria:
        raise ValueError("Query needs at least one search criterion, e.g. city or taxonomy_description.")
    if criteria == {"state"}:
        raise ValueError("The registry requires another criterion with `state` (city, postal_code, taxonomy_description, ...).")


def _get_json(url: str, *, opener: Callable, retries: int, backoff: float, sleep: Callable[[float], None]) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "provider-data-pipeline/0.1"})
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=30) as response:
                payload = json.load(response)
            break
        except HTTPError as error:
            if error.code not in RETRY_STATUSES or attempt == retries:
                raise
            log.warning("HTTP %s from NPI Registry; retry %s/%s", error.code, attempt + 1, retries)
        except URLError as error:
            if attempt == retries:
                raise
            log.warning("Network error (%s); retry %s/%s", error.reason, attempt + 1, retries)
        sleep(backoff * 2**attempt)
    if isinstance(payload, dict) and payload.get("Errors"):
        messages = "; ".join(str(item.get("description", item)) for item in payload["Errors"])
        raise ValueError(f"NPI Registry rejected the query: {messages}")
    return payload


def fetch_records(
    *,
    query: dict[str, Any],
    page_size: int = PAGE_SIZE,
    delay: float = 0.5,
    retries: int = 3,
    backoff: float = 1.0,
    opener: Callable = urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch pages for one search. Returns (records, truncated).

    `truncated` is True when the search hit the API's 1,200-result ceiling, meaning
    more matches may exist. Split the search (by city, ZIP prefix, taxonomy) to get them.
    """
    _check_query(query)
    records: list[dict[str, Any]] = []
    skip = 0
    while True:
        params = {"version": "2.1", **query, "limit": str(page_size), "skip": str(skip)}
        payload = _get_json(f"{API_URL}?{urlencode(params)}", opener=opener, retries=retries, backoff=backoff, sleep=sleep)
        page = payload.get("results", [])
        records.extend(page)
        if len(page) < page_size:
            return records, False
        if skip + page_size > MAX_SKIP:
            log.warning("Hit the %s-result API ceiling for query %s; split the search to get the rest.", MAX_SKIP + page_size, query)
            return records, True
        skip += page_size
        sleep(delay)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text in PLACEHOLDERS else text


def _provider_name(basic: dict[str, Any]) -> str | None:
    organization = _clean(basic.get("organization_name"))
    if organization:
        return organization
    parts = [_clean(basic.get(key)) for key in ("first_name", "middle_name", "last_name")]
    composed = " ".join(part for part in parts if part)
    return composed or _clean(basic.get("name"))


def _primary_flag(value: Any) -> str:
    """The API returns a boolean; older fixtures use 'Y'. Normalize to 'Y'/'N'."""
    return "Y" if str(value).strip().lower() in {"y", "yes", "true", "1"} else "N"


def upsert_records(connection: sqlite3.Connection, records: Iterable[dict[str, Any]]) -> tuple[str, int]:
    unique = {str(record["number"]): record for record in records}  # overlapping searches repeat NPIs
    run_id = datetime.now(UTC).isoformat()
    for npi, record in unique.items():
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
            (npi, record.get("enumeration_type") or "UNKNOWN", _provider_name(basic), _clean(basic.get("credential")),
             _clean(basic.get("enumeration_date")), _clean(basic.get("last_updated")), _clean(basic.get("status")), run_id),
        )
        connection.execute("DELETE FROM addresses WHERE npi = ?", (npi,))
        for address in record.get("addresses", []):
            connection.execute(
                """INSERT INTO addresses
                   (npi, address_purpose, address_1, address_2, city, state, postal_code, telephone)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (npi, _clean(address.get("address_purpose")) or "UNKNOWN", _clean(address.get("address_1")),
                 _clean(address.get("address_2")), _clean(address.get("city")), _clean(address.get("state")),
                 _clean(address.get("postal_code")), _clean(address.get("telephone_number"))),
            )
        connection.execute("DELETE FROM taxonomies WHERE npi = ?", (npi,))
        for taxonomy in record.get("taxonomies", []):
            connection.execute(
                "INSERT INTO taxonomies (npi, code, description, primary_flag) VALUES (?, ?, ?, ?)",
                (npi, _clean(taxonomy.get("code")), _clean(taxonomy.get("desc")), _primary_flag(taxonomy.get("primary"))),
            )
    connection.execute(
        "INSERT INTO ingestion_runs (run_id, record_count, completed_at) VALUES (?, ?, ?)",
        (run_id, len(unique), datetime.now(UTC).isoformat()),
    )
    connection.commit()
    return run_id, len(unique)


# --------------------------------------------------------------------------- #
# Validation (rules live in sql/validations.sql)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rule:
    name: str
    severity: str
    sql: str


RULE_HEADER = re.compile(r"^--\s*rule:\s*(\w+)\s*\|\s*(error|warning)\s*$", re.MULTILINE)


def load_rules(path: str | Path = DEFAULT_RULES) -> list[Rule]:
    text = Path(path).read_text()
    matches = list(RULE_HEADER.finditer(text))
    rules = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        rules.append(Rule(match.group(1), match.group(2), text[match.end():end].strip().rstrip(";")))
    return rules


def validate(connection: sqlite3.Connection, rules_path: str | Path = DEFAULT_RULES) -> dict[str, Any]:
    """Run every rule. `valid` is False only if an *error*-severity rule fails."""
    summary, failures = [], []
    for rule in load_rules(rules_path):
        npis = [row["npi"] for row in connection.execute(f"SELECT DISTINCT npi FROM (\n{rule.sql}\n) ORDER BY npi")]
        summary.append({"rule": rule.name, "severity": rule.severity, "count": len(npis)})
        failures.extend({"npi": npi, "rule": rule.name, "severity": rule.severity} for npi in npis)
    return {
        "valid": not any(item["count"] and item["severity"] == "error" for item in summary),
        "records_checked": connection.execute("SELECT count(*) FROM providers").fetchone()[0],
        "rules": summary,
        "failures": failures,
    }


# --------------------------------------------------------------------------- #
# Client exports
# --------------------------------------------------------------------------- #
def export_client(connection: sqlite3.Connection, config_path: str | Path, output_dir: str | Path) -> list[Path]:
    """Export rows from `provider_export` as defined by a client config.

    `where` is trusted configuration (it is SQL); column names are checked against the view.
    """
    config = json.loads(Path(config_path).read_text())
    columns = config["columns"]
    allowed = {row["name"] for row in connection.execute("PRAGMA table_info(provider_export)")}
    unknown = [column for column in columns if column not in allowed]
    if unknown:
        raise ValueError(f"Unknown export column(s) {unknown}; available: {sorted(allowed)}")
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
    log.info("Exported %s rows for client %s", len(rows), config["name"])
    return written


# --------------------------------------------------------------------------- #
# Profiling
# --------------------------------------------------------------------------- #
def profile(connection: sqlite3.Connection) -> dict[str, Any]:
    """Summarize what is in the database: counts by entity type, specialty, city, state and run."""
    def rows(sql: str) -> list[dict[str, Any]]:
        return [dict(row) for row in connection.execute(sql)]

    return {
        "providers": connection.execute("SELECT count(*) FROM providers").fetchone()[0],
        "by_entity_type": rows(
            "SELECT entity_type_code AS entity_type, count(*) AS n FROM providers GROUP BY 1 ORDER BY n DESC"),
        "by_primary_specialty": rows(
            "SELECT coalesce(taxonomy_description, '(none)') AS specialty, count(*) AS n "
            "FROM provider_export GROUP BY 1 ORDER BY n DESC LIMIT 15"),
        "by_city": rows(
            "SELECT coalesce(city, '(none)') AS city, coalesce(state, '') AS state, count(*) AS n "
            "FROM provider_export GROUP BY 1, 2 ORDER BY n DESC LIMIT 15"),
        "by_run": rows("SELECT run_id, record_count FROM ingestion_runs ORDER BY run_id"),
    }
