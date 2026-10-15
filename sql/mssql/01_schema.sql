CREATE DATABASE ProviderData;
GO
USE ProviderData;
GO

CREATE TABLE dbo.ingestion_runs (
    run_id VARCHAR(50) NOT NULL PRIMARY KEY,
    record_count INT NOT NULL,
    completed_at DATETIMEOFFSET NOT NULL
);

CREATE TABLE dbo.providers (
    npi VARCHAR(10) NOT NULL PRIMARY KEY,
    entity_type_code VARCHAR(10) NOT NULL,
    provider_name NVARCHAR(250) NULL,
    credential NVARCHAR(50) NULL,
    enumeration_date DATE NULL,
    last_updated_date DATE NULL,
    status VARCHAR(10) NULL,
    source_run_id VARCHAR(50) NOT NULL,
    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);

CREATE TABLE dbo.addresses (
    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    npi VARCHAR(10) NOT NULL,
    address_purpose VARCHAR(20) NOT NULL,
    address_1 NVARCHAR(150) NULL,
    address_2 NVARCHAR(150) NULL,
    city NVARCHAR(100) NULL,
    state VARCHAR(10) NULL,
    postal_code VARCHAR(20) NULL,
    telephone VARCHAR(30) NULL,
    CONSTRAINT FK_addresses_providers FOREIGN KEY (npi) 
        REFERENCES dbo.providers (npi) ON DELETE CASCADE
);

CREATE NONCLUSTERED INDEX IX_addresses_npi_purpose 
    ON dbo.addresses (npi, address_purpose)
    INCLUDE (address_1, city, state, postal_code, telephone);

CREATE TABLE dbo.taxonomies (
    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    npi VARCHAR(10) NOT NULL,
    code VARCHAR(20) NULL,
    description NVARCHAR(255) NULL,
    primary_flag CHAR(1) NOT NULL DEFAULT 'N',
    CONSTRAINT FK_taxonomies_providers FOREIGN KEY (npi) 
        REFERENCES dbo.providers (npi) ON DELETE CASCADE
);

CREATE NONCLUSTERED INDEX IX_taxonomies_npi_primary 
    ON dbo.taxonomies (npi, primary_flag)
    INCLUDE (code, description);
GO

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