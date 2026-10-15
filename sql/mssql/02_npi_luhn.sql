USE ProviderData;
GO
CREATE OR ALTER FUNCTION dbo.fn_npi_is_valid (@npi VARCHAR(20))
RETURNS BIT
AS
BEGIN
    IF @npi IS NULL OR LEN(@npi) <> 10 OR @npi LIKE '%[^0-9]%'
        RETURN 0;

    DECLARE @full VARCHAR(15) = '80840' + @npi;
    DECLARE @total INT = 0;
    DECLARE @i INT = 1;
    DECLARE @digit INT;

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