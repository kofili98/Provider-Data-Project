USE ProviderData;
GO

CREATE OR ALTER PROCEDURE dbo.usp_ExportVendorData
    @Specialty NVARCHAR(100) = 'Cardiovascular',
    @State VARCHAR(10) = 'CO'
AS
BEGIN
    SET NOCOUNT ON;

    SELECT 
        pe.npi,
        pe.provider_name,
        pe.credential,
        pe.address_1,
        pe.city,
        pe.state,
        pe.postal_code,
        pe.telephone,
        pe.taxonomy_code,
        pe.taxonomy_description
    FROM dbo.provider_export pe
    WHERE (@State IS NULL OR pe.state = TRIM(@State))
      -- Substring search: finds 'Cardiovascular' anywhere in strings like 'Internal Medicine, Cardiovascular Disease'
      AND (@Specialty IS NULL OR pe.taxonomy_description LIKE '%' + TRIM(@Specialty) + '%')
      -- Enforce Data Quality Gate: filter out critical error records
      AND pe.npi NOT IN (
          SELECT npi FROM dbo.vw_quality_rule_failures WHERE severity = 'error'
      )
    ORDER BY pe.provider_name;
END;
GO