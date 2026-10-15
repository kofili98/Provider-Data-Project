import os
from typing import Generator
import pytest

# Optional import so non-MSSQL test runners can skip gracefully
try:
    import pyodbc
except ImportError:
    pyodbc = None

DEFAULT_CONN_STR = (
    "Driver={ODBC Driver 18 for SQL Server};"
    "Server=localhost\\MSSQLSERVER01;"
    "Database=ProviderData;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)


@pytest.fixture(scope="module")
def mssql_conn() -> Generator:
    """Provide a connection to SQL Server or skip if driver/server is unavailable."""
    if pyodbc is None:
        pytest.skip("pyodbc is not installed")

    conn_str = os.environ.get("MSSQL_CONN_STR", DEFAULT_CONN_STR)
    try:
        conn = pyodbc.connect(conn_str, timeout=5)
    except Exception as exc:
        pytest.skip(f"Could not connect to SQL Server ({conn_str}): {exc}")

    yield conn
    conn.close()


# --------------------------------------------------------------------------- #
# 1. Total Volume & Baseline Reconciliation
# --------------------------------------------------------------------------- #
def test_total_provider_volume(mssql_conn):
    """Verify exactly 603 unique providers were ingested and loaded."""
    cursor = mssql_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM dbo.providers")
    total_providers = cursor.fetchone()[0]
    assert total_providers == 603, f"Expected 603 providers, found {total_providers}"


def test_provider_export_view_row_count(mssql_conn):
    """Verify the 1:1 view matches provider table row count."""
    cursor = mssql_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM dbo.provider_export")
    export_rows = cursor.fetchone()[0]
    assert export_rows == 603, f"Expected 603 export rows, found {export_rows}"


# --------------------------------------------------------------------------- #
# 2. Luhn Check Digit UDF Parity
# --------------------------------------------------------------------------- #
def test_fn_npi_is_valid_udf(mssql_conn):
    """Test SQL Server T-SQL Luhn checksum function (dbo.fn_npi_is_valid)."""
    cursor = mssql_conn.cursor()

    # Valid NPI (Luhn with prefix 80840)
    cursor.execute("SELECT dbo.fn_npi_is_valid('1234567893')")
    assert cursor.fetchone()[0] == 1

    # Invalid check digit
    cursor.execute("SELECT dbo.fn_npi_is_valid('1234567890')")
    assert cursor.fetchone()[0] == 0

    # Non-10-digit / alpha strings
    cursor.execute("SELECT dbo.fn_npi_is_valid('12345')")
    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT dbo.fn_npi_is_valid('123456789A')")
    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT dbo.fn_npi_is_valid(NULL)")
    assert cursor.fetchone()[0] == 0


# --------------------------------------------------------------------------- #
# 3. 14 Data Quality Rules Parity (603, 292, 18, 2)
# --------------------------------------------------------------------------- #
def test_quality_rules_summary_parity(mssql_conn):
    """Reconcile all 14 data quality rules against the SQLite baseline."""
    cursor = mssql_conn.cursor()
    cursor.execute(
        "EXEC dbo.usp_GetProviderQualitySummary @Specialty = '(All)', @City = '(All)', @StaleYears = 5"
    )
    rows = cursor.fetchall()
    summary = {row.rule_name: {"severity": row.severity, "count": row.flagged_count, "status": row.rule_status} for row in rows}

    # Verify all 14 rules exist
    assert len(summary) == 14, f"Expected 14 quality rules, found {len(summary)}"

    # 4 Fatal Errors (Must be 0)
    fatal_errors = ["malformed_npi", "invalid_npi_check_digit", "missing_name", "missing_location_address"]
    for err in fatal_errors:
        assert err in summary, f"Missing error rule: {err}"
        assert summary[err]["severity"] == "error"
        assert summary[err]["count"] == 0, f"Error rule {err} flagged {summary[err]['count']} records (expected 0)"
        assert summary[err]["status"] == "PASS"

    # Warnings with expected baseline flags: (292, 18, 2)
    assert summary["stale_record"]["count"] == 292, f"stale_record count {summary['stale_record']['count']} != 292"
    assert summary["stale_record"]["status"] == "WARNING"

    assert summary["missing_credential"]["count"] == 18, f"missing_credential count {summary['missing_credential']['count']} != 18"
    assert summary["missing_credential"]["status"] == "WARNING"

    assert summary["possible_duplicate_providers"]["count"] == 2, f"possible_duplicate_providers count {summary['possible_duplicate_providers']['count']} != 2"
    assert summary["possible_duplicate_providers"]["status"] == "WARNING"

    # Remaining 7 Warnings (Must be 0)
    clean_warnings = [
        "no_primary_taxonomy",
        "multiple_primary_taxonomies",
        "missing_phone",
        "bad_postal_format",
        "inactive_status",
        "duplicate_addresses",
        "po_box_location",
    ]
    for wrn in clean_warnings:
        assert summary[wrn]["count"] == 0, f"Warning rule {wrn} flagged {summary[wrn]['count']} records (expected 0)"
        assert summary[wrn]["status"] == "PASS"


# --------------------------------------------------------------------------- #
# 4. Detail Drill-Through & Remediation Procedure
# --------------------------------------------------------------------------- #
def test_quality_details_drillthrough(mssql_conn):
    """Verify detail drill-through returns matching record counts."""
    cursor = mssql_conn.cursor()

    # Drill into missing_credential (18 records)
    cursor.execute(
        "EXEC dbo.usp_GetProviderQualityDetails @RuleName = 'missing_credential', @Specialty = '(All)', @City = '(All)'"
    )
    details_18 = cursor.fetchall()
    assert len(details_18) == 18

    # Verify columns and data types
    first = details_18[0]
    assert len(first.npi) == 10
    assert first.rule_name == "missing_credential"
    assert first.failure_reason == "Individual practitioner (NPI-1) missing credential/degree"

    # Drill into possible_duplicate_providers (2 records)
    cursor.execute(
        "EXEC dbo.usp_GetProviderQualityDetails @RuleName = 'possible_duplicate_providers', @Specialty = '(All)', @City = '(All)'"
    )
    details_2 = cursor.fetchall()
    assert len(details_2) == 2


# --------------------------------------------------------------------------- #
# 5. External Vendor Extract & Quality Gating
# --------------------------------------------------------------------------- #
def test_vendor_extract_quality_gating(mssql_conn):
    """Verify vendor extract procedure matches substring filters and gates out errors."""
    cursor = mssql_conn.cursor()
    cursor.execute(
        "EXEC dbo.usp_ExportVendorData @Specialty = 'Cardiovascular', @State = 'CO'"
    )
    extract_rows = cursor.fetchall()

    # Must find cardiovascular records in CO
    assert len(extract_rows) > 0, "Vendor extract returned 0 rows for Colorado Cardiovascular"

    for r in extract_rows:
        assert r.state == "CO"
        assert "Cardio" in r.taxonomy_description or "Cardiovascular" in r.taxonomy_description
        assert len(r.npi) == 10
