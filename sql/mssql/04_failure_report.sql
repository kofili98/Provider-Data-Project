USE ProviderData;
GO

CREATE OR ALTER PROCEDURE dbo.usp_GetProviderQualityDetails
    @RuleName VARCHAR(50) = '(All)',
    @Specialty NVARCHAR(255) = '(All)',
    @City NVARCHAR(100) = '(All)',
    @StaleYears INT = 5
AS
BEGIN
    SET NOCOUNT ON;

    WITH FilteredCohort AS (
        SELECT pe.*
        FROM dbo.provider_export pe
        WHERE (@Specialty IS NULL OR @Specialty = '(All)' OR pe.taxonomy_description = @Specialty)
          AND (@City IS NULL OR @City = '(All)' OR pe.city = @City)
    ),
    Failures AS (
        SELECT f.rule_name, f.severity, f.failure_reason, f.npi
        FROM dbo.vw_quality_rule_failures f
        WHERE f.rule_name <> 'stale_record'
        UNION ALL
        SELECT 'stale_record', 'warning', 
               CONCAT('Record last updated over ', @StaleYears, ' years ago'), 
               c.npi
        FROM FilteredCohort c
        WHERE c.last_updated_date IS NOT NULL
          AND c.last_updated_date < DATEADD(year, -@StaleYears, CAST(GETDATE() AS DATE))
    )
    SELECT 
        fc.npi,
        fc.provider_name,
        fc.entity_type_code,
        fc.credential,
        fc.status,
        fc.last_updated_date,
        DATEDIFF(year, fc.last_updated_date, GETDATE()) AS years_since_update,
        fc.taxonomy_code,
        fc.taxonomy_description,
        fc.address_1,
        fc.city,
        fc.state,
        fc.postal_code,
        fc.telephone,
        fl.rule_name,
        fl.severity,
        fl.failure_reason
    FROM FilteredCohort fc
    INNER JOIN Failures fl ON fc.npi = fl.npi
    WHERE (@RuleName IS NULL OR @RuleName = '(All)' OR fl.rule_name = @RuleName)
    ORDER BY fl.rule_name, fc.provider_name;
END;
GO