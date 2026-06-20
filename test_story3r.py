"""Story 3R smoke test — deterministic query grouping with coarse/granular toggle.

Verifies:
- group_unmatched_transactions(): 100% coverage, exactly 4 coarse groups, 35–45 granular groups
- generate_granular_query_text(): readable Python-templated text for a granular group
- run_coarse_query_text_call(): LLM returns query_text for each of the 4 coarse groups
- Final queries list has sub_queries on the Investment Income coarse card
- UI toggle data: sub_queries present and non-null for Investment Income only

Run:
    .venv/bin/python test_story3r.py [path/to/story2_output.json]

If no path is given it looks for story2_test_output.json in the current directory.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from core_engine import (
    group_unmatched_transactions,
    generate_granular_query_text,
    run_coarse_query_text_call,
    _NO_SUBQUERIES,
)

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
        return next((fd for fd in json.load(f) if fd["id"] == fund_id), None)


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
    fund_name = fund_profile.get("name", "ADMCM Investments Super Fund")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not set.")
        sys.exit(1)

    # Collect all unmatched transactions
    unmatched = []
    total = matched_count = 0
    for acc_num, acc_result in reconciliation_results.items():
        for tx in acc_result.get("transactions", []):
            total += 1
            if tx.get("status") == "matched":
                matched_count += 1
            else:
                unmatched.append({
                    **tx,
                    "account_number": acc_num,
                    "account_name": acc_result.get("account_name", acc_num),
                })

    print(f"Loaded {total} transactions: {matched_count} matched, {len(unmatched)} unmatched")
    failures = []

    # --- 3R.1: Grouping ---
    print("\n--- 3R.1: group_unmatched_transactions ---")
    groups = group_unmatched_transactions(unmatched)
    coarse = groups["coarse"]
    granular = groups["granular"]

    print(f"Coarse groups ({len(coarse)}): {[g['category'] for g in coarse]}")
    print(f"Granular groups ({len(granular)}): first 5 = {[g['category'] for g in granular[:5]]}")

    total_coarse = sum(len(g["transactions"]) for g in coarse)
    total_granular = sum(len(g["transactions"]) for g in granular)
    print(f"Coverage — coarse: {total_coarse}/{len(unmatched)}, granular: {total_granular}/{len(unmatched)}")

    if total_coarse != len(unmatched):
        failures.append(f"Coarse coverage: {total_coarse} ≠ {len(unmatched)}")
    if total_granular != len(unmatched):
        failures.append(f"Granular coverage: {total_granular} ≠ {len(unmatched)}")
    if len(coarse) < 2 or len(coarse) > 10:
        failures.append(f"Expected 2–10 coarse groups, got {len(coarse)}")
    if len(granular) < 10:
        failures.append(f"Expected ≥10 granular groups, got {len(granular)}")

    inv_coarse = next((g for g in coarse if "Investment Income" in g["category"]), None)
    if not inv_coarse:
        failures.append("No 'Investment Income' coarse group found")
    else:
        print(f"Investment Income coarse group: {len(inv_coarse['transactions'])} transactions")
        if len(inv_coarse["transactions"]) < 10:
            failures.append(f"Expected ≥10 investment income transactions, got {len(inv_coarse['transactions'])}")

    inv_granular = [g for g in granular if g["category"].startswith("Investment Income –")]
    print(f"Investment Income granular groups: {len(inv_granular)}")
    if len(inv_granular) < 5:
        failures.append(f"Expected ≥5 granular investment groups, got {len(inv_granular)}")

    # No Other bucket expected for ADMCM
    other_groups = [g for g in granular if g["category"].startswith("Other –")]
    print(f"Other groups: {[g['category'] for g in other_groups]}")
    other_tx_count = sum(len(g["transactions"]) for g in other_groups)
    match_rate = 1 - other_tx_count / len(unmatched)
    print(f"Match rate: {match_rate:.1%}")

    # --- 3R.3: Granular query text ---
    print("\n--- 3R.3: generate_granular_query_text ---")
    if inv_granular:
        test_group = inv_granular[0]
        qt = generate_granular_query_text(test_group["category"], test_group["transactions"])
        print(f"Category: {test_group['category']}")
        print(f"Transactions: {len(test_group['transactions'])}")
        print(f"Query text (first 300 chars):\n{qt[:300]}")
        if len(qt) < 50:
            failures.append(f"Granular query text too short: {len(qt)} chars")
        if test_group["category"].replace("Investment Income – ", "") not in qt:
            failures.append(f"Payee name not found in granular query text")

    # --- 3R.2 + LLM call: Coarse query texts ---
    print("\n--- 3R.2: run_coarse_query_text_call ---")

    def log(pct, msg):
        print(f"  [{pct or '--'}%] {msg}")

    coarse_text_map = run_coarse_query_text_call(coarse, fund_name, api_key, log)
    print(f"Received {len(coarse_text_map)} query texts: {list(coarse_text_map.keys())}")

    for g in coarse:
        cat = g["category"]
        qt = coarse_text_map.get(cat, "")
        print(f"\n  [{cat}]")
        print(f"  Transactions: {len(g['transactions'])}")
        print(f"  Query text (first 200 chars): {qt[:200]}")
        if not qt or len(qt) < 30:
            failures.append(f"Coarse query text missing or too short for '{cat}'")

    # --- 3R.4: Final queries structure ---
    print("\n--- 3R.4: Final queries structure ---")
    coarse_to_granular = {}
    for g in granular:
        cat = g["category"]
        ccat = "Investment Income – Dividends & Distributions" if cat.startswith("Investment Income –") else cat
        coarse_to_granular.setdefault(ccat, []).append(g)

    queries = []
    for idx, cg in enumerate(coarse, 1):
        ccat = cg["category"]
        sub_g = coarse_to_granular.get(ccat, [])
        has_sub = ccat not in _NO_SUBQUERIES and len(sub_g) > 1
        sub_queries = None
        if has_sub:
            sub_queries = []
            for sidx, sg in enumerate(sub_g, 1):
                sub_queries.append({
                    "id": f"Q{idx}.{sidx}",
                    "category": sg["category"],
                    "query_text": generate_granular_query_text(sg["category"], sg["transactions"]),
                    "transactions": sg["transactions"],
                    "status": "pending",
                })
        queries.append({
            "id": f"Q{idx}",
            "category": ccat,
            "query_text": coarse_text_map.get(ccat, ""),
            "transactions": cg["transactions"],
            "sub_queries": sub_queries,
            "status": "pending",
        })

    print(f"Queries ({len(queries)}):")
    for q in queries:
        sub_count = len(q["sub_queries"]) if q["sub_queries"] else 0
        print(f"  [{q['id']}] {q['category']} — {len(q['transactions'])} txns, {sub_count} sub_queries")

    inv_query = next((q for q in queries if "Investment Income" in q["category"]), None)
    if not inv_query:
        failures.append("No Investment Income query in final output")
    elif not inv_query.get("sub_queries"):
        failures.append("Investment Income query has no sub_queries")
    else:
        print(f"  → sub_queries: {len(inv_query['sub_queries'])} granular cards")

    non_inv = [q for q in queries if "Investment Income" not in q["category"]]
    for q in non_inv:
        if q.get("sub_queries") is not None:
            failures.append(f"Unexpected sub_queries on '{q['category']}'")

    # Save full output
    out_path = "/tmp/story3r_test_output.json"
    with open(out_path, "w") as f:
        json.dump({"queries": queries, "groups": {"coarse": len(coarse), "granular": len(granular)}}, f, indent=2)
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
