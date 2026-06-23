import os
import sys
import re
import json
import datetime
import threading
import traceback
import shutil
from flask import Flask, jsonify, request, render_template, send_file
from dotenv import load_dotenv

load_dotenv()
from core_engine import determine_target_filename, discover_fund_profile, load_llm_pricing, calculate_call_cost, record_token_usage


app = Flask(__name__, template_folder="templates")
WORKSPACE_DIR = os.getcwd()
FUNDS_CONFIG_FILE = os.path.join(WORKSPACE_DIR, "funds_config.json")
JOBS_DB_FILE = os.path.join(WORKSPACE_DIR, "jobs_db.json")

def load_funds():
    if not os.path.exists(FUNDS_CONFIG_FILE):
        return []
    with open(FUNDS_CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_funds(funds):
    with open(FUNDS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(funds, f, indent=2)

def load_jobs():
    if not os.path.exists(JOBS_DB_FILE):
        return []
    with open(JOBS_DB_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_jobs(jobs):
    with open(JOBS_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)

def get_job_dir(job_id):
    return os.path.join(WORKSPACE_DIR, "jobs", job_id)

# Background workers
def run_phase1_worker(job_id, folder_path, fund_profile, job_type, api_key):
    """Thread running the classification phase (AI Processor Agent)"""
    job_dir = get_job_dir(job_id)
    scratch_dir = os.path.join(job_dir, "scratch")
    os.makedirs(scratch_dir, exist_ok=True)
    
    def update_job_progress(percent, msg, add_log=None):
        jobs = load_jobs()
        for j in jobs:
            if j["job_id"] == job_id:
                j["progress_percent"] = percent
                j["message"] = msg
                if add_log:
                    j["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {add_log}")
                else:
                    j["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
                break
        save_jobs(jobs)

    try:
        update_job_progress(10, "Scanning folder and initiating AI Processor Agent...")
        from core_engine import run_ai_processor_phase

        try:
            pricing = load_llm_pricing(WORKSPACE_DIR)
        except Exception as _pricing_err:
            print(f"Warning: could not load llm_pricing.json: {_pricing_err}", file=sys.stderr)
            pricing = {}

        def record_llm_usage_p1(call_id, phase, usage):
            cost = calculate_call_cost(usage['model'], usage['prompt_tokens'], usage['completion_tokens'], pricing, openrouter_cost=usage.get('openrouter_cost'))
            _jobs = load_jobs()
            for _j in _jobs:
                if _j['job_id'] == job_id:
                    record_token_usage(_j, call_id, phase, usage, cost)
                    break
            save_jobs(_jobs)

        processed, unprocessed = run_ai_processor_phase(
            folder_path,
            os.path.join("jobs", job_id),
            fund_profile,
            job_type,
            api_key,
            scratch_dir,
            update_job_progress,
            record_usage=record_llm_usage_p1,
        )
        
        jobs = load_jobs()
        for j in jobs:
            if j["job_id"] == job_id:
                j["status"] = "pending_processor_review"
                j["progress_percent"] = 100
                j["message"] = "Documents classified. Pending Human Processor Review."
                j["files"] = processed
                j["unprocessed_files"] = unprocessed
                j["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] AI Processor Agent completed document intelligence. Classified {len(processed)} files.")
                break
        save_jobs(jobs)
        
    except Exception as e:
        print(f"Phase 1 worker failed: {e}", file=sys.stderr)
        traceback.print_exc()
        jobs = load_jobs()
        for j in jobs:
            if j["job_id"] == job_id:
                j["status"] = "failed"
                j["message"] = f"Processor execution failed: {str(e)}"
                j["logs"].append(f"ERROR: {str(e)}")
                j["logs"].append(traceback.format_exc())
                break
        save_jobs(jobs)

def run_phase2_worker(job_id, fund_profile, job_type, api_key):
    """Thread running the reconciliations phase (AI Reviewer Agent)"""
    job_dir = get_job_dir(job_id)
    scratch_dir = os.path.join(job_dir, "scratch")

    def update_job_progress(percent, msg, add_log=None):
        jobs = load_jobs()
        for j in jobs:
            if j["job_id"] == job_id:
                if percent is not None:
                    j["progress_percent"] = percent
                j["message"] = msg
                if add_log:
                    j["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {add_log}")
                else:
                    j["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
                break
        save_jobs(jobs)

    try:
        update_job_progress(70, "Initiating AI Reviewer Agent reconciliations and calculations...")
        from core_engine import run_ai_reviewer_phase, build_phase2_context, run_bank_reconciliation_phase

        try:
            pricing = load_llm_pricing(WORKSPACE_DIR)
        except Exception as _pricing_err:
            print(f"Warning: could not load llm_pricing.json: {_pricing_err}", file=sys.stderr)
            pricing = {}

        def record_llm_usage_p2(call_id, phase, usage):
            cost = calculate_call_cost(usage['model'], usage['prompt_tokens'], usage['completion_tokens'], pricing, openrouter_cost=usage.get('openrouter_cost'))
            _jobs = load_jobs()
            for _j in _jobs:
                if _j['job_id'] == job_id:
                    record_token_usage(_j, call_id, phase, usage, cost)
                    break
            save_jobs(_jobs)

        # Build Phase 2 context and persist it before any AI calls
        jobs = load_jobs()
        job_record = next((j for j in jobs if j["job_id"] == job_id), None)
        if job_record:
            phase2_context = build_phase2_context(job_id, fund_profile, job_record)
            for j in jobs:
                if j["job_id"] == job_id:
                    j["phase2_context"] = phase2_context
                    break
            save_jobs(jobs)

        # Run bank transaction reconciliation and query generation (Stories 2–3R)
        update_job_progress(None, "Phase 2: Running bank transaction reconciliation and query generation...")
        bank_recon = run_bank_reconciliation_phase(
            job_id, fund_profile, job_type, api_key, scratch_dir, update_job_progress,
            record_usage=record_llm_usage_p2,
        )
        jobs = load_jobs()
        for j in jobs:
            if j["job_id"] == job_id:
                ctx = j.get("phase2_context") or {}
                ctx["reconciliation_results"] = bank_recon["reconciliation_results"]
                ctx["queries"] = bank_recon["queries"]
                ctx["summary"] = bank_recon["summary"]
                j["phase2_context"] = ctx
                break
        save_jobs(jobs)

        # Run existing AI reviewer phase: checklist + lead schedules
        update_job_progress(80, "Phase 2: Running checklist and lead schedule verification...")
        results = run_ai_reviewer_phase(
            os.path.join("jobs", job_id),
            fund_profile,
            job_type,
            api_key,
            scratch_dir,
            update_job_progress,
            record_usage=record_llm_usage_p2,
        )
        
        # Compile automated auditor notes / exceptions based on results
        auditor_notes = []
        checklist = results.get("checklist", {})
        
        # 1. Missing documents
        for cat, items in checklist.items():
            for name, details in items.items():
                if details.get("status") == "Missing":
                    auditor_notes.append({
                        "type": "error",
                        "title": f"Missing Document: {name}",
                        "description": details.get("notes", "This required document was not found in the workpapers directory.")
                    })
        
        # 2. Member TSB checks
        member = results.get("member_reconciliation", {})
        if member:
            tsb_24 = member.get("tsb_2024", 0)
            tsb_25 = member.get("tsb_2025", 0)
            if tsb_25 < tsb_24:
                auditor_notes.append({
                    "type": "error",
                    "title": "Member Balance Variance Exception",
                    "description": member.get("audit_finding", "The ATO TSB balance reports show a discrepancy from prior year.")
                })
                
        # 3. Portfolio Variance check
        portfolio = results.get("portfolio_reconciliation", {})
        if portfolio:
            mxt = portfolio.get("mxt_reconciliation", {})
            if mxt and mxt.get("variance_value", 0) > 0:
                auditor_notes.append({
                    "type": "warning",
                    "title": "Security Registry Price Discrepancy",
                    "description": f"A pricing variance of ${mxt.get('variance_value'):.2f} exists for MXT holding. Ord Minnett values it at ASX close price, Automic values at NAV."
                })

        jobs = load_jobs()
        for j in jobs:
            if j["job_id"] == job_id:
                j["status"] = "pending_reviewer_approval"
                j["progress_percent"] = 100
                j["message"] = "Review completed. Pending final sign-off."
                j["results"] = results
                j["auditor_notes"] = auditor_notes
                # Generate default AI reviewer notes
                j["reviewer_notes"] = f"AI Reviewer Agent: Lead schedules verified. We found {len([n for n in auditor_notes if n['type']=='error'])} exceptions and {len([n for n in auditor_notes if n['type']=='warning'])} warnings. Please review the Exception Log and sign off."
                j["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] AI Reviewer Agent completed reconciliations and checklist validation.")
                break
        save_jobs(jobs)
        
    except Exception as e:
        print(f"Phase 2 worker failed: {e}", file=sys.stderr)
        traceback.print_exc()
        jobs = load_jobs()
        for j in jobs:
            if j["job_id"] == job_id:
                j["status"] = "failed"
                j["message"] = f"Reviewer execution failed: {str(e)}"
                j["logs"].append(f"ERROR: {str(e)}")
                j["logs"].append(traceback.format_exc())
                break
        save_jobs(jobs)

@app.route("/")
def index():
    return render_template("index.html")

# API - Funds Configuration
@app.route("/api/funds", methods=["GET", "POST"])
def api_funds():
    if request.method == "GET":
        return jsonify(load_funds())
    else:
        # Create or update fund config
        data = request.json or {}
        funds = load_funds()
        
        fund_id = data.get("id", "").strip().lower()
        if not fund_id:
            return jsonify({"error": "Fund ID is required."}), 400
            
        found = False
        for f in funds:
            if f["id"] == fund_id:
                f.update(data)
                found = True
                break
        if not found:
            funds.append(data)
            
        save_funds(funds)
        return jsonify({"status": "success", "funds": funds})


def _derive_fund_id(folder_name):
    return re.sub(r'[^a-z0-9]+', '_', folder_name.lower()).strip('_')


def _empty_fund_config(fund_id, folder_path, keywords):
    return {
        "id": fund_id,
        "name": "",
        "abn": "",
        "folder_path": folder_path,
        "bank_accounts": [],
        "members": [],
        "keywords": keywords,
    }


def _profile_to_fund_config(fund_id, folder_path, profile, keywords):
    bank_accounts = [
        {
            "name": acc.get("name") or "",
            "number": acc.get("number") or "",
            "bsb": acc.get("bsb") or "",
        }
        for acc in (profile.get("bank_accounts") or [])
    ]
    members = [
        {
            "name": m.get("name") or "",
            "tfn": m.get("tfn") or "",
            "prior_year_tsb": 0,
            "current_year_tsb": 0,
        }
        for m in (profile.get("members") or [])
    ]
    return {
        "id": fund_id,
        "name": profile.get("fund_name") or "",
        "abn": profile.get("abn") or "",
        "folder_path": folder_path,
        "bank_accounts": bank_accounts,
        "members": members,
        "keywords": keywords,
    }


# API - Discover unregistered fund folders
@app.route("/api/funds/discover", methods=["GET"])
def api_funds_discover():
    data_dir = os.path.join(WORKSPACE_DIR, "data")
    if not os.path.isdir(data_dir):
        return jsonify([])

    funds = load_funds()
    registered_paths = {
        os.path.abspath(f["folder_path"])
        for f in funds
        if f.get("folder_path")
    }

    discovered = []
    for entry in os.scandir(data_dir):
        if not entry.is_dir():
            continue
        if os.path.abspath(entry.path) in registered_paths:
            continue
        pdf_count = sum(
            1 for _, _, files in os.walk(entry.path)
            for f in files if f.lower().endswith(".pdf")
        )
        discovered.append({
            "folder_name": entry.name,
            "folder_path": os.path.relpath(entry.path, WORKSPACE_DIR),
            "pdf_count": pdf_count,
        })

    return jsonify(discovered)


# API - Bootstrap fund configs from discovered folders (LLM extraction)
@app.route("/api/funds/bootstrap", methods=["POST"])
def api_funds_bootstrap():
    data = request.json or {}
    folder_paths = data.get("folders", [])

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return jsonify({"error": "OPENROUTER_API_KEY not set"}), 500

    funds = load_funds()
    keyword_template = funds[0]["keywords"] if funds else {}
    existing_ids = {f["id"] for f in funds}

    scratch_dir = os.path.join(WORKSPACE_DIR, "jobs", "_bootstrap_scratch")
    os.makedirs(scratch_dir, exist_ok=True)

    results = []
    for folder_path in folder_paths:
        abs_path = os.path.abspath(folder_path)
        folder_name = os.path.basename(abs_path)

        raw_id = _derive_fund_id(folder_name)
        candidate_id = raw_id
        suffix = 2
        while candidate_id in existing_ids:
            candidate_id = f"{raw_id}_{suffix}"
            suffix += 1
        existing_ids.add(candidate_id)

        warning = None
        has_pdfs = any(
            fn.lower().endswith(".pdf")
            for _, _, files in os.walk(abs_path)
            for fn in files
        ) if os.path.isdir(abs_path) else False

        if not has_pdfs:
            warning = "no PDFs found — fill in manually"
            proposed = _empty_fund_config(candidate_id, folder_path, keyword_template)
        else:
            try:
                profile = discover_fund_profile(abs_path, api_key, scratch_dir)
                proposed = _profile_to_fund_config(candidate_id, folder_path, profile, keyword_template)
            except Exception as e:
                warning = f"extraction failed: {str(e)}"
                proposed = _empty_fund_config(candidate_id, folder_path, keyword_template)

        results.append({"proposed": proposed, "warning": warning})

    return jsonify(results)


# API - List Jobs
@app.route("/api/jobs", methods=["GET"])
def api_jobs():
    return jsonify(load_jobs())

# API - Create Job
@app.route("/api/jobs/create", methods=["POST"])
def api_create_job():
    data = request.json or {}
    fund_id = data.get("fund_id", "").strip()
    job_type = data.get("job_type", "Accounting_Audit").strip() # 'Accounting' or 'Accounting_Audit'
    
    funds = load_funds()
    fund_profile = next((f for f in funds if f["id"] == fund_id), None)
    if not fund_profile:
        return jsonify({"error": f"Fund profile not found for id: {fund_id}"}), 400
        
    folder_path = fund_profile.get("folder_path", "")
    resolved_path = os.path.abspath(folder_path)
    if not os.path.exists(resolved_path):
        # Create it and mock copy ADMCM files if folder_path is docs/HART or others to allow test runs!
        os.makedirs(resolved_path, exist_ok=True)
        if "HART" in resolved_path:
            # Mock copy ADMCM files to HART just for testing purposes
            admcm_path = os.path.abspath("data/ADMCM")
            if os.path.exists(admcm_path):
                for f in os.listdir(admcm_path):
                    f_src = os.path.join(admcm_path, f)
                    if os.path.isfile(f_src):
                        shutil.copy2(f_src, os.path.join(resolved_path, f))
                        
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"job_{timestamp}"
    
    # Initialize directory structure
    job_dir = get_job_dir(job_id)
    os.makedirs(os.path.join(job_dir, "staging"), exist_ok=True)
    os.makedirs(os.path.join(job_dir, "workpaper"), exist_ok=True)
    
    new_job = {
        "job_id": job_id,
        "fund_id": fund_id,
        "fund_name": fund_profile.get("name"),
        "abn": fund_profile.get("abn"),
        "job_type": job_type,
        "status": "processing_docs",
        "progress_percent": 5,
        "message": "AI Processor Agent: Document discovery in progress...",
        "logs": [f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Job created for fund '{fund_profile.get('name')}' under playbook '{job_type}'."],
        "files": [],
        "unprocessed_files": [],
        "processor_notes": "",
        "reviewer_notes": "",
        "results": None,
        "auditor_notes": [],
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    jobs = load_jobs()
    jobs.insert(0, new_job)
    save_jobs(jobs)
    
    api_key = os.environ.get("OPENROUTER_API_KEY")
    
    # Launch Phase 1 worker thread
    t = threading.Thread(
        target=run_phase1_worker,
        args=(job_id, resolved_path, fund_profile, job_type, api_key),
        daemon=True
    )
    t.start()
    
    return jsonify({
        "status": "started",
        "job_id": job_id,
        "message": f"Job {job_id} successfully created. AI Processor Agent started background processing."
    })

# API - Job Details
@app.route("/api/jobs/<job_id>/details", methods=["GET"])
def api_job_details(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)

# API - Human Processor Review Sign-off
@app.route("/api/jobs/<job_id>/processor-review", methods=["POST"])
def api_processor_review(job_id):
    data = request.json or {}
    files_review = data.get("files", [])
    processor_notes = data.get("processor_notes", "").strip()
    
    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found."}), 404
        
    job_dir = get_job_dir(job_id)
    staging_dir = os.path.join(job_dir, "staging")
    workpapers_dir = os.path.join(job_dir, "workpaper")
    
    # Clear workpapers first
    if os.path.exists(workpapers_dir):
        shutil.rmtree(workpapers_dir)
    os.makedirs(workpapers_dir, exist_ok=True)
    
    # Process files copies according to review
    approved_files = []
    
    # We will copy matched statement pages and non-statement files
    # To keep simple, we can copy the classified files from staging or split them.
    # Note that in staging, core_engine has already created the renamed/merged files.
    # We can match staging files and copy them to final workpapers folder with approved names.
    for f in files_review:
        orig_name = f.get("original_name")
        class_name = f.get("classified_name")
        category = f.get("category")
        acc_num = f.get("account_number")
        amount = f.get("amount")
        date_val = f.get("date")
        file_notes = f.get("notes", "")
        
        # Find and copy PDF files
        if class_name and class_name != "[Split and grouped by account]":
            src_file = os.path.join(staging_dir, class_name)
            
            # Check custom classification rename
            new_filename = class_name
            if category:
                # If category changed, determine new name
                new_filename = determine_target_filename({
                    "category": category,
                    "account_number": acc_num,
                    "amount": amount,
                    "date": date_val
                }, class_name)
                
            dest_file = os.path.join(workpapers_dir, new_filename)
            
            if os.path.exists(src_file):
                shutil.copy2(src_file, dest_file)
                approved_files.append({
                    "original_name": orig_name,
                    "classified_name": new_filename,
                    "category": category,
                    "account_number": acc_num,
                    "amount": amount,
                    "date": date_val,
                    "notes": file_notes,
                    "status": "Approved"
                })
            else:
                # Fallback if file not in staging directory (e.g. general error)
                approved_files.append({
                    "original_name": orig_name,
                    "classified_name": class_name,
                    "category": category,
                    "account_number": acc_num,
                    "amount": amount,
                    "date": date_val,
                    "notes": file_notes,
                    "status": "Approved"
                })
                
    job["files"] = approved_files
    job["processor_notes"] = processor_notes
    job["status"] = "processing_review"
    job["progress_percent"] = 65
    job["message"] = "AI Reviewer Agent: Reconciling balances..."
    job["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Human Processor signed off on document classifications. Initiated AI Reviewer Agent.")
    save_jobs(jobs)
    
    # Trigger Phase 2 Worker thread
    funds = load_funds()
    fund_profile = next((f for f in funds if f["id"] == job["fund_id"]), None)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    
    t = threading.Thread(
        target=run_phase2_worker,
        args=(job_id, fund_profile, job["job_type"], api_key),
        daemon=True
    )
    t.start()
    
    return jsonify({
        "status": "started",
        "message": "Human Processor approval submitted. AI Reviewer Agent is running reconciliations."
    })

# API - Human Reviewer Final Sign-off
@app.route("/api/jobs/<job_id>/reviewer-review", methods=["POST"])
def api_reviewer_review(job_id):
    data = request.json or {}
    reviewer_notes = data.get("reviewer_notes", "").strip()
    auditor_notes = data.get("auditor_notes", [])
    
    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found."}), 404
        
    job["reviewer_notes"] = reviewer_notes
    if auditor_notes:
        job["auditor_notes"] = auditor_notes
    job["status"] = "completed"
    job["progress_percent"] = 100
    job["message"] = "Job successfully completed."
    job["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Human Reviewer signed off. Job closed successfully.")
    
    save_jobs(jobs)
    return jsonify({"status": "success", "message": "Job successfully signed off and completed."})

# API - Reconciliation Results & Queries
@app.route("/api/jobs/<job_id>/reconciliation", methods=["GET"])
def api_job_reconciliation(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    ctx = job.get("phase2_context") or {}
    return jsonify({
        "reconciliation_results": ctx.get("reconciliation_results"),
        "queries": ctx.get("queries"),
        "summary": ctx.get("summary"),
    })

# API - Update Query Status
@app.route("/api/jobs/<job_id>/queries/<query_id>/status", methods=["POST"])
def api_update_query_status(job_id, query_id):
    data = request.json or {}
    status = data.get("status", "").strip()
    query_text = data.get("query_text", "").strip()

    if status not in ("sent", "dismissed"):
        return jsonify({"error": "Invalid status. Must be 'sent' or 'dismissed'."}), 400

    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    ctx = job.get("phase2_context") or {}
    queries = ctx.get("queries") or []

    query = next((q for q in queries if str(q.get("id")) == str(query_id)), None)
    if not query:
        for q in queries:
            sub = q.get("sub_queries") or []
            query = next((sq for sq in sub if str(sq.get("id")) == str(query_id)), None)
            if query:
                break
    if not query:
        return jsonify({"error": "Query not found."}), 404

    query["status"] = status
    if query_text:
        query["query_text"] = query_text

    save_jobs(jobs)
    return jsonify({"status": "success", "query_id": query_id, "new_status": status})

# API - Regroup stored queries (Story 3R)
@app.route("/api/jobs/<job_id>/token-usage", methods=["GET"])
def api_job_token_usage(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    token_usage = job.get("token_usage")
    if not token_usage:
        return jsonify({"available": False})
    return jsonify({"available": True, **token_usage})


@app.route("/api/funds/<fund_id>/cost-summary", methods=["GET"])
def api_fund_cost_summary(fund_id):
    jobs = load_jobs()
    fund_jobs = [j for j in jobs if j.get("fund_id") == fund_id]
    total_cost = 0.0
    jobs_included = 0
    jobs_excluded_na = 0
    job_breakdown = []
    for j in fund_jobs:
        tu = j.get("token_usage")
        cost = tu["job_total"]["cost_usd"] if tu else None
        if cost is not None:
            total_cost += cost
            jobs_included += 1
        else:
            jobs_excluded_na += 1
        job_breakdown.append({
            "job_id": j["job_id"],
            "date": j.get("created_at", ""),
            "status": j.get("status", ""),
            "cost_usd": cost,
        })
    return jsonify({
        "fund_id": fund_id,
        "total_cost_usd": round(total_cost, 6),
        "jobs_included": jobs_included,
        "jobs_excluded_na": jobs_excluded_na,
        "job_breakdown": job_breakdown,
    })


@app.route("/api/jobs/<job_id>/regroup-queries", methods=["POST"])
def api_regroup_queries(job_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == job_id), None)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    ctx = job.get("phase2_context") or {}
    existing_queries = ctx.get("queries") or []
    if not existing_queries:
        return jsonify({"error": "No queries to regroup."}), 400

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return jsonify({"error": "OPENROUTER_API_KEY not configured."}), 500

    fund_id = job.get("fund_id", "")
    funds = load_funds()
    fund_profile = next((f for f in funds if f["id"] == fund_id), {})
    fund_name = fund_profile.get("name", "the fund")

    def noop_progress(pct, msg):
        pass

    try:
        regroup_pricing = load_llm_pricing(WORKSPACE_DIR)
    except Exception:
        regroup_pricing = {}

    def record_regroup_usage(call_id, phase, usage):
        cost = calculate_call_cost(usage['model'], usage['prompt_tokens'], usage['completion_tokens'], regroup_pricing, openrouter_cost=usage.get('openrouter_cost'))
        for _j in jobs:
            if _j['job_id'] == job_id:
                record_token_usage(_j, call_id, phase, usage, cost)
                break

    from core_engine import regroup_stored_queries
    new_queries, regrouped, match_rate = regroup_stored_queries(
        existing_queries, fund_name, api_key, noop_progress, record_usage=record_regroup_usage
    )

    if not ("phase2_context" in job):
        job["phase2_context"] = {}
    job["phase2_context"]["queries"] = new_queries
    save_jobs(jobs)

    return jsonify({
        "queries": new_queries,
        "regrouped": regrouped,
        "match_rate": round(match_rate, 4),
    })


# Serving PDF files directly from job directories (staging or workpaper)
@app.route("/api/jobs/<job_id>/file/<phase>/<filename>", methods=["GET"])
def api_serve_job_file(job_id, phase, filename):
    # Prevent traversal
    if phase not in ["staging", "workpaper"]:
        return "Invalid phase", 400
        
    job_dir = get_job_dir(job_id)
    filepath = os.path.join(job_dir, phase, filename)
    
    if not os.path.exists(filepath):
        return "File not found.", 404
        
    return send_file(filepath, mimetype='application/pdf')

# Backwards compatibility endpoints
@app.route("/api/process", methods=["POST"])
def legacy_process():
    # Helper to route legacy requests to the new flow using ADMCM fund
    funds = load_funds()
    admcm = next((f for f in funds if f["id"] == "admcm"), None)
    if not admcm:
        return jsonify({"error": "Default fund config not found."}), 500
        
    # Create new job
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"output_{timestamp}" # Legacy run id format
    
    job_dir = get_job_dir(job_id)
    os.makedirs(os.path.join(job_dir, "staging"), exist_ok=True)
    os.makedirs(os.path.join(job_dir, "workpaper"), exist_ok=True)
    
    # Run immediate classification and reconciliation to simulate legacy workflow
    new_job = {
        "job_id": job_id,
        "fund_id": "admcm",
        "fund_name": "ADMCM Investments Super Fund",
        "abn": "89 292 949 026",
        "job_type": "Accounting_Audit",
        "status": "processing_docs",
        "progress_percent": 10,
        "message": "AI Processor: Legacy execution in progress...",
        "logs": ["Initialised legacy run in background."],
        "files": [],
        "unprocessed_files": [],
        "processor_notes": "Legacy Auto-Run",
        "reviewer_notes": "",
        "results": None,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    jobs = load_jobs()
    jobs.insert(0, new_job)
    save_jobs(jobs)
    
    # Background worker running both phase 1 & 2 for backwards compat
    def run_legacy_compat(run_id, folder_path, fund_profile):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        scratch_dir = os.path.join(get_job_dir(run_id), "scratch")
        os.makedirs(scratch_dir, exist_ok=True)
        
        def update_prog(percent, msg):
            pass # No op for simple compat
            
        try:
            # 1. Classify directly to workpaper (bypass staging for legacy)
            from core_engine import classify_papers, reconcile_papers
            processed, unprocessed = classify_papers(
                folder_path, os.path.join(get_job_dir(run_id), "workpaper"), fund_profile, api_key, scratch_dir, update_prog
            )
            # 2. Reconcile
            results = reconcile_papers(
                os.path.join(get_job_dir(run_id), "workpaper"), fund_profile, api_key, scratch_dir, update_prog
            )
            
            jobs_db = load_jobs()
            for j in jobs_db:
                if j["job_id"] == run_id:
                    j["status"] = "completed"
                    j["progress_percent"] = 100
                    j["files"] = processed
                    j["results"] = results
                    break
            save_jobs(jobs_db)
            
            # Save legacy json files for compat
            state_dir = os.path.join(get_job_dir(run_id), "state")
            os.makedirs(state_dir, exist_ok=True)
            with open(os.path.join(state_dir, "progress.json"), "w", encoding="utf-8") as sf:
                json.dump({"status": "completed", "progress_percent": 100, "message": "Legacy workflow success"}, sf)
            with open(os.path.join(state_dir, "results.json"), "w", encoding="utf-8") as sf:
                json.dump(results, sf)
            with open(os.path.join(state_dir, "profile.json"), "w", encoding="utf-8") as sf:
                json.dump(fund_profile, sf)
                
        except Exception:
            traceback.print_exc()
            
    t = threading.Thread(
        target=run_legacy_compat,
        args=(job_id, os.path.abspath("data/ADMCM"), admcm),
        daemon=True
    )
    t.start()
    
    return jsonify({
        "status": "started",
        "run_id": job_id,
        "message": f"Legacy background thread started for job: {job_id}"
    })

@app.route("/api/progress/<run_id>", methods=["GET"])
def legacy_get_progress(run_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == run_id), None)
    if job:
        return jsonify({
            "status": "completed" if job["status"] == "completed" else "processing",
            "progress_percent": job["progress_percent"],
            "message": job["message"],
            "logs": job["logs"],
            "processed_files_count": len(job["files"]),
            "run_folder": run_id
        })
        
    # Check old files
    progress_file = os.path.join(WORKSPACE_DIR, run_id, "state", "progress.json")
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as sf:
            return jsonify(json.load(sf))
    return jsonify({"status": "idle", "message": "No active or past run found."})

@app.route("/api/results/<run_id>", methods=["GET"])
def legacy_get_results(run_id):
    jobs = load_jobs()
    job = next((j for j in jobs if j["job_id"] == run_id), None)
    if job and job.get("results"):
        funds = load_funds()
        fund_profile = next((f for f in funds if f["id"] == job["fund_id"]), None)
        return jsonify({
            "results": job["results"],
            "profile": fund_profile,
            "run_folder": run_id
        })
        
    # Check old files
    results_file = os.path.join(WORKSPACE_DIR, run_id, "state", "results.json")
    profile_file = os.path.join(WORKSPACE_DIR, run_id, "state", "profile.json")
    if os.path.exists(results_file):
        with open(results_file, "r", encoding="utf-8") as rf:
            results = json.load(rf)
        with open(profile_file, "r", encoding="utf-8") as pf:
            profile = json.load(pf)
        return jsonify({
            "results": results,
            "profile": profile,
            "run_folder": run_id
        })
    return jsonify({"error": "Results not yet available."}), 404

@app.route("/api/workpaper-files/<run_id>/<filename>", methods=["GET"])
def legacy_download_workpaper(run_id, filename):
    # Route to new serve file path
    return api_serve_job_file(run_id, "workpaper", filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Starting SMSF Document Intelligence Web App on port {port}...")
    app.run(host="127.0.0.1", port=port, debug=True)
