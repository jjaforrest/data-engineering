# DDR-00 — Shared conventions

**Baseline version:** v2.0.2 · **Effective:** 2026-10-15 · **Owner:** Data Engineering path owners

> Baseline DDR, provided centrally. Copy into `docs/ddr/` unchanged; record your own choices in `docs/ddr/DDR-ADDENDUM.md`.

These rules apply at every gate; a gate DDR may add to them but never contradicts them.

| Convention | Rule |
|---|---|
| Scenario | A fictional community bank wants one trusted view of lending, payments, fraud and balance integrity. Stakeholders: Head of Lending (KPI-01–03), Payments Operations Lead (KPI-04, 07), Head of Financial Crime (KPI-05, 06), Data Governance Lead (KPI-08). |
| Time | All timestamps UTC. PaySim `step` 1 = 2024-01-01 00:00 UTC; `txn_ts = TIMESTAMP '2024-01-01 00:00:00' + (step − 1) hours`; `txn_date = DATE(txn_ts)`. PaySim uses steps 1–743, all in January 2024. |
| Money | PaySim and API amounts are USD. Silver and Gold store money as `DECIMAL(18,2)`; API integer cents ÷ 100. Never go through a binary float. |
| Naming | `snake_case` tables and columns, prefixed `bronze_`, `silver_`, `quarantine_`, `gold_`, `ops_`. |
| Keys | Surrogate keys are `STRING` `sha2(concat_ws('\|', …), 256)` of the business key each gate DDR names, so they are deterministic across reruns. |
| Code tables | Coded values keep the source code plus a `<column>_desc` column. |
| Landing zone | `Files/landing/core_banking/` and `Files/landing/hmda/` in the Lakehouse are the simulated source systems: written once in Setup, never edited. The API is reached over HTTPS. |
| Batches | One ingestion run of one source = one batch with a new `_batch_id`. A batch is **written to its Bronze table in one atomic append, or not at all**. Each run writes one row to `ops_batch_log`. |
| Batch status | `SUCCEEDED` (rows appended), `FAILED` (nothing appended), `SKIPPED_UNCHANGED` (source unchanged since the last `SUCCEEDED` batch; nothing appended). |
| Which batch Silver reads | By default Silver is fully rebuilt from the **latest `SUCCEEDED` batch** per source. An incremental load (DDR-G2 stretch) must produce exactly what a full rebuild would. |
| DQ severity | **Error**: row goes to the source's quarantine table and is excluded from Silver. **Warning**: row stays in Silver; the failure is counted in `ops_dq_results`. **Suite**: a table-level check; failing it fails the run. |
| Where DQ runs | Great Expectations validates the **conformed, pre-quarantine** DataFrame (`stg_*`), never Silver after the split, so Error rules show their real failure counts. |
| Quarantine | One row per source row failing at least one Error rule, with all conformed columns plus `failed_rules ARRAY<STRING>`, `_batch_id` and `quarantined_at`. For every Error rule R: GX unexpected count for R = quarantine rows where `array_contains(failed_rules, R)`. |
| Table-level rules | Reconciliations, splits and duplicate counts are computed in PySpark into a one-row metrics DataFrame and asserted with GX (`ExpectColumnValuesToBeBetween` / `ExpectColumnValuesToBeInSet` on that DataFrame). |
| DQ results | Every GX run writes one row per rule to `ops_dq_results`: `run_id`, `gate`, `table_name`, `rule_id`, `severity`, `evaluated_rows`, `failed_rows`, `passed`, `run_ts`. |
| Code & Git | The Fabric workspace is connected to the engineer's GitHub repo through Fabric Git integration from Setup. Each gate is a branch and a pull request; the gate is reviewed on the PR. Every stage re-runs from Git with no hand edits to code or data. |
| Tools | GX Core version pinned in the addendum and installed through a Fabric **Environment** attached to every notebook (not `%pip`, which pipeline runs disable by default — verify against current Fabric docs). |

## How the baseline works

- **Baseline wins.** You may not change any baseline definition, formula, rule or field name in your own build. If the data shows a baseline definition is wrong or ambiguous, log a **baseline change request** in your addendum (what you found, evidence, proposed fix), raise it with your reviewer, and keep building to the baseline until the path owners publish a new version.
- **You extend, you don't override.** Your addendum records your slices and row counts, your mock API URL and fault settings, extra fields, extra KPIs or DQ rules, and your judgment calls on anything the baseline doesn't cover. Number extensions `EXT-01`, `EXT-02`, ….
- **Acceptance checks are the "Meets" bar.** Each gate DDR lists numbered checks (`G<n>-AC<nn>`). Reviewers verify each one on the gate PR.
- **Versioning.** Your addendum starts at v1.0 before Week 1. Every later change gets a version, date and reason, so Week 3 can reward a change log that shows what the data taught you.

**Addendum minimum contents:** version and change log; HMDA year, states and Bronze/Silver/quarantine row counts; PaySim and API row counts; mock API URL and fault-injection settings (seed, 500 rate, repeated records); Fabric trial start date and freshness threshold (DDR-G5); pinned tool versions (at least GX Core); extra fields; extensions (`EXT-nn`); assumptions and open questions; baseline change requests and their status.
