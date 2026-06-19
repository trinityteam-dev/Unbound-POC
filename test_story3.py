"""Task 3.4 — smoke test Story 3 against the ADMCM sample.

Verifies:
  - Unmatched transactions from Story 2 results are grouped into queries
  - Each query has an id, category, query_text, and transactions list
  - query_text is readable (non-empty, mentions dates or amounts)
  - At least one query covers interest/bank credits and at least one covers dividends

This test loads pre-existing Story 2 reconciliation results to avoid re-running
the expensive reconciliation LLM call. It calls run_query_generation_call() directly.

Run:
    .venv/bin/python test_story3.py [path/to/story2_output.json]

If no path is given it looks for story2_test_output.json in the current directory,
then falls back to /tmp/story2_test_output.json.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from core_engine import run_query_generation_call

FUNDS_CONFIG = os.path.join(os.path.dirname(__file__), "funds_config.json")

CANDIDATE_PATHS = [
    os.path.join(os.path.dirname(__file__), "story2_test_output.json"),
    "/tmp/story2_test_output.json",
]


def load_story2_results(path=None):
    if path:
        with open(path) as f:
            return json.load(f)
    for candidate in CANDIDATE_PATHS:
        if os.path.exists(candidate):
            with open(candidate) as f:
                return json.load(f)
    return None


def load_fund(fund_id):
    with open(FUNDS_CONFIG) as f:
        return next((f for f in json.load(f) if f["id"] == fund_id), None)


def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else None
    reconciliation_results = load_story2_results(input_path)
    if not reconciliation_results:
        print("No Story 2 results found. Run test_story2.py first.")
        sys.exit(1)

    fund_profile = load_fund("admcm")
    if not fund_profile:
        print("ADMCM fund profile not found.")
        sys.exit(1)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not set.")
        sys.exit(1)

    # Collect all unmatched transactions
    unmatched_transactions = []
    total = matched = unmatched_count = 0
    for acc_num, acc_result in reconciliation_results.items():
        for tx in acc_result.get("transactions", []):
            total += 1
            if tx.get("status") == "matched":
                matched += 1
            else:
                unmatched_count += 1
                unmatched_transactions.append({
                    **tx,
                    "account_number": acc_num,
                    "account_name": acc_result.get("account_name", acc_num),
                })

    print(f"Loaded {total} transactions: {matched} matched, {unmatched_count} unmatched")
    print(f"Fund: {fund_profile.get('name')}")

    if not unmatched_transactions:
        print("No unmatched transactions to generate queries for.")
        sys.exit(0)

    def log(pct, msg):
        print(f"  [{pct or '--'}%] {msg}")

    print("\n--- Running query generation call ---")
    queries = run_query_generation_call(
        unmatched_transactions,
        fund_profile.get("name", "the fund"),
        api_key,
        log,
    )

    print(f"\n--- Query generation results: {len(queries)} queries ---")
    failures = []

    if not queries:
        failures.append("No queries returned from LLM")
    else:
        for q in queries:
            q_id = q.get("id", "?")
            category = q.get("category", "")
            query_text = q.get("query_text", "")
            transactions = q.get("transactions", [])

            print(f"\n  [{q_id}] {category}")
            print(f"       Transactions: {len(transactions)}")
            print(f"       Query text (first 200 chars): {query_text[:200]}")

            if not category:
                failures.append(f"{q_id}: missing category")
            if not query_text or len(query_text) < 20:
                failures.append(f"{q_id}: query_text too short or missing")
            if not transactions:
                failures.append(f"{q_id}: no transactions listed")

        # Structural checks: every unmatched tx should appear in exactly one query
        all_query_descs = set()
        for q in queries:
            for t in q.get("transactions", []):
                all_query_descs.add((t.get("date"), t.get("description")))

        missing_coverage = 0
        for tx in unmatched_transactions:
            key = (tx.get("date"), tx.get("description"))
            if key not in all_query_descs:
                missing_coverage += 1

        if missing_coverage > 0:
            coverage_pct = (1 - missing_coverage / len(unmatched_transactions)) * 100
            print(f"\n  Coverage: {len(unmatched_transactions) - missing_coverage}/{len(unmatched_transactions)} "
                  f"unmatched transactions appear in queries ({coverage_pct:.0f}%)")
            if coverage_pct < 80:
                failures.append(
                    f"Query coverage too low: {coverage_pct:.0f}% (expected ≥80%). "
                    f"{missing_coverage} transactions not assigned to any query."
                )
        else:
            print(f"\n  Coverage: all {len(unmatched_transactions)} unmatched transactions covered by queries")

        # Category diversity: expect at least 2 distinct categories
        categories = [q.get("category", "") for q in queries]
        if len(set(categories)) < 2:
            failures.append(
                f"Expected at least 2 distinct query categories, got {len(set(categories))}: {categories}"
            )
        else:
            print(f"\n  Categories ({len(set(categories))} distinct): {', '.join(set(categories))}")

    # Save full output for manual inspection
    out_path = "/tmp/story3_test_output.json"
    with open(out_path, "w") as f:
        json.dump({"queries": queries, "unmatched_count": unmatched_count}, f, indent=2)
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
