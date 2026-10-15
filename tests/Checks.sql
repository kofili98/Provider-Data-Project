/*USE ProviderData;
SELECT COUNT(*) AS total_providers FROM dbo.providers;
SELECT COUNT(*) AS total_export_rows FROM dbo.provider_export;*/

/*USE ProviderData;
EXEC dbo.usp_GetProviderQualitySummary;*/

/*USE ProviderData;
EXEC dbo.usp_GetProviderQualityDetails @RuleName = 'missing_credential';*/

USE ProviderData;
EXEC dbo.usp_ExportVendorData @Specialty = 'Cardiovascular', @State = 'CO';

/*USE ProviderData;
SELECT DISTINCT state, taxonomy_description, COUNT(*) AS count
FROM dbo.provider_export
GROUP BY state, taxonomy_description;*/