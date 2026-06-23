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

- [x] **4.1** Run Stories 2–3 engine against ADMCM sample with three candidate models: `x-ai/grok-4.20`, `google/gemini-2.5-flash`, `anthropic/claude-sonnet-4-6`
- [x] **4.2** Evaluate each model on: JSON schema compliance, transaction tagging accuracy, query readability, latency, cost per run
- [x] **4.3** Document findings in `docs/model_selection_notes.md`
- [x] **4.4** Set chosen model as the default in `run_reconciliation_call()` and `run_query_generation_call()`; update fallback model accordingly
- [x] **4.5** If text-based transaction extraction (Story 2, Approach A) shows accuracy problems, evaluate the multimodal/vision fallback — send the rendered statement page as a base64 image to a vision-capable model instead of extracted text. Requires extending `query_openrouter()` to support image message parts. Documented here as a contingency, not a committed task.

---

## Story 5 — Review Reconciliation Results & Queries in the UI

**Done when:** The UI shows a reconciliation summary and one card per query category after Phase 2 completes.

- [x] **5.1** Add `GET /api/jobs/<job_id>/reconciliation` endpoint in `app.py` — returns `job["phase2_context"]["reconciliation_results"]` and `job["phase2_context"]["queries"]`
- [x] **5.2** Design reconciliation summary panel in `templates/index.html`
  - Shown in the `pending_reviewer_approval` job state
  - Displays: total transactions, matched count, unmatched count — per account and overall
  - Transaction table per account: date, description, amount, matched/unmatched badge, reason, linked document name
- [x] **5.3** Design query cards panel in `templates/index.html`
  - One card per query from `queries` list
  - Each card shows: category heading, query text, collapsible transaction list
  - Read-only at this stage (editable in Story 6)
- [x] **5.4** Wire both panels to the job detail view; confirm they render correctly on a completed ADMCM Phase 2 run

---

## Story 6 — Edit Query + Send CTA with Confirmation Window *(UI only)*

**Done when:** Each query card is editable; Send opens a confirmation dialog; query status is tracked. No actual sending behind it.

- [x] **6.1** Make query text editable per card (textarea, pre-populated with LLM-generated text)
- [x] **6.2** Add "Send" button per card; clicking it opens a confirmation dialog showing the final query text and a placeholder recipient field
- [x] **6.3** Confirmation dialog has Confirm and Cancel actions; Confirm marks the query as `sent` in the UI
- [x] **6.4** Add `POST /api/jobs/<job_id>/queries/<query_id>/status` endpoint in `app.py` — accepts `{ status: sent|dismissed, query_text }`, persists to `job["phase2_context"]["queries"]` in `jobs_db.json`
- [x] **6.5** Reflect per-query status visually on the card (pending / sent / dismissed badge)
- [x] **6.6** Test: edit a query, send, confirm dialog, verify status persists on page refresh

---

## Story 3R — Deterministic Query Grouping with Coarse / Granular Toggle

> ⚠️ **Partially superseded by [Story 3S](#story-3s--semantic-transaction-classification-with-fixed-smsf-taxonomy).** Tasks 3R.1 and 3R.5 are replaced. The coarse/granular toggle (3R.7), query-text generation (3R.2, 3R.3), and the coarse/granular data structure (Step 4) are unchanged.

**Revises:** Story 3's grouping step. The LLM query-text generation is retained but scoped to coarse groups only. The grouping decision itself moves to Python.

**Done when:** Unmatched transactions are grouped deterministically by Python into coarse (default, 5 buckets) and granular (per-security) views; coarse `query_text` is LLM-generated in one fixed call; granular `query_text` is Python-templated at zero additional LLM cost; the UI shows a toggle; existing stored jobs are re-grouped where possible.

---

### Background & Premise

Story 3 delegated both grouping and query-text writing to a single LLM call. This produced non-deterministic output. Running the same 164 ADMCM unmatched transactions against grok-4.20 on three separate occasions yielded:

| Run | Groups produced |
|---|---|
| Story 4 benchmark | 14 |
| Stored ADMCM job (`job_20260619_112732`) | 40 |
| Story 3 test | 5 |

The variance is a problem in production: a reviewer would see a different number of cards each time the job is re-run, with no stable mapping between cards and security names.

~~Examining what grouping actually requires reveals it is **pure string pattern-matching** on the transaction description. Australian bank transaction descriptions follow a predictable format:~~

~~```~~
~~"Direct Credit 531532 NAB INTERIM DIV DV251/01064980"~~
~~                ↑ BSB  ↑ PAYEE NAME      ↑ reference~~
~~```~~

~~Identifying the payee ("NAB") does not require language understanding. Delegating it to an LLM adds cost, latency, and non-determinism with no benefit over a regex rule.~~

> **Why this was superseded:** The `Direct Credit BSB PAYEE REF` format is CBA-specific. Macquarie, ANZ, Westpac, and most banks use free-form description text for pension payments, contributions, and interest credits. Any fund that isn't CBA-backed falls entirely into `Other –` buckets. See [Story 3S](#story-3s--semantic-transaction-classification-with-fixed-smsf-taxonomy).

Additionally, the product needs a **coarse / granular toggle** for the reviewer:
- **Coarse (default):** ~5 cards — one per broad category (Bank Interest, Investment Income, Broker Settlements, etc.). Easier to scan; suitable for quick decisions.
- **Granular:** one card per security (NAB Dividends, BHP Dividends, GQG Dividends, etc.). More actionable when directing queries to specific counterparties.

LLM-based grouping cannot serve both modes from a single call. Python grouping produces both from the same parsing pass.

---

### Approach

#### ~~Step 1 — Python extracts both grouping levels in one pass~~ *(superseded by [Story 3S](#story-3s--semantic-transaction-classification-with-fixed-smsf-taxonomy) Step 1)*

~~`group_unmatched_transactions(unmatched_transactions)` returns two lists from a single pass over the transactions:~~

~~**Granular rules (applied first, in priority order):**~~

~~| Pattern in `description` | Granular group |~~
~~|---|---|~~
~~| `"Credit Interest"` | `"Bank Interest"` |~~
~~| `"FinClear Service"` (debit) | `"Broker Settlements"` |~~
~~| `"ASIC"` | `"Regulatory Fees – ASIC"` |~~
~~| `"ATO"` + credit | `"ATO Tax Refund"` |~~
~~| `"Direct Credit XXXXXX PAYEE ref"` | `"Investment Income – {PAYEE_NAME}"` |~~
~~| `"Transfer To/From"` | `"Internal Transfer"` |~~
~~| No match | `"Other – {description[:40]}"` |~~

~~For `Direct Credit` transactions, the payee is extracted as the token(s) following the BSB number and before any trailing reference codes (e.g. `DV251/…`, `cm-…`, numeric IDs ≥9 digits). Payee tokens are joined and title-cased.~~

~~**Coarse roll-up (applied after):**~~

~~All `"Investment Income – *"` granular groups collapse to `"Investment Income – Dividends & Distributions"`. All other groups carry through 1:1. This roll-up is a plain Python dict.~~

#### Step 2 — LLM generates `query_text` for coarse groups only (1 call, fixed output)

The 5 coarse groups (with their full transaction lists) are sent to the LLM in a single call. The prompt asks **only for query_text per group** — no grouping decision is left to the LLM. Response schema: `{ groups: [{ category, query_text }] }` matched back to coarse groups by category name.

#### Step 3 — Python templates `query_text` for granular groups (0 LLM calls)

```
"We have identified {N} unmatched {PAYEE_NAME} transactions totalling
${TOTAL:.2f}. Please provide the relevant {document_type} for each
of the following:

{date} | {description} | {amount}
..."
```

`document_type` is inferred from the payee (e.g. "DIV" in description → "dividend statement", "DST"/"DIST" → "distribution notice", otherwise "supporting documentation").

#### Step 4 — Queries stored as coarse cards with embedded `sub_queries`

```json
{
  "id": "Q2",
  "category": "Investment Income – Dividends & Distributions",
  "query_text": "<LLM-generated text covering all 126 transactions>",
  "transactions": [ ...126 transactions... ],
  "sub_queries": [
    {
      "id": "Q2.1",
      "category": "Investment Income – NAB",
      "query_text": "<Python-templated text>",
      "transactions": [ ...8 NAB transactions... ]
    },
    {
      "id": "Q2.2",
      "category": "Investment Income – GQG",
      "query_text": "<Python-templated text>",
      "transactions": [ ...5 GQG transactions... ]
    }
  ]
}
```

- **Coarse view:** render top-level queries only (5 cards, existing behaviour)
- **Granular view:** for each coarse query, render its `sub_queries` if present; otherwise render the coarse query as-is (e.g. Bank Interest and Broker Settlements have no meaningful sub-grouping)
- **Toggle is front-end only** — no additional API call; both levels are pre-computed and stored

#### Handling existing stored jobs *(superseded by [Story 3S](#story-3s--semantic-transaction-classification-with-fixed-smsf-taxonomy) Task 3S.4)*

When a job's `phase2_context.queries` was produced by the old LLM-based Story 3 implementation:

1. Flatten all `q.transactions` across all stored queries into one list
2. ~~Run `group_unmatched_transactions()` on the descriptions~~
3. ~~If ≥80% of transactions match a Python pattern → produce fresh coarse + granular groups; replace stored queries~~
4. ~~If <80% match (descriptions missing or unrecognisable) → retain existing queries as-is; set `sub_queries: null` on each~~
5. The UI hides the toggle button when all coarse queries have `sub_queries: null`

A `POST /api/jobs/<job_id>/regroup-queries` endpoint exposes this on demand for older jobs.

---

### Token Cost Analysis (grok-4.20)

*Pricing: grok-4.20 via OpenRouter — $3.00 / M input tokens, $15.00 / M output tokens. Verify current rates on OpenRouter dashboard; these were correct as of Story 4 benchmarking (2026-06-19).*

*ADMCM baseline: 164 unmatched transactions @ ~25 tokens each = 4,100 transaction tokens. System prompt ~400 tokens. Each query_text ~130 tokens (avg 531 chars ÷ 4 chars/token from Story 4 benchmark).*

| Approach | Groups | Input tokens | Output tokens | Est. cost |
|---|---|---|---|---|
| Story 3 original — grok produced 5 groups (best case) | 5 | ~4,500 | ~650 | **$0.024** |
| Story 3 original — grok produced 14 groups (Story 4 benchmark) | 14 | ~4,500 | ~1,820 | **$0.041** |
| Story 3 original — grok produced 40 groups (stored job) | 40 | ~4,500 | ~5,200 | **$0.092** |
| Story 3 original — Gemini produced 46 groups (Story 4 benchmark) | 46 | ~4,500 | ~5,980 | **$0.103** |
| **Story 3R — Python groups coarse, LLM writes 5 texts (1 call)** | **5** | **~4,300** | **~650** | **$0.023** |
| **Story 3R — toggle to granular** | **~40** | **0** | **0** | **$0.000** |

**Key observations:**

1. Output tokens dominate cost. Input is ~$0.013 regardless of approach. The variance is entirely in output.
2. The original approach's output cost ranges **4× ($0.011 to $0.090)** depending on how the LLM happens to group on a given run — unpredictable and unbudgetable.
3. Story 3R fixes output at exactly 5 query texts every run (~$0.010 output) regardless of fund complexity. **Total cost is predictable at ~$0.023 per job.**
4. The granular toggle costs **$0.000 additional** — Python templates require no API call.
5. At scale: 100 jobs/month on the old approach costs $2.40–$10.30. On Story 3R it costs $2.30, flat.

---

### Tasks

- ~~[x] **3R.1** Write `group_unmatched_transactions(unmatched_transactions)` in `core_engine.py`~~ *(replaced by [Story 3S](#story-3s--semantic-transaction-classification-with-fixed-smsf-taxonomy) tasks 3S.1–3S.3)*
  - ~~Returns `{ "coarse": [{category, transactions}], "granular": [{category, transactions}] }`~~
  - ~~Granular: regex extraction of payee/security from `"Direct Credit XXXXXX PAYEE ref"` pattern; named rules for Interest, FinClear, ASIC, ATO~~
  - ~~Coarse: dict mapping granular category prefixes to coarse buckets~~
  - ~~Falls back to `"Other – {truncated description}"` for unmatched patterns — never silently drops a transaction~~
  - ~~Logs the distribution: how many transactions matched each rule~~

- [x] **3R.2** Write `build_coarse_query_text_prompt(coarse_groups, fund_name)` in `core_engine.py`
  - Sends the N coarse groups (category + transaction list) to the LLM
  - Asks **only** for `query_text` per group — no grouping decision left to LLM
  - Response schema: `{ groups: [{ category, query_text }] }` — matched back by category name
  - Returns a dict `{ category → query_text }`

- [x] **3R.3** Write `generate_granular_query_text(category, transactions)` in `core_engine.py`
  - Pure Python template — no LLM call
  - Infers `document_type` from payee name / transaction description keywords (DIV → "dividend statement", DST/DIST → "distribution notice", otherwise "supporting documentation")
  - Returns a professional, readable query string

- [x] **3R.4** Replace `run_query_generation_call()` with revised orchestration in `run_bank_reconciliation_phase()`
  - Calls `group_unmatched_transactions()` → `coarse_groups`, `granular_groups`
  - Calls `build_coarse_query_text_prompt()` for coarse `query_text` (1 LLM call)
  - Calls `generate_granular_query_text()` per granular group (Python, no LLM)
  - Assembles coarse queries with embedded `sub_queries` list; `sub_queries` is `null` if a coarse group has no meaningful sub-division (e.g. Bank Interest, Broker Settlements)
  - Returns `queries` list in same schema as before (backward compatible)

- ~~[x] **3R.5** Write `regroup_stored_queries(existing_queries, fund_name, api_key, update_progress)` in `core_engine.py`~~ *(replaced by [Story 3S](#story-3s--semantic-transaction-classification-with-fixed-smsf-taxonomy) task 3S.4)*
  - ~~Flattens all transactions from existing queries into one list~~
  - ~~Runs `group_unmatched_transactions()` on them~~
  - ~~If ≥80% of transactions matched to a named pattern: runs LLM call for fresh coarse texts, returns new queries with `sub_queries`~~
  - ~~If <80%: returns original queries with `sub_queries: null` added to each (no change to `query_text`)~~
  - ~~Logs which path was taken and match rate~~

- [x] **3R.6** Add `POST /api/jobs/<job_id>/regroup-queries` endpoint in `app.py`
  - Calls `regroup_stored_queries()` on `job["phase2_context"]["queries"]`
  - Persists updated queries to `jobs_db.json`
  - Returns `{ queries, regrouped: true|false, match_rate }` so UI can show feedback

- [x] **3R.7** Add coarse / granular toggle to query cards panel in `templates/index.html`
  - Toggle control visible only when at least one coarse query has a non-null `sub_queries` list
  - Default (coarse): render top-level query cards as before
  - Granular: for each coarse card, if `sub_queries` is present render the sub-query cards in its place; if `sub_queries` is null render the coarse card unchanged
  - Toggle state is front-end only (local JS variable, no API call)
  - Preserve Send / Dismiss / edit behaviour on both coarse and granular cards

- [x] **3R.8** Test against ADMCM:
  - Coarse produces 4 groups covering 100% of 164 unmatched transactions (Bank Interest 33, Investment Income 127, Broker Settlements 3, Regulatory Fees – ASIC 1)
  - Granular produces 43 per-security groups (40 Investment Income + 3 named) covering 100%
  - Python template produces readable query text for granular groups (verified GQG, ACDC)
  - LLM coarse texts are professional and reference specific amounts (verified all 4 groups)
  - UI toggle button appears only when sub_queries are present; switches between views
  - Edge case: job with no transactions → no toggle shown (`sub_queries: null`)

---

## Story 3S — Semantic Transaction Classification with Fixed SMSF Taxonomy

**Revises:** Story 3R's grouping step (Task 3R.1 and 3R.5). The coarse/granular toggle (3R.7), LLM query-text call (3R.2), Python granular templates (3R.3), and the `sub_queries` data structure (Step 4) are all unchanged.

**Done when:** A `transaction_categories.json` file at the workspace root defines the SMSF transaction taxonomy; unmatched transactions are classified by the LLM into those categories (one batched call per job) and then grouped deterministically in Python; the taxonomy is loaded at runtime — no category name, description, or example is hardcoded in the app; ADMCM produces the same 4 coarse groups as before; Cobble produces 4 meaningful groups instead of 11 `Other –` buckets; existing `POST /api/jobs/<job_id>/regroup-queries` endpoint re-classifies without the 80% threshold gate.

---

### Background & Premise

Story 3R solved non-determinism by moving grouping to Python rules. The rules were validated against ADMCM, where every CBA bank account formats transaction descriptions as:

```
"Direct Credit 531532 NAB INTERIM DIV DV251/01064980"
                ↑ BSB  ↑ PAYEE NAME      ↑ reference
```

When the **Cobble Family Super Fund** was onboarded — a Macquarie CMA pension fund — all 42 unmatched transactions fell through to the `else` branch (`Other – {description[:40]}`), producing 11 poorly-named queries:

| Python output (Story 3R) | Correct grouping | Transactions |
|---|---|---|
| `Other – MACQUARIE CMA INTEREST PAID` | `Bank Interest` | 12 |
| `Other – PENSION` | `Pension Payments` | 12 |
| `Other – CHERYL'S RE-CONTRIBUTION` | `Member Contributions` | 4 |
| `Other – RE-CONTRIBUTION 1` | `Member Contributions` | 1 |
| `Other – RE-CONTRIBUTION 2` | `Member Contributions` | 1 |
| `Other – RE-CONTRIBUTION 3` | `Member Contributions` | 1 |
| `Other – COMPLETE RECONTRIBUTION 1` | `Member Contributions` | 1 |
| `Other – ATO ATO002000021374899` | `ATO Tax Payment` | 1 |
| `Other – LUMP SUM SHORTFALL PENSION` | `Pension Payments` | 1 |
| `Other – MR IAN WILLIAM COBBLE COBBLE` | `Pension Payments` + `Member Contributions` | 7 |
| `Other – MR IAN WILLIAM COBBLE Cobble` | `Pension Payments` | 1 |

42 transactions → 11 `Other –` queries. Correct classification → 4 meaningful queries.

The root cause is that Story 3R's premise — *"Australian bank transaction descriptions follow a predictable format"* — held only for CBA Direct Credit entries. Macquarie, ANZ, Westpac, and most banks use free-form description text for pension payments, contributions, and interest credits. Adding more Python rules would fix Cobble but not the next fund.

**The key insight:** Story 3 non-determinism came from the LLM making *structural* decisions (how many groups? which to merge?). Story 3R correctly removed that freedom. Story 3S applies the same constraint at the classification step: the LLM picks from a **fixed, closed-set taxonomy** rather than inventing categories. Assigning a label from 11 known options at temperature=0 is a classification task — stable and near-deterministic — not a creative grouping exercise.

---

### Taxonomy Configuration File

The category list lives in **`transaction_categories.json`** at the workspace root — not in the app code or the LLM prompt string. The app reads this file at runtime to build the classification prompt, validate the LLM's response, and label query groups. Editing categories, descriptions, or examples requires only a JSON edit; no code change or redeploy is needed.

**Why a file, not code:** The accountants and processors at BeFree are the domain experts on what transaction categories matter in an SMSF audit. A JSON file they can open, read, and edit in any text editor is more accessible than a Python constant or a buried prompt string. It also means the taxonomy can be refined as new fund types are onboarded without touching the app.

**Editing:** Directly in `transaction_categories.json`. No UI editor for now — the file is human-readable and the fields are self-explanatory.

**Future scope (not built now):** A `playbook_overrides` key could allow per-playbook category lists (e.g. `Accounting_Only` jobs might not need `Broker Settlements`). The current design is a single global list.

#### File structure

```json
{
  "version": 1,
  "categories": [
    {
      "id": "bank_interest",
      "label": "Bank Interest",
      "description": "Interest credited by any bank on any cash or investment account",
      "direction": "credit",
      "examples": [
        "MACQUARIE CMA INTEREST PAID",
        "Credit Interest",
        "INT CREDIT WESTPAC"
      ],
      "sub_groupable": false
    },
    {
      "id": "pension_payments",
      "label": "Pension Payments",
      "description": "Regular and lump-sum pension drawdowns paid to members",
      "direction": "debit",
      "examples": [
        "PENSION",
        "LUMP SUM SHORTFALL PENSION",
        "MEMBER PENSION PAYMENT"
      ],
      "sub_groupable": false
    },
    {
      "id": "member_contributions",
      "label": "Member Contributions",
      "description": "Contributions and re-contributions into the fund by members of any kind",
      "direction": "credit",
      "examples": [
        "CHERYL'S RE-CONTRIBUTION",
        "RE-CONTRIBUTION 1",
        "COMPLETE RECONTRIBUTION 1",
        "NON CONCESSIONAL CONTRIBUTION"
      ],
      "sub_groupable": false
    },
    {
      "id": "ato_tax_payment",
      "label": "ATO Tax Payment",
      "description": "Tax instalments, PAYG, or tax balances paid to the ATO",
      "direction": "debit",
      "examples": [
        "ATO ATO002000021374899",
        "ATO PAYMENT",
        "PAYG INSTALMENT"
      ],
      "sub_groupable": false
    },
    {
      "id": "ato_tax_refund",
      "label": "ATO Tax Refund",
      "description": "Tax refunds received from the ATO",
      "direction": "credit",
      "examples": [
        "ATO TAX REFUND",
        "ATO EFT"
      ],
      "sub_groupable": false
    },
    {
      "id": "investment_income",
      "label": "Investment Income",
      "description": "Dividends, trust distributions, and managed fund income received",
      "direction": "credit",
      "examples": [
        "Direct Credit 531532 NAB INTERIM DIV DV251/01064980",
        "Direct Credit 082401 GQG PARTNERS DST",
        "MXT DISTRIBUTION"
      ],
      "sub_groupable": true
    },
    {
      "id": "broker_settlements",
      "label": "Broker Settlements",
      "description": "Buy or sell trade settlements for shares, ETFs, or other securities",
      "direction": "either",
      "examples": [
        "FinClear Service",
        "CHESS SETTLEMENT",
        "ORD MINNETT SETTLEMENT"
      ],
      "sub_groupable": false
    },
    {
      "id": "regulatory_fees",
      "label": "Regulatory Fees",
      "description": "ASIC levies, ASX fees, and other government or regulatory charges",
      "direction": "debit",
      "examples": [
        "ASIC ANNUAL REVIEW FEE",
        "ASX LISTING FEE"
      ],
      "sub_groupable": false
    },
    {
      "id": "administration_fees",
      "label": "Administration Fees",
      "description": "Accounting, audit, fund management, and administration fees",
      "direction": "debit",
      "examples": [
        "BELL PARTNERSHIP ACCOUNTING FEE",
        "AUDIT FEE",
        "SMSF ADMINISTRATION"
      ],
      "sub_groupable": false
    },
    {
      "id": "insurance_premiums",
      "label": "Insurance Premiums",
      "description": "Life insurance, TPD, and income protection premium payments",
      "direction": "debit",
      "examples": [
        "TAL LIFE INSURANCE",
        "AIA INCOME PROTECTION",
        "INSURANCE PREMIUM"
      ],
      "sub_groupable": false
    },
    {
      "id": "other",
      "label": "Other",
      "description": "Transactions that genuinely do not fit any of the above categories — use as a last resort only",
      "direction": "either",
      "examples": [],
      "is_fallback": true,
      "sub_groupable": false
    }
  ]
}
```

#### Field reference

| Field | Type | Purpose |
|---|---|---|
| `id` | string | Machine identifier — used internally; never shown in UI |
| `label` | string | Display name — appears on query cards and in the LLM prompt |
| `description` | string | Sent to the LLM verbatim to guide classification; edit this to tune accuracy |
| `direction` | `"credit"` / `"debit"` / `"either"` | Hint injected into the prompt alongside the description |
| `examples` | string[] | Real transaction descriptions; sent to the LLM as references; add more as new banks/funds are seen |
| `sub_groupable` | bool | `true` → apply per-security granular breakdown (currently `investment_income` only) |
| `is_fallback` | bool | Marks the catch-all category; the prompt instructs the LLM to use it only when nothing else fits |

---

### Approach

#### Step 1 — Load taxonomy from `transaction_categories.json`

New function `load_transaction_categories(workspace_dir)`:

- Reads `{workspace_dir}/transaction_categories.json` at runtime
- Returns the parsed list of category objects
- Raises a clear error if the file is missing or malformed — the app cannot classify without it
- Called once per Phase 2 run; the result is passed down to `build_classification_prompt()` and `classify_transactions()`

#### Step 2 — LLM classifies each transaction into the loaded taxonomy (1 batched call)

New function `classify_transactions(unmatched_transactions, categories, fund_name, api_key, model)`:

- Sends all unmatched transactions in a single prompt as a numbered list: `{index} | {date} | {description} | {DR/CR} ${amount}`
- System prompt is built from the loaded categories — `label`, `description`, `direction`, and `examples` fields are injected verbatim; nothing about categories is hardcoded in the prompt string
- The label list is passed as a closed enum so the LLM cannot invent new category names
- Response schema: `{ "classified": [{ "tx_index": 0, "category": "Bank Interest" }, ...] }`
  - Index-based response avoids duplicating transaction text in the output; output tokens ≈ N × 8 regardless of description length
- Validation: every index 0..N-1 must appear exactly once; `category` must match a `label` from the loaded taxonomy
- On validation failure (missing index, unknown label): falls back to the `is_fallback` category for the offending transactions, logs a warning — never drops a transaction
- Returns the original transaction list with `smsf_category` added to each dict

#### Step 3 — Python groups by assigned category (deterministic)

Simple `defaultdict(list)` keyed by `smsf_category`. Two levels:

- **Coarse:** one bucket per taxonomy category (e.g. all `Bank Interest` transactions together)
- **Granular:** for categories where `sub_groupable: true` (currently `investment_income` only), apply the existing `_extract_payee()` function to produce per-security sub-groups (e.g. `Investment Income – NAB`); all other categories get `sub_queries: null`
- The `sub_groupable` flag is read from the loaded JSON — adding a new sub-groupable category in future requires only a JSON edit

Steps 4, 5, 6 — LLM writes coarse `query_text`, Python templates granular `query_text`, `sub_queries` embedding — are **unchanged from Story 3R**.

---

### What changes vs Story 3R

| | Story 3R | Story 3S |
|---|---|---|
| Grouping engine | Python rules (CBA patterns only) | LLM classification into fixed taxonomy |
| Non-determinism | Eliminated (pure Python) | Minimised (fixed labels, temperature=0) |
| Fund-agnosticism | CBA + known banks only | Any Australian bank/SMSF fund type |
| Investment Income granular | Python payee extraction | Unchanged — same Python `_extract_payee()` |
| Query text generation | LLM (1 call) | Unchanged |
| Granular query text | Python template | Unchanged |
| `sub_queries` structure | Same | Unchanged |
| Regroup endpoint | 80% match-rate gate | Always re-classifies via LLM |

---

### Token Cost Analysis (grok-4.20)

*Pricing: $3.00 / M input, $15.00 / M output tokens (OpenRouter, as of Story 4 benchmarking 2026-06-19).*

*Classification call: N transactions × ~20 tokens each + ~400-token system prompt. Output: N × ~8 tokens (index + category label).*

| Scenario | Classification call | Query-text call | Total est. cost |
|---|---|---|---|
| Cobble — 42 unmatched tx | ~$0.005 | ~$0.008 | **~$0.013** |
| ADMCM — 164 unmatched tx | ~$0.013 | ~$0.010 | **~$0.023** |
| Large fund — 300 unmatched tx | ~$0.022 | ~$0.012 | **~$0.034** |

Cost is flat and predictable. The classification call's output is small (index + label only), so the additional call adds minimal cost vs Story 3R.

---

### Tasks

- [ ] **3S.0** Create `transaction_categories.json` at the workspace root
  - Initial content: the 11 categories defined in the Taxonomy Configuration File section above
  - Reviewed by the processor/accountant before implementation goes live — categories, descriptions, and examples should reflect BeFree's actual practice
  - This file is the single source of truth; no category data lives anywhere else in the codebase

- [ ] **3S.1** Write `load_transaction_categories(workspace_dir)` in `core_engine.py`
  - Reads `{workspace_dir}/transaction_categories.json`
  - Returns the parsed `categories` list
  - Raises `FileNotFoundError` with a clear message if the file is absent — the app cannot proceed without it
  - Raises `ValueError` if the JSON is malformed or no `is_fallback` category is present

- [ ] **3S.2** Write `build_classification_prompt(unmatched_transactions, categories)` in `core_engine.py`
  - Accepts the loaded `categories` list — no hardcoded category data
  - Formats transactions as a numbered list: `{i} | {date} | {description} | {DR/CR} ${amount}`
  - System prompt is assembled from the categories: for each entry injects `label`, `description`, `direction`, and `examples` (if any)
  - The closed enum of valid labels is derived from `[c["label"] for c in categories]` — injected into the prompt verbatim so the LLM cannot invent new labels
  - Explicitly instructs the LLM to use the `is_fallback` category only as a last resort
  - Response schema: `{ "classified": [{ "tx_index": int, "category": str }] }`

- [ ] **3S.3** Write `classify_transactions(unmatched_transactions, categories, fund_name, api_key, model)` in `core_engine.py`
  - Calls `build_classification_prompt()` → `query_openrouter()` with `response_format={"type": "json_object"}` and `temperature=0`
  - Validates response: all indices 0..N-1 present exactly once; each `category` value matches a `label` in the loaded taxonomy
  - On validation error: logs warning, assigns the `is_fallback` category to offending transactions, continues — never raises
  - Returns the original transaction list with `smsf_category` field added to each dict
  - Logs category distribution: `Bank Interest: 12, Pension Payments: 13, Member Contributions: 9, ATO Tax Payment: 1, Other: 0`

- [ ] **3S.4** Replace `group_unmatched_transactions()` call in `run_bank_reconciliation_phase()` with the new pipeline
  - Call `load_transaction_categories()` once at the start of the phase
  - Call `classify_transactions()` to tag each transaction with `smsf_category`
  - Coarse groups: `defaultdict(list)` keyed by `smsf_category` — sort order follows category order in the JSON
  - Granular groups: for categories where `sub_groupable: true` apply `_extract_payee()`; all others get `sub_queries: null`
  - `run_coarse_query_text_call()`, `generate_granular_query_text()`, and the `sub_queries` assembly in 3R.4 are unchanged

- [ ] **3S.5** Update `regroup_stored_queries()` in `core_engine.py`
  - Load taxonomy via `load_transaction_categories()` then call `classify_transactions()` — remove the 80% match-rate threshold entirely
  - Always re-classify and regenerate: flatten existing query transactions → `classify_transactions()` → group → `run_coarse_query_text_call()`
  - Log: category distribution before and after, to make re-grouping auditable
  - Return value schema unchanged: `(queries, regrouped: bool, match_rate: float)` — set `match_rate=1.0`

- [ ] **3S.6** Regression test against ADMCM
  - All 164 unmatched ADMCM transactions classified into named categories — zero `Other`
  - Granular toggle still shows per-security `Investment Income` sub-groups (payee extraction unchanged)
  - Coarse query texts are professional and reference specific amounts
  - Total cost within expected range (~$0.023)

- [ ] **3S.7** Regression test against Cobble (`job_20260621_103331`)
  - Call `POST /api/jobs/job_20260621_103331/regroup-queries`
  - Verify result: 4 coarse groups (`ATO Tax Payment`, `Bank Interest`, `Pension Payments`, `Member Contributions`) — zero `Other` groups
  - Verify `sub_queries: null` on all groups (Cobble has no Investment Income)
  - Verify query text is professional and references specific transaction dates and amounts

---

## Story 7 — Integrate the Reconciliation Flow into the Main App

**Done when:** The new engine runs as part of the standard job lifecycle, alongside (not replacing) the existing checklist and lead schedules.

- [x] **7.1** Confirm approach with review: run both `reconcile_papers()` (checklist + lead schedules) AND `run_bank_reconciliation_phase()` in sequence within `run_phase2_worker` — requires P1-E approval
- [x] **7.2** Update `run_phase2_worker` in `app.py` to call `run_bank_reconciliation_phase()` and store results in `job["phase2_context"]`
- [x] **7.3** Apply P1-D (remove the two hardcoded `audit_checks` from `reconcile_papers()`) — requires P1-D approval
- [x] **7.4** Verify no regressions: checklist panel, lead schedules, exception log all render correctly after integration
- [x] **7.5** Verify new reconciliation and query panels appear correctly in the same job view

---

## Story 8 — Validate End-to-End Flow on ADMCM Sample

**Done when:** A full run is reviewed and demo/sign-off-ready.

- [x] **8.1** Run full ADMCM job end-to-end: Phase 1 classification → human processor sign-off → Phase 2 (reconciliation + checklist) → query review → human reviewer sign-off
- [x] **8.2** Verify all bank statement transactions are extracted correctly (no missing rows)
- [x] **8.3** Verify known expected matches are tagged correctly: ATO refund, accountancy fee, audit fee, Ord Minnett EFT transfers, MXT distribution
- [x] **8.4** Verify unmatched items generate meaningful, readable client queries
- [x] **8.5** Verify checklist, lead schedules, and exception log are unaffected
- [x] **8.6** Verify query edit + Send CTA + confirmation flow works end-to-end
- [ ] **8.7** Sign-off review with stakeholder; update `PHASE2_SPRINT_PLAN.md` story statuses

---

## Story T — Token Economics & Cost Visibility

**Done when:** Every LLM call records token usage and estimated cost in real time; costs roll up from call → phase → job → fund; the job header (alongside fund name, ABN, job ID) shows a live cost figure as the job processes; fund-level total cost is visible aggregated across all jobs for that fund; historical jobs without token data show N/A throughout.

---

### Goals & Non-Goals

**Goals:**
- Give BeFree operators clear sight of the cost of processing each fund
- Real-time cost feedback as a job runs (not just post-completion)
- Stable, auditable cost records per job in `jobs_db.json`
- Token counts as a supporting detail alongside the primary cost figure

**Non-Goals:**
- Client billing or invoicing
- Cost alerting or budget enforcement
- Backfilling token data for historical jobs (show N/A, no re-run)

---

### Data Model

Token usage is stored per job in `jobs_db.json` under a `token_usage` key. The three sub-keys form the rollup hierarchy.

```json
"token_usage": {
  "calls": [
    {
      "call_id": "phase1_classify_pass",
      "phase": "phase1",
      "model": "x-ai/grok-4.20",
      "prompt_tokens": 14200,
      "completion_tokens": 1340,
      "total_tokens": 15540,
      "cost_usd": 0.0346,
      "timestamp": "2026-06-22T10:23:41Z"
    },
    {
      "call_id": "phase2_extract_transactions_BSB001",
      "phase": "phase2",
      "model": "x-ai/grok-4.20",
      "prompt_tokens": 8800,
      "completion_tokens": 2100,
      "total_tokens": 10900,
      "cost_usd": 0.0581,
      "timestamp": "2026-06-22T10:31:05Z"
    }
  ],
  "phases": {
    "phase1": {
      "total_tokens": 45000,
      "cost_usd": 0.312
    },
    "phase2": {
      "total_tokens": 22400,
      "cost_usd": 0.183
    }
  },
  "job_total": {
    "total_tokens": 67400,
    "cost_usd": 0.495
  }
}
```

**Field notes:**
- `call_id` is a human-readable label describing the call's purpose (e.g. `phase2_classify_transactions`, `phase2_coarse_query_text`) — not a UUID. Used for debugging and audit.
- `phases` and `job_total` are always derived and kept in sync immediately after each call is recorded. No separate aggregation step is needed at read time.
- `token_usage` key is absent on jobs created before this story ships. The UI treats `null`/absent as N/A throughout.

**Phase labels used across the codebase:**

| Phase label | What it covers |
|---|---|
| `phase1` | All `query_openrouter()` calls in `classify_papers()` |
| `phase2` | All Phase 2 calls: `extract_transactions_from_statement()`, `run_reconciliation_call()`, `classify_transactions()`, `run_coarse_query_text_call()` |

---

### Pricing Configuration

Cost is calculated using a `llm_pricing.json` file at the workspace root. OpenRouter's chat completions response returns `usage.prompt_tokens` and `usage.completion_tokens` but does not include a cost field. Per-model pricing is therefore config-driven in USD.

```json
{
  "version": 1,
  "currency": "USD",
  "models": {
    "x-ai/grok-4.20": {
      "input_per_million": 3.00,
      "output_per_million": 15.00
    },
    "google/gemini-2.5-flash": {
      "input_per_million": 0.15,
      "output_per_million": 0.60
    },
    "anthropic/claude-sonnet-4-6": {
      "input_per_million": 3.00,
      "output_per_million": 15.00
    }
  }
}
```

**Pricing update process:** Edit `llm_pricing.json` directly — no code change or restart required. Verify against the OpenRouter dashboard at the time of any model change.

*Rates above are correct as of Story 4 benchmarking (2026-06-19). Always verify before using for operational reporting.*

---

### Fund-Level Cost Aggregation

A fund's total cost is the sum of `token_usage.job_total.cost_usd` across all jobs for that `fund_id` in `jobs_db.json`. No separate fund-level store is needed — the aggregation is computed at read time from existing job records. Historical jobs (missing `token_usage`) are excluded from the sum but flagged in the breakdown.

---

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/jobs/<job_id>/token-usage` | Returns `token_usage` for a single job. If the key is absent, returns `{ "available": false }`. |
| `GET /api/funds/<fund_id>/cost-summary` | Returns: total cost across all jobs, per-job breakdown (job_id, date, cost, status), count of historical jobs excluded (N/A). |

The job-level endpoint is polled by the UI during active runs to deliver real-time cost updates. No webhook or push mechanism is needed.

---

### UI Changes

**Job header (where fund name, ABN, job ID appear):**

- Add a cost badge: `Cost: $0.495` (USD, 3 decimal places)
- During an active job: badge updates live (polls `GET /api/jobs/<job_id>/token-usage` on the same interval as job status polling)
- Phase breakdown available on hover or expand: `Phase 1: $0.312 | Phase 2: $0.183`
- Token count shown as secondary detail beneath cost: `67,400 tokens`
- If `token_usage` is absent (historical job): badge shows `Cost: N/A`

**Fund-level cost summary:**

- Shown in the fund's job list or a collapsible section of the fund header
- Displays: total cost across all jobs (USD), number of jobs included, number excluded (N/A)
- Per-job row: date, job ID, status, cost — so an operator can see which runs drove the spend

---

### Tasks

- [ ] **T.1** Create `llm_pricing.json` at the workspace root
  - Initial rates for the three candidate models from Story 4 benchmarking
  - Verified against OpenRouter dashboard before commit

- [ ] **T.2** Write `load_llm_pricing(workspace_dir)` in `core_engine.py`
  - Reads and parses `llm_pricing.json`
  - Raises `FileNotFoundError` with a clear message if absent
  - Returns a pricing dict keyed by model ID
  - Called once per job at worker startup; result is passed to `record_token_usage()`

- [ ] **T.3** Write `calculate_call_cost(model, prompt_tokens, completion_tokens, pricing)` in `core_engine.py`
  - Looks up per-million rates from the `pricing` dict
  - If the model is not in `pricing`, logs a warning and returns `0.0` — never raises; an unknown model must not crash a job
  - Returns cost as a `float` rounded to 6 decimal places

- [ ] **T.4** Extend `query_openrouter()` return value to include usage data
  - Current return: the response content string
  - New return: a tuple `(content: str, usage: dict)` where `usage = { "model": str, "prompt_tokens": int, "completion_tokens": int, "total_tokens": int }`
  - `usage` is populated from `response_json["usage"]` if present; defaults to `{ ..., "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }` if the field is absent (defensive — should not happen with OpenRouter)
  - All existing callers must be updated to unpack the tuple (T.6)

- [ ] **T.5** Write `record_token_usage(job, call_id, phase, usage, cost_usd)` in `core_engine.py`
  - Appends a full call record to `job["token_usage"]["calls"]`
  - Recalculates `phases[phase]` totals and `job_total` in place
  - Initialises `job["token_usage"]` if the key doesn't exist yet
  - Called immediately after each `query_openrouter()` call; `jobs_db.json` is persisted by the worker's existing save mechanism after each call

- [ ] **T.6** Update all `query_openrouter()` call sites in `core_engine.py` to unpack the new tuple and call `record_token_usage()`
  - Phase 1: classification call(s) in `classify_papers()` → phase label `"phase1"`
  - Phase 2 call sites (all phase label `"phase2"`):
    - `extract_transactions_from_statement()` — one call per bank account; `call_id` includes the account number (e.g. `phase2_extract_txns_062-001-123456789`)
    - `run_reconciliation_call()` — `call_id`: `phase2_reconcile`
    - `classify_transactions()` — `call_id`: `phase2_classify_transactions`
    - `run_coarse_query_text_call()` — `call_id`: `phase2_coarse_query_text`
  - The `pricing` dict (loaded in T.2) must be available at each call site — pass it down from the worker or load once and thread through

- [ ] **T.7** Add `GET /api/jobs/<job_id>/token-usage` endpoint in `app.py`
  - Returns `job["token_usage"]` if present, or `{ "available": false }` if absent
  - No authentication changes needed

- [ ] **T.8** Add `GET /api/funds/<fund_id>/cost-summary` endpoint in `app.py`
  - Scans `jobs_db.json` for all jobs where `job["fund_id"] == fund_id`
  - Sums `token_usage.job_total.cost_usd` for jobs that have the key; counts jobs without it as N/A
  - Returns: `{ fund_id, total_cost_usd, jobs_included, jobs_excluded_na, job_breakdown: [{ job_id, date, status, cost_usd|null }] }`

- [ ] **T.9** Update job header in `templates/index.html`
  - Add cost badge alongside the existing fund name / ABN / job ID row
  - Badge format: `Cost: $0.495` — USD, always 3 decimal places
  - Token sub-detail: `67,400 tokens` — shown below the badge, formatted with thousands separator
  - Phase breakdown: shown on hover (tooltip) or in a collapsible — `Phase 1: $0.312 | Phase 2: $0.183`
  - Historical jobs (no `token_usage`): badge shows `Cost: N/A`; no token detail shown

- [ ] **T.10** Wire real-time polling in `templates/index.html`
  - Poll `GET /api/jobs/<job_id>/token-usage` on the same interval as existing job status polling (while job state is `processing_phase1` or `processing_phase2`)
  - Update cost badge and token detail in place without full page reload
  - Stop polling once job reaches a terminal state (`pending_processor_approval`, `pending_reviewer_approval`, `completed`, `failed`)

- [ ] **T.11** Add fund-level cost summary to the UI
  - Shown in the fund header or alongside the fund's job list
  - Displays: `Total processing cost: $1.24` (sum across all jobs with data)
  - Sub-line: `3 jobs included · 2 jobs N/A (no data)`
  - Per-job cost visible in the existing job list rows: add a `Cost` column showing `$0.495` or `N/A`

- [ ] **T.12** Validate against ADMCM
  - Run a full Phase 1 + Phase 2 ADMCM job; confirm all expected call sites record usage
  - Verify phase totals and job total match manual sum of individual call records
  - Verify cost badge appears in job header and updates during the run
  - Verify fund-level summary shows the job in its breakdown
  - Open an old job (pre-story); verify N/A appears correctly — no errors, no partial data shown
