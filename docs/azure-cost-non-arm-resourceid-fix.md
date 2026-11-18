# GAMe v0.3.4.1 — Azure Cost Management ResourceId validation fix

## Symptom

The Azure collector retrieves scope ActualCost but ingestion fails with HTTP 422:

`body.rows.11 - Value error, Azure resource identifier must be an ARM-style path or empty for unassigned charges`

## Cause

The `ResourceId` returned by Azure Cost Management is a billing dimension and may contain non-ARM labels or values for charges not directly associated with a resource. The API previously required all nonempty IDs to begin with `/`.

## Resolution

The Azure scope-cost ingestion validator now accepts empty or printable text resource identifiers up to 450 characters, including Azure billing labels. It continues to reject control characters and overlong values. Scope validation, amounts, currency, dates, credential checks, scope-level classification and idempotent imports are unchanged. Existing behavior canonicalizes the resource identifier to lowercase for database keys.

## Install

Stop the app, extract the ZIP over the parent directory containing `game-mvp`, then restart with the existing collector credential. No migration or credential rotation is necessary.

Run `python scripts/collect_azure_costs.py --scope /subscriptions/<subscription-id>/resourceGroups/<group> --days 7` using the actual scope. Check **Agentic FinOps → Azure resource-scope charges**. Importing the same period twice should not double count charges.

## Data-quality constraint

Azure Cost Management scope ActualCost is not a verified invoice and is not automatically allocatable to Foundry agents. Unassigned billing dimensions remain unallocated. The precise row 11 value from the user's Azure response was not available locally; the test includes typical non-ARM billing identifiers.
