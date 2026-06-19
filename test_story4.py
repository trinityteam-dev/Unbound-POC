"""Story 4 — Model Selection Benchmark.

Runs the Stories 2–3 reconciliation + query generation pipeline against the ADMCM sample
using three candidate models and prints a comparison table.

Transaction extraction runs once with the default model; the same pre-extracted transactions
are reused for every model's reconciliation call so we measure reconciliation quality, not
extraction time (which is a structural task unlikely to differ materially across models).

Candidate models:
  - x-ai/grok-4.20            (current default)
  - google/gemini-2.5-flash
  - anthropic/claude-sonnet-4-6

Usage:
    .venv/bin/python test_story4.py [JOB_ID]

Writes full results to /tmp/story4_benchmark.json.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from core_engine import (
    build_phase2_context,
    extract_transactions_from_statement,
    run_reconciliation_call,
    run_query_generation_call,
)

JOBS_DB = os.path.join(os.path.dirname(__file__), "jobs_db.json")
FUNDS_CONFIG = os.path.join(os.path.dirname(__file__), "funds_config.json")

CANDIDATE_MODELS = [
    "x-ai/grok-4.20",
    "google/gemini-2.5-flash",
    "anthropic/claude-sonnet-4-6",
]

KNOWN_MATCHES = [
    ("ATO refund",      5674.46),
    ("Accountancy fee", 270.41),
    ("Audit fee",       517.00),
]


def load_record(job_id):
    with open(JOBS_DB) as f:
        return next((j for j in json.load(f) if j["job_id"] == job_id), None)


def load_fund(fund_id):
    with open(FUNDS_CONFIG) as f:
        return next((fd for fd in json.load(f) if fd["id"] == fund_id), None)


def noop_log(pct, msg):
    print(f"  [{pct or '--'}%] {msg}")


def find_admcm_job():
    with open(JOBS_DB) as f:
        jobs = json.load(f)
    for j in jobs:
        if j.get("fund_id") != "admcm":
            continue
        wp = f"jobs/{j['job_id']}/workpaper"
        if os.path.exists(wp) and any("Bank Statement" in fn for fn in os.listdir(wp)):
            return j["job_id"]
    return None


def to_float(val):
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def check_known_matches(all_transactions):
    results = {}
    for label, amount in KNOWN_MATCHES:
        found = None
        for t in all_transactions:
            debit = to_float(t.get("debit"))
            credit = to_float(t.get("credit"))
            if abs(debit - amount) < 0.02 or abs(credit - amount) < 0.02:
                found = t
                break
        if found:
            results[label] = found.get("status", "unknown")
        else:
            results[label] = "NOT FOUND"
    return results


def schema_compliant(transactions):
    """Check that debit/credit fields are numeric (not strings)."""
    for t in transactions:
        for field in ("debit", "credit", "balance"):
            val = t.get(field)
            if val is not None and not isinstance(val, (int, float)):
                return False
    return True


def check_query_quality(queries, unmatched_transactions):
    if not queries:
        return {"query_count": 0, "avg_text_len": 0, "category_count": 0, "coverage_pct": 0}
    query_descs = set()
    for q in queries:
        for t in q.get("transactions", []):
            query_descs.add((t.get("date"), t.get("description")))
    covered = sum(
        1 for tx in unmatched_transactions
        if (tx.get("date"), tx.get("description")) in query_descs
    )
    coverage_pct = round(covered / len(unmatched_transactions) * 100) if unmatched_transactions else 100
    avg_text_len = round(
        sum(len(q.get("query_text", "")) for q in queries) / len(queries)
    )
    categories = {q.get("category", "") for q in queries}
    return {
        "query_count": len(queries),
        "avg_text_len": avg_text_len,
        "category_count": len(categories),
        "coverage_pct": coverage_pct,
    }


def main():
    job_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not job_id:
        job_id = find_admcm_job()
    if not job_id:
        print("No suitable ADMCM job found.")
        sys.exit(1)

    print(f"Benchmark job: {job_id}")

    job_record = load_record(job_id)
    fund_profile = load_fund(job_record["fund_id"])
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not set.")
        sys.exit(1)

    fund_name = fund_profile.get("name", "the fund")

    # --- Phase 1: build context (model-agnostic) ---
    print("\n--- Building phase2_context ---")
    ctx = build_phase2_context(job_id, fund_profile, job_record)
    print(f"  {len(ctx['bank_accounts'])} bank accounts, "
          f"{len(ctx['supporting_documents'])} supporting docs")

    # --- Phase 2: extract transactions once (structural task, not model-sensitive) ---
    print("\n--- Extracting transactions (default model) ---")
    transactions_by_account = {}
    for account in ctx.get("bank_accounts", []):
        stmt = account.get("statement_path")
        if not stmt:
            continue
        print(f"  Extracting: {account['name']}...")
        txns = extract_transactions_from_statement(stmt, account, api_key)
        if txns:
            transactions_by_account[account["number"]] = txns
            print(f"    → {len(txns)} transactions")

    if not transactions_by_account:
        print("No transactions extracted. Aborting.")
        sys.exit(1)

    # --- Phase 3: benchmark each candidate model ---
    benchmark_results = {}

    for model in CANDIDATE_MODELS:
        print(f"\n{'='*60}")
        print(f"  MODEL: {model}")
        print(f"{'='*60}")

        result = {"model": model, "reconciliation": {}, "query_generation": {}, "errors": []}

        # Reconciliation call
        print(f"  Running reconciliation call...")
        t0 = time.time()
        try:
            recon_results = run_reconciliation_call(
                ctx, api_key, noop_log,
                model=model,
                transactions_by_account=transactions_by_account,
            )
            recon_latency = round(time.time() - t0, 1)

            # Summarise
            total = matched = unmatched_count = 0
            all_txns = []
            for acc_num, acc_result in recon_results.items():
                txns = acc_result.get("transactions", [])
                acc_m = sum(1 for t in txns if t.get("status") == "matched")
                acc_u = sum(1 for t in txns if t.get("status") == "unmatched")
                total += len(txns)
                matched += acc_m
                unmatched_count += acc_u
                all_txns.extend(txns)

            match_pct = round(matched / total * 100) if total else 0
            known = check_known_matches(all_txns)
            known_pass = sum(1 for s in known.values() if s == "matched")
            numeric_schema = schema_compliant(all_txns)

            result["reconciliation"] = {
                "latency_s": recon_latency,
                "total_txns": total,
                "matched": matched,
                "unmatched": unmatched_count,
                "match_pct": match_pct,
                "known_match_results": known,
                "known_pass": f"{known_pass}/{len(KNOWN_MATCHES)}",
                "json_valid": True,
                "numeric_schema": numeric_schema,
            }

            schema_ok = "Y" if numeric_schema else "N (string amounts)"
            print(f"    Latency: {recon_latency}s | "
                  f"{total} txns | {matched} matched ({match_pct}%) | "
                  f"Known: {known_pass}/{len(KNOWN_MATCHES)} | Schema: {schema_ok}")
            for label, status in known.items():
                marker = "PASS" if status == "matched" else "FAIL"
                print(f"      [{marker}] {label}: {status}")

        except json.JSONDecodeError as e:
            recon_latency = round(time.time() - t0, 1)
            result["reconciliation"] = {"latency_s": recon_latency, "json_valid": False}
            result["errors"].append(f"JSON parse error: {e}")
            recon_results = {}
            all_txns = []
            unmatched_count = 0
            print(f"    FAILED (JSON parse error): {e}")

        except Exception as e:
            recon_latency = round(time.time() - t0, 1)
            result["reconciliation"] = {"latency_s": recon_latency, "json_valid": False}
            result["errors"].append(f"Error: {e}")
            recon_results = {}
            all_txns = []
            unmatched_count = 0
            print(f"    FAILED: {e}")

        # Query generation call (uses this model's unmatched transactions)
        unmatched_transactions = []
        for acc_num, acc_result in recon_results.items():
            for tx in acc_result.get("transactions", []):
                if tx.get("status") != "matched":
                    unmatched_transactions.append({
                        **tx,
                        "account_number": acc_num,
                        "account_name": acc_result.get("account_name", acc_num),
                    })

        print(f"  Running query generation ({len(unmatched_transactions)} unmatched)...")
        t1 = time.time()
        try:
            queries = run_query_generation_call(
                unmatched_transactions, fund_name, api_key, noop_log, model=model
            )
            query_latency = round(time.time() - t1, 1)
            quality = check_query_quality(queries, unmatched_transactions)

            result["query_generation"] = {
                "latency_s": query_latency,
                "json_valid": True,
                **quality,
            }
            print(f"    Latency: {query_latency}s | "
                  f"{quality['query_count']} queries | "
                  f"{quality['category_count']} categories | "
                  f"Coverage: {quality['coverage_pct']}% | "
                  f"Avg text: {quality['avg_text_len']} chars")

        except json.JSONDecodeError as e:
            query_latency = round(time.time() - t1, 1)
            result["query_generation"] = {"latency_s": query_latency, "json_valid": False}
            result["errors"].append(f"Query JSON parse error: {e}")
            print(f"    FAILED (JSON parse error): {e}")

        except Exception as e:
            query_latency = round(time.time() - t1, 1)
            result["query_generation"] = {"latency_s": query_latency, "json_valid": False}
            result["errors"].append(f"Query error: {e}")
            print(f"    FAILED: {e}")

        benchmark_results[model] = result

    # --- Summary table ---
    print(f"\n{'='*60}")
    print("  BENCHMARK SUMMARY")
    print(f"{'='*60}")
    header = (f"{'Model':<35} {'JSON':>5} {'Schema':>7} {'Match%':>7} {'Known':>6} "
              f"{'Recon(s)':>9} {'Queries':>8} {'Cov%':>5} {'Qry(s)':>7}")
    print(header)
    print("-" * len(header))
    for model in CANDIDATE_MODELS:
        r = benchmark_results.get(model, {})
        rec = r.get("reconciliation", {})
        qry = r.get("query_generation", {})
        json_ok = "Y" if rec.get("json_valid") else "N"
        schema_ok = "Y" if rec.get("numeric_schema") else ("N" if rec.get("json_valid") else "-")
        match_pct = rec.get("match_pct", "-")
        known = rec.get("known_pass", "-")
        recon_s = rec.get("latency_s", "-")
        q_count = qry.get("query_count", "-")
        cov = qry.get("coverage_pct", "-")
        qry_s = qry.get("latency_s", "-")
        short = model.split("/")[-1][:34]
        print(f"{short:<35} {str(json_ok):>5} {str(schema_ok):>7} {str(match_pct):>7} "
              f"{str(known):>6} {str(recon_s):>9} {str(q_count):>8} {str(cov):>5} {str(qry_s):>7}")

    # Save full results
    out_path = "/tmp/story4_benchmark.json"
    with open(out_path, "w") as f:
        json.dump(benchmark_results, f, indent=2)
    print(f"\nFull results written to: {out_path}")

    # Overall pass/fail: every model must return valid JSON
    failures = [
        m for m, r in benchmark_results.items()
        if not r.get("reconciliation", {}).get("json_valid")
    ]
    if failures:
        print(f"\nFAILED: {len(failures)} model(s) did not return valid JSON: {failures}")
        sys.exit(1)
    else:
        print("\nAll models returned valid JSON — benchmark complete.")


if __name__ == "__main__":
    main()
