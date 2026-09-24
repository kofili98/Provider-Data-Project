---
name: export-triage
description: Triage problems with the provider data pipeline's ingestion, validation, and client exports. Use whenever someone reports missing providers, an empty or wrong-looking export, a search that returns 0 records, HTTP 429/5xx errors, validation failures, stale or duplicate provider data, or asks why the numbers in a client file look off. Trigger even if the person never says "triage" or names the tool.
---

# Export triage

Find the root cause of a pipeline or export problem from evidence, fix it, and explain the outcome in plain language a non-technical requester can act on.

## 1. Pin down the symptom

Confirm before running anything: which client config, which database file, when it was last ingested, and the exact symptom (empty file, missing providers, wrong values, an error message). If any of these is missing, ask for it. Do not guess.

## 2. Collect evidence in this order

1. `provider-pipeline --database <db> profile` shows what is actually loaded: counts by entity type, primary specialty, city and state, and ingestion run.
2. The ingest summary: check `per_search` for any search with `records: 0` and `truncated_searches` for searches that hit the 1,200-result ceiling.
3. `provider-pipeline --database <db> validate`: separate error rules (block delivery) from warning rules (caveat only).
4. The client config in `configs/clients/`: compare its `where` filter and `columns` against what `profile` shows is loaded.

## 3. Match the symptom to a cause

| Symptom | Check | Likely cause and fix |
|---|---|---|
| Export has 0 rows | `profile`: is the specialty and city present? | Not present: the search wording did not match the registry (e.g. `Cardiology` vs `Cardiovascular Disease`); fix the search and re-ingest. Present: the client `where` is too strict; loosen it. |
| Providers missing vs. expectation | `truncated_searches`, `per_search` | Search hit the 1,200 ceiling: split by city, ZIP prefix or specialty. Or the city or specialty was never searched. Or the provider's LOCATION address is in a different city than expected (the export uses the first LOCATION address only). |
| Results far too broad | The query JSON | A misspelled parameter is silently ignored by the API; correct the name. |
| `ingest failed: ... requires another criterion` | The query | Searching by `state` alone; add city, postal_code or taxonomy_description. |
| HTTP 429 or 5xx | Ingest log | Rate limiting or outage. The pipeline retries with backoff; raise `--delay` and re-run. Re-runs are safe because ingestion upserts. |
| `Unknown export column` | `docs/integration-guide.md` field dictionary | The column is not in the `provider_export` view. |
| Taxonomy fields empty | `no_primary_taxonomy` warning | Provider has no primary specialty on record. |
| Old database misbehaves after an upgrade | - | Re-run `init-db`; it recreates the export view. |
| Validation errors | The failing NPI | Look the NPI up in the registry; errors are real record defects or an ingestion bug. |
| Many warnings (stale, missing credential, possible duplicate) | Warning counts | These describe the source data, not a pipeline bug. Report them as caveats; do not "fix" them. |

## 4. Verify the fix

Re-run only the affected step. Confirm the row count or record count changed as expected and say what it was before and after. If the result is still wrong, return to step 2 with the new evidence.

## 5. Report back

Write to the requester in plain language, in this shape:

- **What we saw:** one sentence, in their terms.
- **Cause:** one or two sentences, no jargon.
- **Fix:** what changed and the before/after numbers.
- **What to expect:** anything they should double-check.
- **Data caveat:** only if relevant (see rules).

## Rules

- Never edit the database by hand to make numbers look right; fix the search, config or code and re-run.
- An NPI proves a provider was enumerated, not that they are licensed or in good standing. Never imply otherwise.
- If the evidence does not identify a cause, say so and list the next data needed instead of guessing.
- When you resolve a failure pattern that is not in the troubleshooting table in `docs/integration-guide.md`, add a row for it so this skill and the docs improve together.
