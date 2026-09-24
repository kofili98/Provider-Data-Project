-- Data-quality rules, run by `provider-pipeline validate`.
-- Each rule starts with a header line:  -- rule: <name> | <error|warning>
-- and must SELECT an `npi` column. Zero rows means the check passes.
-- Errors fail `validate --fail-on-error`; warnings are reported only.

-- rule: malformed_npi | error
SELECT npi FROM providers
WHERE length(npi) <> 10 OR npi GLOB '*[^0-9]*';

-- rule: invalid_npi_check_digit | error
SELECT npi FROM providers
WHERE length(npi) = 10 AND npi NOT GLOB '*[^0-9]*' AND npi_is_valid(npi) = 0;

-- rule: missing_name | error
SELECT npi FROM providers
WHERE provider_name IS NULL OR trim(provider_name) = '';

-- rule: missing_location_address | error
SELECT p.npi FROM providers p
WHERE NOT EXISTS (
  SELECT 1 FROM addresses a WHERE a.npi = p.npi AND a.address_purpose = 'LOCATION');

-- rule: no_primary_taxonomy | warning
SELECT p.npi FROM providers p
WHERE (SELECT count(*) FROM taxonomies t WHERE t.npi = p.npi AND t.primary_flag = 'Y') = 0;

-- rule: multiple_primary_taxonomies | warning
SELECT p.npi FROM providers p
WHERE (SELECT count(*) FROM taxonomies t WHERE t.npi = p.npi AND t.primary_flag = 'Y') > 1;

-- rule: missing_phone | warning
SELECT DISTINCT npi FROM addresses
WHERE address_purpose = 'LOCATION' AND (telephone IS NULL OR trim(telephone) IN ('', '--'));

-- rule: bad_postal_format | warning
SELECT DISTINCT npi FROM addresses
WHERE address_purpose = 'LOCATION' AND postal_code IS NOT NULL
  AND NOT (
    (length(postal_code) IN (5, 9) AND postal_code NOT GLOB '*[^0-9]*')
    OR postal_code GLOB '[0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]');

-- rule: inactive_status | warning
SELECT npi FROM providers WHERE status IS NULL OR status <> 'A';

-- rule: duplicate_addresses | warning
SELECT npi FROM addresses
GROUP BY npi, address_purpose, upper(address_1), upper(city), state, postal_code
HAVING count(*) > 1;

-- rule: possible_duplicate_providers | warning
WITH keyed AS (
  SELECT p.npi,
         upper(trim(p.provider_name)) AS name_key,
         upper(trim(a.address_1)) AS addr_key,
         substr(a.postal_code, 1, 5) AS zip_key
  FROM providers p
  JOIN addresses a ON a.npi = p.npi AND a.address_purpose = 'LOCATION'
  WHERE p.provider_name IS NOT NULL AND a.address_1 IS NOT NULL
)
SELECT npi FROM keyed
WHERE (name_key, addr_key, zip_key) IN (
  SELECT name_key, addr_key, zip_key FROM keyed
  GROUP BY name_key, addr_key, zip_key HAVING count(DISTINCT npi) > 1);

-- rule: stale_record | warning
SELECT npi FROM providers
WHERE last_updated_date IS NOT NULL AND last_updated_date < date('now', '-5 years');

-- rule: missing_credential | warning
SELECT npi FROM providers
WHERE entity_type_code = 'NPI-1' AND (credential IS NULL OR trim(credential) = '');

-- rule: po_box_location | warning
SELECT DISTINCT npi FROM addresses
WHERE address_purpose = 'LOCATION'
  AND (upper(address_1) LIKE 'PO BOX%' OR upper(address_1) LIKE 'P.O. BOX%' OR upper(address_1) LIKE 'P O BOX%');
