# Sample Run & Validation Audit Logs

This document records the empirical execution results of the provider data pipeline across both project phases:
1. **Original Baseline Run (September 24, 2026)**: Initial ingestion and data-quality audit using Python 3.14 and SQLite.
2. **Project Scope Expansion Run (October 15, 2026)**: Enterprise database migration to Microsoft SQL Server 2025, T-SQL quality rule porting, SSRS reporting interface validation, and automated CSV subscription delivery.

---

## 1. Original Baseline Run (September 24, 2026 — SQLite & CLI)

A real end-to-end run against the live CMS NPI Registry API using Python 3.14 on Windows and SQLite.

### 1.1. Ingestion Summary
Six regional searches across Colorado (Denver, Aurora, Boulder; Cardiovascular Disease and Dermatology), structured to remain beneath the API's 1,200-result pagination ceiling:

| Search Region & Specialty | Raw Records Returned | Notes |
|---|---|---|
| Denver, Cardiovascular Disease | 206 | Under ceiling |
| Aurora, Cardiovascular Disease | 157 | Under ceiling |
| Boulder, Cardiovascular Disease | 29 | Under ceiling |
| Denver, Dermatology | 145 | Under ceiling |
| Aurora, Dermatology | 89 | Under ceiling |
| Boulder, Dermatology | 39 | Under ceiling |
| **Raw Ingestion Total** | **665** | |
| **Unique Providers Loaded** | **601** | **De-duplicated on NPI** |

*No search was truncated. The 64 duplicates represent practitioners practicing across multiple municipalities (e.g. both Denver and Aurora); ingestion automatically de-duplicated on NPI.*

### 1.2. Quality Rule Validation
14 SQL rules executed via `provider-pipeline validate`. Result: `valid: true`. All four error-level rules returned 0 defects across the 601 records.

| Quality Rule | Severity | Providers Flagged | Directory Share | Operational Interpretation |
|---|---|---|---|---|
| `stale_record` | Warning | **292** | 48.6% | Registry entry unmodified in 5+ years (freshness risk). |
| `missing_credential` | Warning | **18** | 3.0% | Individual practitioners (`NPI-1`) missing degree (MD/DO). |
| `possible_duplicate_providers`| Warning | **2** | 0.3% | Identical provider name and location with different NPIs. |
| *All 11 Other Rules* | Error / Warn | **0** | 0.0% | Clean NPIs, checksums, names, physical locations, and phones. |

### 1.3. Issue Found and Resolved
An initial test query searched for specialty `Cardiology`. In the CMS registry, this taxonomy is cataloged as `Cardiovascular Disease`, yielding 0 results. Adding per-search record metrics to the ingestion summary diagnosed the issue, and correcting the term yielded 392 raw cardiovascular results.

### 1.4. SQLite Reproduction Runbook
```bash
provider-pipeline --database provider_data.db init-db
provider-pipeline --database provider_data.db ingest --query-file searches.json
provider-pipeline --database provider_data.db profile
provider-pipeline --database provider_data.db validate
provider-pipeline --database provider_data.db export --config configs/clients/colorado-cardiology.json --output-dir exports
```

---

## 2. Project Scope Expansion Run (October 15, 2026 — SQL Server 2025 & SSRS)

An enterprise deployment executing data migration to Microsoft SQL Server 2025 (`localhost\MSSQLSERVER01`), T-SQL quality logic compilation, and reporting validation on SQL Server Reporting Services (SSRS).

### 2.1. Live Re-Ingestion & Registry Growth (603 Providers)
Executing `python src/provider_pipeline/mssql_loader.py` queried the live CMS NPI Registry API and loaded records directly into SQL Server (`ProviderData`):

| Search Region & Specialty | Raw Records | Unique NPIs | Variance vs Sept 2026 |
|---|---|---|---|
| Denver, Cardiovascular Disease | 206 | — | Same |
| Aurora, Cardiovascular Disease | 157 | — | Same |
| Boulder, Cardiovascular Disease | 29 | — | Same |
| Denver, Dermatology | 147 | — | **+2 newly registered practitioners** |
| Aurora, Dermatology | 89 | — | Same |
| Boulder, Dermatology | 39 | — | Same |
| **Active Cohort Total** | **667** | **603** | **+2 net unique providers (601 ➔ 603)** |

*The pipeline absorbed the live registry growth seamlessly, upserting 603 unique providers into `dbo.providers` and matching 603 rows in `dbo.provider_export`.*

---

### 2.2. In-Database T-SQL Quality Engine Validation
Database scripts in `sql/mssql/` were executed in SSMS and verified:

1. **`01_schema.sql`**: Created tables (`providers`, `addresses`, `taxonomies`, `ingestion_runs`) with clustered/non-clustered indexes and `dbo.provider_export` view.
2. **`02_npi_luhn.sql`**: Implemented `dbo.fn_npi_is_valid`, validating the 15-digit Luhn algorithm prefixed with `80840`. Verified that valid NPI `1234567893` returned `1`, while bad check digits returned `0`.
3. **`03_quality_rules.sql`**: Deployed `dbo.vw_quality_rule_failures` porting all 14 rules to T-SQL (converting `GLOB` to `LIKE` and tuple `IN` subqueries to `INNER JOIN`).
4. **`04_failure_report.sql`**: Compiled reporting procedures `dbo.usp_GetProviderQualitySummary` and `dbo.usp_GetProviderQualityDetails`.
5. **`05_VendorReportExport.sql`**: Compiled `dbo.usp_ExportVendorData` with substring specialty matching (`LIKE '%Cardio%'`) and quality gating.

#### Automated Parity Reconciliation Query (`tests/Reconcilliation.sql`)
Executing the reconciliation script in SSMS yielded 100% parity against baseline quality findings:

```sql
USE ProviderData;
EXEC dbo.usp_GetProviderQualitySummary @Specialty = '(All)', @City = '(All)', @StaleYears = 5;
```

**Results:**
* `total_records_evaluated`: **603**
* `malformed_npi`, `invalid_npi_check_digit`, `missing_name`, `missing_location_address`: **0 (PASS)**
* `stale_record` (5+ years): **292 (WARNING, 48.4%)**
* `missing_credential`: **18 (WARNING, 3.0%)**
* `possible_duplicate_providers`: **2 (WARNING, < 1.0%)**
* All other 7 warning checks: **0 (PASS)**

---

### 2.3. Automated Python Test Suite (`test_mssql_parity.py`)
Executing `python -m pytest tests/test_mssql_parity.py -v` confirmed:
* `test_total_provider_volume`: **PASSED** (603 records confirmed).
* `test_provider_export_view_row_count`: **PASSED** (603 rows confirmed).
* `test_fn_npi_is_valid_udf`: **PASSED** (Valid/invalid checksum handling verified).
* `test_quality_rules_summary_parity`: **PASSED** (Parity verified across all 14 rules).
* `test_quality_details_drillthrough`: **PASSED** (18 credential exceptions and 2 duplicate exceptions verified).
* `test_vendor_extract_quality_gating`: **PASSED** (Substring filtering and error suppression verified).

---

### 2.4. SSRS Web Portal & Report Suite Execution
Published to `http://localhost/Reports` under catalog folder `/ProviderReports`:

1. **`Provider_Data_Quality_Summary.rdl`**:
   * Rendered KPI tiles: Monitored = `603`, Errors = `0`, Warnings = `312`, Stale = `292`.
   * Pass/Fail Matrix displayed all 14 rules with dynamic green/red/amber status styling.
   * Staleness Horizon column chart plotted age distribution, highlighting the 5+ year cliff (292 records) in red (`#C53030`).
2. **`Provider_Data_Quality_Detail.rdl`**:
   * Interactive drill-through confirmed: clicking the `292` count on the Summary dashboard opened the Detail report displaying the 292 stale records.
   * Dynamic staleness wording verified: rows correctly displayed *"Record updated more than 5 years ago"*.
   * Back-navigation link preserved active filters when returning to the Summary.
3. **`Vendor_Extract_Colorado_Cardiology.rdl`**:
   * Automated monthly Windows File Share subscription tested.
   * Rendered clean comma-delimited CSV drops to `\\localhost\VendorExports` with zero fatal quality errors.

---

## 3. Comparative Summary: Evolution & Baseline Parity

| Evaluation Metric | Baseline Run (Sept 2026) | Scope Expansion Run (Oct 2026) | Architecture Variance & Impact |
|---|---|---|---|
| **Storage Engine** | SQLite 3 (`provider_data.db`) | Microsoft SQL Server 2025 (`ProviderData`) | Enterprise relational database with clustered indexes and ACID concurrency. |
| **Ingestion Mechanism** | Python CLI (`provider-pipeline`) | Python + `pyodbc` (`fast_executemany = True`) | High-speed enterprise pipeline loading directly into SQL Server. |
| **Total Ingested Cohort** | 601 Unique Providers | **603 Unique Providers** | **+2 net providers** reflecting live federal registry additions. |
| **Checksum Verification** | Python hook (`npi_is_valid`) | T-SQL Scalar UDF (`dbo.fn_npi_is_valid`) | In-database 15-digit Luhn calculation with prefix `80840`. |
| **Quality Evaluation** | 14 Disjoint SQL Queries | Parameterized Stored Procedures | Consolidated procedures supporting dynamic filtering and drill-down. |
| **Fatal Errors (4 Rules)** | `0` (100% Valid) | **`0` (100% Valid)** | Complete parity maintained across database engines. |
| **Stale Records (5+ Yrs)** | `292` (48.6%) | **`292` (48.4%)** | Freshness risk identified and spotlighted visually in SSRS. |
| **Missing Credentials** | `18` (3.0%) | **`18` (3.0%)** | Remediation queue verified in drill-through detail report. |
| **Potential Duplicates** | `2` (< 1.0%) | **`2` (< 1.0%)** | Complex subquery rewritten into performant T-SQL `INNER JOIN`. |
| **User Interface** | Terminal JSON dumps | **SSRS Web Portal (3 `.rdl` Reports)** | Interactive executive scorecards, charts, and drill-through tables. |
| **Extract Automation** | On-demand CLI command | **SQL Server Agent & File Share Drop** | Unattended monthly scheduled CSV delivery (`\\localhost\VendorExports`). |
