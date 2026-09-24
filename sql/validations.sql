-- Run these queries after ingestion. A zero-row result is a passing check.
SELECT npi FROM providers WHERE length(npi) <> 10 OR npi GLOB '*[^0-9]*';

SELECT npi FROM providers
WHERE provider_name IS NULL OR trim(provider_name) = '';

SELECT p.npi FROM providers p
LEFT JOIN addresses a ON a.npi = p.npi AND a.address_purpose = 'LOCATION'
WHERE a.npi IS NULL;

SELECT npi, count(*) AS duplicate_count FROM providers
GROUP BY npi HAVING count(*) > 1;