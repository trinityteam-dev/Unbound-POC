# SMSF Document Intelligence v2

A web-based AI agent orchestration platform for classifying, verifying, and generating SMSF audit workpapers.

## Overview

The app runs a two-phase human-in-the-loop pipeline:

1. **AI Processor Agent** — classifies raw PDF documents into playbook categories, extracts metadata, and merges bank statement pages by account.
2. **Human Processor sign-off** — review and approve/override AI classifications.
3. **AI Reviewer Agent** — reconciles the approved workpapers, validates a document checklist, and builds cash and portfolio lead schedules.
4. **Human Reviewer sign-off** — final approval before job completion.

## Requirements

- Python 3.9+
- `pdftoppm` (from poppler) — for OCR fallback rendering
- `tesseract` — for OCR on scanned PDFs
- An [OpenRouter](https://openrouter.ai) API key

Install system dependencies on macOS:

```bash
brew install poppler tesseract
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY
```

## Running

```bash
python app.py
```

Open [http://127.0.0.1:5001](http://127.0.0.1:5001) in your browser.

## Configuration

Fund profiles are stored in `funds_config.json`. Each fund entry requires:

| Field | Description |
|---|---|
| `id` | Unique identifier (lowercase, underscores) |
| `name` | Fund display name |
| `abn` | Fund ABN |
| `folder_path` | Path to the folder containing the fund's source PDFs |
| `bank_accounts` | List of `{ name, number, bsb }` objects |
| `members` | List of `{ name, tfn, prior_year_tsb, current_year_tsb }` objects |
| `keywords` | Playbook classification rules — `{ "Accounting_Audit": { "Category": "keywords..." } }` |

## Project Structure

```
app.py                          # Flask app — routes and background worker threads
core_engine.py                  # AI classification, OCR, reconciliation engine
classify_workpapers.py          # Standalone classification script (CLI)
verify_and_generate_workpapers.py  # Standalone verification script (CLI)
funds_config.json               # Fund profiles and playbook keyword config
jobs_db.json                    # Job execution state (runtime, not committed)
templates/index.html            # Single-page UI
data/                           # Fund source documents (gitignored)
jobs/                           # Per-job working directories (runtime, not committed)
```

## Playbooks

Two playbooks are supported:

- **Accounting & Audit (Full)** — includes Audit Invoice, Trust Deed, ATO Trustee Declaration, and TSB documents
- **Accounting (Limited Ledger)** — excludes audit-specific document categories
