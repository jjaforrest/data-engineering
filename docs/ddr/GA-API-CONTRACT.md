# G0 Mock Payment API Contract

**Companion to:** DDR-G0 v2.0 (Mock API contract table) · **Version:** v1.0 draft · **Date:** 2026-10-09 · **Owner:** Data Engineering path owners

> This document spells out the DDR-G0 mock API contract in buildable detail for stories S0-08, S0-09 and S0-10. DDR-G0 always wins: if anything here disagrees with it, follow DDR-G0 and raise it with your reviewer. Rules marked **PROPOSED** fill gaps DDR-G0 leaves open; build to them unless the path owners publish a different answer.

## 1. Data served

| Item | Rule |
|---|---|
| Source | The original PaySim CSV (Kaggle), **data rows 1–100,000** in file order (the header is not a data row). |
| Row number | `row_num` = 1-based data row in the original file, the same numbering as `core_row_num` in the core banking file. Rows 1–90,000 are also in the core file; rows 90,001–100,000 exist only in the API. That split is what Week 2 matching relies on (90,000 `BOTH`, 10,000 `API_ONLY`). |
| Record order | Ascending `row_num`, stable across requests and restarts. |
| Dataset version | `v1`. (The DDR-G2 stretch adds `v2` = rows 1–100,500; out of scope for Setup.) |
| How the rows reach the app | **PROPOSED:** add an `api` subcommand to `setup/prepare_sources.py` that copies the header and the first 100,000 data lines byte for byte into `api/data/paysim_api_v1.csv.gz`. Commit that one file with a `.gitignore` exception (`!api/data/*.csv.gz`) so the deployed app needs nothing outside Git. Record its SHA-256 in the addendum. |

## 2. Common rules (all endpoints)

| Element | Rule |
|---|---|
| Transport | HTTPS only once deployed. JSON bodies, `Content-Type: application/json`. |
| Auth | Header `X-API-Key: <key>`. Missing or wrong → **401**. The key lives in a Container Apps secret exposed as an environment variable, never in Git. **PROPOSED:** `/v1/meta` needs the key too. |
| Gzip | Responses are gzip-compressed when the client sends `Accept-Encoding: gzip` (FastAPI `GZipMiddleware`). |
| Error body | **PROPOSED:** `{"error": {"code": "<code>", "message": "<text>"}}` with codes `unauthorized`, `rate_limited`, `invalid_request`, `page_out_of_range`, `injected_fault`. |
| Order of checks | 1. Auth (401) → 2. Rate limit (429) → 3. Parameter validation (422 / 404) → 4. Fault injection (500) → 5. Success (200). |
| Workers | Run with **one worker process** and **one replica** (Container Apps max replicas 1, S0-10), so the rate limiter and the "first request" state stay consistent (S0-09). |

## 3. `GET /v1/transactions`

**Query parameters**

| Parameter | Rule |
|---|---|
| `page` | Integer ≥ 1, default 1. |
| `pageSize` | Integer 1–1,000, default 500. |
| Invalid values | **PROPOSED:** `page` < 1, or `pageSize` outside 1–1,000 → **422** (FastAPI's built-in validation with `Query(ge=…, le=…)`). |
| Page past the end | **PROPOSED:** `page` > last page → **404** `page_out_of_range`. |

**Paging maths.** Last page = ⌈100,000 ÷ `pageSize`⌉ (200 pages at the default 500; 100 pages at 1,000). Page *n* serves base records with `row_num` from (*n* − 1) × `pageSize` + 1 to min(*n* × `pageSize`, 100,000), then any injected repeats (section 6).

**Response 200**

```json
{
  "data": [ { …record… }, … ],
  "page": 1,
  "pageSize": 500,
  "totalRecords": 100000,
  "nextPage": 2
}
```

- `nextPage` = `page + 1`, or `null` on the last page.
- `totalRecords` is always 100,000 (distinct records), even when repeats make `data` longer than `pageSize`.

## 4. Record schema

| Field | JSON type | From PaySim | Rule |
|---|---|---|---|
| `transactionId` | string (UUID) | row number | UUID v5 of the row number (section 5). Stable across requests, restarts and engineers. |
| `timestamp` | string | `step` | 2024-01-01T00:00:00Z + (`step` − 1) hours, formatted `YYYY-MM-DDTHH:MM:SSZ` (UTC, no fractional seconds). Step 1 → `2024-01-01T00:00:00Z`; step 743 → `2024-01-31T22:00:00Z`. |
| `transactionType` | string | `type` | `CASH_IN` → `cash-in`, `CASH_OUT` → `cash-out`, `DEBIT` → `debit`, `PAYMENT` → `payment`, `TRANSFER` → `transfer`. |
| `amountCents` | integer | `amount` | Money rule below. |
| `originAccount` | string | `nameOrig` | Unchanged. |
| `destinationAccount` | string | `nameDest` | Unchanged (merchants start with `M`). |
| `originBalanceBeforeCents` | integer | `oldbalanceOrg` | Money rule. |
| `originBalanceAfterCents` | integer | `newbalanceOrig` | Money rule. |
| `destinationBalanceBeforeCents` | integer | `oldbalanceDest` | Money rule. |
| `destinationBalanceAfterCents` | integer | `newbalanceDest` | Money rule. |

- **Money rule:** `int((Decimal(text) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))`, built from the CSV **text**, never a float. `9839.64` → `983964`; `170136.0` → `17013600`; `0.0` → `0`.
- **Not served:** `step` (only as `timestamp`), `isFraud`, `isFlaggedFraud`. No other fields.
- Field names are exactly as above (camelCase); every record has all ten fields, none null.

## 5. Transaction IDs

**PROPOSED** (shared by every engineer, so IDs are comparable across the cohort):

```python
import uuid
DE_PATH_NS = uuid.uuid5(uuid.NAMESPACE_URL, "urn:de-path:paysim:transaction")
# = b9758bc5-73b1-5c8e-bf5c-0df00074ad86
transaction_id = str(uuid.uuid5(DE_PATH_NS, str(row_num)))   # name = row number, no padding
```

Check values: row 1 → `4034166e-2e85-5f82-94d4-e544abdb09e9`; row 100,000 → `bb52074a-cbd4-5c83-8735-d4250cfe2796`.

## 6. Fault injection (S0-09)

| Element | Rule |
|---|---|
| Inputs | Only (`seed`, `page`, `pageSize`). The seed is recorded in the addendum. Never time or randomness from the OS. |
| Injected 500s | 1–2% of the pages for a given `pageSize` (at least one page) return **500** `injected_fault` on their **first** valid request since startup. The retry returns that page normally, identical to an unfaulted page. Pick the faulty pages with a seeded selection, e.g. `random.Random(f"{seed}:{pageSize}").sample(range(2, last + 1), k)`. |
| Repeated records | At least **100** records in total, each copied from a strictly **earlier** page, are appended after the page's own records in a later page's `data`. A repeat is an exact copy (same `transactionId` and values). Page 1 carries none. |
| Determinism | Two full pulls with the same seed and `pageSize` return byte-identical `data` for every page. The pattern changes only if `seed` or `pageSize` changes. |
| Restart caveat | "First request" state is in memory, so a restart or a scale-from-zero can make a faulty page fail once more. Note this as an assumption in the addendum. |

## 7. Rate limiting (S0-09)

| Element | Rule |
|---|---|
| Limit | 60 requests per minute per API key, across all endpoints. |
| Over the limit | **429** `rate_limited` with `Retry-After: <seconds>` (integer ≥ 1, the time until a request will be accepted). |
| What counts | **PROPOSED:** requests that pass auth and are not themselves rejected with 429. 401s do not count. |
| Window | Fixed or sliding 60-second window, your choice; record it in the addendum. |

## 8. `GET /v1/meta`

```json
{"datasetVersion": "v1", "totalRecords": 100000, "contentHash": "<64 hex chars>"}
```

- Lets a client skip a pull when nothing changed (DDR-G1 `SKIPPED_UNCHANGED`; `contentHash` becomes the batch's `source_fingerprint`).
- **PROPOSED `contentHash`:** SHA-256 (lower-case hex) over the 100,000 base records in `row_num` order, each serialised as `json.dumps(record, sort_keys=True, separators=(",", ":"))` plus `"\n"`, UTF-8 encoded. Repeats and faults are excluded, so the hash does not depend on the seed and is the same for every engineer who follows sections 4–5.
- Not subject to fault injection.

## 9. Example

```
GET /v1/transactions?page=1&pageSize=2
X-API-Key: <key>
Accept-Encoding: gzip
```

```json
{
  "data": [
    {
      "transactionId": "4034166e-2e85-5f82-94d4-e544abdb09e9",
      "timestamp": "2024-01-01T00:00:00Z",
      "transactionType": "payment",
      "amountCents": 983964,
      "originAccount": "C1231006815",
      "destinationAccount": "M1979787155",
      "originBalanceBeforeCents": 17013600,
      "originBalanceAfterCents": 16029636,
      "destinationBalanceBeforeCents": 0,
      "destinationBalanceAfterCents": 0
    },
    { … }
  ],
  "page": 1,
  "pageSize": 2,
  "totalRecords": 100000,
  "nextPage": 2
}
```

The record is PaySim data row 1; check it against your own file.

## 10. Conformance checks

| # | Check | Story |
|---|---|---|
| C01 | Rounding: `9839.64` → `983964`; a half-cent value rounds up (`0.005` → `1`). | S0-08 |
| C02 | Timestamps: step 1 → `2024-01-01T00:00:00Z`; step 743 → `2024-01-31T22:00:00Z`. | S0-08 |
| C03 | `transactionId` for rows 1 and 100,000 matches section 5. | S0-08 |
| C04 | Last page at `pageSize` 500 is page 200 with `nextPage: null`; page 201 → 404. | S0-08 |
| C05 | No key and a wrong key → 401. | S0-08 |
| C06 | `/v1/meta` returns `v1`, 100000 and a 64-character hash; the same hash after a restart. | S0-08 |
| C07 | Response carries `Content-Encoding: gzip` when asked. | S0-08 / S0-10 |
| C08 | 61 requests inside a minute → a 429 with `Retry-After`. | S0-09 |
| C09 | An injected 500, then an identical page on retry. | S0-09 |
| C10 | Two full pulls are identical; distinct `transactionId`s = 100,000; total records received = 100,000 + repeats (≥ 100). | S0-09 |
| C11 | Called from a Fabric notebook over HTTPS: a 200, a 401, a 429 and an injected 500 (G0-AC03). | S0-10 |

## 11. Record in your addendum (section 4)

Base URL · hosting (Container Apps environment and app name) · fault seed · 500 rate and the faulty page count at `pageSize` 500 · total repeated records · UUID v5 namespace · `contentHash` definition and value · rate-limit window type · restart caveat · SHA-256 of `api/data/paysim_api_v1.csv.gz`.

## 12. Later extensions (not part of Setup)

- DDR-G2 stretch: `datasetVersion` `v2` serving rows 1–100,500.
- DDR-G5: `POST /v1/kpi-reports` (contract in DDR-G5).
