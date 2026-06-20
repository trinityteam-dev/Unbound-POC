"""Story 5 smoke test — runs the bank reconciliation engine for an existing
pending_reviewer_approval ADMCM job and injects results into phase2_context
so the UI panels can be verified in the browser.

Run:
    .venv/bin/python test_story5.py [JOB_ID]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

JOBS_DB = os.path.join(os.path.dirname(__file__), "jobs_db.json")
FUNDS_CONFIG = os.path.join(os.path.dirname(__file__), "funds_config.json")


def load_jobs():
    with open(JOBS_DB) as f:
        return json.load(f)


def save_jobs(jobs):
    with open(JOBS_DB, "w") as f:
        json.dump(jobs, f, indent=2)


def load_fund(fund_id):
    with open(FUNDS_CONFIG) as f:
        return next((fu for fu in json.load(f) if fu["id"] == fund_id), None)


def find_suitable_job(job_id=None):
    jobs = load_jobs()
    if job_id:
        return next((j for j in jobs if j["job_id"] == job_id), None)
    # Auto-pick: most-recent ADMCM job in pending_reviewer_approval with workpapers
    for j in jobs:
        if j.get("fund_id") != "admcm":
            continue
        if j.get("status") not in ("pending_reviewer_approval", "completed"):
            continue
        wp = os.path.join("jobs", j["job_id"], "workpaper")
        if os.path.exists(wp) and any("Bank Statement" in fn for fn in os.listdir(wp)):
            return j
    return None


def main():
    job_id = sys.argv[1] if len(sys.argv) > 1 else None
    job = find_suitable_job(job_id)
    if not job:
        print("No suitable ADMCM job found (pending_reviewer_approval with workpaper bank statements).")
        sys.exit(1)

    print(f"Using job: {job['job_id']} (status={job['status']})")

    fund_profile = load_fund(job["fund_id"])
    if not fund_profile:
        print("Fund profile not found.")
        sys.exit(1)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not set.")
        sys.exit(1)

    scratch_dir = os.path.join("jobs", job["job_id"], "scratch")
    os.makedirs(scratch_dir, exist_ok=True)

    def log(pct, msg, add_log=None):
        print(f"  [{pct or '--'}%] {msg}")

    print("\n--- Running run_bank_reconciliation_phase ---")
    from core_engine import run_bank_reconciliation_phase
    result = run_bank_reconciliation_phase(
        job["job_id"], fund_profile, job["job_type"], api_key, scratch_dir, log
    )

    summary = result["summary"]
    print(f"\nSummary: total={summary['total']}, matched={summary['matched']}, unmatched={summary['unmatched']}")
    print(f"Queries generated: {len(result['queries'])}")
    for q in result["queries"]:
        print(f"  [{q.get('category')}] {len(q.get('transactions', []))} txns")

    # Inject results into job["phase2_context"]
    jobs = load_jobs()
    for j in jobs:
        if j["job_id"] == job["job_id"]:
            ctx = j.get("phase2_context") or {}
            ctx["reconciliation_results"] = result["reconciliation_results"]
            ctx["queries"] = result["queries"]
            ctx["summary"] = summary
            j["phase2_context"] = ctx
            break
    save_jobs(jobs)

    print(f"\nInjected reconciliation results into job {job['job_id']} phase2_context.")
    print("Open the app in your browser, select this job, go to Step 2 - Orchestration tab.")
    print("The Bank Transaction Reconciliation and Client Queries panels should now render.")


if __name__ == "__main__":
    main()
