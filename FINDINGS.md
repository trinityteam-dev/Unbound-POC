# Codebase Findings & Build Backlog

Session date: 2026-06-18. Covers Phase 1 bug analysis, Phase 2 sprint readiness, and orphaned code.

---

## 1. Phase 1 Bugs — `classify_papers()` in `core_engine.py`

### Bug A — Name collisions silently overwrite files (Gap 2)

**File:** `core_engine.py:508-512`

`classify_papers()` copies non-bank-statement files to `staging/` using plain `shutil.copy2()`. When two source files are classified to the same target name, the second silently overwrites the first. No error, no log warning.

**Confirmed collisions on ADMCM sample:**

| Source files | Target name | Loser |
|---|---|---|
| `2025 Tax Statement - Metrics.pdf` (740k) + `ADMCM - ITA.pdf` (72k) | `Income Tax.pdf` | Tax Statement (740k lost) |
| `Portfolio_Valuation at 30.06.25.pdf` (107k) + `Ledger_Summary...pdf` (15k) + `FY25 Periodic Statement...pdf` | `Portfolio Valuation at 30.06.25.pdf` | Actual portfolio valuation (107k lost) |

**Fix:** Wire the already-written `get_unique_filepath()` (currently orphaned at `core_engine.py:304`) into the copy path at line 509:
```python
# Replace:
dest_filepath = os.path.join(workpapers_dir, target_name)
# With:
dest_filepath = get_unique_filepath(workpapers_dir, target_name)
```

---

### Bug B — `Ordr Mint Transation Listing` missing from ADMCM playbook keywords

**File:** `funds_config.json` → `admcm.keywords.Accounting_Audit`

The `Ordr Mint Transation Listing` category exists in `determine_target_filename()` and the default fallback keywords, but is absent from ADMCM's playbook in `funds_config.json`. The AI is never offered it as a choice, so the Ord Minnett broker transaction listing (`Ledger_Summary. 01.07.24 to 30.06.25.pdf`) gets misclassified as `Portfolio Valuation` and then overwritten (see Bug A).

**Fix:** Add to `funds_config.json` → `admcm.keywords.Accounting_Audit`:
```json
"Ordr Mint Transation Listing": "Ord Minnett, broker, transaction, ledger, account 1160944, buy, sell, EFT"
```
Same addition needed for `Accounting` playbook if Ord Minnett transactions are relevant there.

**Note:** The typo `"Ordr Mint Transation Listing"` (missing 'e' in Order and Transaction) is baked into `determine_target_filename()`, `classify_workpapers.py`, and `funds_config.json`. If corrected, it must be corrected everywhere consistently.

---

### Non-issue (investigated, not a bug)

**"Silently dropped files" (Gap 1) — DOES NOT EXIST.**

`SMSF ex[enses to 30.11.24.pdf`, `SMSF expenses to 30.05.25.pdf`, `SMSF expenses to 30.11.25.pdf` — despite their misleading names — are correctly identified by the AI as CBA Direct Investment bank statements (account `06200016743999`). Their pages are merged into `Bank Statement - CBA Direct Investment Bank Account - 06200016743999.pdf`. Confirmed in job logs.

---

## 2. Orphaned Functions in `core_engine.py`

### `discover_fund_profile()` — lines 128–252

**Never called** by the Flask app, `app.py`, or any script.

**What it does:** Given a folder of raw PDFs and an API key, reads up to 8 representative files and asks the LLM to extract the fund's name, ABN, bank accounts, members, TFNs, TSB balances, and investment holdings — i.e., auto-populate `funds_config.json` without manual entry.

**Why orphaned:** When the app was refactored to use `funds_config.json` as the manual source of truth, this function was superseded. However, it is largely ready to use and could be exposed as a "Discover Fund from Documents" feature — a thin wrapper mapping its return keys to the `funds_config.json` schema (`fund_name` → `name`, add `id` and `folder_path`, default `keywords` to `{}`).

**Has a hardcoded fallback:** If the API call fails and any filename contains "admcm" or "martignoni", it returns the ADMCM profile hardcoded. This is test-only behaviour.

### `get_unique_filepath()` — lines 304–311

**Never called** within `core_engine.py` or `app.py`. A duplicate version exists in `classify_workpapers.py` (line 237) where it IS used.

**What it does:** Appends `_1`, `_2` etc. to a filename if the destination path already exists, preventing overwrites.

**Fix:** Wire into `classify_papers()` at line 509 (see Bug A above).

---

## 3. Legacy Code

### `output/` folder and standalone scripts

`classify_workpapers.py` and `verify_and_generate_workpapers.py` are v1-era standalone CLI scripts. They write to `output/Output_processor/` (hardcoded path). The Flask app never reads from or writes to `output/`. These scripts are preserved for reference but are not part of the live app flow.

### `POST /api/process` legacy route — `app.py:463`

A hidden route that runs `classify_papers()` + `reconcile_papers()` back-to-back in one shot via `run_legacy_compat()`, skipping the human processor sign-off step entirely. Never triggered by the UI. Preserved for backward compatibility with v1 integrations.

### `reconcile_papers()` as incumbent Phase 2

The current `reconcile_papers()` (`core_engine.py:683`) is the **existing Phase 2** that the sprint plan's Story 7 intends to replace. It does document checklist verification and financial lead schedule calculation — not transaction-level bank reconciliation. It does NOT implement any of the 8 sprint stories.

---

## 4. Phase 2 Sprint Plan Analysis

**Sprint plan file:** `PHASE2_SPRINT_PLAN.md`

**Epic:** Automated Bank Reconciliation & Client Query Generation  
**Schedule:** Tue 16 Jun – Wed 1 Jul 2026

### Story 1 — Consume classified documents + notes

**Input sources for Phase 2:**
1. `jobs/<job_id>/workpaper/` — all approved, renamed PDFs (after Bug A + Bug B fixes)
2. `jobs_db.json` → `job.processor_notes` — human processor notes (text, not a file)
3. A fund-specific **Reconciliation Notes PDF** — to be uploaded by the accountant alongside fund documents in `docs/<fund>/`. Does not exist yet for ADMCM.

**Required changes to support the Reconciliation Notes PDF:**
- Add a new playbook category (e.g., `"Reconciliation Notes"`) to `funds_config.json` for each fund, with keywords like `"reconciliation, instructions, notes, treatment, fund notes, queries"`
- Add the category to `determine_target_filename()` so it lands in workpaper as `Reconciliation Notes.pdf`
- Phase 2 reads this file first and injects its text as a preamble/instruction block in the LLM prompt before reconciling

**Workpaper folder sufficiency:** Once Bug A and Bug B are fixed AND the Reconciliation Notes category is added, the workpaper folder is the complete document universe for Phase 2. No other source needed for documents.

### Stories 2–8 — Not implemented

None of the following exist anywhere in the codebase:
- Transaction-level bank reconciliation (matched/unmatched per transaction)
- Client query generation from unmatched items
- Model selection for reconciliation reliability
- Reconciliation results + query review UI
- Editable query + Send CTA with confirmation dialog
- Integration of new flow into job lifecycle (replacing `reconcile_papers()`)
- End-to-end validation on ADMCM sample

---

## 5. Fund Configuration

### How `funds_config.json` is populated

**Manually only.** There is no UI to add or create funds. The `POST /api/funds` route can upsert a fund entry but is only called from the UI to save playbook keyword changes. To add a new fund, either edit `funds_config.json` directly or POST the full fund object to the API.

`discover_fund_profile()` was designed to auto-populate this from documents but is never called (see Orphaned Functions above).

### Hart Family Super Fund

`Hart Family Superannuation Fund` has no real documents. On first job run, the system seeds `docs/HART/` with byte-for-byte copies of the ADMCM documents. It exists purely as a test fixture. Its members, bank accounts, and ABN are synthetic.

---

## 6. Changes Made in This Session

| Change | Files |
|---|---|
| Removed hardcoded API key, replaced with `.env` loading + error if missing | `classify_workpapers.py`, `verify_and_generate_workpapers.py` |
| Updated `.env.example` placeholder | `.env.example` |
| Initialised local git repo | `.git/` |
| Added `.gitignore` — excludes `.env`, `jobs/*`, `docs/*`, `output/`, `.venv/` | `.gitignore` |
| Added `docs/.gitkeep` and `jobs/.gitkeep` to preserve folders in git | `docs/.gitkeep`, `jobs/.gitkeep` |
| Created `README.md` | `README.md` |
| Initial commit pushed to `git@github.com:trinityteam-dev/Unbound-POC.git` | — |
