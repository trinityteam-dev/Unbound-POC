# SMSF Document Intelligence v2 — Code Reference

This document describes every function across all project Python files in plain functional terms: what it does, what it takes in, and what it returns. A [Call Graph](#call-graph) at the end shows how the functions connect to form the two main processing pipelines.

---

## Table of Contents

1. [app.py — Web Server & API Layer](#apppy)
2. [core_engine.py — AI Processing Engine](#core_enginepy)
3. [classify_workpapers.py — Standalone CLI Classifier (POC)](#classify_workpaperspy)
4. [verify_and_generate_workpapers.py — Standalone CLI Reconciler (POC)](#verify_and_generate_workpaperspy)
5. [extract_checklist.py — Checklist PDF Utility](#extract_checklistpy)
6. [Call Graph](#call-graph)

---

## app.py

The HTTP layer. Serves the browser UI, exposes the REST API, and spins up background threads to run Phase 1 and Phase 2 work without blocking the browser.

---

### Data Access Helpers

#### `load_funds()`
Reads `funds_config.json` from the workspace and returns the full list of registered SMSF fund profiles. If the file does not exist or is malformed, returns an empty list.

#### `save_funds(funds)`
Writes the given list of fund profiles back to `funds_config.json`, replacing whatever was there.
- `funds` — list of fund config dicts to persist.

#### `load_jobs()`
Reads `jobs_db.json` and returns all job records. If the file is absent or broken, returns an empty list.

#### `save_jobs(jobs)`
Writes the given list of job records to `jobs_db.json`.
- `jobs` — list of job dicts to persist.

#### `get_job_dir(job_id)`
Returns the absolute filesystem path to a job's working directory (`jobs/<job_id>/`).
- `job_id` — the job's unique identifier string (e.g. `job_20260621_103331`).

---

### Background Worker Threads

#### `run_phase1_worker(job_id, folder_path, fund_profile, job_type, api_key)`
The Phase 1 background thread. Picks up a newly created job and runs the AI Processor Agent against all documents in the fund's input folder. When it finishes, the job status changes to `pending_processor_review` and the `files` list is populated with classifications for the human to review.

Internally defines a nested `update_job_progress(percent, msg)` helper that writes live progress updates into `jobs_db.json` so the browser polling loop can show them.

- `job_id` — identifies which job to update in the database.
- `folder_path` — absolute path to the fund's source document folder.
- `fund_profile` — the fund config dict (name, accounts, members, keywords, etc.).
- `job_type` — `"Accounting"` or `"Accounting_Audit"` — controls which document categories are active.
- `api_key` — OpenRouter API key for LLM calls.

Calls → `run_ai_processor_phase`, `load_llm_pricing`, `calculate_call_cost`, `record_token_usage`

#### `run_phase2_worker(job_id, fund_profile, job_type, api_key)`
The Phase 2 background thread. Runs after the human processor approves Phase 1 classifications. Executes bank reconciliation, query generation, and the checklist/lead-schedule verification, then flips the job to `pending_reviewer_approval`.

Also defines its own `update_job_progress` nested helper.

After Phase 2 completes, it scans the AI results and auto-generates `auditor_notes`: exceptions for missing documents, member TSB balance drops, and MXT pricing variances.

- `job_id` — which job to run.
- `fund_profile` — fund config dict.
- `job_type` — `"Accounting"` or `"Accounting_Audit"`.
- `api_key` — OpenRouter API key.

Calls → `build_phase2_context`, `run_bank_reconciliation_phase`, `run_ai_reviewer_phase`, `load_llm_pricing`, `calculate_call_cost`, `record_token_usage`

---

### Flask Route Functions

#### `index()`
`GET /` — Serves the main single-page application HTML template.

#### `api_funds()`
`GET /api/funds` — Returns the full list of registered fund profiles as JSON.
`POST /api/funds` — Creates a new fund profile or updates an existing one (matched by `id`). The request body must include at minimum an `id` field.

#### `_derive_fund_id(folder_name)`
Private helper. Converts a folder name into a clean, URL-safe ID string by lowercasing it and replacing all non-alphanumeric characters with underscores.
- `folder_name` — e.g. `"The Cobble Family Super Fund"` → `"the_cobble_family_super_fund"`.

#### `_empty_fund_config(fund_id, folder_path, keywords)`
Private helper. Returns a minimal blank fund config dict with empty `bank_accounts` and `members` lists. Used as a safe fallback when automatic profile extraction fails.
- `fund_id` — derived ID string.
- `folder_path` — relative path to the fund's document folder.
- `keywords` — the keyword config template copied from an existing fund.

#### `_profile_to_fund_config(fund_id, folder_path, profile, keywords)`
Private helper. Converts a raw LLM-extracted profile dict (from `discover_fund_profile`) into the structured fund config format expected by the app — normalising bank account fields and initialising member TSB values to zero.
- `fund_id` — derived ID string.
- `folder_path` — relative path to the document folder.
- `profile` — the dict returned by `discover_fund_profile`.
- `keywords` — keyword config template.

#### `api_funds_discover()`
`GET /api/funds/discover` — Scans the `data/` directory for sub-folders that are not already registered as funds. For each unregistered folder, counts its PDFs recursively (including nested sub-folders) and returns a list of candidates the user can choose to bootstrap.

#### `api_funds_bootstrap()`
`POST /api/funds/bootstrap` — Takes a list of folder paths from the request body and, for each one, calls `discover_fund_profile` to extract fund metadata automatically from its PDF documents. Returns a list of proposed fund configs (with warnings if extraction failed or no PDFs were found). Does **not** save anything — the proposed configs are returned for the user to confirm first.

- Request body: `{ "folders": ["data/COBBLE", ...] }`

Calls → `discover_fund_profile`, `_derive_fund_id`, `_profile_to_fund_config`, `_empty_fund_config`

#### `api_jobs()`
`GET /api/jobs` — Returns all job records from the database.

#### `api_create_job()`
`POST /api/jobs/create` — Creates a new job record for a given fund and immediately launches `run_phase1_worker` in a background thread. Sets initial job status to `processing_docs`.

- Request body: `{ "fund_id": "admcm", "job_type": "Accounting_Audit" }`

Calls → `run_phase1_worker` (in a new thread)

#### `api_job_details(job_id)`
`GET /api/jobs/<job_id>/details` — Returns the full job record for a single job, including current status, progress percentage, file classifications, and AI results.

#### `api_processor_review(job_id)`
`POST /api/jobs/<job_id>/processor-review` — Records the human processor's review decisions. Copies the approved files from the `staging/` folder to the `workpaper/` folder, applies any category overrides, saves the processor's notes, and kicks off `run_phase2_worker` in a background thread.

- Request body: `{ "files": [...], "processor_notes": "..." }`

Calls → `run_phase2_worker` (in a new thread), `determine_target_filename`

#### `api_reviewer_review(job_id)`
`POST /api/jobs/<job_id>/reviewer-review` — Records the human reviewer's final sign-off. Updates the job status to `completed` and saves the reviewer's notes.

- Request body: `{ "reviewer_notes": "...", "auditor_notes": [...] }`

#### `api_job_reconciliation(job_id)`
`GET /api/jobs/<job_id>/reconciliation` — Returns the Phase 2 reconciliation results, client queries, and match-rate summary from the job's `phase2_context`.

#### `api_update_query_status(job_id, query_id)`
`POST /api/jobs/<job_id>/queries/<query_id>/status` — Marks a client query as `sent` or `dismissed`. Also accepts an updated `query_text` in case the reviewer has edited the query before sending. Searches both top-level queries and their sub-queries.

- Request body: `{ "status": "sent", "query_text": "..." }`

#### `api_job_token_usage(job_id)`
`GET /api/jobs/<job_id>/token-usage` — Returns the token usage and cost summary for a job (`calls`, `phases`, `job_total`). Returns `{ "available": false }` if no token data has been recorded yet (job predates Story T).

#### `api_fund_cost_summary(fund_id)`
`GET /api/funds/<fund_id>/cost-summary` — Aggregates total AI processing cost across all jobs for a fund. Returns a per-job breakdown and the running total in USD.

#### `api_regroup_queries(job_id)`
`POST /api/jobs/<job_id>/regroup-queries` — Re-runs LLM semantic classification against all existing query transactions and rebuilds the query groups using the SMSF taxonomy from `transaction_categories.json`. Replaces the stored queries in the job and returns the new list.

Calls → `regroup_stored_queries`, `load_llm_pricing`, `calculate_call_cost`, `record_token_usage`

#### `api_serve_job_file(job_id, phase, filename)`
`GET /api/jobs/<job_id>/file/<phase>/<filename>` — Streams a PDF file from a job's `staging/` or `workpaper/` folder to the browser. Validates that `phase` is one of the two allowed values to prevent directory traversal.

#### `legacy_process()`
`POST /api/process` — Backwards-compatibility endpoint from the original POC. Runs both Phase 1 and Phase 2 back-to-back in a single background thread against the hardcoded `data/ADMCM` folder.

#### `legacy_get_progress(run_id)`
`GET /api/progress/<run_id>` — Backwards-compat progress polling endpoint. Checks `jobs_db.json` first, then falls back to the old file-based `state/progress.json`.

#### `legacy_get_results(run_id)`
`GET /api/results/<run_id>` — Backwards-compat results endpoint. Returns the AI reviewer results and fund profile for a completed run.

#### `legacy_download_workpaper(run_id, filename)`
`GET /api/workpaper-files/<run_id>/<filename>` — Backwards-compat file download endpoint. Delegates directly to `api_serve_job_file`.

---

## core_engine.py

The AI processing engine. Contains everything related to reading PDFs, running OCR, calling the LLM, classifying documents, reconciling transactions, and generating client queries. This is the core library imported by `app.py`.

---

### Utilities & Infrastructure

#### `find_executable(name, default_path)`
Searches for a command-line tool (`pdftoppm` or `tesseract`) first on the system `PATH`, then at a known default location (e.g. Homebrew on Mac). Returns whichever path is found, falling back to just the name if neither is present.
- `name` — tool name, e.g. `"tesseract"`.
- `default_path` — fallback path, e.g. `"/opt/homebrew/bin/tesseract"`.

#### `extract_pdf_text(filepath, max_pages=3)`
Reads up to `max_pages` pages of a PDF using the `pypdf` library and returns the concatenated text. Raises a `RuntimeError` if the file cannot be parsed.
- `filepath` — full path to the PDF.
- `max_pages` — how many pages to read (default 3; enough for document identification).

#### `ocr_pdf_first_page(filepath, scratch_dir)`
Convenience wrapper that runs OCR on just the first page of a PDF. Delegates to `ocr_pdf_single_page` with `page_idx=0`.
- `filepath` — path to the PDF.
- `scratch_dir` — temp folder for intermediate image files.

#### `ocr_pdf_single_page(filepath, page_idx, scratch_dir)`
Converts a single PDF page to a PNG image using `pdftoppm` and then extracts text from that image using Tesseract OCR. Used for scanned PDFs where embedded text is absent or sparse. Returns the extracted text string.
- `filepath` — path to the PDF.
- `page_idx` — zero-based page number.
- `scratch_dir` — temp directory for the intermediate PNG file.

---

### Token Economics

#### `load_llm_pricing(workspace_dir)`
Reads `llm_pricing.json` from the workspace root and returns a dict keyed by model ID, containing per-million-token input/output rates. Used as a fallback when OpenRouter doesn't report a cost.
- `workspace_dir` — path to the project root directory.

#### `calculate_call_cost(model, prompt_tokens, completion_tokens, pricing, openrouter_cost=None)`
Calculates the USD cost of a single LLM API call. Prefers the `openrouter_cost` figure from the API response (the actual billed amount). Falls back to multiplying token counts by the rates in `llm_pricing.json` only when OpenRouter doesn't provide a cost. Returns a float rounded to 6 decimal places.
- `model` — model ID string, e.g. `"x-ai/grok-4.20"`.
- `prompt_tokens` — number of input tokens used.
- `completion_tokens` — number of output tokens generated.
- `pricing` — the dict returned by `load_llm_pricing`.
- `openrouter_cost` — optional float cost from the API response's `usage.cost` field.

#### `record_token_usage(job, call_id, phase, usage, cost_usd)`
Appends one LLM call record to the job's `token_usage` structure and updates the running totals for both the phase and the overall job. Mutates the `job` dict in place — the caller must save it to `jobs_db.json` afterwards.
- `job` — the job dict (loaded from the database).
- `call_id` — a descriptive string identifying this call, e.g. `"phase1_classify_Invoice.pdf"`.
- `phase` — phase label, e.g. `"phase1"` or `"phase2"`.
- `usage` — the usage dict returned by `query_openrouter` (contains `model`, `prompt_tokens`, etc.).
- `cost_usd` — the cost from `calculate_call_cost`.

---

### LLM Communication

#### `query_openrouter(api_key, system_prompt, user_content, response_format=None, model="x-ai/grok-4.20", timeout=120)`
The central function for sending prompts to OpenRouter's API. Sends a system + user message pair, waits for the response, and returns a tuple of `(response_text, usage_dict)`.

If the primary model (`grok-4.20`) fails, it automatically retries with the fallback model (`gemini-2.5-flash`) before propagating the error.

- `api_key` — OpenRouter API key.
- `system_prompt` — the instructions/role definition for the AI.
- `user_content` — the actual document content or data for the AI to process.
- `response_format` — optional `{"type": "json_object"}` to force a JSON response.
- `model` — which LLM to use.
- `timeout` — seconds to wait for the response.

---

### Fund Profile Discovery (Story 10 / Bootstrap)

#### `discover_fund_profile(input_dir, api_key, scratch_dir)`
Scans a fund's document folder, picks a representative sample of PDFs (prioritising files with keywords like "statement", "valuation", "member"), extracts their text, and asks the LLM to identify the fund's name, ABN, bank accounts, members, and investments from those snippets. Returns a structured profile dict.

Falls back to a hardcoded ADMCM profile if it detects ADMCM files and the API call fails.
- `input_dir` — path to the folder containing the fund's PDFs.
- `api_key` — OpenRouter API key.
- `scratch_dir` — temp folder for OCR if needed.

Calls → `extract_pdf_text`, `ocr_pdf_first_page`, `query_openrouter`

---

### Phase 1: Document Classification

#### `determine_target_filename(classification, original_name)`
Maps an LLM classification result to the standardised workpaper filename. For example, a Bank Statement classification with account number `06716720642566` becomes `"Bank Statement - 06716720642566.pdf"`. Falls back to a sanitised version of the category name for unknown categories.
- `classification` — the JSON dict from the LLM with `category`, `account_number`, `amount`, and `date` fields.
- `original_name` — the original source filename (used only for the unclassified fallback).

#### `get_unique_filepath(dest_dir, filename)`
Ensures there is no filename collision in `dest_dir`. If `filename` already exists, appends `_1`, `_2`, etc. until a free name is found. Returns the full path to the (possibly renamed) file.
- `dest_dir` — the destination folder.
- `filename` — the desired filename.

#### `classify_papers(input_dir, workpapers_dir, fund_profile, api_key, scratch_dir, update_progress, job_type="Accounting_Audit", record_usage=None)`
The Phase 1 classification engine. Processes every PDF in `input_dir` (skipping the `Additional Notes` subfolder), extracts text or falls back to OCR for scanned documents, calls the LLM to classify each one, and copies the file to `workpapers_dir` with its standardised name.

Special handling for bank statements: instead of copying each statement file separately, it reads every page, identifies which account each page belongs to (by searching for account numbers), and merges the pages into one PDF per account.

Returns two lists: `(processed_files, unprocessed_files)`.
- `input_dir` — source folder with the original documents.
- `workpapers_dir` — destination folder for classified/renamed copies.
- `fund_profile` — fund config (used for account numbers and keyword categories).
- `api_key` — OpenRouter key.
- `scratch_dir` — temp folder for OCR files.
- `update_progress` — callback `(percent, message)` for live progress updates.
- `job_type` — controls which document categories are active.
- `record_usage` — optional callback `(call_id, phase, usage)` to track token costs.

Calls → `extract_pdf_text`, `ocr_pdf_first_page`, `ocr_pdf_single_page`, `query_openrouter`, `fallback_classify_by_keywords`, `determine_target_filename`, `get_unique_filepath`

#### `fallback_classify_by_keywords(filename, text, keywords_config, fund_profile)`
Rule-based keyword classifier that runs when the LLM API call fails. Matches the document's filename and extracted text against known patterns (e.g. "audit" + "invoice" → Audit Invoice, "portfolio" → Portfolio Valuation). Returns a classification dict in the same format as the LLM response. Used only as a last resort.
- `filename` — the document's filename.
- `text` — the extracted or OCR'd text.
- `keywords_config` — the fund's keyword categories from `funds_config.json`.
- `fund_profile` — used for account number matching.

#### `run_ai_processor_phase(folder_path, run_id, fund_profile, job_type, api_key, scratch_dir, update_progress, record_usage=None)`
Top-level wrapper for Phase 1. Creates the `staging/` directory under the job folder and calls `classify_papers` to classify all documents into it. Returns `(processed, unprocessed)` lists.
- `folder_path` — source document folder.
- `run_id` — relative path to the job directory, e.g. `"jobs/job_20260621_103331"`.
- Other params — as per `classify_papers`.

Calls → `classify_papers`

---

### Phase 2: Checklist & Lead Schedule Reconciliation

#### `reconcile_papers(workpapers_dir, fund_profile, api_key, scratch_dir, update_progress, job_type="Accounting_Audit", record_usage=None)`
Reads all PDFs from the `workpapers_dir`, builds a large context block of their text, and sends it to the LLM with a detailed schema asking for the full audit checklist status plus four reconciliation schedules: cash at bank, portfolio, tax accounts, and member TSB.

After the LLM responds, this function re-populates all `files` arrays in the checklist by pattern-matching filenames (e.g. portfolio valuation files match "Portfolio Valuation"), and enforces playbook-specific overrides (e.g. the Accounting playbook suppresses audit/permanent doc checks).

Falls back to pre-calculated hardcoded data (from `verify_and_generate_workpapers.py`) if the API call fails.

Returns the full `ai_results` dict with `checklist`, `cash_reconciliation`, `portfolio_reconciliation`, `tax_reconciliation`, and `member_reconciliation`.
- `workpapers_dir` — the folder of approved, renamed workpaper PDFs.
- `fund_profile` — fund config for dynamic schema generation.
- `api_key` — OpenRouter key.
- `scratch_dir` — temp dir; cached OCR files here are reused.
- `update_progress` — progress callback.
- `job_type` — `"Accounting"` or `"Accounting_Audit"`.
- `record_usage` — optional token tracking callback.

Calls → `query_openrouter`

#### `run_ai_reviewer_phase(run_id, fund_profile, job_type, api_key, scratch_dir, update_progress, record_usage=None)`
Top-level wrapper for the checklist/lead-schedule half of Phase 2. Creates the `workpaper/` directory if needed and calls `reconcile_papers`. Returns the AI results dict.
- `run_id` — relative path to the job folder.
- Other params — as per `reconcile_papers`.

Calls → `reconcile_papers`

---

### Phase 2: Bank Reconciliation Pipeline

#### `build_phase2_context(job_id, fund_profile, job_record)`
Assembles the structured context dict that every Phase 2 reconciliation function needs. Maps each fund bank account to its statement PDF file in the workpaper folder, collects all non-bank-statement files into `supporting_documents`, and locates the accountant's reconciliation notes PDF (if any) in the `Additional Notes` subfolder.

Returns a dict with keys: `fund_id`, `job_type`, `bank_accounts`, `supporting_documents`, `reconciliation_notes_path`, `processor_notes`, `unprocessed_files`.
- `job_id` — used to build the workpaper folder path.
- `fund_profile` — provides the list of fund bank accounts.
- `job_record` — the job dict from `jobs_db.json` (provides the approved file list).

#### `_extract_supporting_doc_text(doc_path, scratch_dir=None)`
Private helper. Extracts the full text of a supporting document PDF using `pypdf`. If the total extracted text is sparse (under 100 characters — typical of scanned PDFs), falls back to Tesseract OCR on every page. Returns the extracted text string (may be empty if all methods fail).
- `doc_path` — path to the PDF.
- `scratch_dir` — optional temp dir for OCR; derived from `doc_path` if not provided.

Calls → `ocr_pdf_single_page`

#### `_extract_portfolio_holdings(full_text, doc_name)`
Private helper. Parses the raw text of a Portfolio Valuation PDF into a compact, one-line-per-holding summary (e.g. `"MXT: Metrics Master Income Trust (14000 units)"`). Uses ASX ticker pattern matching to anchor each security block. Falls back to the first 6,000 characters of raw text if no tickers are found. This avoids sending 15K+ characters of portfolio PDF to the LLM when a few hundred structured characters suffice.
- `full_text` — the full extracted text of the portfolio valuation document.
- `doc_name` — the document filename, used to label the output block.

#### `build_reconciliation_prompt(phase2_context, transactions_by_account, scratch_dir=None)`
Builds the system prompt and user content for the reconciliation LLM call (Story 2). The prompt includes:
- The accountant's reconciliation notes as a mandatory preamble (if present).
- Excerpts from every supporting document (OCR fallback for scanned files; compact holdings summary for portfolio valuations).
- A numbered transaction listing for each bank account.

Returns `(system_prompt, user_content)`.
- `phase2_context` — the dict from `build_phase2_context`.
- `transactions_by_account` — dict mapping account number to list of transaction dicts.
- `scratch_dir` — passed through to `_extract_supporting_doc_text`.

Calls → `_extract_supporting_doc_text`, `_extract_portfolio_holdings`

#### `_parse_via_llm(text, account, api_key, model=None, record_usage=None)`
Private helper. Sends the raw text of a bank statement to the LLM and asks it to extract every transaction as structured JSON: date, description, debit, credit, balance. Returns the parsed result dict.
- `text` — the full text of the bank statement.
- `account` — the account dict (name, number) for context in the prompt.
- `api_key` — OpenRouter key.
- `model` — optional model override.
- `record_usage` — optional token tracking callback.

Calls → `query_openrouter`

#### `extract_transactions_from_statement(pdf_path, account, api_key, model=None, record_usage=None)`
Reads a bank statement PDF, extracts its full text across all pages (with OCR fallback if text is sparse), and calls `_parse_via_llm` to extract every transaction. Returns a list of transaction dicts `{date, description, debit, credit, balance, raw_line}`.
- `pdf_path` — path to the bank statement PDF.
- `account` — account dict.
- `api_key` — OpenRouter key.
- `model` / `record_usage` — passed through to `_parse_via_llm`.

Calls → `_parse_via_llm`, `ocr_pdf_first_page`

#### `run_reconciliation_call(phase2_context, api_key, update_progress, model=PHASE2_DEFAULT_MODEL, transactions_by_account=None, record_usage=None, scratch_dir=None)`
Runs LLM Call 1 of the bank reconciliation pipeline. Extracts transactions from each bank statement PDF (unless pre-extracted transactions are passed in via `transactions_by_account`), then calls the reconciliation LLM to classify each transaction as `matched` or `unmatched` against the supporting documents.

Returns a dict keyed by account number, each value being the LLM's reconciliation result for that account.
- `phase2_context` — from `build_phase2_context`.
- `api_key` — OpenRouter key.
- `update_progress` — progress callback.
- `model` — which LLM to use.
- `transactions_by_account` — if provided, skips transaction extraction (useful for benchmarking).
- `record_usage` — token tracking callback.
- `scratch_dir` — passed through to `build_reconciliation_prompt`.

Calls → `extract_transactions_from_statement`, `build_reconciliation_prompt`, `query_openrouter`

#### `build_query_generation_prompt(unmatched_transactions, fund_name)`
Builds the system prompt and user content for LLM Call 2 (Story 3 — original LLM-grouped query generation). Formats the unmatched transactions with their reasons and instructs the LLM to group them by category and write professional client query text. Returns `(system_prompt, user_content)`.
- `unmatched_transactions` — list of transaction dicts flagged as unmatched by the reconciliation call.
- `fund_name` — the fund's display name.

#### `run_query_generation_call(unmatched_transactions, fund_name, api_key, update_progress, model=PHASE2_DEFAULT_MODEL, record_usage=None)`
Runs LLM Call 2: sends the unmatched transactions to the LLM and gets back a list of grouped client queries. Each query has an id, category, query text, and the list of transactions it covers. Returns the queries list.
- `unmatched_transactions` — list of unmatched transaction dicts.
- `fund_name` — fund display name for prompt context.
- Other params — standard API/tracking args.

Calls → `build_query_generation_prompt`, `query_openrouter`

---

### Phase 2: Deterministic Query Grouping (Story 3R)

#### `_tx_amount_str(tx)`
Private helper. Returns a human-readable amount string for a transaction regardless of which field format it uses. New-format transactions have separate `debit`/`credit` numeric fields; old-format transactions have a single `amount` string. Returns strings like `"DR $270.41"` or `"CR $61.29"`.
- `tx` — a transaction dict.

#### `_tx_credit_float(tx)`
Private helper. Extracts the credit value from a transaction dict as a float, handling both new-format (`credit` field) and old-format (`amount` string starting with `"CR "`). Returns `0.0` if the transaction has no credit.
- `tx` — a transaction dict.

#### `_format_payee_token(token)`
Private helper. Formats a single word of a payee name: short all-caps tokens (ASX tickers like `"MXT"`) stay uppercased; everything else is title-cased.
- `token` — a single word string.

#### `_extract_payee(description)`
Private helper. Parses the payee/security name out of a bank statement description like `"Direct Credit 067167 MXT DISTRIBUTION cm-123456"`. Strips the BSB prefix, the reference number suffix, and trailing distribution/dividend qualifiers (e.g. `DST`, `DIV`, `JUN`). Returns the clean payee name.
- `description` — raw transaction description string.

Calls → `_format_payee_token`

#### `group_unmatched_transactions(unmatched_transactions)`
Groups unmatched transactions into labelled buckets using a fixed rule set (no LLM). Rules:
- `"Credit Interest"` → Bank Interest
- Contains `"FinClear Service"` → Broker Settlements
- Contains `"ASIC"` → Regulatory Fees – ASIC
- Contains `"ATO"` and is a credit → ATO Tax Refund
- Contains `"Transfer To/From"` → Internal Transfer
- Starts with `"Direct Credit"` → Investment Income – {payee} (granular) / Investment Income – Dividends & Distributions (coarse)
- Everything else → Other – {first 40 chars}

Returns a dict with two keys: `"coarse"` and `"granular"`, each a list of `{category, transactions}` dicts.
- `unmatched_transactions` — the unmatched transaction list.

Calls → `_extract_payee`

---

### Phase 2: Semantic Query Generation (Story 3S)

#### `load_transaction_categories(workspace_dir)`
Reads and validates `transaction_categories.json` from the workspace root. Returns the list of category dicts. Raises errors if the file is missing or if no fallback category is defined.
- `workspace_dir` — project root path.

#### `build_classification_prompt(unmatched_transactions, categories)`
Builds the system prompt and user content for the LLM transaction classification call. The prompt includes the full category taxonomy from `transaction_categories.json` and asks the LLM to assign exactly one label to each transaction. Returns `(system_prompt, user_content)`.
- `unmatched_transactions` — list of transaction dicts.
- `categories` — the list from `load_transaction_categories`.

#### `classify_transactions(unmatched_transactions, categories, fund_name, api_key, model=PHASE2_DEFAULT_MODEL, record_usage=None)`
Calls the LLM to assign each unmatched transaction a category from the SMSF taxonomy. Validates every returned label against the allowed list; any invalid or missing label falls back to the taxonomy's `is_fallback` category. Returns the original transaction list with an `smsf_category` field added to each dict.
- `unmatched_transactions` — transactions to classify.
- `categories` — taxonomy from `load_transaction_categories`.
- `fund_name` — used for logging.
- Other params — standard API/tracking args.

Calls → `build_classification_prompt`, `query_openrouter`

#### `build_coarse_query_text_prompt(coarse_groups, fund_name)`
Builds the prompt for the LLM call that writes the professional query text for each coarse group. The grouping is already done in Python — this just asks the LLM to write the wording. Returns `(system_prompt, user_content)`.
- `coarse_groups` — list of `{category, transactions}` dicts.
- `fund_name` — used in the prompt for personalisation.

#### `generate_granular_query_text(category, transactions, fund_name="")`
Generates query text for a granular Investment Income group **without** calling the LLM. Uses a Python string template, infers the document type from description keywords (`DIV` → dividend statement, `DST`/`DIST` → distribution notice), and formats the transaction list inline. Avoids an extra LLM call for sub-queries.
- `category` — the granular category label (e.g. `"Investment Income – ANZ"`).
- `transactions` — the transactions in this group.
- `fund_name` — used in the query text.

#### `run_coarse_query_text_call(coarse_groups, fund_name, api_key, update_progress, model=PHASE2_DEFAULT_MODEL, record_usage=None)`
Calls the LLM once to write professional query text for all coarse groups in a single request. Returns a dict mapping `category → query_text`.
- `coarse_groups` — list of `{category, transactions}` dicts.
- Other params — standard API/tracking args.

Calls → `build_coarse_query_text_prompt`, `query_openrouter`

#### `_build_queries_from_classified(classified_txs, categories, fund_name, api_key, update_progress, model=PHASE2_DEFAULT_MODEL, record_usage=None)`
Private shared helper used by both `run_bank_reconciliation_phase` and `regroup_stored_queries`. Takes a list of transactions with `smsf_category` labels and:
1. Groups them into coarse buckets by category.
2. Groups `sub_groupable` categories (e.g. Investment Income) into per-security granular buckets.
3. Calls `run_coarse_query_text_call` for the LLM-written coarse query text.
4. Generates granular sub-query text using `generate_granular_query_text` (no LLM).
5. Assembles and returns the final queries list.

Calls → `run_coarse_query_text_call`, `generate_granular_query_text`, `_extract_payee`

#### `regroup_stored_queries(existing_queries, fund_name, api_key, update_progress, record_usage=None)`
Re-groups the transactions from a job's existing queries using fresh LLM semantic classification. Extracts all transactions from the stored queries, runs `classify_transactions`, then calls `_build_queries_from_classified` to produce a new set of query groups. Returns `(new_queries, regrouped, match_rate)`.
- `existing_queries` — the current queries list from the job.
- `fund_name` — fund display name.
- Other params — standard API/tracking args.

Calls → `load_transaction_categories`, `classify_transactions`, `_build_queries_from_classified`

#### `run_bank_reconciliation_phase(job_id, fund_profile, job_type, api_key, scratch_dir, update_progress, record_usage=None)`
The top-level Phase 2 orchestrator for the bank reconciliation pipeline. Runs the full sequence:
1. Loads the job record from `jobs_db.json`.
2. Calls `build_phase2_context` to map statements and supporting docs.
3. Calls `run_reconciliation_call` to extract transactions and reconcile them (LLM Call 1).
4. Collects all unmatched transactions across all accounts.
5. Calls `classify_transactions` to semantically label them (LLM Call 3S).
6. Calls `_build_queries_from_classified` to produce grouped queries with professional query text (LLM Call 3R).

Returns `{ phase2_context, reconciliation_results, queries, summary }`.

Calls → `build_phase2_context`, `run_reconciliation_call`, `load_transaction_categories`, `classify_transactions`, `_build_queries_from_classified`

---

## classify_workpapers.py

Standalone command-line script from the original POC. Run it directly from the terminal to classify a folder of PDFs without using the web app. Most of its logic has since been absorbed and improved in `core_engine.py`.

```
python3 classify_workpapers.py <input_folder_path> [output_parent_path]
```

#### `find_executable(name, default_path)`
Same purpose as in `core_engine.py` — locates `pdftoppm` and `tesseract`.

#### `extract_pdf_text(filepath)`
Simplified PDF text extractor (reads up to 3 pages). Unlike the `core_engine` version, this one prints errors to stderr and returns an empty string rather than raising an exception.
- `filepath` — path to the PDF.

#### `ocr_pdf_first_page(filepath)`
OCRs the first page of a PDF. Functionally identical to `core_engine.ocr_pdf_first_page` but writes directly to a tempfile rather than a managed `scratch_dir` folder.
- `filepath` — path to the PDF.

#### `query_openrouter_classification(text_content)`
Simplified OpenRouter call that classifies one document against the hardcoded 11-category system prompt. Returns the parsed JSON classification dict, or `None` on error.
- `text_content` — extracted text from the document.

#### `determine_target_filename(classification, original_name)`
Identical in logic to `core_engine.determine_target_filename`. Maps a classification dict to the standardised workpaper filename.

#### `get_unique_filepath(dest_dir, filename)`
Identical in logic to `core_engine.get_unique_filepath`. Avoids filename collisions.

#### `main()`
Entry point. Scans the input folder for PDFs, classifies each one, and copies it to `output/workpaper/` with its standardised name. Prints a summary at the end.

Calls → `extract_pdf_text`, `ocr_pdf_first_page`, `query_openrouter_classification`, `determine_target_filename`, `get_unique_filepath`

---

## verify_and_generate_workpapers.py

Standalone command-line script from the original POC. Reads the workpaper folder, calls the LLM for audit analysis, saves JSON results, and generates a self-contained HTML dashboard. Its reconciliation logic is now handled by `core_engine.reconcile_papers`; this file is primarily kept as the source of the hardcoded fallback data.

#### `get_document_text(filename)`
Reads the text of a workpaper PDF. Checks for a cached OCR file in `output/scratch/` first; if not found, extracts text directly from the PDF using `pypdf`.
- `filename` — just the filename (not the full path); looks in `output/workpaper/`.

#### `main()`
Entry point. Gathers all workpaper PDFs, extracts their text, sends it to the LLM for audit analysis, saves `reconciliation_results.json` and `checklist_status.json` to `output/Output_processor/`, and generates `index.html`.

Calls → `get_document_text`, `get_fallback_audit_data`, `generate_dashboard_html`

#### `get_fallback_audit_data(available_files)`
Returns a complete hardcoded audit result dict containing pre-verified figures for the ADMCM fund. Used as a fallback when the LLM API is unavailable, and as the fallback data source for `core_engine.reconcile_papers`.
- `available_files` — the list of filenames in the workpaper folder (not used in the current implementation; parameter kept for compatibility).

#### `generate_dashboard_html(checklist, cash, portfolio, tax, member)`
Generates a self-contained HTML audit dashboard with three tabs: Document Checklist, Lead Schedules & Reconciliations, and Audit Issues & Exceptions. Returns the full HTML string.
- `checklist` — the checklist dict from the AI results.
- `cash` — the cash reconciliation dict.
- `portfolio` — the portfolio reconciliation dict.
- `tax` — the tax reconciliation dict.
- `member` — the member reconciliation dict.

---

## extract_checklist.py

A one-off utility script that extracts text from the `Document Required Checklist - 2025.pdf` file and saves it to `data/checklist_extracted.txt`. Not part of the runtime pipeline.

#### `main()`
Opens the checklist PDF, prints the first 1,000 characters of each page to the terminal, and saves the full extracted text to a `.txt` file.

---

## Call Graph

The two main execution pipelines, shown as call trees. Indentation = called by the line above.

---

### Pipeline 1 — Phase 1: Document Classification

Triggered by `POST /api/jobs/create`.

```
api_create_job()
└── run_phase1_worker()                         [background thread]
    ├── load_llm_pricing()
    └── run_ai_processor_phase()
        └── classify_papers()
            ├── extract_pdf_text()              [for each PDF]
            ├── ocr_pdf_first_page()            [fallback if text < 50 chars]
            ├── query_openrouter()              [classify each document]
            │   └── query_openrouter()          [auto-retry with gemini-2.5-flash]
            ├── fallback_classify_by_keywords() [fallback if API call fails]
            ├── determine_target_filename()
            ├── get_unique_filepath()
            └── ocr_pdf_single_page()           [for scanned bank statement pages]
```

---

### Pipeline 2 — Phase 2: Reconciliation & Query Generation

Triggered by `POST /api/jobs/<job_id>/processor-review` (after human approval).

```
api_processor_review()
└── run_phase2_worker()                              [background thread]
    ├── load_llm_pricing()
    ├── build_phase2_context()
    │
    ├── run_bank_reconciliation_phase()
    │   ├── build_phase2_context()
    │   ├── run_reconciliation_call()                [LLM Call 1: reconcile transactions]
    │   │   ├── extract_transactions_from_statement()
    │   │   │   ├── ocr_pdf_first_page()             [fallback for scanned statements]
    │   │   │   └── _parse_via_llm()
    │   │   │       └── query_openrouter()
    │   │   ├── build_reconciliation_prompt()
    │   │   │   ├── _extract_supporting_doc_text()
    │   │   │   │   └── ocr_pdf_single_page()        [fallback for scanned supporting docs]
    │   │   │   └── _extract_portfolio_holdings()    [for Portfolio Valuation docs]
    │   │   └── query_openrouter()                   [LLM Call 1 actual]
    │   │
    │   ├── load_transaction_categories()
    │   ├── classify_transactions()                  [LLM Call 3S: semantic classification]
    │   │   ├── build_classification_prompt()
    │   │   └── query_openrouter()
    │   │
    │   └── _build_queries_from_classified()
    │       ├── run_coarse_query_text_call()         [LLM Call 3R: write query text]
    │       │   ├── build_coarse_query_text_prompt()
    │       │   └── query_openrouter()
    │       ├── generate_granular_query_text()       [no LLM — Python template]
    │       └── _extract_payee()
    │           └── _format_payee_token()
    │
    └── run_ai_reviewer_phase()                      [LLM Call 2: checklist + lead schedules]
        └── reconcile_papers()
            └── query_openrouter()
```

---

### Pipeline 3 — Fund Bootstrap (Story 10)

Triggered by `POST /api/funds/bootstrap`.

```
api_funds_bootstrap()
├── _derive_fund_id()
├── _profile_to_fund_config()   [if PDFs found and extraction succeeds]
├── _empty_fund_config()        [fallback if no PDFs or extraction fails]
└── discover_fund_profile()
    ├── extract_pdf_text()      [for each representative PDF]
    ├── ocr_pdf_first_page()    [fallback for scanned PDFs]
    └── query_openrouter()      [extract fund name, ABN, accounts, members]
```

---

### Pipeline 4 — Query Regroup (Story 3R on-demand)

Triggered by `POST /api/jobs/<job_id>/regroup-queries`.

```
api_regroup_queries()
├── load_llm_pricing()
└── regroup_stored_queries()
    ├── load_transaction_categories()
    ├── classify_transactions()          [LLM: re-classify all stored transactions]
    │   ├── build_classification_prompt()
    │   └── query_openrouter()
    └── _build_queries_from_classified()
        ├── run_coarse_query_text_call()
        │   ├── build_coarse_query_text_prompt()
        │   └── query_openrouter()
        ├── generate_granular_query_text()
        └── _extract_payee()
```

---

### Token Usage Flow (Story T)

Every LLM call feeds token data through this chain:

```
query_openrouter()                         → returns (content, usage)
    usage includes: prompt_tokens,
                    completion_tokens,
                    openrouter_cost
         ↓
record_llm_usage_p1() / record_llm_usage_p2()  [inline closures in app.py workers]
    ├── calculate_call_cost()              → prefers openrouter_cost; falls back to pricing table
    └── record_token_usage()              → mutates job dict; caller saves to jobs_db.json
         ↓
api_job_token_usage()                      → GET /api/jobs/<id>/token-usage
api_fund_cost_summary()                    → GET /api/funds/<id>/cost-summary
```
