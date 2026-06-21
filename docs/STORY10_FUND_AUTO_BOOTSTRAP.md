# Story 10 — Auto-Bootstrap Fund Config from Dropped Documents

> **Status: Implemented — tasks 10.0–10.4 complete — awaiting browser regression sign-off (10.5).**
> Design finalised 2026-06-21.

**Done when:** Dropping a new fund folder (containing PDFs) into `data/` causes the app to detect it on page
load, scan the documents with the existing extraction pipeline, propose a pre-filled `funds_config.json`
entry via one LLM call per folder, and let the operator confirm or edit before registering — with no manual
JSON editing required.

---

## Background & Motivation

Adding a fund today requires the operator to hand-author a `funds_config.json` entry containing bank
account numbers, BSBs, member TFNs, and keyword dictionaries — all of which are already printed in
the documents that will be dropped into the same folder. The pipeline already has `extract_pdf_text()`
and `ocr_pdf_first_page()` (used in Phase 1), so the extraction infrastructure is in place. The only
missing piece is a lightweight pre-scan pass that runs those helpers before Phase 1 and sends the text
to the LLM to pull out structured fund metadata.

This story adds that pre-scan pass (one backend endpoint), a discovery check on page load, and a
bootstrap modal in the UI that loops through every newly detected folder, shows editable proposed
configs, and writes confirmed entries to `funds_config.json`.

---

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| `id` derivation | `basename(folder).lower()`, non-alphanumeric → `_`, strip leading/trailing `_` | Deterministic, no operator input required; collision gets `_2`, `_3` etc. |
| `keywords` | Copied verbatim from the **first** fund already in `funds_config.json` | Keywords are generic per playbook type; close enough for a new fund on day one. Operator can tune later. |
| Fields the LLM cannot provide | Set to `""` (strings) or `0` (numeric TSB values) | Leaves a clear "fill me in" signal; `0` avoids type errors in downstream TSB arithmetic |
| Scope of LLM call | **First page of every PDF** in the folder — one call per folder | Keeps token usage low; fund name / ABN / account numbers are always on page-1 headers |
| Extraction failures | Return the proposed config with empty fields; do not abort | Operator fills gaps in the modal — the card still registers, just needs manual data |
| Multiple folders | Endpoint accepts a list; UI processes all discovered folders in one modal flow | Single round-trip for the entire discovery batch |

---

## What Each `funds_config.json` Field Can Come From

| Field | Source | Auto-populated? |
|---|---|---|
| `id` | Derived from folder name | ✅ Always |
| `name` | Fund name on trust deed, ATO correspondence, or bank statement header | ✅ LLM extraction |
| `abn` | Trust deed, ATO letters, most correspondence | ✅ LLM extraction |
| `folder_path` | The discovered folder path | ✅ Always |
| `bank_accounts[].name` | Bank statement header | ✅ LLM extraction |
| `bank_accounts[].number` | Bank statement header | ✅ LLM extraction |
| `bank_accounts[].bsb` | Bank statement header | ✅ LLM extraction |
| `members[].name` | Trust deed, ATO trustee declaration | ✅ LLM extraction |
| `members[].tfn` | ATO declaration | ✅ LLM extraction |
| `members[].prior_year_tsb` | Prior-year audit output — not in source documents | ❌ Set to `0` |
| `members[].current_year_tsb` | ATO portal mid-audit — not in source documents | ❌ Set to `0` |
| `keywords` | Copied from first existing fund config | ✅ Always (template copy) |

---

## Tasks

- [x] **10.0** Backend — folder discovery endpoint (`app.py`)
  - Add `GET /api/funds/discover`
  - Scans every direct subdirectory of the `data/` folder
  - Excludes any folder whose path matches an existing `fund_profile["folder_path"]` (after `os.path.abspath`)
  - Counts `.pdf` files in each unregistered folder (non-recursive — top-level only)
  - Returns: `[{ "folder_name": "JONES_SUPER", "folder_path": "data/JONES_SUPER", "pdf_count": 7 }]`
  - Returns an empty list (not an error) if `data/` does not exist or has no new subdirectories

- [x] **10.1** Backend — LLM bootstrap endpoint (`app.py`)
  - Add `POST /api/funds/bootstrap`
  - Request body: `{ "folders": ["data/JONES_SUPER", "data/SMITH_FAMILY"] }`
  - For each folder path in the list:
    1. Enumerate all `.pdf` files at the top level of the folder
    2. For each PDF, attempt `extract_pdf_text(path, max_pages=1)` (already in `core_engine.py`);
       on failure or empty result, fall back to `ocr_pdf_first_page(path, scratch_dir)` (already in `core_engine.py`)
    3. Assemble a single prompt containing all extracted first-page texts, labelled by filename
    4. Send to `query_openrouter()` asking for structured JSON:
       ```json
       {
         "fund_name": "...",
         "abn": "...",
         "bank_accounts": [{ "name": "...", "number": "...", "bsb": "..." }],
         "members": [{ "name": "...", "tfn": "..." }]
       }
       ```
    5. Derive `id`: `re.sub(r'[^a-z0-9]+', '_', os.path.basename(folder).lower()).strip('_')`
    6. Resolve `id` collision: if `id` already exists in `funds_config.json`, append `_2`, `_3`, etc.
    7. Copy `keywords` from `funds[0]["keywords"]` if any funds exist; else `{}`
    8. Build the proposed config object — fields the LLM did not return default to `""` (strings)
       or `0` (numeric TSB values); `folder_path` is always set to the input folder path
    9. If the folder has zero PDFs, return a proposed config with all fields empty and a
       `"warning": "no PDFs found"` flag — do not skip the folder entirely
  - Returns: `[{ "proposed": { ...funds_config entry... }, "warning": null|"..." }]`
    (one result per input folder, in the same order)
  - Does **not** write to `funds_config.json` — that is the operator's confirm step

- [x] **10.2** Backend — validate `POST /api/funds` handles bootstrap shape
  - The existing `POST /api/funds` endpoint already writes to `funds_config.json` and handles
    `id` updates vs inserts — verify it accepts `bank_accounts` and `members` as arrays
  - Add one guard: if the incoming `id` is empty, return 400 (already present; confirm it rejects)
  - No new endpoint needed — this task is a verification + any small defensive additions only

- [x] **10.3** UI — discovery notification on page load (`templates/index.html`)
  - After `loadFunds()` completes (or alongside it), call `GET /api/funds/discover`
  - If the response contains one or more folders, render a dismissable notification bar at the
    top of the main content area:
    `"N new fund folder(s) detected in data/ — [Set up now]  [✕ Dismiss]"`
  - Clicking **Set up now** opens the bootstrap modal (task 10.4)
  - Clicking **✕** hides the bar for the session (does not suppress future page loads)
  - If zero folders found, no bar is shown — no visual noise on the happy path
  - Discovery call is fire-and-forget: a failure (network error, `data/` missing) silently
    suppresses the bar rather than showing an error to the operator

- [x] **10.4** UI — bootstrap modal (`templates/index.html`)
  - Modal opens with a list of all discovered folders (folder name + PDF count)
  - A single **"Scan all"** button triggers `POST /api/funds/bootstrap` with all folder paths;
    a per-folder spinner shows while the LLM call runs
  - Once results arrive, render one **editable config card** per folder containing:
    - Fund name (text input)
    - ABN (text input)
    - Bank accounts table — one row per account with Name / Account Number / BSB columns;
      rows can be added or deleted
    - Members table — one row per member with Name / TFN / Prior TSB / Current TSB columns;
      rows can be added or deleted
    - A read-only "ID" chip showing the derived id (e.g. `jones_super`)
    - A yellow notice if `warning` was set (e.g. "No PDFs found — fill in manually")
  - Each card has a **Register** button; clicking it calls `POST /api/funds` with that card's
    current field values (including any operator edits)
  - On success: the card collapses to a green "✓ Registered" confirmation; the fund immediately
    appears in the SELECT FUND dropdown (re-fetch `GET /api/funds` and re-render)
  - A **Register all** button at the bottom registers all cards in sequence
  - Modal can be closed at any time; unregistered cards are silently discarded (the folder
    remains on disk and will be detected again on next page load)

- [ ] **10.5** Regression verification
  - Existing ADMCM and Hart funds still appear in the dropdown unchanged
  - Dropping a new folder with PDFs into `data/` causes the discovery bar to appear on refresh
  - Scanning a folder with typical SMSF documents (bank statement, trust deed) populates
    fund name, ABN, bank account number/BSB, and at least one member name correctly
  - Scanning a folder with zero PDFs shows the card with empty fields and a warning — does not crash
  - Dropping two new folders at once shows both cards in the modal; both can be registered independently
  - A registered fund immediately appears in the SELECT FUND dropdown without a page reload
  - After registration, refreshing the page shows no discovery bar for the newly registered fund

---

## Out of Scope

- Phase 1 keyword tuning for the new fund (operator's job post-registration)
- Reading `members.prior_year_tsb` / `current_year_tsb` from documents (not available in source PDFs)
- Watching `data/` for changes in real time (polling / file-system events)
- Editing or deleting an existing registered fund via the UI (separate story)
- Nested subfolders within the fund folder (only top-level PDFs are scanned for bootstrap)
