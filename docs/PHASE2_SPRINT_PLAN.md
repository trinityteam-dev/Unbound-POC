# Epic: Automated Bank Reconciliation & Client Query Generation (POC)

**Goal:** After Phase 1 classification, automatically reconcile bank transactions
against supporting documents and turn the gaps into ready-to-send client queries.

**Engine approach:** Two sequential LLM calls via OpenRouter (reconcile → generate queries).

**Schedule:** Starts Tue 16 Jun, wraps by Wed 1 Jul. Thu 2 Jul is buffer (upper limit, not a working day).
Weekends (20–21 & 27–28 Jun) excluded.

---

## Stories

| # | Story | Dates | Done when |
|---|---|---|---|
| 1 | **Consume classified documents from Phase 1** | Tue 16 Jun | Phase 2 reliably picks up classified files + notes from a completed Phase 1 job |
| 2 | **Reconcile bank transactions against supporting evidence** *(LLM call 1)* | Wed 17 – Fri 19 Jun | A run returns each transaction tagged matched/unmatched with a reason |
| 3 | **Group & explain unmatched transactions as client queries** *(LLM call 2)* | Mon 22 – Tue 23 Jun | Unmatched items grouped by category, each with a humanized query listing its transactions |
| 4 | **Select the right AI model for reliable output** | Wed 24 Jun | Chosen model produces stable, well-formed output across sample runs |
| 5 | **Review reconciliation results & queries in the UI** | Thu 25 – Fri 26 Jun | Results screen shows the reconciliation summary and one card per query category |
| 6 | **Edit query + Send CTA with confirmation window** *(UI only — no actual send)* | Mon 29 Jun | Each query is editable; Send opens a confirmation dialog; status tracked. No sending behind it |
| 3R | **Deterministic query grouping with coarse / granular toggle** | Mon 22 Jun | Python groups unmatched transactions; LLM writes coarse query text only (1 fixed call); granular text is Python-templated at zero extra cost; UI toggle switches views; existing jobs re-grouped on demand |
| 7 | **Integrate the reconciliation flow into the main app** | Tue 30 Jun | New flow replaces existing Phase 2 within the standard job lifecycle |
| 8 | **Validate the end-to-end flow on the ADMCM sample** | Wed 1 Jul | Full run reviewed and demo/sign-off-ready |
| — | **Buffer** | Thu 2 Jul | Contingency only — upper limit |

---

## Notes

- **Shape:** Stories 2–3 are the high-risk core (5 days, front-loaded). Story 4 firms up
  reliability, Stories 5–6 are the user-facing review/query experience, Stories 7–8
  integrate and prove it on the sample.
- **Story 6 scope:** Generate query + editable text + a **Send** call-to-action that opens a
  **confirmation window only**. No email/sending functionality behind it.
- **Two-call engine (Stories 2 & 3):** Call 1 reconciles (matched/unmatched); Call 2 takes the
  unmatched items and writes the grouped, humanized queries. Implementation detail — no board impact.
