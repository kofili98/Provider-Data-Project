CREATE TABLE IF NOT EXISTS providers (
  npi TEXT PRIMARY KEY,
  entity_type_code TEXT NOT NULL,
  provider_name TEXT,
  credential TEXT,
  enumeration_date TEXT,
  last_updated_date TEXT,
  status TEXT,
  source_run_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS addresses (
  id INTEGER PRIMARY KEY,
  npi TEXT NOT NULL REFERENCES providers(npi) ON DELETE CASCADE,
  address_purpose TEXT NOT NULL,
  address_1 TEXT,
  address_2 TEXT,
  city TEXT,
  state TEXT,
  postal_code TEXT,
  telephone TEXT
);

CREATE TABLE IF NOT EXISTS taxonomies (
  id INTEGER PRIMARY KEY,
  npi TEXT NOT NULL REFERENCES providers(npi) ON DELETE CASCADE,
  code TEXT,
  description TEXT,
  primary_flag TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id TEXT PRIMARY KEY,
  record_count INTEGER NOT NULL,
  completed_at TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS provider_export AS
SELECT p.npi, p.provider_name, p.credential, p.status,
       a.address_1, a.city, a.state, a.postal_code, a.telephone,
       t.code AS taxonomy_code, t.description AS taxonomy_description
FROM providers p
LEFT JOIN addresses a ON a.npi = p.npi AND a.address_purpose = 'LOCATION'
LEFT JOIN taxonomies t ON t.npi = p.npi AND t.primary_flag = 'Y';