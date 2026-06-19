# Phase 2 Model Selection Notes

**Date:** 2026-06-19  
**Task:** Story 4 — Select the Right AI Model for Reliable Output  
**Test fund:** ADMCM (job_20260619_112732)  
**Benchmark inputs:** 197 bank transactions across 3 accounts, 9 supporting documents  

---

## Candidate Models

| Model | Provider |
|---|---|
| `x-ai/grok-4.20` | xAI (current default) |
| `google/gemini-2.5-flash` | Google |
| `anthropic/claude-sonnet-4-6` | Anthropic |

---

## Benchmark Results

| Model | JSON Valid | Schema OK | Match% | Known (3) | Recon (s) | Queries | Coverage | Qry text (s) |
|---|---|---|---|---|---|---|---|---|
| **grok-4.20** | ✅ | ✅ | 17% | **3/3** | 60.7 | 14 | 94% | 33.3 |
| gemini-2.5-flash | ✅ | ❌ | 6% | 2/3 | 93.5 | 46 | 100% | 72.9 |
| claude-sonnet-4-6 | ❌ | ❌ | — | — | 256.9 | — | — | — |

### Evaluation criteria

- **JSON Valid** — response parsed as JSON without error
- **Schema OK** — numeric fields (`debit`, `credit`, `balance`) are numbers, not strings
- **Match%** — % of transactions tagged `matched` (rough quality proxy; not necessarily higher = better)
- **Known (3)** — whether the 3 known expected matches were correctly tagged `matched`:
  - ATO refund $5,674.46
  - Accountancy fee $270.41
  - Audit fee $517.00
- **Queries** — number of client query groups generated from unmatched transactions
- **Coverage** — % of unmatched transactions assigned to a query group
- **Qry text (s)** — wall-clock seconds for the query generation call

---

## Per-Model Findings

### grok-4.20 — SELECTED

- All 3 known transactions correctly tagged `matched`
- Numeric schema compliant (debit/credit as floats, not strings)
- Generated 14 well-grouped queries (avg 531 chars each) — professional and readable
- 94% unmatched transaction coverage in queries
- ~60s reconciliation, ~33s query generation — acceptable for a background worker
- Fallback from prior Grok call failures already implemented in `query_openrouter()`

### gemini-2.5-flash — NOT SELECTED

- Missed the Accountancy fee match (tagged `unmatched`)
- **Schema non-compliant**: returned `debit`/`credit` as strings (e.g., `"270.41"` instead of `270.41`)
  — requires downstream code to coerce types, a fragile dependency
- Generated 46 queries for 185 unmatched transactions — essentially one-transaction-per-query
  with very short text (avg 205 chars); not useful for client communication
- Slower: ~94s for reconciliation
- Could be reconsidered as fallback if grok-4.20 is unavailable, with a type-coercion patch

### claude-sonnet-4-6 — NOT SELECTED

- Returned an **empty response** (JSON parse error on empty string) after 257s
- Root cause: the reconciliation prompt is large (~30k tokens: 197 transactions + 9 supporting
  document extracts). Claude's handling of this prompt size via OpenRouter appeared to fail
  silently — the API returned a choice with `None`/empty content rather than an error
- No fallback path available at this prompt scale without chunking the request
- May be worth revisiting for the transaction extraction step (smaller, single-account prompts)
  or for future chunked reconciliation approaches

---

## Decision

**`x-ai/grok-4.20` is the default model for Phase 2.**

Set in `core_engine.py` as `PHASE2_DEFAULT_MODEL = "x-ai/grok-4.20"`.  
Applied as the explicit default in `run_reconciliation_call()` and `run_query_generation_call()`.

The fallback inside `query_openrouter()` remains `google/gemini-2.5-flash`. If grok fails at the
API level and Gemini takes over, downstream code must tolerate string amounts — acceptable as a
last-resort fallback but not a production default.

---

## Story 4.5 — Multimodal/Vision Fallback

Not evaluated. Text-based extraction with grok-4.20 correctly parsed all 197 transactions across
3 accounts (150 + 38 + 9) with zero warnings. Accuracy is sufficient for the POC. The vision
fallback remains documented in the implementation plan as a contingency for future formats.
