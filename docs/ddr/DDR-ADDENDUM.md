# DDR Addendum: Azure Environment & Mock API Configuration

* **Status:** Draft (Pending peer review prior to `addendum-v1.0` tag)
* **DDR Reference:** GA-AC01..AC05 evidence; Baseline DDRs → Addendum minimum contents
* **Dependencies:** SA-12

---

## 1. Azure Subscription & Governance

| Parameter | Value / Configuration | Rebuild / CLI Verification Notes |
| :--- | :--- | :--- |
| **Subscription Offer** | `<e.g., Pay-As-You-Go / Azure for Students / Enterprise Agreement>` | Verify via `az account show --query "{name:Azure subscription 1, id:b307d683-cb3a-4e18-80e4-5aaaefb1e0ae}"` |
| **Tenant ID** | `0af27ce5-e003-471b-aad2-f5a75a618fe6` | Primary Entra ID tenant hosting the subscription |
| **Budget Name** | `<MonthlyBudget1>` | Scoped to the resource group below |
| **Budget Amount & Period** | `<$50.00 USD / Monthly>` | Alert thresholds configured at `50%`, `100%` actual spend, and `100%` forecast spend |
| **Primary Region** | `<e.g., eastus2>` | Must support required Container Apps / App Service SKUs |
| **Resource Group** | `<rg-de-path-engineer>` | `az group create -n rg-de-path-engineer -l eastus` |

---

## 2. Security & Compute Infrastructure

| Parameter | Value / Configuration | Rebuild / CLI Verification Notes |
| :--- | :--- | :--- |
| **Key Vault Name** | `kv-depath-2fee01e0` | Must be globally unique (3–24 alphanumeric/hyphen chars); RBAC enabled |
| **Container Image Location** | `ghcr.io/jjaforrest/paysim-api:v1` | Include registry auth method (public pull) |
| **Compute Hosting** | Azure Container App `cae-paysim-mock` | Ingress enabled on port `8000`, external traffic allowed |
| **Mock API Base URL** | `ca-paysim-api.kindsand-c066c1cc.eastus.azurecontainerapps.io` | Public HTTPS endpoint; health check at `/health` |

---

## 3. Mock API Determinism & Fault Injection

| Setting | Source (Env Var / Code) | Configured Value | Behavior & Rebuild Notes |
| :--- | :--- | :--- | :--- |
| **PRNG Seed** | `FAULT_SEED` env var (matches `DEFAULT_SEED` in `api/faults.py:9`) | `42` | Fixed integer seed for SHA-256 unit hashing (`f"{seed}:{page}:{page_size}:{salt}"`) |
| **HTTP 500 Error Rate** | `error_rate` default in `FaultInjector` (`api/faults.py:62`) | `0.015` (1.5%) | Enforced within `0.01–0.02`; fails with HTTP `500` (`injected_fault`) on the **first** valid request per `(seed, page, pageSize)` since startup, then returns `200` on retry (**3** faulty pages at `pageSize=500`: `[13, 171, 178]`) |
| **Repeated Records** | `repeat_count` default in `FaultInjector` (`api/faults.py:63`) | `120` records | Enforced `>= 100`; deterministic duplicate records copied from strictly earlier pages and appended to later pages (page 1 carries none) |
| **UUID v5 Namespace** | `TRANSACTION_NAMESPACE` constant (`api/main.py:38`) | `7f3b9c2a-4d1e-4b8a-9c6f-2e5d8a1b4c7f` | Hardcoded namespace UUID; `transactionId` = `uuid5(TRANSACTION_NAMESPACE, str(row_number))` (1-indexed, no zero-padding) |
| **Rate Limit Window** | `RateLimiter` default (`api/faults.py:24`) | `60` req / `60.0s` sliding window | Per-API-key in-memory sliding window (`deque` of `time.monotonic()` timestamps); returns HTTP `429` (`rate_limited`) with `Retry-After` header |
| **API Key (`MOCK_API_KEY`)** | `MOCK_API_KEY` env var (`api/main.py:31`) -> `secretRef: paysim-api-key` | Key Vault secret `<kv-secret-name>` | Validated via `X-API-Key` header before rate limit and fault checks (code falls back to `"dev-processor-key"` if env var is unset) |

---

## 4. Assumptions & Open Questions

### Assumptions
* **Ephemeral Fault State:** Fault counters and PRNG sequences are held in-memory; restarting, redeploying, or scaling the container/instance resets the sequence back to the initial `FAULT_SEED`.
* **Single-Replica Execution:** The mock API runs with `minReplicas=1` and `maxReplicas=1` so horizontal scaling does not split deterministic fault counters across instances.
* **Key Vault Access:** The compute resource uses a System-Assigned Managed Identity with the `Key Vault Secrets User` role rather than static access policies or connection strings in app settings.
* **Tagging Gate:** This document will remain untagged until peer review confirms buildability; Setup will apply the `addendum-v1.0` git tag upon sign-off.

### Open Questions
* `<e.g., Should Key Vault purge protection be disabled in dev so a teardown/rebuild can reuse the exact same Key Vault name immediately?>`
* `<e.g., Does the reviewer require read access to the subscription to verify budget alerts, or is a CLI export sufficient?>`

---

## 5. Peer Review Sign-Off Checklist (Buildability Check)

* [ ] Can the resource group, Key Vault, and compute host be provisioned using only the names, SKUs, and regions above?
* [ ] Is the container image registry accessible without undocumented credentials?
* [ ] Do the environment variable names match what the application binary expects on startup?
* [ ] Ready for Setup to tag `addendum-v1.0`?