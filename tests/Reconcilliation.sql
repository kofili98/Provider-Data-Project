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
    END AS expected_sqlite_count,
    CASE 
        WHEN flagged_count = CASE rule_name
            WHEN 'stale_record' THEN 292
            WHEN 'missing_credential' THEN 18
            WHEN 'possible_duplicate_providers' THEN 2
            ELSE 0
        END THEN 'PASS'
        ELSE 'FAIL'
    END AS parity_status
FROM @Summary;