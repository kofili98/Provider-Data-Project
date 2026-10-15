# Report Requirements Specification: Provider Directory Quality Suite

**Document Version:** 2.1  
**Effective Date:** October 2026  
**Cadence:** Monthly Generation & Audit Cycle  
**Owner:** Provider Data Governance & Operations Team  

---

## 1. Executive Summary & Purpose

Under the **No Surprises Act** and **CMS Provider Directory Compliance Mandates**, health plans and provider networks must maintain accurate, up-to-date provider directories, verifying information at least quarterly and publishing corrections promptly. 

This specification defines the functional and operational requirements for the **Provider Directory Quality Reporting Suite**, deployed via **SQL Server Reporting Services (SSRS)**. The suite transitions the provider data pipeline from a backend CLI data ingest into an enterprise reporting interface that:
1. Evaluates all active provider records against **14 standardized data quality rules**.
2. Surfaces data staleness trends across the **603-provider monitored cohort**, spotlighting records that have not been re-attested in **5+ years**.
3. Facilitates one-click operational drill-through to provider-level outreach lists.
4. Generates automated, data-quality-gated CSV extracts for external vendor and clearinghouse ingestion.

---

## 2. Stakeholders & Target Audience

| Persona | Role in Organization | How They Use the Reports |
|---|---|---|
| **Provider Data Steward** | Data Quality Analyst | Daily/weekly monitoring of exception queues; triggers outreach to clinics with missing phone numbers, PO boxes, or bad ZIP codes. |
| **Credentialing Specialist** | Network Operations | Reviews individual providers (`NPI-1`) flagged with `missing_credential` to verify degree and state licensing board status. |
| **Network Operations Manager** | Leadership / Compliance | Audits monthly compliance posture; tracks the 5+ year staleness cliff; signs off on directory publication. |
| **Downstream Trading Partners** | External Clearinghouses / Payers | Ingests monthly validated provider rosters via automated CSV file share drops. |

---

## 3. Reporting Suite Inventory

The reporting solution consists of three specialized `.rdl` artifacts hosted in the **`ProviderReports`** catalog on the SSRS web portal (`http://localhost/Reports`):

```
SSRS Report Portal (/ProviderReports)
│
├── 1. Provider_Data_Quality_Summary.rdl  (Executive Dashboard & Rule Matrix)
│       │
│       └── [Interactive Drill-Through] ──► 2. Provider_Data_Quality_Detail.rdl (Record Drill-Down)
│
└── 3. Vendor_Extract_Colorado_Cardiology.rdl (Automated Monthly CSV Feed)
```

### 3.1. Summary Report (`Provider_Data_Quality_Summary.rdl`)
* **Role:** High-level executive dashboard and interactive compliance scorecard.
* **Layout Structure:**
  * **Top KPI Scorecards:** Four metric tiles displaying Total Providers Monitored (`603`), Critical Errors (`0`), Warnings (`312`), and Stale Records count (`292`).
  * **Pass/Fail Quality Matrix:** Tablix displaying all 14 data quality rules, severity ratings (`error` vs `warning`), flagged provider counts, percentage of directory, and color-coded status badges (`PASS` in green, `FAIL` in red, `WARNING` in amber).
  * **Staleness Horizon Chart:** Clustered column chart plotting provider counts across five age tiers (`< 1 Year`, `1 - 3 Years`, `3 - 5 Years`, `5 - 7 Years`, `7+ Years`). Buckets $\ge 5$ years are highlighted in red to spotlight directory freshness decay.
  * **Drill-Through Actions:** Clicking any rule name or flagged count automatically launches the Detail report pre-filtered to those providers.

### 3.2. Detail Drill-Through Report (`Provider_Data_Quality_Detail.rdl`)
* **Role:** Actionable provider remediation queue for data stewards.
* **Layout Structure:**
  * **Navigation Header:** "← Back to Quality Summary Dashboard" link preserving user filter context.
  * **Dynamic Title:** Reflects the active rule filter and staleness tier.
  * **Provider Remediation Table:** Columns for NPI, Full Provider Name, Credential, Primary Taxonomy/Specialty, Practice Location (Address, City, State, ZIP), Telephone, Last Update Date, and Detailed Failure Reason.
  * **Dynamic Staleness Text:** Translates raw timestamps into standardized operational phrasing:
    * `< 1 Year`: *"Record updated less than a year ago"*
    * `1 - 3 Years`: *"Record updated less than 3 years ago"*
    * `3 - 5 Years`: *"Record updated less than 5 years ago"*
    * $\ge 5$ Years: *"Record updated more than 5 years ago"*

### 3.3. External Vendor Extract (`Vendor_Extract_Colorado_Cardiology.rdl`)
* **Role:** Headless, tabular data export formatted for external vendor file drops.
* **Layout Structure:** Single table bound to `dbo.usp_ExportVendorData` (`05_VendorReportExport.sql`) with zero margins, zero headers/footers, and strict comma-delimited CSV formatting.
* **Quality Gate:** Built-in SQL suppression excluding any provider record failing an `error`-severity rule.

---

## 4. Parameter Architecture & Logic

All report queries run against stored procedures in the `ProviderData` database on SQL Server (defined in `04_failure_report.sql` and `05_VendorReportExport.sql`):

| Parameter Name | Data Type | Default Value | UI Prompt Label | Available Values / Source |
|---|---|---|---|---|
| **`@Specialty`** | `String` | `(All)` | Primary Specialty | Dropdown populated via `SELECT '(All)' UNION SELECT DISTINCT taxonomy_description FROM dbo.provider_export` |
| **`@City`** | `String` | `(All)` | Practice City | Dropdown populated via `SELECT '(All)' UNION SELECT DISTINCT city FROM dbo.provider_export` |
| **`@StaleYears`** | `Integer` | `5` | Staleness Threshold (Years) | User integer prompt (default 5 years per CMS historical freshness benchmark) |
| **`@RuleName`** | `String` | `(All)` | Quality Rule Filter | Passed behind the scenes via drill-through click; optional dropdown in Detail view |
| **`@State`** | `String` | `CO` | State Code | Fixed or prompted on vendor extract report |

---

## 5. Cadence, Delivery & Operational SLAs

### 5.1. Refresh Cadence: Monthly Cycle
* **Pipeline Ingestion:** The 1st calendar day of every month at 02:00 Mountain Time, an automated SQL Server Agent job executes the Python CLI ingestion pipeline, harvesting updated records from the CMS NPI Registry API and loading them into SQL Server.
* **Cohort Scale:** Monitored cohort active baseline reflects **603 unique providers** across regional searches.
* **Report Dataset Cache Refresh:** The SSRS reporting catalog reflects the fresh monthly run immediately upon ingestion completion.

### 5.2. Subscription & Automated File Distribution
* **Target Delivery:** The 1st calendar day of every month at 06:00 Mountain Time.
* **Destination:** Windows File Share (`\\localhost\VendorExports` or dedicated storage volume).
* **Naming Convention:** `Vendor_Extract_Colorado_Cardiology_YYYY_MM_DD.csv`.
* **Execution Engine:** SQL Server Agent (`SQL Server Agent (MSSQLSERVER01)`) triggering native SSRS Shared Schedule events.

### 5.3. Remediation Workflow & SLAs
1. **Critical Errors (`FAIL`):** Resolution SLA = **48 hours**. Records with malformed NPIs, invalid Luhn check digits, or missing names/locations are suppressed from public directories until corrected.
2. **Stale Records ($\ge 5$ Years):** Resolution SLA = **30 days** (within current monthly cycle). Data stewards dispatch digital re-attestation notices to practice clinics.
3. **Missing Credentials (`missing_credential`):** Resolution SLA = **10 business days**. Credentialing specialists verify state medical board licensing registries.

---

## 6. Access Control & Security Matrix

Access to the SSRS Web Portal (`http://localhost/Reports`) is governed by role-based security:

| Role / Group | Assigned Persona | Permissions in Portal |
|---|---|---|
| **Content Manager** | Data Governance Lead, System Admin | Full control: publish reports, manage data sources, configure schedules, edit credentials. |
| **My Reports / Publisher** | Senior Data Engineers | Deploy and edit `.rdl` reports, run ad-hoc queries. |
| **Browser (Read-Only)** | Data Stewards, External Recruiters, Guests | View folders, run reports, view KPI cards, click drill-through links, export to PDF/Excel/CSV. Cannot edit or see connection passwords. |

* **Stored Credentials:** The shared data source (`dsProviderData`) utilizes stored Windows credentials (`BIG-KENSHI\ofili` or service account) with `TrustServerCertificate=True` to enable unattended subscription execution without exposing passwords to end-users.
