"""
test_story10.py — Story 10 regression checks
Tests tasks 10.0–10.4 (structural / API); 10.5 requires live browser interaction.
"""
import json
import os
import shutil
import sys
import tempfile
from app import app

client = app.test_client()


def ok(msg):  print(f"  PASS  {msg}")
def fail(msg): print(f"  FAIL  {msg}"); sys.exit(1)
def heading(title): print(f"\n--- {title} ---")


# ---------------------------------------------------------------------------
# 10.0  GET /api/funds/discover returns unregistered folders
# ---------------------------------------------------------------------------
def check_10_0():
    heading("10.0: GET /api/funds/discover")

    r = client.get("/api/funds/discover")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = json.loads(r.data)
    assert isinstance(data, list), "Expected a list response"
    ok("Endpoint returns 200 and a list")

    # Registered funds should NOT appear
    funds_r = client.get("/api/funds")
    funds = json.loads(funds_r.data)
    registered_paths = {os.path.abspath(f["folder_path"]) for f in funds}
    for item in data:
        assert os.path.abspath(item["folder_path"]) not in registered_paths, \
            f"Registered path {item['folder_path']} appeared in discover output"
    ok("Registered folders are excluded from discover output")

    # Each item has required fields
    for item in data:
        assert "folder_name" in item
        assert "folder_path" in item
        assert "pdf_count" in item
        assert isinstance(item["pdf_count"], int)
    ok(f"Response shape correct ({len(data)} unregistered folder(s) found)")


# ---------------------------------------------------------------------------
# 10.0b  Discover with a synthetic new folder
# ---------------------------------------------------------------------------
def check_10_0_synthetic():
    heading("10.0b: Synthetic unregistered folder detection")

    # Create a temporary subfolder inside data/
    data_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(data_dir, exist_ok=True)
    tmp_folder = os.path.join(data_dir, "_test_story10_synth")
    os.makedirs(tmp_folder, exist_ok=True)

    # Place a dummy file so pdf_count is 0 (no real PDFs needed for this test)
    dummy = os.path.join(tmp_folder, "placeholder.txt")
    with open(dummy, "w") as f:
        f.write("test")

    try:
        r = client.get("/api/funds/discover")
        data = json.loads(r.data)
        names = [d["folder_name"] for d in data]
        assert "_test_story10_synth" in names, \
            f"Synthetic folder not in discover output; got: {names}"
        ok("Synthetic unregistered folder detected by discover endpoint")

        item = next(d for d in data if d["folder_name"] == "_test_story10_synth")
        assert item["pdf_count"] == 0
        ok("pdf_count is 0 for folder with no PDFs")
    finally:
        shutil.rmtree(tmp_folder, ignore_errors=True)


# ---------------------------------------------------------------------------
# 10.1  POST /api/funds/bootstrap with no-PDF folder returns warning
# ---------------------------------------------------------------------------
def check_10_1_no_pdfs():
    heading("10.1a: Bootstrap — empty folder returns warning, not error")

    data_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(data_dir, exist_ok=True)
    tmp_folder = os.path.join(data_dir, "_test_story10_empty")
    os.makedirs(tmp_folder, exist_ok=True)
    rel_path = os.path.relpath(tmp_folder, os.getcwd())

    try:
        r = client.post("/api/funds/bootstrap",
                        json={"folders": [rel_path]},
                        content_type="application/json")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        results = json.loads(r.data)
        assert isinstance(results, list) and len(results) == 1
        result = results[0]
        ok("Bootstrap returns list with one result for one folder")

        assert result.get("warning") is not None, "Expected a warning for no-PDF folder"
        ok(f"Warning present: {result['warning']}")

        p = result["proposed"]
        assert p["id"], "id must be non-empty"
        assert p["folder_path"] == rel_path
        assert isinstance(p["bank_accounts"], list)
        assert isinstance(p["members"], list)
        assert isinstance(p["keywords"], dict)
        ok(f"Proposed config shape correct (id={p['id']})")
    finally:
        shutil.rmtree(tmp_folder, ignore_errors=True)


# ---------------------------------------------------------------------------
# 10.1b  ID derivation and collision avoidance
# ---------------------------------------------------------------------------
def check_10_1_id_derivation():
    heading("10.1b: ID derivation logic")

    from app import _derive_fund_id
    assert _derive_fund_id("JONES SUPER FUND") == "jones_super_fund"
    ok("Spaces become underscores, case-lowered")
    assert _derive_fund_id("HART-2024") == "hart_2024"
    ok("Hyphens become underscores")
    assert _derive_fund_id("  __ADMCM__  ") == "admcm"
    ok("Leading/trailing underscores stripped")
    assert _derive_fund_id("ABC123") == "abc123"
    ok("Alphanumeric passthrough")


# ---------------------------------------------------------------------------
# 10.2  POST /api/funds rejects empty id
# ---------------------------------------------------------------------------
def check_10_2():
    heading("10.2: POST /api/funds rejects empty id")

    r = client.post("/api/funds",
                    json={"id": "", "name": "Test", "folder_path": "data/TEST"},
                    content_type="application/json")
    assert r.status_code == 400, f"Expected 400 for empty id, got {r.status_code}"
    ok("Empty id correctly rejected with 400")

    r2 = client.post("/api/funds",
                     json={"name": "Test", "folder_path": "data/TEST"},
                     content_type="application/json")
    assert r2.status_code == 400, f"Expected 400 for missing id, got {r2.status_code}"
    ok("Missing id correctly rejected with 400")


# ---------------------------------------------------------------------------
# 10.3  HTML: discovery bar present in template
# ---------------------------------------------------------------------------
def check_10_3():
    heading("10.3: Discovery bar in template")

    r = client.get("/")
    assert r.status_code == 200
    html = r.data.decode()

    assert 'id="discovery-bar"' in html
    ok("discovery-bar element present")
    assert 'checkForNewFunds' in html
    ok("checkForNewFunds JS function present")
    assert 'openBootstrapModal' in html
    ok("openBootstrapModal call wired to Set up now button")

    # Bar must be inside .workspace-content, before #welcome-view
    wc_pos = html.index('class="workspace-content"')
    bar_pos = html.index('id="discovery-bar"')
    welcome_pos = html.index('id="welcome-view"')
    assert bar_pos > wc_pos, "discovery-bar must be inside .workspace-content"
    assert bar_pos < welcome_pos, "discovery-bar must precede #welcome-view"
    ok("discovery-bar position correct (inside workspace-content, before welcome-view)")

    # fetchFunds must call checkForNewFunds
    assert 'checkForNewFunds()' in html
    ok("checkForNewFunds() called (wired into fetchFunds)")


# ---------------------------------------------------------------------------
# 10.4  HTML: bootstrap modal present and wired
# ---------------------------------------------------------------------------
def check_10_4():
    heading("10.4: Bootstrap modal in template")

    r = client.get("/")
    html = r.data.decode()

    assert 'id="bootstrap-modal"' in html
    ok("bootstrap-modal element present")
    assert 'id="bootstrap-modal-body"' in html
    ok("bootstrap-modal-body slot present")
    assert 'id="bootstrap-modal-actions"' in html
    ok("bootstrap-modal-actions slot present")
    assert 'registerAllBootstrapFunds' in html
    ok("registerAllBootstrapFunds wired to Register All button")

    for fn in ["scanAllFolders", "renderBootstrapCards", "registerBootstrapFund",
               "registerAllBootstrapFunds", "_bsAcctRow", "_bsMemberRow",
               "_bsAddAcct", "_bsAddMember", "_readBsCard"]:
        assert f"function {fn}" in html or f"async function {fn}" in html, \
            f"Missing function: {fn}"
        ok(f"{fn}() present")

    assert "_discoveredFolders" in html
    assert "_bootstrapProposals" in html
    ok("Bootstrap globals declared")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Story 10 checks")
    check_10_0()
    check_10_0_synthetic()
    check_10_1_no_pdfs()
    check_10_1_id_derivation()
    check_10_2()
    check_10_3()
    check_10_4()
    print("\n" + "=" * 60)
    print("All Story 10 automated checks PASSED.")
    print("Task 10.5 (browser regression) requires manual verification.")
    print("=" * 60)
