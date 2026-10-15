# Provider Data Pipeline & SSRS Reporting Suite

An end-to-end healthcare data engineering and reporting platform that ingests practitioner records from the federal [CMS National Provider Identifier (NPI) Registry API](https://www.google.com/search?q=https%3A%2F%2Fnpiregistry.cms.hhs.gov%2Fapi-page), enforces 14 regulatory data-quality rules in Microsoft SQL Server, and delivers interactive compliance dashboards and automated vendor data extracts via SQL Server Reporting Services (SSRS).

---

## Architecture & Data Flow

```
                               [ CMS NPI Registry API (v2.1) ]
                                              │
                                              ▼
                               [ Python Ingestion Pipeline ]
                      (Pagination, Backoff, Deduplication, pyodbc Loader)
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼                                             ▼
            [ SQLite Database ]                         [ Microsoft SQL Server 2025 ]
            (Lightweight Local)                            (Enterprise Data Warehouse)
            ├── providers                               ├── dbo.providers
            ├── addresses                               ├── dbo.addresses
            ├── taxonomies                              ├── dbo.taxonomies
            └── provider_export                         └── dbo.provider_export
                                                                     │
                                             ┌───────────────────────┴───────────────────────┐
                                             ▼                                               ▼
                              [ T-SQL Quality Validation Layer ]             [ Automated Monthly Job Scheduling ]
                              ├── 01_schema.sql (Tables, View)               ├── SQL Server Agent (MSSQLSERVER01)
                              ├── 02_npi_luhn.sql (Luhn Checksum UDF)        └── 1st of Month Automated Execution
                              ├── 03_quality_rules.sql (14 Rules View)
                              ├── 04_failure_report.sql (Summary/Detail Procs)
                              └── 05_VendorReportExport.sql (Extract Proc)
                                             │
                                             ▼
                              [ SSRS Reporting Portal (/ProviderReports) ]
                              ├── 1. Provider_Data_Quality_Summary.rdl  (KPIs & 5+ Yr Staleness Chart)
                              ├── 2. Provider_Data_Quality_Detail.rdl   (Drill-Through Remediation Queue)
                              └── 3. Vendor_Extract_Colorado_Cardiology.rdl (Quality-Gated CSV Export Feed)
```

---

## Project Narrative & Evolution

### The Problem
Healthcare provider directories suffer from severe data decay. Self-reported registry updates lapse, practice addresses list PO boxes, and check digits fail—causing claim denials, network directory inaccuracies, and non-compliance with the **CMS Interoperability Mandates** and the **No Surprises Act** (which mandates directory accuracy and regular audits).

### The Solution
This project bridges the gap between raw public REST APIs and executive data governance:
1. **Extraction & Ingestion**: A resilient Python pipeline queries CMS NPI Registry endpoints, navigating API rate limits (HTTP 429 backoff) and the 1,200-result pagination ceiling, normalizing nested JSON structures into relational entities.
2. **Enterprise Database Migration**: Ingested data is loaded into Microsoft SQL Server (`ProviderData`) with typed schemas, clustered indexes, and relational integrity.
3. **In-Database Quality Engine**: 14 business and compliance checks—including an in-database implementation of the 15-digit Luhn check digit algorithm (`dbo.fn_npi_is_valid`)—audit provider records for missing credentials, address duplication, and directory staleness.
4. **Interactive SSRS Reporting**: Executives and data stewards interact with web portal dashboards to filter quality issues by medical specialty or municipality, visualize freshness cliffs, drill through to provider contact lists, and dispatch automated monthly CSV feeds to external vendor partners.

---

## Key Features

* **Resilient API Harvester**: Python-based ingestion engine supporting chunked pagination, exponential retry backoff, NPI de-duplication across overlapping searches, and ceiling detection.
* **14 Regulatory Data Quality Rules**:
  * **4 Critical Errors**: Malformed NPI (length/numeric), invalid Luhn checksum (prefix `80840`), missing provider name, and missing physical practice location address.
  * **10 Data Hygiene Warnings**: Multiple/missing primary taxonomies, missing clinic telephone, invalid ZIP/ZIP+4 formats, inactive status, duplicate addresses, potential duplicate providers, PO Box practice addresses, missing medical credentials (`NPI-1`), and stale records ($\ge 5$ years unmodified).
* **T-SQL Checksum Engine (`dbo.fn_npi_is_valid`)**: High-performance scalar user-defined function executing the ISO/IEC 7812 Luhn algorithm directly inside SQL Server.
* **Modular T-SQL Architecture**: Cleanly partitioned database scripts in `sql/mssql/` separating DDL, functions, views, reporting procedures, and vendor extracts.
* **Executive Summary Dashboard (`Provider_Data_Quality_Summary.rdl`)**:
  * High-level KPI cards tracking directory volume (603 monitored providers) and active defects.
  * Pass/Fail compliance matrix with conditional green/red/amber status indicators.
  * Staleness Horizon histogram highlighting the 5+ year attestation cliff in red.
* **Interactive Drill-Through Exception Queue (`Provider_Data_Quality_Detail.rdl`)**:
  * Actionable record-level view linking directly from summary table cells and chart columns.
  * Context-aware operational staleness wording (*"Record updated more than 5 years ago"*).
  * Filter passback preserving user selections on return.
* **Automated Monthly Vendor Feeds (`Vendor_Extract_Colorado_Cardiology.rdl`)**:
  * Headless CSV extraction feed tailored to downstream payer/clearinghouse specifications.
  * Built-in automated quality gating that suppresses records failing fatal errors from outbound vendor files.
  * Scheduled distribution via SQL Server Agent and native SSRS Windows File Share subscriptions.

---

## Repository Structure

```text
Provider-Data-Project/
├── README.md                          # Project narrative, architecture, and runbook
├── pyproject.toml                     # Python packaging configuration
├── searches.json                      # Target search criteria (Colorado Cardio & Derm)
│
├── configs/clients/                   # Downstream client export schemas
│   ├── colorado-cardiology.json
│   └── example.json
│
├── docs/                              # Architecture and design documentation
│   ├── integration-guide.md           # Technical integration runbook & T-SQL mappings
│   ├── reports_specs.md               # Functional report requirements & monthly SLAs
│   └── sample-run.md                  # Baseline live run results and count benchmarks
│
├── fixtures/
│   └── npi-response.json              # Sample JSON fixture for offline testing
│
├── sql/
│   ├── schema.sql                     # Legacy SQLite schema DDL
│   ├── validations.sql                # Legacy SQLite data quality queries
│   └── mssql/                         # Enterprise T-SQL Database Scripts
│       ├── 01_schema.sql              # Tables, clustered indexes, and provider_export view
│       ├── 02_npi_luhn.sql            # Scalar Luhn checksum function (dbo.fn_npi_is_valid)
│       ├── 03_quality_rules.sql       # 14 quality validation rules view (dbo.vw_quality_rule_failures)
│       ├── 04_failure_report.sql      # Summary and detail reporting stored procedures
│       └── 05_VendorReportExport.sql  # Substring-matched vendor export stored procedure
│
├── src/provider_pipeline/             # Python ETL Core Engine
│   ├── __init__.py
│   ├── cli.py                         # Command-line interface
│   ├── pipeline.py                    # API client, JSON cleaner, and SQLite loader
│   └── mssql_loader.py                # Direct pyodbc loader for SQL Server 2025
│
├── tests/                             # Automated Test Suites & Reconciliation
│   ├── Reconcilliation.sql            # T-SQL audit script for SQL Server parity checks
│   ├── test_mssql_parity.py           # Pytest suite verifying 603-provider reconciliation
│   └── test_pipeline.py               # Unit tests for core ingestion and SQLite logic
│
└── ProviderReports/                   # SSRS Visual Studio Project (ProviderReports.sln)
    ├── dsProviderData.rds             # Shared Data Source (localhost\MSSQLSERVER01)
    ├── Provider_Data_Quality_Summary.rdl
    ├── Provider_Data_Quality_Detail.rdl
    └── Vendor_Extract_Colorado_Cardiology.rdl
```

---

## Quickstart & Execution Runbook

### Prerequisites
* Python 3.11+
* Microsoft SQL Server 2022/2025 Developer Edition (instance: `localhost\MSSQLSERVER01`)
* SQL Server Management Studio (SSMS 20+)
* SQL Server Reporting Services (SSRS 2022)
* ODBC Driver 18 for SQL Server

---

### Step 1: Deploy Database Architecture in SQL Server
1. Open **SSMS** and connect to `localhost\MSSQLSERVER01` (enable *Trust server certificate*).
2. Execute the scripts in `sql/mssql/` in numerical order:
   * `01_schema.sql` (Creates database `ProviderData`, tables, indexes, and base view).
   * `02_npi_luhn.sql` (Creates the `dbo.fn_npi_is_valid` check digit function).
   * `03_quality_rules.sql` (Creates `dbo.vw_quality_rule_failures` with all 14 rules).
   * `04_failure_report.sql` (Creates `dbo.usp_GetProviderQualitySummary` and `dbo.usp_GetProviderQualityDetails`).
   * `05_VendorReportExport.sql` (Creates `dbo.usp_ExportVendorData`).

---

### Step 2: Run Data Ingestion & Migration
From your terminal in the repository root:

```bash
# 1. Install dependencies
pip install pyodbc pytest

# 2. Ingest from CMS NPI API and load directly into SQL Server
python src/provider_pipeline/mssql_loader.py
```

---

### Step 3: Run Automated Parity Tests
Verify that the database ingested the active cohort cleanly and that all stored procedures return expected counts:

```bash
python -m pytest tests/test_mssql_parity.py -v
```

---

### Step 4: Deploy SSRS Reports & Configure Subscriptions
1. Open `ProviderReports/ProviderReports.sln` in **Visual Studio 2022**.
2. Set project Target Server URL to `http://localhost/ReportServer` and Target Folder to `ProviderReports`.
3. Right-click the project -> click **Deploy**.
4. In your browser, open `http://localhost/Reports`:
   * Navigate to `Data Sources/dsProviderData` -> **Manage** -> enter Windows stored credentials (`BIG-KENSHI\ofili`).
   * Navigate to `ProviderReports/Vendor_Extract_Colorado_Cardiology` -> **Manage** -> **Subscriptions** -> configure recurring monthly CSV drops to your network share (e.g. `\\localhost\VendorExports` or `\\localhost\Exports`).
5. Ensure the **SQL Server Agent (MSSQLSERVER01)** service is running in Windows Services (`services.msc`).

---

## Baseline Parity & Audit Verification

A live run across 6 regional searches (Cardiovascular Disease and Dermatology in Denver, Aurora, and Boulder, CO) captures **603 unique providers** from the federal registry (reflecting live registry growth from the initial 601 benchmark).

To audit data parity directly in SSMS, execute `tests/Reconcilliation.sql`:

```sql
USE ProviderData;
EXEC dbo.usp_GetProviderQualitySummary @Specialty = '(All)', @City = '(All)', @StaleYears = 5;
```

### Baseline Audit Results (603 Unique Providers)

| Quality Rule | Severity | Status | Flagged Count | Share of Directory | Operational Finding / Impact |
|---|---|---|---|---|---|
| `malformed_npi` | Error | **PASS** | `0` | `0.0%` | All records adhere to 10-digit standard. |
| `invalid_npi_check_digit` | Error | **PASS** | `0` | `0.0%` | All records satisfy Luhn prefix `80840` checksum. |
| `missing_name` | Error | **PASS** | `0` | `0.0%` | Provider names fully populated. |
| `missing_location_address` | Error | **PASS** | `0` | `0.0%` | Practice location physical addresses present. |
| `stale_record` (5+ years) | Warning | **WARNING** | **`292`** | **`48.4%`** | **Critical freshness risk:** Nearly half the directory has not re-attested in 5+ years. |
| `missing_credential` | Warning | **WARNING** | **`18`** | **`3.0%`** | Individual (`NPI-1`) physicians lacking degree title (MD/DO). |
| `possible_duplicate_providers` | Warning | **WARNING** | **`2`** | **`< 1.0%`** | Identical provider name and facility sharing two NPIs. |
| *All Other 7 Warning Rules* | Warning | **PASS** | `0` | `0.0%` | Clean phone, ZIP, status, taxonomy, and address records. |
| **Total Monitored Cohort** | | | **`603`** | **`100.0%`** | **Parity Confirmed Across 603 Records** |

---

## Documentation Index

* **[docs/reports\_specs.md](https://www.google.com/search?q=docs%2Freports_specs.md)**: Report Requirements Specification detailing stakeholder personas, monthly SLAs, parameter definitions, and remediation workflows.
* **[docs/integration-guide.md](https://www.google.com/search?q=docs%2Fintegration-guide.md)**: Full Technical Integration Guide covering T-SQL type mappings, index design, stored procedure schemas, and environment troubleshooting.
* **[docs/sample-run.md](https://www.google.com/search?q=docs%2Fsample-run.md)**: Empirical sample run log and baseline verification audit.
