"""Task 2.5 — smoke test Story 2 against the ADMCM sample job.

Verifies:
  - Transactions are extracted from both CBA bank statements
  - Known transactions (ATO refund $5,674.46, accountancy fee $270.41, audit fee $517.00)
    are present and tagged 'matched'

Run:
    .venv/bin/python test_story2.py [JOB_ID]
"""
import json
import os
import sys
import pprint

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from core_engine import build_phase2_context, run_reconciliation_call

JOBS_DB = os.path.join(os.path.dirname(__file__), "jobs_db.json")
FUNDS_CONFIG = os.path.join(os.path.dirname(__file__), "funds_config.json")

KNOWN_MATCHES = [
    ("ATO refund",         5674.46),
    ("Accountancy fee",    270.41),
    ("Audit fee",          517.00),
]


def load_record(job_id):
    with open(JOBS_DB) as f:
        return next((j for j in json.load(f) if j["job_id"] == job_id), None)


def load_fund(fund_id):
    with open(FUNDS_CONFIG) as f:
        return next((f for f in json.load(f) if f["id"] == fund_id), None)


def main():
    # Pick job: explicit arg or most-recent ADMCM job with workpaper files
    if len(sys.argv) > 1:
        job_id = sys.argv[1]
    else:
        with open(JOBS_DB) as f:
            jobs = json.load(f)
        job_id = None
        for j in jobs:
            if j.get("fund_id") != "admcm":
                continue
            wp = f"jobs/{j['job_id']}/workpaper"
            if os.path.exists(wp) and any("Bank Statement" in fn for fn in os.listdir(wp)):
                job_id = j["job_id"]
                break
        if not job_id:
            print("No suitable ADMCM job found.")
            sys.exit(1)

    print(f"Testing against job: {job_id}")
    job_record = load_record(job_id)
    if not job_record:
        print(f"Job {job_id} not found.")
        sys.exit(1)

    fund_profile = load_fund(job_record["fund_id"])
    if not fund_profile:
        print(f"Fund profile not found.")
        sys.exit(1)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not set.")
        sys.exit(1)

    def log(pct, msg):
        print(f"  [{pct or '--'}%] {msg}")

    print("\n--- Building phase2_context ---")
    ctx = build_phase2_context(job_id, fund_profile, job_record)
    print(f"  Bank accounts: {len(ctx['bank_accounts'])}")
    for a in ctx["bank_accounts"]:
        print(f"    {a['name']} ({a['number']}): statement_path={a['statement_path']}")
    print(f"  Supporting docs: {len(ctx['supporting_documents'])}")
    for d in ctx["supporting_documents"]:
        print(f"    {d['classified_name']} ({d['category']})")
    print(f"  Reconciliation notes: {ctx['reconciliation_notes_path']}")

    print("\n--- Running reconciliation call ---")
    results = run_reconciliation_call(ctx, api_key, log)

    print("\n--- Reconciliation results summary ---")
    total = matched = unmatched = 0
    all_transactions = []
    for acc_num, acc_result in results.items():
        txns = acc_result.get("transactions", [])
        acc_matched = sum(1 for t in txns if t.get("status") == "matched")
        acc_unmatched = sum(1 for t in txns if t.get("status") == "unmatched")
        total += len(txns)
        matched += acc_matched
        unmatched += acc_unmatched
        all_transactions.extend(txns)
        print(f"  {acc_result.get('account_name', acc_num)}: "
              f"{len(txns)} txns, {acc_matched} matched, {acc_unmatched} unmatched")

    print(f"\n  TOTAL: {total} transactions | {matched} matched | {unmatched} unmatched")

    print("\n--- Checking known expected matches ---")
    failures = []
    for label, amount in KNOWN_MATCHES:
        found = None
        for t in all_transactions:
            debit = t.get("debit") or 0
            credit = t.get("credit") or 0
            if abs(debit - amount) < 0.02 or abs(credit - amount) < 0.02:
                found = t
                break
        if found:
            status = found.get("status", "unknown")
            marker = "PASS" if status == "matched" else "FAIL"
            print(f"  [{marker}] {label} ${amount}: status={status}, doc={found.get('matched_document')}")
            if status != "matched":
                failures.append(f"{label} ${amount} tagged '{status}' (expected 'matched')")
        else:
            print(f"  [FAIL] {label} ${amount}: transaction NOT FOUND in results")
            failures.append(f"{label} ${amount} not found in results")

    # Save full output to /tmp for manual inspection
    out_path = "/tmp/story2_test_output.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to: {out_path}")

    if failures:
        print(f"\nFAILED ({len(failures)} checks):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\nAll checks PASSED.")


if __name__ == "__main__":
    main()
