# Phase 2 Implementation Plan
# Automated Bank Reconciliation & Client Query Generation

---

## ⚠️ Phase 1 Touch-Points — Requires Review Before Implementation

The following items require extending Phase 1 code. **No changes will be made until confirmed.**

| # | Change | File | Reason |
|---|---|---|---|
| P1-A | Add `Tax Statement Metrics` and `F25 Periodic Statement Metrics` to ADMCM playbook keywords | `funds_config.json` | These categories are missing, causing misclassification. Story 1 intake depends on correctly classified workpapers. |
| P1-B | Exclude the `Additional Notes` subfolder from Phase 1's `os.walk` scan in `classify_papers()` | `core_engine.py` | Reconciliation notes live at `data/<fund>/Additional Notes/` and are read directly by Phase 2. Phase 1 must not attempt to classify these files. |
| P1-C | Adopt `Additional Notes` as a reserved subfolder convention — no config change needed | — | Phase 2 derives the path as `{fund_profile["folder_path"]}/Additional Notes/`. Any PDF found there is treated as a reconciliation instruction file. No keyword or category entry required. |
| P1-D | Remove the two hardcoded `audit_checks` from `cash_reconciliation` in `reconcile_papers()` | `core_engine.py` | These check the ATO refund and Ord Minnett EFT at summary level — Story 2 will surface the same transactions with full detail. Remove at Story 7 integration to avoid duplication. |
| P1-E | Replace `run_ai_reviewer_phase()` call in `run_phase2_worker` with new Phase 2 engine | `app.py` | Story 7 integration point. Existing `reconcile_papers()` (checklist + lead schedules) must still run alongside the new engine, not be replaced. Confirm approach before Story 7. |

---

## Story 1 — Consume Classified Documents from Phase 1

**Done when:** `build_phase2_context()` returns a valid, structured context dict from any completed Phase 1 job. Smoke-tested against ADMCM.

- [x] **1.1** Confirm Phase 1 touch-points P1-A and P1-B are approved and applied (P1-C requires no code change)
- [x] **1.2** Write `build_phase2_context(job_id, fund_profile, job_record)` in `core_engine.py`
  - Partitions `job["files"]` into `bank_accounts` (one entry per fund account, with `statement_path`) and `supporting_documents` (all non-bank-statement files)
  - Resolves `reconciliation_notes_path` by scanning `{fund_profile["folder_path"]}/Additional Notes/` for any PDF files — exposed as a dedicated field, separate from supporting documents; `None` if the folder is absent or empty
  - Includes `processor_notes`, `unprocessed_files`, `fund_id`, `job_type`
  - Logs a warning (not error) for any bank account in `fund_profile` with no matching statement file
- [x] **1.3** Call `build_phase2_context()` at the start of `run_phase2_worker` in `app.py`; store result as `job["phase2_context"]`
- [x] **1.4** Smoke test: run against a completed ADMCM job, print context, verify all three bank accounts and supporting docs are correctly partitioned

---

## Story 2 — Reconcile Bank Transactions Against Supporting Evidence *(LLM Call 1)*

**Done when:** A run returns every bank transaction tagged `matched` or `unmatched` with a reason and a pointer to the matching document where applicable.

### Design Note — How document content reaches the LLM

The OpenRouter chat completions API used by `query_openrouter()` accepts **text only** — files cannot be attached the way they can in the ChatGPT/Claude UI. All document content must be sent as extracted text. Two roles, two treatments:

- **Bank statements → structured transaction rows.** Raw `pypdf`/OCR text flattens transaction tables (columns run together, rows wrap, OCR adds noise). The statement must be turned into a clean, ordered list of rows first. This is what lets us (a) feed the reconciler an unambiguous numbered list and (b) verify no rows were dropped.
- **Supporting documents → extracted text excerpts.** Invoices, valuations, broker listing, tax statements are read as *evidence*, not reconciled row-by-row. A labeled text excerpt per document (tagged with its Phase 1 category) is sufficient.

### Transaction extraction — two approaches

Task 2.1 produces the structured rows. There are two ways to do it; the data contract (output schema) is identical so downstream tasks are unaffected by the choice.

| | Input | Parser | Pros | Cons |
|---|---|---|---|---|
| **Approach A — LLM-based** *(POC default)* | extracted statement text | a dedicated `query_openrouter()` call | Robust to messy/OCR'd text and varying statement layouts; no format-specific code | Extra LLM call (cost/latency); must validate row count |
| **Approach B — Code-based** | extracted statement text | regex / heuristics in Python | Free, fast, deterministic | Brittle across statement formats; high-maintenance regex |

**Both consume the same extracted text — neither sends the file.** The only difference is what does the parsing. A third option (multimodal vision models reading the rendered page image directly) is deferred to Story 4 as a fallback if text-based accuracy proves too low.

**POC decision: implement Approach A (LLM-based) only as step 1.** Approach B is documented for a future optimisation pass and should not be built now.

- [x] **2.1** Write `extract_transactions_from_statement(pdf_path, account, api_key)` in `core_engine.py`
  - **Approach A (LLM-based) — build this for the POC:**
    - Extract full text from the merged statement PDF (reuse existing `extract_pdf_text` + OCR fallback)
    - Send the extracted text to `query_openrouter()` with a prompt that asks for structured rows in JSON
    - Response schema: `{ transactions: [{ date, description, debit, credit, balance, raw_line }] }`
    - Preserve original row order; handle multi-page statements in one call (chunk only if context limit is hit)
    - **Validation:** log the parsed row count; if zero rows returned from a non-empty statement, surface a warning
  - **Approach B (code-based) — documented, NOT built in POC:**
    - Same output schema, produced by regex/heuristics over the extracted text instead of an LLM call
    - To be considered only if Approach A proves too slow/costly at scale
  - Function signature should keep the parser swappable (e.g. an internal `_parse_via_llm` vs `_parse_via_regex`) so Approach B can be slotted in later without changing callers
- [x] **2.2** Write `build_reconciliation_prompt(phase2_context, transactions_by_account)` in `core_engine.py`
  - Injects reconciliation notes text (if present) as a preamble instruction block
  - Provides all transactions across all accounts as the subject
  - Provides supporting document text excerpts as evidence (invoices, valuations, broker listing, tax statements)
  - Response schema: `{ account, transactions: [{ date, description, amount, type, status: matched|unmatched, matched_document, reason }] }`
- [x] **2.3** Write `run_reconciliation_call(phase2_context, api_key, update_progress)` in `core_engine.py`
  - Calls `query_openrouter()` with the reconciliation prompt
  - Parses and validates JSON response
  - Returns `reconciliation_results` dict keyed by account number
- [x] **2.4** Write `run_bank_reconciliation_phase(job_id, fund_profile, job_type, api_key, scratch_dir, update_progress)` in `core_engine.py` as the new Phase 2 orchestrator
  - Calls `build_phase2_context()` → `extract_transactions_from_statement()` per account (passing `api_key` for the LLM parse pass) → `run_reconciliation_call()`
  - Returns partial results at this stage (Story 3 will extend it)
- [x] **2.5** Test against ADMCM: verify known transactions (ATO refund $5,674.46, accountancy fee $270.41, audit fee $517.00) are tagged `matched`

---

## Story 3 — Group & Explain Unmatched Transactions as Client Queries *(LLM Call 2)*

**Done when:** Unmatched items are grouped by category, each with a humanized query text that lists the relevant transactions.

- [x] **3.1** Write `build_query_generation_prompt(unmatched_transactions, fund_name)` in `core_engine.py`
  - Passes all unmatched transactions (across all accounts) to the LLM
  - Instructs LLM to group by likely category (e.g. "Unknown Expense", "Unidentified Credit", "Investment Purchase")
  - Response schema: `{ queries: [{ id, category, query_text, transactions: [{ date, description, amount }] }] }`
- [x] **3.2** Write `run_query_generation_call(unmatched_transactions, fund_name, api_key, update_progress)` in `core_engine.py`
  - Calls `query_openrouter()` with the query generation prompt
  - Parses and validates JSON response
  - Returns `queries` list
- [x] **3.3** Extend `run_bank_reconciliation_phase()` to chain Story 3 call after Story 2
  - Extracts unmatched transactions from reconciliation results
  - Calls `run_query_generation_call()`
  - Returns combined `{ reconciliation_results, queries, summary: { total, matched, unmatched } }`
- [x] **3.4** Test against ADMCM: verify unmatched items produce coherent, readable query text grouped by category

---

## Story 4 — Select the Right AI Model for Reliable Output

**Done when:** A model is chosen and set as the default for the reconciliation engine, with evidence of consistent structured output.

- [ ] **4.1** Run Stories 2–3 engine against ADMCM sample with three candidate models: `x-ai/grok-4.20`, `google/gemini-2.5-flash`, `anthropic/claude-sonnet-4-6`
- [ ] **4.2** Evaluate each model on: JSON schema compliance, transaction tagging accuracy, query readability, latency, cost per run
- [ ] **4.3** Document findings in `docs/model_selection_notes.md`
- [ ] **4.4** Set chosen model as the default in `run_reconciliation_call()` and `run_query_generation_call()`; update fallback model accordingly
- [ ] **4.5** If text-based transaction extraction (Story 2, Approach A) shows accuracy problems, evaluate the multimodal/vision fallback — send the rendered statement page as a base64 image to a vision-capable model instead of extracted text. Requires extending `query_openrouter()` to support image message parts. Documented here as a contingency, not a committed task.

---

## Story 5 — Review Reconciliation Results & Queries in the UI

**Done when:** The UI shows a reconciliation summary and one card per query category after Phase 2 completes.

- [ ] **5.1** Add `GET /api/jobs/<job_id>/reconciliation` endpoint in `app.py` — returns `job["phase2_context"]["reconciliation_results"]` and `job["phase2_context"]["queries"]`
- [ ] **5.2** Design reconciliation summary panel in `templates/index.html`
  - Shown in the `pending_reviewer_approval` job state
  - Displays: total transactions, matched count, unmatched count — per account and overall
  - Transaction table per account: date, description, amount, matched/unmatched badge, reason, linked document name
- [ ] **5.3** Design query cards panel in `templates/index.html`
  - One card per query from `queries` list
  - Each card shows: category heading, query text, collapsible transaction list
  - Read-only at this stage (editable in Story 6)
- [ ] **5.4** Wire both panels to the job detail view; confirm they render correctly on a completed ADMCM Phase 2 run

---

## Story 6 — Edit Query + Send CTA with Confirmation Window *(UI only)*

**Done when:** Each query card is editable; Send opens a confirmation dialog; query status is tracked. No actual sending behind it.

- [ ] **6.1** Make query text editable per card (textarea, pre-populated with LLM-generated text)
- [ ] **6.2** Add "Send" button per card; clicking it opens a confirmation dialog showing the final query text and a placeholder recipient field
- [ ] **6.3** Confirmation dialog has Confirm and Cancel actions; Confirm marks the query as `sent` in the UI
- [ ] **6.4** Add `POST /api/jobs/<job_id>/queries/<query_id>/status` endpoint in `app.py` — accepts `{ status: sent|dismissed, query_text }`, persists to `job["phase2_context"]["queries"]` in `jobs_db.json`
- [ ] **6.5** Reflect per-query status visually on the card (pending / sent / dismissed badge)
- [ ] **6.6** Test: edit a query, send, confirm dialog, verify status persists on page refresh

---

## Story 7 — Integrate the Reconciliation Flow into the Main App

**Done when:** The new engine runs as part of the standard job lifecycle, alongside (not replacing) the existing checklist and lead schedules.

- [ ] **7.1** Confirm approach with review: run both `reconcile_papers()` (checklist + lead schedules) AND `run_bank_reconciliation_phase()` in sequence within `run_phase2_worker` — requires P1-E approval
- [ ] **7.2** Update `run_phase2_worker` in `app.py` to call `run_bank_reconciliation_phase()` and store results in `job["phase2_context"]`
- [ ] **7.3** Apply P1-D (remove the two hardcoded `audit_checks` from `reconcile_papers()`) — requires P1-D approval
- [ ] **7.4** Verify no regressions: checklist panel, lead schedules, exception log all render correctly after integration
- [ ] **7.5** Verify new reconciliation and query panels appear correctly in the same job view

---

## Story 8 — Validate End-to-End Flow on ADMCM Sample

**Done when:** A full run is reviewed and demo/sign-off-ready.

- [ ] **8.1** Run full ADMCM job end-to-end: Phase 1 classification → human processor sign-off → Phase 2 (reconciliation + checklist) → query review → human reviewer sign-off
- [ ] **8.2** Verify all bank statement transactions are extracted correctly (no missing rows)
- [ ] **8.3** Verify known expected matches are tagged correctly: ATO refund, accountancy fee, audit fee, Ord Minnett EFT transfers, MXT distribution
- [ ] **8.4** Verify unmatched items generate meaningful, readable client queries
- [ ] **8.5** Verify checklist, lead schedules, and exception log are unaffected
- [ ] **8.6** Verify query edit + Send CTA + confirmation flow works end-to-end
- [ ] **8.7** Sign-off review with stakeholder; update `PHASE2_SPRINT_PLAN.md` story statuses
