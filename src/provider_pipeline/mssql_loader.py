import json
import sys
from pathlib import Path
from datetime import datetime, UTC
import sqlite3
import pyodbc

# 1. Project root is 2 levels up from src/provider_pipeline/
MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parents[1]

# Ensure src is on sys.path for direct execution
SRC_DIR = MODULE_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from provider_pipeline.pipeline import (
    fetch_records,
    _clean,
    _provider_name,
    _primary_flag,
    connect as connect_sqlite,
    initialize_database
)

# 2. File paths anchored to project root
SEARCHES_FILE = ROOT_DIR / "searches.json"
SQLITE_DB_PATH = ROOT_DIR / "provider_data.db"
SQLITE_SCHEMA_PATH = ROOT_DIR / "sql/schema.sql"

def run_pipeline():
    if not SEARCHES_FILE.exists():
        raise FileNotFoundError(f"Missing searches.json at: {SEARCHES_FILE}")

    print("--- Step 1: Querying CMS NPI API ---")
    queries = json.loads(SEARCHES_FILE.read_text())
    all_records = []

    for q in queries:
        print(f"Fetching: {q.get('city')} - {q.get('taxonomy_description')}...")
        records, truncated = fetch_records(query=q, delay=0.3)
        all_records.extend(records)
        print(f" -> Returned {len(records)} records")

    unique_records = {str(r["number"]): r for r in all_records}
    total_unique = len(unique_records)
    print(f"\nTotal unique providers: {total_unique}")

    # --- Step 2: Save to SQLite (provider_data.db) ---
    print(f"\n--- Step 2: Writing to SQLite ({SQLITE_DB_PATH.name}) ---")
    sqlite_conn = connect_sqlite(SQLITE_DB_PATH)
    initialize_database(sqlite_conn, SQLITE_SCHEMA_PATH)

    run_id = datetime.now(UTC).isoformat()
    for npi, rec in unique_records.items():
        basic = rec.get("basic", {})
        sqlite_conn.execute(
            """INSERT OR REPLACE INTO providers 
               (npi, entity_type_code, provider_name, credential, enumeration_date, last_updated_date, status, source_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (npi, rec.get("enumeration_type") or "UNKNOWN", _provider_name(basic), _clean(basic.get("credential")),
             _clean(basic.get("enumeration_date")), _clean(basic.get("last_updated")), _clean(basic.get("status")), run_id)
        )
        sqlite_conn.execute("DELETE FROM addresses WHERE npi = ?", (npi,))
        for a in rec.get("addresses", []):
            sqlite_conn.execute(
                """INSERT INTO addresses (npi, address_purpose, address_1, address_2, city, state, postal_code, telephone)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (npi, _clean(a.get("address_purpose")) or "UNKNOWN", _clean(a.get("address_1")),
                 _clean(a.get("address_2")), _clean(a.get("city")), _clean(a.get("state")),
                 _clean(a.get("postal_code")), _clean(a.get("telephone_number")))
            )
        sqlite_conn.execute("DELETE FROM taxonomies WHERE npi = ?", (npi,))
        for t in rec.get("taxonomies", []):
            sqlite_conn.execute(
                """INSERT INTO taxonomies (npi, code, description, primary_flag) VALUES (?, ?, ?, ?)""",
                (npi, _clean(t.get("code")), _clean(t.get("desc")), _primary_flag(t.get("primary")))
            )
    sqlite_conn.execute(
        "INSERT INTO ingestion_runs (run_id, record_count, completed_at) VALUES (?, ?, ?)",
        (run_id, total_unique, run_id)
    )
    sqlite_conn.commit()
    print("SQLite database successfully updated.")

    # --- Step 3: Load into SQL Server ---
    print("\n--- Step 3: Loading into SQL Server (localhost\\MSSQLSERVER01) ---")
    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        "Server=localhost\\MSSQLSERVER01;"
        "Database=ProviderData;"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    mssql_conn = pyodbc.connect(conn_str)
    cursor = mssql_conn.cursor()
    cursor.fast_executemany = True

    provider_rows = []
    address_rows = []
    taxonomy_rows = []

    for npi, rec in unique_records.items():
        basic = rec.get("basic", {})
        provider_rows.append((
            npi, rec.get("enumeration_type") or "UNKNOWN", _provider_name(basic),
            _clean(basic.get("credential")), _clean(basic.get("enumeration_date")),
            _clean(basic.get("last_updated")), _clean(basic.get("status")), run_id
        ))
        for a in rec.get("addresses", []):
            address_rows.append((
                npi, _clean(a.get("address_purpose")) or "UNKNOWN", _clean(a.get("address_1")),
                _clean(a.get("address_2")), _clean(a.get("city")), _clean(a.get("state")),
                _clean(a.get("postal_code")), _clean(a.get("telephone_number"))
            ))
        for t in rec.get("taxonomies", []):
            taxonomy_rows.append((
                npi, _clean(t.get("code")), _clean(t.get("desc")), _primary_flag(t.get("primary"))
            ))

    cursor.execute("DELETE FROM dbo.taxonomies;")
    cursor.execute("DELETE FROM dbo.addresses;")
    cursor.execute("DELETE FROM dbo.providers;")
    cursor.execute("DELETE FROM dbo.ingestion_runs;")

    cursor.executemany(
        """INSERT INTO dbo.providers 
           (npi, entity_type_code, provider_name, credential, enumeration_date, last_updated_date, status, source_run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        provider_rows
    )
    cursor.executemany(
        """INSERT INTO dbo.addresses 
           (npi, address_purpose, address_1, address_2, city, state, postal_code, telephone)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        address_rows
    )
    cursor.executemany(
        """INSERT INTO dbo.taxonomies (npi, code, description, primary_flag) VALUES (?, ?, ?, ?)""",
        taxonomy_rows
    )
    cursor.execute(
        "INSERT INTO dbo.ingestion_runs (run_id, record_count, completed_at) VALUES (?, ?, SYSUTCDATETIME())",
        (run_id, total_unique)
    )

    mssql_conn.commit()
    print(f"SQL Server ingestion successful! Loaded {total_unique} providers.")

if __name__ == "__main__":
    run_pipeline()