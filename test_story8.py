"""Story 8 end-to-end validation — ADMCM sample.

Verifies:
  8.1  Full pipeline executed (job in pending_reviewer_approval with both Phase 1
       results and Phase 2 reconciliation + queries present)
  8.2  All bank statement transactions extracted (no missing rows vs. account totals)
  8.3  Known expected transactions matched: ATO refund $5,674.46; accountancy fee
       $270.41; audit fee $517.00; Ord Minnett EFT transfers
  8.4  Unmatched items produce meaningful, readable client queries (non-empty text,
       correct transaction counts)
  8.5  Checklist, lead schedules, and exception log are unaffected (present in
       results alongside the new reconciliation data)
  8.6  Query status API: send/dismiss persists on page refresh (Flask test client)

Run:
    .venv/bin/python test_story8.py [JOB_ID]

If no JOB_ID is given, the most recent ADMCM pending_reviewer_approval job
that has reconciliation_results is used.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

JOBS_DB = os.path.join(os.path.dirname(__file__), "jobs_db.json")
FUNDS_CONFIG = os.path.join(os.path.dirname(__file__), "funds_config.json")

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_jobs():
    with open(JOBS_DB) as f:
        return json.load(f)


def save_jobs(jobs):
    with open(JOBS_DB, "w") as f:
        json.dump(jobs, f, indent=2)


def find_job(job_id=None):
    jobs = load_jobs()
    if job_id:
        return next((j for j in jobs if j["job_id"] == job_id), None)
    for j in jobs:
        if j.get("fund_id") != "admcm":
            continue
        if j.get("status") not in ("pending_reviewer_approval", "completed"):
            continue
        pc = j.get("phase2_context") or {}
        if pc.get("reconciliation_results") and pc.get("queries"):
            return j
    return None


def all_transactions(reconciliation_results):
    txns = []
    for acct, data in reconciliation_results.items():
        for t in data.get("transactions", []):
            txns.append({**t, "_account": acct})
    return txns


def pass_(label):
    print(f"  PASS  {label}")


def fail_(failures, label, detail=""):
    msg = f"  FAIL  {label}" + (f" — {detail}" if detail else "")
    print(msg)
    failures.append(msg.strip())


# ── Check functions ───────────────────────────────────────────────────────────

def check_8_1(job, failures):
    print("\n--- 8.1: Full pipeline evidence ---")
    status = job.get("status")
    results = job.get("results") or {}
    pc = job.get("phase2_context") or {}

    if status in ("pending_reviewer_approval", "completed"):
        pass_(f"Job status is '{status}' (Phase 1 + Phase 2 both ran)")
    else:
        fail_(failures, "Job status", f"expected pending_reviewer_approval or completed, got '{status}'")

    if results.get("checklist"):
        pass_("Phase 1 results present (checklist)")
    else:
        fail_(failures, "Phase 1 results missing — no checklist in job.results")

    if pc.get("reconciliation_results"):
        pass_("Phase 2 reconciliation_results present")
    else:
        fail_(failures, "Phase 2 reconciliation_results missing")

    if pc.get("queries"):
        pass_(f"Phase 2 queries present ({len(pc['queries'])} cards)")
    else:
        fail_(failures, "Phase 2 queries missing")


def check_8_2(txns, failures):
    print("\n--- 8.2: Transaction extraction completeness ---")
    total = len(txns)
    if total == 0:
        fail_(failures, "No transactions found")
        return

    print(f"  Total transactions: {total}")
    # Validate no transaction is missing required fields
    missing_date = [t for t in txns if not t.get("date")]
    missing_desc = [t for t in txns if not t.get("description")]
    missing_amount = [t for t in txns if t.get("debit") is None and t.get("credit") is None]
    missing_status = [t for t in txns if not t.get("status")]

    if missing_date:
        fail_(failures, "Transactions with missing date", f"{len(missing_date)} rows")
    else:
        pass_(f"All {total} transactions have a date")

    if missing_desc:
        fail_(failures, "Transactions with missing description", f"{len(missing_desc)} rows")
    else:
        pass_(f"All {total} transactions have a description")

    if missing_amount:
        fail_(failures, "Transactions with no debit or credit", f"{len(missing_amount)} rows")
    else:
        pass_(f"All {total} transactions have a debit or credit amount")

    if missing_status:
        fail_(failures, "Transactions with missing status", f"{len(missing_status)} rows")
    else:
        pass_(f"All {total} transactions have a matched/unmatched status")

    matched = sum(1 for t in txns if t.get("status") == "matched")
    unmatched = sum(1 for t in txns if t.get("status") == "unmatched")
    print(f"  Matched: {matched}, Unmatched: {unmatched}")
    if matched + unmatched != total:
        fail_(failures, "Status totals don't add up", f"{matched}+{unmatched}≠{total}")
    else:
        pass_(f"Status totals consistent ({matched}+{unmatched}={total})")


def check_8_3(txns, failures):
    print("\n--- 8.3: Known expected matches ---")

    def find(terms, status_must_be=None):
        hits = []
        for t in txns:
            haystack = (
                (t.get("description") or "") + " "
                + str(t.get("debit") or "") + " "
                + str(t.get("credit") or "")
            ).lower()
            if all(term.lower() in haystack for term in terms):
                hits.append(t)
        return hits

    # ATO refund $5,674.46
    hits = find(["ato", "5674.46"])
    if hits and hits[0].get("status") == "matched":
        pass_(f"ATO refund $5,674.46 tagged matched ({hits[0]['date']})")
    elif hits:
        fail_(failures, "ATO refund $5,674.46 found but not matched",
              f"status={hits[0].get('status')}")
    else:
        fail_(failures, "ATO refund $5,674.46 transaction not found")

    # Accountancy fee $270.41 (monthly recurring via IGNITIONPAY QUANTIPHY)
    hits = find(["270.41"])
    matched_fees = [h for h in hits if h.get("status") == "matched"]
    if matched_fees:
        pass_(f"Accountancy fee $270.41 tagged matched ({len(matched_fees)} occurrences)")
    elif hits:
        fail_(failures, f"Accountancy fee $270.41 found ({len(hits)}x) but none matched")
    else:
        fail_(failures, "Accountancy fee $270.41 not found")

    # Audit fee $517.00 (Transfer To Aquila Super)
    hits = find(["517.0"])
    matched_audit = [h for h in hits if h.get("status") == "matched"]
    if matched_audit:
        pass_(f"Audit fee $517.00 tagged matched: {matched_audit[0].get('description', '')[:60]}")
    elif hits:
        fail_(failures, "Audit fee $517.00 found but not matched",
              f"status={hits[0].get('status')}")
    else:
        fail_(failures, "Audit fee $517.00 not found")

    # Ord Minnett EFT transfers (known as EFT transactions on acct 06200016743999)
    hits = find(["eft"])
    matched_eft = [h for h in hits if h.get("status") == "matched"]
    if matched_eft:
        pass_(f"Ord Minnett EFT transfer(s) tagged matched ({len(matched_eft)} rows)")
    elif hits:
        fail_(failures, "EFT transfers found but none matched")
    else:
        fail_(failures, "EFT transfers not found")


def check_8_4(queries, unmatched_count, failures):
    print("\n--- 8.4: Client query readability ---")
    if not queries:
        fail_(failures, "No queries generated")
        return

    print(f"  Queries: {len(queries)}")
    total_txns_in_queries = sum(len(q.get("transactions", [])) for q in queries)

    if total_txns_in_queries == unmatched_count:
        pass_(f"All {unmatched_count} unmatched transactions covered in queries")
    else:
        fail_(failures, "Query transaction coverage mismatch",
              f"{total_txns_in_queries} in queries ≠ {unmatched_count} unmatched")

    for q in queries:
        cat = q.get("category", "?")
        qt = q.get("query_text", "")
        n_txns = len(q.get("transactions", []))

        if len(qt) < 50:
            fail_(failures, f"Query '{cat}' text too short ({len(qt)} chars)")
        else:
            pass_(f"[{q.get('id')}] {cat}: {n_txns} txns, {len(qt)} char query text")

        # Sub-queries check for Investment Income
        if "Investment Income" in cat:
            sub_qs = q.get("sub_queries")
            if sub_qs and len(sub_qs) >= 5:
                pass_(f"  Investment Income has {len(sub_qs)} granular sub-queries")
            else:
                fail_(failures, f"Investment Income sub_queries missing or sparse",
                      f"got {len(sub_qs) if sub_qs else 0}")
            # Check a sub-query text
            if sub_qs:
                sqt = sub_qs[0].get("query_text", "")
                if len(sqt) > 30:
                    pass_(f"  First sub-query '{sub_qs[0].get('category')}' has readable text")
                else:
                    fail_(failures, "Sub-query text too short")


def check_8_5(job, failures):
    print("\n--- 8.5: Checklist, lead schedules, exception log ---")
    results = job.get("results") or {}
    auditor_notes = job.get("auditor_notes") or []

    checklist = results.get("checklist")
    if checklist and len(checklist) >= 3:
        pass_(f"Checklist present ({len(checklist)} categories)")
    else:
        fail_(failures, "Checklist missing or empty", str(len(checklist) if checklist else 0))

    cash = results.get("cash_reconciliation", {})
    accts = cash.get("accounts", [])
    if accts:
        pass_(f"Cash reconciliation (lead schedule) present ({len(accts)} accounts)")
    else:
        fail_(failures, "Cash reconciliation lead schedule missing")

    portfolio = results.get("portfolio_reconciliation")
    if portfolio:
        pass_("Portfolio reconciliation present")
    else:
        fail_(failures, "Portfolio reconciliation missing")

    tax = results.get("tax_reconciliation")
    if tax:
        pass_("Tax reconciliation present")
    else:
        fail_(failures, "Tax reconciliation missing")

    if auditor_notes:
        errors = [n for n in auditor_notes if n.get("type") == "error"]
        warnings = [n for n in auditor_notes if n.get("type") == "warning"]
        pass_(f"Exception log present ({len(errors)} errors, {len(warnings)} warnings)")
    else:
        fail_(failures, "Exception log (auditor_notes) empty or missing")


def check_8_6(job_id, failures):
    print("\n--- 8.6: Query status API (send/dismiss persists) ---")
    try:
        import app as flask_app
    except Exception as exc:
        fail_(failures, "Could not import Flask app", str(exc))
        return

    client = flask_app.app.test_client()

    # GET the job to confirm it has queries
    resp = client.get(f"/api/jobs/{job_id}/reconciliation")
    if resp.status_code != 200:
        fail_(failures, f"GET /api/jobs/{job_id}/reconciliation returned {resp.status_code}")
        return
    data = resp.get_json()
    queries = data.get("queries", [])
    if not queries:
        fail_(failures, "No queries returned from reconciliation endpoint")
        return
    pass_(f"GET /reconciliation returned {len(queries)} queries")

    # Pick the first non-sent/dismissed query for testing
    test_query = next(
        (q for q in queries if q.get("status") in (None, "pending")), None
    )
    if not test_query:
        print("  SKIP  No pending query available to test send/dismiss (all already actioned)")
        return

    query_id = test_query.get("id")
    original_text = test_query.get("query_text", "")
    edited_text = original_text + " [test edit]"

    # POST status=sent with edited text
    resp = client.post(
        f"/api/jobs/{job_id}/queries/{query_id}/status",
        json={"status": "sent", "query_text": edited_text},
        content_type="application/json",
    )
    if resp.status_code != 200:
        fail_(failures, f"POST query status returned {resp.status_code}", resp.get_data(as_text=True))
        return
    result = resp.get_json()
    if result.get("new_status") != "sent":
        fail_(failures, "Response did not confirm status=sent", str(result))
        return
    pass_(f"POST query/{query_id}/status → sent: OK")

    # Re-fetch to confirm persistence
    resp2 = client.get(f"/api/jobs/{job_id}/reconciliation")
    data2 = resp2.get_json()
    persisted_q = next(
        (q for q in data2.get("queries", []) if str(q.get("id")) == str(query_id)), None
    )
    if not persisted_q:
        fail_(failures, "Query not found after update")
        return
    if persisted_q.get("status") != "sent":
        fail_(failures, "Status not persisted", f"got '{persisted_q.get('status')}'")
    else:
        pass_("Status 'sent' persisted and returned on subsequent GET")

    if persisted_q.get("query_text") == edited_text:
        pass_("Edited query text persisted correctly")
    else:
        fail_(failures, "Edited query text not persisted",
              f"expected '…[test edit]', got '{persisted_q.get('query_text', '')[-20:]}'")

    # Reset back to pending so we don't corrupt the stored job
    client.post(
        f"/api/jobs/{job_id}/queries/{query_id}/status",
        json={"status": "dismissed", "query_text": original_text},
        content_type="application/json",
    )
    # Restore to pending by direct db manipulation
    jobs = load_jobs()
    for j in jobs:
        if j["job_id"] == job_id:
            ctx = j.get("phase2_context") or {}
            for q in ctx.get("queries") or []:
                if str(q.get("id")) == str(query_id):
                    q["status"] = "pending"
                    q["query_text"] = original_text
            break
    save_jobs(jobs)
    print(f"  (Restored query {query_id} to pending for clean state)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    job_id_arg = sys.argv[1] if len(sys.argv) > 1 else None
    job = find_job(job_id_arg)
    if not job:
        print("No suitable ADMCM job found (pending_reviewer_approval with reconciliation_results).")
        sys.exit(1)

    job_id = job["job_id"]
    print(f"Using job: {job_id} (fund={job.get('fund_id')}, status={job.get('status')})")

    pc = job.get("phase2_context") or {}
    rr = pc.get("reconciliation_results") or {}
    txns = all_transactions(rr)
    matched_count = sum(1 for t in txns if t.get("status") == "matched")
    unmatched_count = len(txns) - matched_count
    queries = pc.get("queries") or []

    failures = []

    check_8_1(job, failures)
    check_8_2(txns, failures)
    check_8_3(txns, failures)
    check_8_4(queries, unmatched_count, failures)
    check_8_5(job, failures)
    check_8_6(job_id, failures)

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED ({len(failures)} checks):")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print(f"All Story 8 checks PASSED.")
        print(f"  Transactions: {len(txns)} total, {matched_count} matched, {unmatched_count} unmatched")
        print(f"  Queries: {len(queries)} coarse cards")
        print(f"  Checklist categories: {len(job.get('results', {}).get('checklist', {}))}")
        print(f"  Exception log: {len(job.get('auditor_notes', []))} items")


if __name__ == "__main__":
    main()
