---
name: run-doc-intelligence-v2
description: Run, start, launch, screenshot, verify, or test the SMSF Document Intelligence v2 Flask app. Use when asked to run the app, confirm a change works in the browser, check the UI, or smoke-test an API endpoint.
---

# Run: SMSF Document Intelligence v2

Flask web app (port 5001). Driven via `curl` for API smoke tests and the
Claude Preview tool (`preview_start` / `preview_screenshot` / `preview_eval`)
for UI verification. No custom driver needed.

All paths are relative to the project root:
`/Users/arjunanand/Workspace/Development/ClientEngagements/BeFree/Code/doc-intelligence-v2`

---

## Prerequisites

- Python virtualenv at `.venv/` (already present in this repo)
- `.env` file at repo root with `OPENROUTER_API_KEY=<key>`
- `funds_config.json` and `jobs_db.json` at repo root (present in repo)
- `transaction_categories.json` and `llm_pricing.json` at repo root (present in repo)

No extra `apt-get` packages required on macOS. The venv already has all
dependencies from `requirements.txt`.

---

## Launch (agent path — API smoke test)

```bash
cd /Users/arjunanand/Workspace/Development/ClientEngagements/BeFree/Code/doc-intelligence-v2

# Start on a free port (5001 is default; use 5099 if 5001 is taken by the preview tool)
PORT=5099 .venv/bin/python app.py &>/tmp/smsf-app.log &
sleep 3

# Smoke test: jobs list
curl -s http://127.0.0.1:5099/api/jobs | python3 -c "
import sys, json
jobs = json.load(sys.stdin)
print(f'OK — {len(jobs)} jobs')
for j in jobs[:3]:
    tu = j.get('token_usage') or {}
    cost = tu.get('job_total', {}).get('cost_usd', 'N/A')
    print(f'  {j[\"job_id\"]} | {j[\"status\"]} | cost={cost}')
"

# Smoke test: funds list
curl -s http://127.0.0.1:5099/api/funds | python3 -c "
import sys, json; funds=json.load(sys.stdin)
[print(f['id'], '—', f['name']) for f in funds]
"

# Smoke test: token-usage endpoint (requires a job that has been processed)
JOB_ID=job_20260622_143009
curl -s http://127.0.0.1:5099/api/jobs/$JOB_ID/token-usage

# Smoke test: fund cost summary
curl -s http://127.0.0.1:5099/api/funds/admcm/cost-summary | python3 -c "
import sys, json; d=json.load(sys.stdin)
print(f'admcm total: \${d[\"total_cost_usd\"]:.3f} across {d[\"jobs_included\"]} jobs ({d[\"jobs_excluded_na\"]} N/A)')
"

# Stop
kill %1
```

Expected output for jobs smoke test:
```
OK — 16 jobs
  job_20260622_143009 | pending_reviewer_approval | cost=1.032018
  job_20260622_142219 | pending_reviewer_approval | cost=0.203334
  job_20260622_135702 | pending_reviewer_approval | cost=0.910173
```

---

## Launch (agent path — UI screenshot)

Use the Claude Preview tool. The launch config is in `.claude/launch.json`
(name: `smsf-app`, port: 5001).

```
preview_start("smsf-app")
preview_eval("selectJob('job_20260622_143009')")
preview_screenshot()
```

To check the cost badge:
```
preview_eval("JSON.stringify({ cost: document.getElementById('cost-badge-value')?.textContent, tokens: document.getElementById('cost-badge-tokens')?.textContent })")
```

To check the fund cost summary in the sidebar:
```
preview_eval("document.getElementById('fund-cost-summary')?.style.display + ' | ' + document.getElementById('fund-cost-total')?.textContent")
```

---

## Launch (human path)

```bash
cd <project-root>
source .venv/bin/activate
python app.py
# → http://127.0.0.1:5001
```

Open browser, select a fund from the sidebar dropdown, click **Run Audit Pipeline**.
Phase 1 runs in background (~60–120 s). After processor sign-off, Phase 2 runs (~120–300 s).

---

## Key API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/jobs` | All jobs with full records (includes `token_usage`) |
| GET | `/api/jobs/<id>/details` | Single job detail |
| GET | `/api/jobs/<id>/token-usage` | Token + cost breakdown (`available: false` if historical) |
| GET | `/api/funds/<fund_id>/cost-summary` | Aggregate cost across all jobs for a fund |
| POST | `/api/jobs/create` | Create a new job `{"fund_id":"admcm","job_type":"Accounting_Audit"}` |
| POST | `/api/jobs/<id>/processor-review` | Approve Phase 1 and kick off Phase 2 |
| POST | `/api/jobs/<id>/reviewer-review` | Final sign-off |
| POST | `/api/jobs/<id>/regroup-queries` | Re-classify unmatched transactions via LLM |
| GET | `/api/funds` | Registered fund profiles |

---

## Gotchas

- **Port conflict with preview tool**: The preview tool binds port 5001. When running a parallel Bash server for smoke tests, use `PORT=5099` (or any free port). The two processes can coexist.
- **`jobs_db.json` is mutable state**: Every run appends a job record. The file is not committed to git. Historical jobs (pre-token-tracking) have no `token_usage` key and return `{"available": false}` from the token-usage endpoint — this is correct behaviour, not a bug.
- **`OPENROUTER_API_KEY` required for any Phase 1/2 run**: Without it, job creation succeeds but the worker thread fails immediately. Check `job["logs"]` in the jobs API response for the error.
- **Phase 2 model**: Hardcoded to `x-ai/grok-4.20` (`PHASE2_DEFAULT_MODEL` in `core_engine.py`). Fallback is `google/gemini-2.5-flash`. No env var override — change the constant if needed.
- **`transaction_categories.json` required for Phase 2**: If missing, `load_transaction_categories()` raises `FileNotFoundError` and the job fails at the classification step. File is present in repo root.
- **`llm_pricing.json` required for cost tracking**: If missing, `load_llm_pricing()` warns to stderr and returns empty pricing — jobs still run but all costs record as `$0.00`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `curl` returns 0 bytes / connection refused | Server not started, or wrong port. Check `PORT=` env var. |
| Job stays at `processing_docs` forever | Worker thread crashed. Check `job["logs"]` via `/api/jobs/<id>/details`. Usually missing API key or unreadable PDF. |
| `token_usage` key absent on a job | Job was created before Story T shipped. Expected — shows as N/A in UI. |
| `preview_start` returns `reused: true` but page is blank | Call `preview_eval("window.location.reload()")` then retry screenshot. |
| Phase 2 fails with `FileNotFoundError: transaction_categories.json` | File must exist at repo root. It is committed — check `git status`. |
