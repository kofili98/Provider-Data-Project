USE ProviderData;
GO

CREATE OR ALTER VIEW dbo.vw_quality_rule_failures AS

-- Rule 1: malformed_npi (error)
SELECT npi, 'malformed_npi' AS rule_name, 'error' AS severity, 'NPI is not exactly 10 numeric digits' AS failure_reason
FROM dbo.providers
WHERE LEN(npi) <> 10 OR npi LIKE '%[^0-9]%'

UNION ALL
-- Rule 2: invalid_npi_check_digit (error)
SELECT npi, 'invalid_npi_check_digit', 'error', 'Check digit validation failed (Luhn prefix 80840)'
FROM dbo.providers
WHERE LEN(npi) = 10 AND npi NOT LIKE '%[^0-9]%' AND dbo.fn_npi_is_valid(npi) = 0

UNION ALL
-- Rule 3: missing_name (error)
SELECT npi, 'missing_name', 'error', 'Missing provider or organization name'
FROM dbo.providers
WHERE provider_name IS NULL OR TRIM(provider_name) = ''

UNION ALL
-- Rule 4: missing_location_address (error)
SELECT p.npi, 'missing_location_address', 'error', 'No practice (LOCATION) address on file'
FROM dbo.providers p
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.addresses a 
    WHERE a.npi = p.npi AND a.address_purpose = 'LOCATION'
)

UNION ALL
-- Rule 5: no_primary_taxonomy (warning)
SELECT p.npi, 'no_primary_taxonomy', 'warning', 'No primary taxonomy specialty marked'
FROM dbo.providers p
WHERE (
    SELECT COUNT(*) FROM dbo.taxonomies t 
    WHERE t.npi = p.npi AND t.primary_flag = 'Y'
) = 0

UNION ALL
-- Rule 6: multiple_primary_taxonomies (warning)
SELECT p.npi, 'multiple_primary_taxonomies', 'warning', 'More than one primary taxonomy specialty marked'
FROM dbo.providers p
WHERE (
    SELECT COUNT(*) FROM dbo.taxonomies t 
    WHERE t.npi = p.npi AND t.primary_flag = 'Y'
) > 1

UNION ALL
-- Rule 7: missing_phone (warning)
SELECT DISTINCT npi, 'missing_phone', 'warning', 'Practice location phone is missing or blank'
FROM dbo.addresses
WHERE address_purpose = 'LOCATION' 
  AND (telephone IS NULL OR TRIM(telephone) IN ('', '--'))

UNION ALL
-- Rule 8: bad_postal_format (warning)
SELECT DISTINCT npi, 'bad_postal_format', 'warning', 'Postal code does not match 5-digit, 9-digit, or ZIP+4 pattern'
FROM dbo.addresses
WHERE address_purpose = 'LOCATION' AND postal_code IS NOT NULL
  AND NOT (
    (LEN(postal_code) IN (5, 9) AND postal_code NOT LIKE '%[^0-9]%')
    OR postal_code LIKE '[0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]'
  )

UNION ALL
-- Rule 9: inactive_status (warning)
SELECT npi, 'inactive_status', 'warning', 'Registry status is not Active (status <> A)'
FROM dbo.providers
WHERE status IS NULL OR status <> 'A'

UNION ALL
-- Rule 10: duplicate_addresses (warning)
SELECT npi, 'duplicate_addresses', 'warning', 'Exact duplicate practice address listed multiple times'
FROM dbo.addresses
GROUP BY npi, address_purpose, UPPER(address_1), UPPER(city), state, postal_code
HAVING COUNT(*) > 1

UNION ALL
-- Rule 11: possible_duplicate_providers (warning - converted from SQLite row tuple)
SELECT k.npi, 'possible_duplicate_providers', 'warning', 'Possible duplicate provider (identical name, address, and 5-digit ZIP with different NPI)'
FROM (
    SELECT p.npi,
           UPPER(TRIM(p.provider_name)) AS name_key,
           UPPER(TRIM(a.address_1)) AS addr_key,
           SUBSTRING(a.postal_code, 1, 5) AS zip_key
    FROM dbo.providers p
    JOIN dbo.addresses a ON a.npi = p.npi AND a.address_purpose = 'LOCATION'
    WHERE p.provider_name IS NOT NULL AND a.address_1 IS NOT NULL
) k
INNER JOIN (
    SELECT UPPER(TRIM(p2.provider_name)) AS name_key,
           UPPER(TRIM(a2.address_1)) AS addr_key,
           SUBSTRING(a2.postal_code, 1, 5) AS zip_key
    FROM dbo.providers p2
    JOIN dbo.addresses a2 ON a2.npi = p2.npi AND a2.address_purpose = 'LOCATION'
    WHERE p2.provider_name IS NOT NULL AND a2.address_1 IS NOT NULL
    GROUP BY UPPER(TRIM(p2.provider_name)), UPPER(TRIM(a2.address_1)), SUBSTRING(a2.postal_code, 1, 5)
    HAVING COUNT(DISTINCT p2.npi) > 1
) d ON k.name_key = d.name_key AND k.addr_key = d.addr_key AND k.zip_key = d.zip_key

UNION ALL
-- Rule 12: stale_record (warning - 5+ year baseline)
SELECT npi, 'stale_record', 'warning', 'Provider registry entry last updated more than 5 years ago'
FROM dbo.providers
WHERE last_updated_date IS NOT NULL 
  AND last_updated_date < DATEADD(year, -5, CAST(GETDATE() AS DATE))

UNION ALL
-- Rule 13: missing_credential (warning)
SELECT npi, 'missing_credential', 'warning', 'Individual practitioner (NPI-1) missing credential/degree'
FROM dbo.providers
WHERE entity_type_code = 'NPI-1' AND (credential IS NULL OR TRIM(credential) = '')

UNION ALL
-- Rule 14: po_box_location (warning)
SELECT DISTINCT npi, 'po_box_location', 'warning', 'Practice location address indicates a PO Box instead of a physical office'
FROM dbo.addresses
WHERE address_purpose = 'LOCATION'
  AND (UPPER(address_1) LIKE 'PO BOX%' OR UPPER(address_1) LIKE 'P.O. BOX%' OR UPPER(address_1) LIKE 'P O BOX%');
GO

/* =========================================================================
     STORED PROCEDURE: SUMMARY REPORT DATASET
   ========================================================================= */
CREATE OR ALTER PROCEDURE dbo.usp_GetProviderQualitySummary
    @Specialty NVARCHAR(255) = '(All)',
    @City NVARCHAR(100) = '(All)',
    @StaleYears INT = 5
AS
BEGIN
    SET NOCOUNT ON;

    -- Master list of all 14 rules to guarantee every rule appears in the output
    DECLARE @AllRules TABLE (rule_name VARCHAR(50), severity VARCHAR(10), sort_order INT);
    INSERT INTO @AllRules VALUES
        ('malformed_npi', 'error', 1),
        ('invalid_npi_check_digit', 'error', 2),
        ('missing_name', 'error', 3),
        ('missing_location_address', 'error', 4),
        ('no_primary_taxonomy', 'warning', 5),
        ('multiple_primary_taxonomies', 'warning', 6),
        ('missing_phone', 'warning', 7),
        ('bad_postal_format', 'warning', 8),
        ('inactive_status', 'warning', 9),
        ('duplicate_addresses', 'warning', 10),
        ('possible_duplicate_providers', 'warning', 11),
        ('stale_record', 'warning', 12),
        ('missing_credential', 'warning', 13),
        ('po_box_location', 'warning', 14);

    -- Base filtered cohort based on report parameters
    WITH FilteredCohort AS (
        SELECT pe.npi, pe.last_updated_date
        FROM dbo.provider_export pe
        WHERE (@Specialty IS NULL OR @Specialty = '(All)' OR pe.taxonomy_description = @Specialty)
          AND (@City IS NULL OR @City = '(All)' OR pe.city = @City)
    ),
    DynamicFailures AS (
        -- Static rule failures filtered by cohort
        SELECT f.rule_name, f.npi
        FROM dbo.vw_quality_rule_failures f
        JOIN FilteredCohort c ON f.npi = c.npi
        WHERE f.rule_name <> 'stale_record'
        UNION ALL
        -- Dynamic staleness rule based on @StaleYears parameter
        SELECT 'stale_record' AS rule_name, c.npi
        FROM FilteredCohort c
        WHERE c.last_updated_date IS NOT NULL 
          AND c.last_updated_date < DATEADD(year, -@StaleYears, CAST(GETDATE() AS DATE))
    )
    SELECT 
        r.rule_name,
        r.severity,
        COUNT(DISTINCT df.npi) AS flagged_count,
        (SELECT COUNT(*) FROM FilteredCohort) AS total_records_evaluated,
        CASE 
            WHEN COUNT(DISTINCT df.npi) = 0 THEN 'PASS'
            WHEN r.severity = 'error' THEN 'FAIL'
            ELSE 'WARNING'
        END AS rule_status
    FROM @AllRules r
    LEFT JOIN DynamicFailures df ON r.rule_name = df.rule_name
    GROUP BY r.rule_name, r.severity, r.sort_order
    ORDER BY r.sort_order;
END;
GO