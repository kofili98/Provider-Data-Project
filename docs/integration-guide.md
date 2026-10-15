# Integration Guide: Enterprise SQL Server & SSRS Reporting Suite

## 1. Architectural Overview

This project provides an end-to-end data pipeline and enterprise reporting suite for healthcare provider directories (NPI Registry). 

Originally built as a Python CLI tool using SQLite, the architecture has expanded into an **Enterprise SQL Server (T-SQL) and SQL Server Reporting Services (SSRS)** platform supporting regulatory audits (CMS & No Surprises Act) and automated external vendor data feeds.

```
                              [ CMS NPI Registry API (v2.1) ]
                                             │
                                             ▼
                              [ Python Pipeline / pyodbc Ingestion ]
                                             │
                                             ▼
                      [ Microsoft SQL Server 2025 (ProviderData) ]
                      ├── Core Tables: providers, addresses, taxonomies
                      ├── Quality Logic: dbo.fn_npi_is_valid (Luhn UDF)
                      ├── Unified Rules: dbo.vw_quality_rule_failures
                      └── Stored Procs: Summary, Detail, Vendor Export
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
         [ SSRS Web Portal & Reports ]              [ Automated Scheduling & Extracts ]
         ├── Provider_Data_Quality_Summary.rdl      ├── SQL Server Agent (MSSQLSERVER01)
         ├── Provider_Data_Quality_Detail.rdl       └── Monthly CSV Subscription Drop
         └── Vendor_Extract_Colorado_Cardiology.rdl      (\\VendorExports\Vendor_Extract_*.csv)
```

---

## 2. Prerequisites & Environment Setup

* **Python**: Version 3.11 or newer.
* **Database Driver**: Microsoft ODBC Driver 18 for SQL Server (`msodbcsql18`).
* **Python Libraries**: `pyodbc>=5.0.0`, `pytest>=8.0.0` (install via `pip install pyodbc pytest`).
* **Database Engine**: Microsoft SQL Server 2022 / 2025 Developer Edition (named instance: `localhost\MSSQLSERVER01`).
* **Management Client**: SQL Server Management Studio (SSMS 20+).
* **Reporting Services**: Microsoft SQL Server Reporting Services (SSRS 2022) or Power BI Report Server.
* **Report Authoring**: Visual Studio 2022 with the *Microsoft Reporting Services Projects* extension (or Microsoft Report Builder).

---

## 3. Database Migration: SQLite to SQL Server (T-SQL)

### 3.1. Data Type & Schema Mappings

SQLite uses dynamic typing (`TEXT`, `INTEGER`). T-SQL requires explicit precision, collation, foreign keys with cascading deletes, and clustered/non-clustered indexes:

| Table / Field | SQLite Type | SQL Server (T-SQL) Type | Index & Constraints | Description |
|---|---|---|---|---|
| `providers.npi` | `TEXT` | `VARCHAR(10)` | `PRIMARY KEY CLUSTERED` | 10-digit National Provider Identifier |
| `providers.entity_type_code` | `TEXT` | `VARCHAR(10)` | `NOT NULL` | `NPI-1` (Individual) or `NPI-2` (Organization) |
| `providers.provider_name` | `TEXT` | `NVARCHAR(250)` | Nullable | Organization or composite First/Middle/Last |
| `providers.credential` | `TEXT` | `NVARCHAR(50)` | Nullable | Medical degree (MD, DO, NP, etc.) |
| `providers.enumeration_date`| `TEXT` | `DATE` | Nullable | Initial NPI issue date (YYYY-MM-DD) |
| `providers.last_updated_date`| `TEXT`| `DATE` | `NONCLUSTERED INDEX` | Date of last registry update |
| `providers.status` | `TEXT` | `VARCHAR(10)` | Nullable | `A` = Active |
| `providers.source_run_id` | `TEXT` | `VARCHAR(50)` | `NOT NULL` | Ingestion timestamp for data lineage |
| `addresses.id` | `INTEGER` | `INT IDENTITY(1,1)` | `PRIMARY KEY CLUSTERED` | Auto-incrementing primary key |
| `addresses.npi` | `TEXT` | `VARCHAR(10)` | `FK` to `providers(npi) ON DELETE CASCADE` | Parent provider reference |
| `addresses.address_purpose` | `TEXT` | `VARCHAR(20)` | `NOT NULL` | `LOCATION` (practice) or `MAILING` |
| `addresses.postal_code` | `TEXT` | `VARCHAR(20)` | Nullable | 5-digit, 9-digit, or ZIP+4 |
| `addresses.telephone` | `TEXT` | `VARCHAR(30)` | Nullable | Phone number |
| `taxonomies.id` | `INTEGER` | `INT IDENTITY(1,1)` | `PRIMARY KEY CLUSTERED` | Auto-incrementing primary key |
| `taxonomies.primary_flag` | `TEXT` | `CHAR(1)` | `CHECK IN ('Y', 'N')` | `Y` = Primary specialty |
| `taxonomies.description` | `TEXT` | `NVARCHAR(255)`| Nullable | Taxonomy specialty title |

### 3.2. Clustered & Covering Indexes (`01_schema.sql`)
```sql
CREATE NONCLUSTERED INDEX IX_addresses_npi_purpose 
    ON dbo.addresses (npi, address_purpose)
    INCLUDE (address_1, city, state, postal_code, telephone);

CREATE NONCLUSTERED INDEX IX_taxonomies_npi_primary 
    ON dbo.taxonomies (npi, primary_flag)
    INCLUDE (code, description);
```

### 3.3. Base Export View (`dbo.provider_export`)
The export view extracts exactly one location address and one primary taxonomy per provider, utilizing T-SQL `OUTER APPLY` for optimal query execution plans:
```sql
CREATE OR ALTER VIEW dbo.provider_export AS
SELECT 
    p.npi, p.entity_type_code, p.provider_name, p.credential, p.status, p.last_updated_date,
    a.address_1, a.city, a.state, a.postal_code, a.telephone,
    t.code AS taxonomy_code, t.description AS taxonomy_description
FROM dbo.providers p
OUTER APPLY (
    SELECT TOP 1 a1.address_1, a1.city, a1.state, a1.postal_code, a1.telephone
    FROM dbo.addresses a1
    WHERE a1.npi = p.npi AND a1.address_purpose = 'LOCATION'
    ORDER BY a1.id ASC
) a
OUTER APPLY (
    SELECT TOP 1 t1.code, t1.description
    FROM dbo.taxonomies t1
    WHERE t1.npi = p.npi AND t1.primary_flag = 'Y'
    ORDER BY t1.id ASC
) t;
GO
```

---

## 4. Porting the 14 Quality Rules to T-SQL

### 4.1. Syntax & Engine Translations

| Quality Rule | SQLite Syntax (`validations.sql`) | T-SQL Port (`sql/mssql/`) | Technical Rationale |
|---|---|---|---|
| **Luhn Check Digit** | `npi_is_valid(npi) = 0` (Python C hook) | `dbo.fn_npi_is_valid(npi) = 0` (`02_npi_luhn.sql`) | T-SQL has no native Luhn algorithm; ported as an in-database scalar function. |
| **Pattern Matching** | `npi GLOB '*[^0-9]*'` | `npi LIKE '%[^0-9]%'` (`03_quality_rules.sql`) | T-SQL uses `LIKE` wildcards with negated character sets `[^0-9]`. |
| **ZIP+4 Regex** | `postal_code GLOB '[0-9]...-[0-9]...'` | `postal_code LIKE '[0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'` | Evaluates formatted 10-character ZIP+4 strings. |
| **Duplicate Match** | `(name, addr, zip) IN (SELECT ...)` | `INNER JOIN (SELECT ... GROUP BY ... HAVING COUNT(*) > 1)` | T-SQL does not support row-value tuple constructors in `IN` predicates. |
| **Staleness Math** | `date('now', '-5 years')` | `DATEADD(year, -@StaleYears, CAST(GETDATE() AS DATE))` | Dynamic date arithmetic parameterized for custom reporting thresholds. |
| **Substring Extraction** | `substr(postal_code, 1, 5)` | `SUBSTRING(postal_code, 1, 5)` | Standard T-SQL string slicing. |
| **Whitespace Trim** | `trim(field)` | `TRIM(field)` or `LTRIM(RTRIM(field))` | Handles leading/trailing spaces across all SQL Server versions. |

### 4.2. Luhn Check Digit Function (`02_npi_luhn.sql`)
CMS NPIs are 10-digit identifiers where the 10th digit is a checksum calculated using the Luhn formula prefixed with the constant `80840` (making 15 total digits):
```sql
CREATE OR ALTER FUNCTION dbo.fn_npi_is_valid (@npi VARCHAR(20))
RETURNS BIT
AS
BEGIN
    IF @npi IS NULL OR LEN(@npi) <> 10 OR @npi LIKE '%[^0-9]%' RETURN 0;

    DECLARE @full VARCHAR(15) = '80840' + @npi;
    DECLARE @total INT = 0, @i INT = 1, @digit INT;

    WHILE @i <= 15
    BEGIN
        SET @digit = CAST(SUBSTRING(@full, 16 - @i, 1) AS INT);
        IF (@i % 2) = 0
        BEGIN
            SET @digit = @digit * 2;
            IF @digit > 9 SET @digit = @digit - 9;
        END
        SET @total = @total + @digit;
        SET @i = @i + 1;
    END

    RETURN CASE WHEN (@total % 10) = 0 THEN 1 ELSE 0 END;
END;
GO
```

---

## 5. Modular T-SQL Architecture & Stored Procedures

The T-SQL layer in `sql/mssql/` is cleanly partitioned into 5 modular scripts:

1. **`01_schema.sql`**: Core table definitions, clustered/non-clustered indexes, and `dbo.provider_export` view.
2. **`02_npi_luhn.sql`**: Scalar checksum function (`dbo.fn_npi_is_valid`).
3. **`03_quality_rules.sql`**: Unified failure view (`dbo.vw_quality_rule_failures`) evaluating all 14 data quality rules.
4. **`04_failure_report.sql`**: Stored procedures for SSRS reporting:
   * **`dbo.usp_GetProviderQualitySummary`**: Aggregates pass/fail status, flagged counts, and cohort totals across all 14 rules.
   * **`dbo.usp_GetProviderQualityDetails`**: Powers drill-through exception queues returning provider contact details, `years_since_update`, and specific failure triggers.
5. **`05_VendorReportExport.sql`**: Stored procedure `dbo.usp_ExportVendorData` supporting substring matching (`LIKE '%' + @Specialty + '%'`) and automated suppression of records failing `error`-level quality rules.

---

## 6. SSRS Report Development & Portal Deployment

### 6.1. Visual Studio Solution Architecture
Reports are organized in `ProviderReports/ProviderReports.sln`:
* **`dsProviderData.rds`**: Shared Data Source connecting to `localhost\MSSQLSERVER01;Initial Catalog=ProviderData;Integrated Security=True;TrustServerCertificate=True;`.
* **`Provider_Data_Quality_Summary.rdl`**: Executive dashboard with KPI tiles, pass/fail matrix, and staleness histogram.
* **`Provider_Data_Quality_Detail.rdl`**: Drill-through exception report with dynamic staleness wording.
* **`Vendor_Extract_Colorado_Cardiology.rdl`**: Headless CSV feed.

### 6.2. Deployment Runbook
1. Open Project Properties in Visual Studio:
   * **`TargetServerURL`**: `http://localhost/ReportServer` (Backend web service).
   * **`TargetReportFolder`**: `ProviderReports`.
   * **`TargetDataSourceFolder`**: `Data Sources`.
2. Right-click the project -> click **Deploy**.
3. Configure Stored Credentials on the Web Portal:
   * Navigate to `http://localhost/Reports` -> `Data Sources` -> `dsProviderData` -> **Manage**.
   * Under **Credentials**, select **Using the following credentials** -> enter Windows account (`BIG-KENSHI\ofili`) -> click **Test connection** -> **Save**.
   * *(Stored credentials are required for unattended SQL Server Agent execution).*

---

## 7. Monthly Automation & Scheduling Runbook

### 7.1. Orchestration Cadence (1st of Each Month)
```
02:00 MT: SQL Agent executes Python Ingest (API -> SQL Server)
06:00 MT: SQL Agent triggers SSRS Vendor CSV Subscription Drop
```

### 7.2. SQL Server Agent Job Setup
* **Job Name**: `Job_Sync_Provider_Data_And_Reports`
* **Step 1 (CmdExec)**:
  ```cmd
  python src/provider_pipeline/mssql_loader.py
  ```
* **Step 2 (T-SQL)**: Trigger the native SSRS Subscription Schedule event:
  ```sql
  USE ReportServer;
  EXEC dbo.AddEvent 
      @EventType = 'SharedSchedule', 
      @EventData = '<Subscription-Schedule-GUID>';
  ```

---

## 8. Testing, Parity & Count Reconciliation

To verify that the SQL Server migration maintained 100% data parity across the active **603-provider cohort** (capturing live registry additions alongside the 601 baseline), execute `tests/Reconcilliation.sql` in SSMS:

```sql
USE ProviderData;
GO

DECLARE @Summary TABLE (
    rule_name VARCHAR(50), severity VARCHAR(10), flagged_count INT,
    total_evaluated INT, rule_status VARCHAR(10)
);

INSERT INTO @Summary
EXEC dbo.usp_GetProviderQualitySummary @Specialty = '(All)', @City = '(All)', @StaleYears = 5;

SELECT 
    rule_name,
    flagged_count AS sql_count,
    CASE rule_name
        WHEN 'stale_record' THEN 292
        WHEN 'missing_credential' THEN 18
        WHEN 'possible_duplicate_providers' THEN 2
        ELSE 0
    END AS baseline_sqlite_count,
    CASE 
        WHEN flagged_count = CASE rule_name
            WHEN 'stale_record' THEN 292
            WHEN 'missing_credential' THEN 18
            WHEN 'possible_duplicate_providers' THEN 2
            ELSE 0
        END THEN 'PASS (Parity Confirmed)'
        ELSE 'FAIL (Count Discrepancy)'
    END AS parity_audit
FROM @Summary;
```

* **Live Audit Results**:
  * Total Unique Providers: **`603`**
  * Critical Errors (4 rules): **`0`**
  * `stale_record`: **`292`** (48.4%)
  * `missing_credential`: **`18`** (3.0%)
  * `possible_duplicate_providers`: **`2`** (< 1.0%)
  * All Other Warnings: **`0`**

Automated Python testing is executed via:
```bash
python -m pytest tests/test_mssql_parity.py -v
```

---

## 9. Comprehensive Troubleshooting Guide

| Issue / Symptom | Root Cause | Resolution |
|---|---|---|
| `The network name cannot be found` on subscription run | Windows File Share delivery requires a UNC network path (`\\Server\Share`), not a local drive letter (`C:\...`). | Share the destination folder in Windows (e.g. `D:\VendorExports` shared as `VendorExports`), grant Modify permissions, and set Path to `\\localhost\VendorExports`. |
| `The certificate chain was issued by an authority that is not trusted` | ODBC Driver 18 and SSMS 20 require TLS encryption by default on self-signed local certificates. | Check **Trust server certificate** in SSMS connection options; append `TrustServerCertificate=yes;` to Python connection strings. |
| `The SQL Agent service is not running` | SQL Server Agent startup type is set to Manual on Developer Edition installations. | Open `services.msc`, locate `SQL Server Agent (MSSQLSERVER01)`, set Startup type to **Automatic**, and click **Start**. |
| `Subscription can't be created ... credentials are not stored` | Data source uses Windows Integrated authentication; background jobs cannot prompt a human. | Open `http://localhost/Reports` -> `Data Sources/dsProviderData` -> **Manage** -> set to **Using the following credentials** and save Windows login. |
| `Forward dependencies are not valid` on parameter `RuleName` | Circular dependency in report parameter setup (e.g. default value set to `=Parameters!RuleName.Value`). | In `Provider_Data_Quality_Detail.rdl`, set `RuleName` Available Values to **None**, and Default Values to static text **`(All)`**. |
| Vendor extract query returns 0 rows | Exact string matching (`= 'Cardiovascular Disease'`) failed against composite titles (`Internal Medicine, Cardiovascular Disease`). | Use substring matching: `taxonomy_description LIKE '%' + TRIM(@Specialty) + '%'`. |
