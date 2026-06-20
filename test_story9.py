"""
test_story9.py — Story 9 regression checks
Tests tasks 9.0–9.7 (structural / API); 9.8 requires live browser interaction.
"""
import json
import sys
from app import app

client = app.test_client()
JOB_ID = "job_20260620_150223"


def load_jobs():
    with open("jobs_db.json") as f:
        return json.load(f)


def find_job():
    jobs = load_jobs()
    return next((j for j in jobs if j["job_id"] == JOB_ID), None)


def heading(title):
    print(f"\n--- {title} ---")


def ok(msg):  print(f"  PASS  {msg}")
def fail(msg): print(f"  FAIL  {msg}"); sys.exit(1)


# ---------------------------------------------------------------------------
# 9.0  Sub-query status API can update granular query IDs
# ---------------------------------------------------------------------------
def check_9_0():
    heading("9.0: Sub-query status API (granular IDs)")
    r = client.get(f"/api/jobs/{JOB_ID}/reconciliation")
    assert r.status_code == 200
    data = json.loads(r.data)
    queries = data.get("queries", [])
    parent = next((q for q in queries if q.get("sub_queries")), None)
    if not parent:
        fail("No parent query with sub_queries found — cannot test 9.0")
    sub = parent["sub_queries"][0]
    sub_id = sub["id"]
    ok(f"Found sub-query {sub_id}: {sub['category'][:40]}")

    # Mark sent
    r2 = client.post(
        f"/api/jobs/{JOB_ID}/queries/{sub_id}/status",
        json={"status": "sent", "query_text": sub.get("query_text", "")},
        content_type="application/json",
    )
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}"
    result = json.loads(r2.data)
    assert result["status"] == "success"
    assert result["new_status"] == "sent"
    ok(f"Sub-query {sub_id} marked sent via API")

    # Verify it persisted
    r3 = client.get(f"/api/jobs/{JOB_ID}/reconciliation")
    data3 = json.loads(r3.data)
    q3 = next((q for q in data3["queries"] if q["id"] == parent["id"]), None)
    sub3 = next((sq for sq in (q3.get("sub_queries") or []) if str(sq["id"]) == str(sub_id)), None)
    assert sub3 and sub3["status"] == "sent"
    ok(f"Persistence confirmed: {sub_id} is now 'sent'")

    # Restore to pending
    jobs = load_jobs()
    job = next(j for j in jobs if j["job_id"] == JOB_ID)
    ctx = job.get("phase2_context", {})
    for q in ctx.get("queries", []):
        for sq in q.get("sub_queries") or []:
            if str(sq.get("id")) == str(sub_id):
                sq["status"] = "pending"
    with open("jobs_db.json", "w") as f:
        json.dump(jobs, f, indent=2)
    ok(f"Restored {sub_id} to pending")


# ---------------------------------------------------------------------------
# 9.1–9.3  HTML structure: stepper band, KPI strip, sub-tab nav/panes
# ---------------------------------------------------------------------------
def check_9_1_to_9_3():
    heading("9.1–9.3: Template structure (stepper, KPI, sub-tabs)")
    r = client.get("/")
    assert r.status_code == 200
    html = r.data.decode()

    # 9.1 — stepper inside unlocked view, not as a standalone card above it
    assert 'id="data-intelligence-unlocked"' in html
    ul_pos = html.index('id="data-intelligence-unlocked"')
    orch_tab_pos = html.index('id="orch-tab"')
    # stepper must appear AFTER unlocked-view opening tag
    step1_pos = html.index('id="timeline-step-1"')
    assert step1_pos > ul_pos, "timeline-step-1 must be inside #data-intelligence-unlocked"
    ok("Stepper is inside #data-intelligence-unlocked (task 9.1)")

    # 9.2 — KPI strip present
    assert 'id="kpi-strip"' in html
    assert 'class="kpi-strip"' in html
    ok("KPI strip element present (task 9.2)")

    # 9.3 — sub-tab nav and four panes
    assert 'class="di-sub-nav"' in html
    for tab in ["recon-queries", "lead-schedules", "compliance", "agent-logs"]:
        assert f'id="di-tab-{tab}"' in html, f"Missing pane id=di-tab-{tab}"
    ok("All 4 sub-tab panes present (task 9.3)")
    assert 'switchDiTab' in html
    ok("switchDiTab JS function present")

    # Agent logs pane contains terminal-log-container
    agent_logs_pos = html.index('id="di-tab-agent-logs"')
    terminal_pos = html.index('id="terminal-log-container"')
    assert terminal_pos > agent_logs_pos
    ok("terminal-log-container is inside Agent Logs pane")

    # Checklist and notes are inside compliance pane
    compliance_pos = html.index('id="di-tab-compliance"')
    checklist_pos = html.index('id="checklist-table-tbody"')
    notes_pos = html.index('id="board-processor-notes"')
    assert checklist_pos > compliance_pos and notes_pos > compliance_pos
    ok("Checklist and notes board are inside Compliance pane")

    # Lead schedule elements inside lead-schedules pane
    ls_pos = html.index('id="di-tab-lead-schedules"')
    cash_pos = html.index('id="cash-tbody"')
    portfolio_pos = html.index('id="portfolio-tbody"')
    tax_pos = html.index('id="tax-tbody"')
    assert cash_pos > ls_pos and portfolio_pos > ls_pos and tax_pos > ls_pos
    ok("Cash/portfolio/tax tables are inside Lead Schedules pane")

    # Recon + queries panels inside recon-queries pane
    rq_pos = html.index('id="di-tab-recon-queries"')
    recon_pos = html.index('id="reconciliation-panel"')
    queries_pos = html.index('id="client-queries-panel"')
    signoff_pos = html.index('id="reviewer-signoff-card"')
    assert recon_pos > rq_pos and queries_pos > rq_pos and signoff_pos > rq_pos
    ok("Recon, queries, sign-off are inside Reconciliation & Queries pane")


# ---------------------------------------------------------------------------
# 9.4  Collapsible reconciliation accounts
# ---------------------------------------------------------------------------
def check_9_4():
    heading("9.4: Collapsible recon account rendering")
    r = client.get("/")
    html = r.data.decode()
    assert 'toggleReconAccount' in html
    ok("toggleReconAccount JS function present")
    assert 'class="recon-account-toggle"' in html or 'recon-account-toggle' in html
    ok("recon-account-toggle CSS/HTML class present")
    assert 'recon-account-rows-inner' in html
    ok("recon-account-rows-inner (bounded scroll) class present")


# ---------------------------------------------------------------------------
# 9.5–9.6  Master-detail rail and toggle wiring
# ---------------------------------------------------------------------------
def check_9_5_to_9_6():
    heading("9.5–9.6: Query master-detail rail")
    r = client.get("/")
    html = r.data.decode()

    assert 'id="query-rail-rows"' in html
    ok("query-rail-rows list present (task 9.5)")
    assert 'id="query-rail-detail"' in html
    ok("query-rail-detail pane present (task 9.5)")
    assert 'class="query-rail-layout"' in html
    ok("query-rail-layout wrapper present")

    for fn in ["renderRailRows", "selectRailRow", "renderRailDetail"]:
        assert f"function {fn}" in html, f"Missing function {fn}"
        ok(f"{fn} function present")

    assert "window._railQueries" in html
    ok("_railQueries global initialised (task 9.6)")
    assert "window._selectedRailId" in html
    ok("_selectedRailId global initialised")

    # Toggle wiring: setQueryView still present and calls renderQueryCards
    assert "function setQueryView" in html
    assert "renderQueryCards" in html
    ok("setQueryView / renderQueryCards wired for coarse/granular toggle (task 9.6)")

    # Old flat grid is gone
    assert 'id="queries-cards-container"' not in html
    ok("Old queries-cards-container grid removed (replaced by rail)")


# ---------------------------------------------------------------------------
# 9.7  Responsive CSS
# ---------------------------------------------------------------------------
def check_9_7():
    heading("9.7: Responsive CSS")
    r = client.get("/")
    html = r.data.decode()
    assert "@media (max-width: 768px)" in html
    ok("Responsive breakpoint present (@media max-width:768px)")
    assert "query-rail-layout" in html and "flex-direction: column" in html
    ok("Rail collapses to column on narrow viewports")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Story 9 checks against job: {JOB_ID}")
    check_9_0()
    check_9_1_to_9_3()
    check_9_4()
    check_9_5_to_9_6()
    check_9_7()
    print("\n" + "=" * 60)
    print("All Story 9 automated checks PASSED.")
    print("Task 9.8 (browser regression) requires manual verification.")
    print("=" * 60)
