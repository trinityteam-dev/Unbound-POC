# Bank Reconciliation Match Rate — Investigation Findings

**Date:** 2026-06-22
**Job investigated:** `job_20260622_143009` (ADMCM Investments Super Fund)
**Observed match rate:** 17 / 197 transactions (8.6%)
**Trigger:** `Direct Credit 607019 MCP MASTER INCOM` transactions (~$184.80) unmatched despite
`Tax Statement Metrics.pdf` listing the exact Metrics Master Income Trust distribution amounts.

---

## Root Cause 1 — Scanned PDFs silently excluded from reconciliation context

### What happens

`build_reconciliation_prompt` (`core_engine.py`) extracts supporting document text using only
`PdfReader.extract_text()`. When that returns empty (scanned/image-only PDFs), the `if doc_text:`
guard silently skips the document — it is never mentioned in the evidence block sent to the LLM.

```python
# core_engine.py — build_reconciliation_prompt()
doc_text = "".join(
    (page.extract_text() or "") + "\n" for page in reader.pages
).strip()[:3000]
if doc_text:                          # ← scanned PDFs fall through here silently
    supporting_docs_lines.append(...)
```

### Documents affected (ADMCM job)

| Document | pypdf chars | Sent to LLM? |
|---|---|---|
| `Tax Statement Metrics.pdf` | **0** (3 scanned pages) | ❌ No |
| `F25 Periodic Statement Metrics.pdf` | **0** (3 scanned pages) | ❌ No |
| `Income Tax Activity.pdf` | 446 | ✅ Yes |
| `Accountancy - $270.41.pdf` | 636 | ✅ Yes |
| `Audit Invoice.pdf` | 1,283 | ✅ Yes |
| `Income Tax.pdf` | 1,145 | ✅ Yes |
| `Total Super annuation balance.pdf` | 5,434 | ✅ Yes (truncated) |
| `Portfolio Valuation at 01.07.24.pdf` | 15,040 | ✅ Yes (truncated) |
| `Portfolio Valuation at 30.06.25.pdf` | 12,773 | ✅ Yes (truncated) |

### The OCR cache gap

Phase 1 (`classify_papers`) **does** run Tesseract OCR on scanned PDFs and caches the result
in `scratch/ocr_{original_filename}.txt`. However:

1. **Only page 1 is OCR'd.** `ocr_pdf_first_page` hardcodes `page_idx=0`. Pages 2–N are never
   rendered or processed.
2. **Phase 2 never reads the scratch cache.** `build_reconciliation_prompt` has no code path
   that looks in the scratch directory.
3. **Filename mismatch.** The scratch key is the original source filename
   (e.g. `ocr_2025 Tax Statement - Metrics .pdf.txt`) but Phase 2 only has the
   classified/renamed filename (`Tax Statement Metrics.pdf`). Even if Phase 2 did look in
   scratch, the names wouldn't resolve without a lookup table.

### Why the Tax Statement was sufficient anyway (for RC#1)

For `2025 Tax Statement - Metrics .pdf`, page 1 happens to contain the complete distribution
table for FY25 — all 12 monthly amounts. The page-1-only OCR text in scratch is sufficient to
match every MCP MASTER INCOM transaction **if it were sent to the LLM**. For
`FY25 Periodic Statement - Metrics .pdf`, the detailed transaction history is on pages 2–3 and
is not in the scratch cache at all.

### The naming alias problem

Even if both documents reached the LLM, the LLM must bridge:

- Bank description: `Direct Credit 607019 MCP MASTER INCOM cm-2108460`
- Document text: `Metrics Master Income Trust | Investment Manager: Metrics Credit Partners Pty Ltd`

"MCP" = Metrics Credit Partners (the investment manager), which CBA uses as the paying entity
label. The OCR text explicitly confirms this relationship, so a capable LLM would make the
connection — but only if it sees the document.

### Impact

All **15 `Direct Credit 607019 MCP MASTER INCOM` transactions** (monthly distributions,
Jun 2024 – Aug 2025) are unmatched.

---

## Root Cause 2 — 3,000-char hard truncation cuts off most of the Portfolio Valuation

### What happens

`build_reconciliation_prompt` truncates each supporting document to 3,000 characters:

```python
doc_text = "".join(...).strip()[:3000]   # ← hard limit applied to every doc
```

### Consequence for Portfolio Valuation at 30.06.25

The portfolio valuation is 12,773 chars. The first 3,000 chars covers securities A–M
(ACDC through MQG). MXT (Metrics Master Income Trust, 14,000 units) appears at character
**~3,100** — just past the cutoff. NAB, NDIA, QUB, RBTZ, REG, RIO, S32, SANTOS, and all
remaining holdings are also beyond the window.

| Visible in first 3,000 chars | Hidden (chars 3,000+) |
|---|---|
| ACDC, BHP, BLX, CHC, CSL, EDV, EOS, EVT, GPT, GQG, LYL, MGR, MMS, MPL, MQG | **MXT, NAB, NDIA, QUB, RBTZ, REG, RIO, S32, SANTOS, SUBD, TECH, WOW** and more |

The LLM therefore has no knowledge of the fund's MXT holding from the portfolio valuation,
and cannot use it as corroborating evidence even if the scanned Tax Statement were fixed.

### Impact

Approximately **127 dividend/distribution transactions** reference securities not visible in the
truncated portfolio valuation (23× BSB 458106 dividends for holdings like BLX/NDIA/ACDC that
fall outside the visible section, 15× MCP, plus NAB/SANTOS/QUB credits).

### The core tension

The limit cannot simply be raised to an arbitrary value because:
- Document lengths are unknown at build time
- Multiple documents are concatenated: at 9 docs × 15K chars each = 135K chars ≈ 34K tokens,
  plus 197 transactions ≈ 8K tokens, the total prompt exceeds practical limits for any model
- Removing the limit entirely is not viable as fund complexity grows

### Options for RC#2

#### Option A — Document-aware Python extraction (no extra LLM calls)

For structured documents whose text is machine-readable, write a compact Python extractor
instead of sending raw text:

- **Portfolio Valuation** (tabular, fully text-extractable): parse the securities table via
  regex → produce `{ticker | name | units | market_value | est_income}` — one line per holding.
  Compresses 15K chars → ~1–2K chars with zero information loss for reconciliation purposes.
- **Invoices, ICA/ITA, TSB statements** (already compact, 400–1,300 chars each): send as-is.
- **Scanned documents** (Tax Statement, F25 Periodic): fix via RC#1 (OCR all pages), then the
  extracted text is already compact.

**Pros:** zero extra LLM calls, deterministic, fast, no added latency or cost.
**Cons:** requires a parser per document type; brittle for novel layouts.

#### Option B — LLM summarization pre-pass (1 call per document)

Before building the reconciliation prompt, run a cheap preprocessing LLM call on each
supporting document:

> *"Extract only the information relevant to transaction reconciliation: security names, tickers,
> amounts, dates, payees. Return a compact structured summary."*

The summary replaces raw text in the reconciliation prompt. A 15K portfolio valuation becomes
a ~1K structured list; a tax statement becomes a dated distribution table.

**Pros:** works for any document type and layout — no new parsers needed; scales to future
document types automatically.
**Cons:** adds N LLM calls (one per supporting doc) → extra latency and cost. For ADMCM:
9 docs × ~$0.002 each ≈ $0.018 additional per job.

#### Option C — Split reconciliation by document (flip the loop)

Instead of one call with all transactions + all documents, run one call per supporting document:

> *"Here is ONE document and the full transaction list. Return the indices of transactions this
> document supports, and why."*

Aggregate all per-document match lists. Any transaction matched by ≥1 call is marked `matched`.

**Pros:** each call stays small and focused regardless of document size; naturally parallelisable.
**Cons:** doesn't produce `unmatched_reason` in the same pass; transactions matched by multiple
documents need deduplication; overall latency = N × call time unless parallelised.

#### Option D — Proportional budget allocation (quick fix, no extra calls)

Replace the per-document hard limit with a shared total budget distributed proportionally:

```python
TOTAL_SUPPORTING_CHARS = 25_000   # ~6,250 tokens
per_doc_budget = TOTAL_SUPPORTING_CHARS // len(supporting_docs)
doc_text = full_text[:per_doc_budget]
```

Every document gets a fair share rather than the first 3,000 chars blindly. Degrades
gracefully as document count grows.

**Pros:** trivial to implement; eliminates silent exclusion.
**Cons:** still truncates large documents; does not guarantee the important section of a
specific document lands within its allocated slice.

#### Recommendation

| Horizon | Action |
|---|---|
| **Short term** | Option D — replace `[:3000]` with a proportional budget. Eliminates total exclusion immediately. |
| **Right solution** | Option A for Portfolio Valuations (tabular, text-extractable, zero cost). Combine with the RC#1 OCR-all-pages fix for scanned documents. Together these solve both RC#1 and RC#2 cleanly. |
| **Future / general** | Option B when new document types are onboarded whose structure is unknown. |

---

## Root Cause 3 — Ordr Minnett Transaction Listing excluded from supporting evidence

### What happens

During Phase 1, `classify_papers` assigns `account_number=1160944` to
`Ordr Mint Transation Listing.pdf` because the Ord Minnett account number appears in the
document text. In `build_phase2_context`, any file record with an `account_number` matching a
registered bank account is placed in `bank_accounts` (used for transaction extraction), not
`supporting_documents` (evidence for reconciliation).

```python
# build_phase2_context — the split logic
bank_account_map = {}
for f in job_record.get("files", []):
    acct = f.get("account_number")
    if acct and acct in account_numbers:      # ← Ordr Mint lands here
        bank_account_map[acct] = f

# ... later
supporting_documents = []
for f in job_record.get("files", []):
    if f.get("classified_name") not in bank_classified_names:  # ← Ordr Mint excluded
        supporting_documents.append(...)
```

### Consequence

The Ordr Minnett Transaction Listing is used as the bank statement for account 1160944
(which is correct for transaction extraction). However, it is **not available as evidence**
in the reconciliation prompt. FinClear settlement debits on the CBA accounts
(`Direct Debit 625407 FinClear Service ...`) cannot be matched to the broker listing because
the broker listing isn't in the evidence block.

Currently those 4 FinClear debits are matched to `Portfolio Valuation at 01.07.24.pdf` /
`Portfolio Valuation at 30.06.25.pdf` — a loose match that is defensible (the valuation
confirms the trades occurred) but not the ideal supporting document.

### Impact

The Ord Minnett broker listing cannot serve as evidence for CBA-side settlement entries.
The correct supporting document for FinClear debits is absent from the evidence pool.

---

## Root Cause 4 — LLM inconsistency on recurring payments against a single invoice

### What happens

18 identical `IGNITIONPAY QUANTIPHY_*` debits of exactly **$270.41** represent monthly
accountancy fee payments. `Accountancy - $270.41.pdf` IS present in the supporting documents
and IS sent to the LLM. Yet only **2 of the 18** are matched:

| Transaction | Status |
|---|---|
| 17/06/2024 DR $270.41 | ✅ matched → `Accountancy - $270.41.pdf` |
| 15/07/2024 DR $270.41 | ❌ unmatched |
| 15/08/2024 through 17/03/2025 (10 payments) | ❌ unmatched |
| 15/04/2025 DR $270.41 | ✅ matched → `Accountancy - $270.41.pdf` |
| 15/05/2025 through 17/11/2025 (5 payments) | ❌ unmatched |

The LLM treats a single invoice as evidence for one specific payment rather than recognising
that a standing engagement at a fixed monthly amount covers all recurring debits to the same
payee for the same amount.

### Impact

16 out of 18 accountancy fee payments are marked unmatched despite the supporting invoice
being present and the amount being exact.

### Likely cause

The reconciliation prompt instructs the LLM to match each transaction to a specific document.
With no explicit instruction that one document can cover multiple recurring transactions of the
same type, the LLM applies a conservative 1:1 interpretation — one invoice proves one payment.
The system prompt needs to explicitly model the "recurring fee" pattern.

---

## Summary

| # | Root Cause | Transactions affected | Fix complexity |
|---|---|---|---|
| RC1 | Scanned PDFs excluded (no OCR fallback in Phase 2) | 15+ MCP transactions + F25 items | Medium — OCR all pages; pass scratch cache into Phase 2 |
| RC2 | 3,000-char truncation cuts off large documents | 127+ dividend/distribution transactions | Medium — proportional budget (quick) or structured extraction (right) |
| RC3 | Ordr Mint classified as bank account, not evidence | FinClear settlement matching | Low — separate broker listing role from bank account role in context |
| RC4 | LLM inconsistency on recurring payments from one invoice | 16 / 18 accountancy fee payments | Low-Medium — prompt engineering to model recurring fee pattern |
