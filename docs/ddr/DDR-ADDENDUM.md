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

All fault and ID generation parameters are injected via environment variables (sourced from Key Vault references where applicable).

| Setting | Env Variable Name | Configured Value | Behavior & Purpose |
| :--- | :--- | :--- | :--- |
| **PRNG Seed** | `FAULT_SEED` | `<42>` | Fixed integer seed ensuring deterministic fault sequences across runs |
| **HTTP 500 Error Rate** | `FAULT_500_RATE` | `<e.g., 0.15>` | Float `0.0`–`1.0` representing probability of simulated `500 Internal Server Error` |
| **Repeat / Retry Window** | `FAULT_REPEATS` | `<e.g., 3>` | Number of consecutive identical responses/faults before state advances |
| **UUID v5 Namespace** | `UUID_V5_NAMESPACE` | `<e.g., 6ba7b810-9dad-11d1-80b4-00c04fd430c8>` | Fixed namespace UUID used to generate deterministic entity IDs from input keys |

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