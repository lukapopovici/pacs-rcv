import threading
import time
import httpx
import json
import os
from pathlib import Path
import dearpygui.dearpygui as dpg

# ── Config ────────────────────────────────────────────────────────────────────
API_URL   = os.getenv("API_URL",    "http://localhost:8000")
API_TOKEN = os.getenv("API_TOKEN",  "changeme")
ORTHANC   = os.getenv("ORTHANC_URL","http://localhost:8042")

HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

# ── State ─────────────────────────────────────────────────────────────────────
state = {
    "studies":        [],
    "jobs":           [],
    "records":        [],
    "search_results": [],
    "pacs_configs":   [],
    "selected_study": None,
    "selected_job":   None,
    "stats":          {},
    "audit":          [],
    "workers":        [],
}

# ── HTTP helpers ──────────────────────────────────────────────────────────────
def api_get(path):
    try:
        r = httpx.get(f"{API_URL}{path}", headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

def api_post(path, json_body=None, files=None, params=None):
    try:
        if files:
            r = httpx.post(f"{API_URL}{path}", headers=HEADERS,
                           files=files, params=params, timeout=60)
        else:
            r = httpx.post(f"{API_URL}{path}", headers=HEADERS,
                           json=json_body, timeout=30)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

def api_delete(path):
    try:
        r = httpx.delete(f"{API_URL}{path}", headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

def set_status(msg, error=False):
    color = [220, 60, 60] if error else [60, 200, 100]
    if dpg.does_item_exist("status_bar"):
        dpg.set_value("status_bar", msg)
        dpg.configure_item("status_bar", color=color)

def log(msg):
    if dpg.does_item_exist("log_box"):
        ts = time.strftime("%H:%M:%S")
        current = dpg.get_value("log_box") or ""
        dpg.set_value("log_box", f"[{ts}] {msg}\n" + current)

# ── Health ────────────────────────────────────────────────────────────────────
def check_health():
    def _do():
        data, err = api_get("/health")
        if err:
            set_status(f"API unreachable: {err}", error=True)
            if dpg.does_item_exist("health_api"):
                dpg.set_value("health_api", "API: OFFLINE")
                dpg.configure_item("health_api", color=[220, 60, 60])
            return
        api_ok  = data.get("api") == "ok"
        pacs_ok = data.get("pacs_reachable", False)
        if dpg.does_item_exist("health_api"):
            dpg.set_value("health_api",  "API: OK"  if api_ok  else "API: OFFLINE")
            dpg.set_value("health_pacs", "PACS: OK" if pacs_ok else "PACS: OFFLINE")
            dpg.configure_item("health_api",  color=[60,200,100] if api_ok  else [220,60,60])
            dpg.configure_item("health_pacs", color=[60,200,100] if pacs_ok else [220,60,60])
    threading.Thread(target=_do, daemon=True).start()

# ── Studies tab ───────────────────────────────────────────────────────────────
def refresh_studies():
    def _do():
        set_status("Fetching studies...")
        data, err = api_get("/studies")
        if err:
            set_status(f"Error: {err}", error=True)
            return
        state["studies"] = data or []
        _rebuild_studies_table()
        set_status(f"Loaded {len(state['studies'])} studies.")
        log(f"Loaded {len(state['studies'])} studies.")
    threading.Thread(target=_do, daemon=True).start()

def _rebuild_studies_table():
    if not dpg.does_item_exist("studies_table"):
        return
    dpg.delete_item("studies_table", children_only=True)
    for col in ["#", "Study ID", "Actions"]:
        dpg.add_table_column(label=col, parent="studies_table")
    for i, sid in enumerate(state["studies"]):
        short = sid[:22] + "..." if len(sid) > 22 else sid
        with dpg.table_row(parent="studies_table"):
            dpg.add_text(str(i + 1))
            dpg.add_text(short)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Details",  callback=lambda s,a,u=sid: show_study_details(u), width=65)
                dpg.add_button(label="Ingest",   callback=lambda s,a,u=sid: ingest_study(u),       width=55)
                dpg.add_button(label="Forward",  callback=lambda s,a,u=sid: open_forward_dialog(u),width=65)

def show_study_details(study_id):
    def _do():
        data, err = api_get(f"/studies/{study_id}")
        if err:
            log(f"Study detail error: {err}")
            return
        tags    = data.get("MainDicomTags", {})
        patient = data.get("PatientMainDicomTags", {})
        text = (
            f"Study ID:     {study_id}\n"
            f"Patient:      {patient.get('PatientName','N/A')}\n"
            f"Patient ID:   {patient.get('PatientID','N/A')}\n"
            f"Modality:     {tags.get('Modality','N/A')}\n"
            f"Date:         {tags.get('StudyDate','N/A')}\n"
            f"Description:  {tags.get('StudyDescription','N/A')}\n"
            f"Series:       {len(data.get('Series', []))}\n"
            f"Instances:    {len(data.get('Instances', []))}\n"
        )
        if dpg.does_item_exist("study_detail_text"):
            dpg.set_value("study_detail_text", text)
    threading.Thread(target=_do, daemon=True).start()

def ingest_study(study_id):
    def _do():
        set_status(f"Ingesting {study_id[:16]}...")
        data, err = api_post(f"/query/ingest/{study_id}")
        if err:
            set_status(f"Ingest error: {err}", error=True)
            log(f"Ingest error: {err}")
        else:
            set_status("Study ingested.")
            log(f"Ingested study → DB id {data.get('id')}")
    threading.Thread(target=_do, daemon=True).start()

def ingest_all():
    def _do():
        set_status("Ingesting all studies...")
        data, err = api_post("/query/ingest/all")
        if err:
            set_status(f"Bulk ingest error: {err}", error=True)
        else:
            i = len(data.get("ingested",[])); s = len(data.get("skipped",[])); f = len(data.get("failed",[]))
            set_status(f"Done. Ingested:{i} Skipped:{s} Failed:{f}")
            log(f"Bulk ingest — ingested:{i} skipped:{s} failed:{f}")
    threading.Thread(target=_do, daemon=True).start()

# ── Forward dialog ────────────────────────────────────────────────────────────
def open_forward_dialog(study_id):
    if dpg.does_item_exist("forward_dialog"):
        dpg.delete_item("forward_dialog")
    with dpg.window(label=f"Forward — {study_id[:18]}...", tag="forward_dialog",
                    modal=True, width=500, height=360, pos=[200,160]):
        dpg.add_text("Target PACS URL:")
        dpg.add_input_text(tag="fwd_pacs_url",  default_value="http://localhost:8042", width=440)
        dpg.add_text("User:"); dpg.add_input_text(tag="fwd_pacs_user", default_value="orthanc", width=440)
        dpg.add_text("Password:"); dpg.add_input_text(tag="fwd_pacs_pass", default_value="orthanc", password=True, width=440)
        dpg.add_checkbox(label="Anonymize", tag="fwd_anon")
        dpg.add_text("Examination result (optional):")
        dpg.add_input_text(tag="fwd_result", multiline=True, width=440, height=70)
        dpg.add_spacer(height=6)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Forward", width=100, callback=lambda: _submit_forward(study_id))
            dpg.add_button(label="Cancel",  width=80,  callback=lambda: dpg.delete_item("forward_dialog"))

def _submit_forward(study_id):
    body = {
        "source_study_id":   study_id,
        "target_pacs_url":   dpg.get_value("fwd_pacs_url"),
        "target_pacs_user":  dpg.get_value("fwd_pacs_user"),
        "target_pacs_pass":  dpg.get_value("fwd_pacs_pass"),
        "anonymize":         dpg.get_value("fwd_anon"),
        "examination_result":dpg.get_value("fwd_result") or None,
    }
    if dpg.does_item_exist("forward_dialog"):
        dpg.delete_item("forward_dialog")
    def _do():
        data, err = api_post("/forward/study", json_body=body)
        if err:
            set_status(f"Forward error: {err}", error=True)
            log(f"Forward error: {err}")
        else:
            set_status(f"Forward queued: {data.get('job_id','')[:16]}...")
            log(f"Forward job: {data.get('job_id')}")
    threading.Thread(target=_do, daemon=True).start()

# ── Jobs tab ──────────────────────────────────────────────────────────────────
def refresh_jobs():
    def _do():
        data, err = api_get("/jobs")
        if err:
            set_status(f"Jobs error: {err}", error=True)
            return
        state["jobs"] = data or []
        _rebuild_jobs_table()
        set_status(f"Loaded {len(state['jobs'])} jobs.")
    threading.Thread(target=_do, daemon=True).start()

def _rebuild_jobs_table():
    if not dpg.does_item_exist("jobs_table"):
        return
    dpg.delete_item("jobs_table", children_only=True)
    for col in ["Type", "Status", "Progress", "Created", "Actions"]:
        dpg.add_table_column(label=col, parent="jobs_table")
    for job in state["jobs"]:
        prog = job.get("progress", {})
        prog_str = f"{prog.get('done',0)}/{prog.get('total',0)}"
        created  = job.get("created_at","")[:19].replace("T"," ")
        status   = job.get("status","")
        color    = [60,200,100] if status=="completed" else [220,60,60] if "failed" in status else [220,180,60]
        with dpg.table_row(parent="jobs_table"):
            dpg.add_text(job.get("type","-"))
            dpg.add_text(status, color=color)
            dpg.add_text(prog_str)
            dpg.add_text(created)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Details", callback=lambda s,a,u=job: _show_job_detail(u), width=65)

def _show_job_detail(job):
    if not dpg.does_item_exist("job_detail_text"):
        return
    errors    = job.get("errors",[])
    instances = job.get("instances",[])
    ok_count  = sum(1 for i in instances if i.get("ok") or i.get("status")=="ok")
    text = (
        f"Job ID:    {job.get('id','')}\n"
        f"Type:      {job.get('type','')}\n"
        f"Status:    {job.get('status','')}\n"
        f"Progress:  {job.get('progress',{}).get('done',0)}/{job.get('progress',{}).get('total',0)}\n"
        f"Instances: {len(instances)} total, {ok_count} ok\n"
        f"Errors:    {len(errors)}\n"
        f"Created:   {job.get('created_at','')[:19]}\n"
        f"Updated:   {job.get('updated_at','')[:19]}\n"
    )
    if errors:
        text += "\nErrors:\n"
        for e in errors[:5]:
            text += f"  - {json.dumps(e)}\n"
    dpg.set_value("job_detail_text", text)

# ── Search tab ────────────────────────────────────────────────────────────────
def do_search():
    query    = dpg.get_value("search_query")
    modality = dpg.get_value("search_modality").strip() or None
    if not query:
        set_status("Enter a search query.", error=True)
        return
    def _do():
        set_status("Searching...")
        params = f"?q={query}" + (f"&modality={modality}" if modality else "")
        data, err = api_get(f"/query/search{params}")
        if err:
            set_status(f"Search error: {err}", error=True)
            return
        state["search_results"] = data or []
        _rebuild_search_table()
        set_status(f"Found {len(state['search_results'])} results.")
    threading.Thread(target=_do, daemon=True).start()

def _rebuild_search_table():
    if not dpg.does_item_exist("search_table"):
        return
    dpg.delete_item("search_table", children_only=True)
    for col in ["Modality","Date","Description","Comments","Instances"]:
        dpg.add_table_column(label=col, parent="search_table")
    for r in state["search_results"]:
        with dpg.table_row(parent="search_table"):
            dpg.add_text(r.get("modality") or "-")
            dpg.add_text(r.get("study_date") or "-")
            dpg.add_text((r.get("study_description") or "")[:40])
            dpg.add_text((r.get("image_comments")    or "")[:50])
            dpg.add_text(str(r.get("instance_count") or "-"))

# ── Admin tab ─────────────────────────────────────────────────────────────────
def refresh_admin():
    """Refresh all admin sections in parallel."""
    threading.Thread(target=_fetch_stats,   daemon=True).start()
    threading.Thread(target=_fetch_pacs,    daemon=True).start()
    threading.Thread(target=_fetch_audit,   daemon=True).start()
    threading.Thread(target=_fetch_workers, daemon=True).start()

def _fetch_stats():
    data, err = api_get("/admin/stats")
    if err:
        log(f"Stats error: {err}")
        return
    state["stats"] = data
    _render_stats(data)

def _render_stats(d):
    if not dpg.does_item_exist("stats_text"):
        return
    jobs  = d.get("jobs", {})
    orth  = d.get("orthanc", {})
    redis = d.get("redis", {})
    sr    = jobs.get("success_rate_pct")
    sr_str = f"{sr}%" if sr is not None else "N/A"
    text = (
        f"── Jobs ──────────────────────\n"
        f"  Total       : {jobs.get('total',0)}\n"
        f"  Completed   : {jobs.get('completed',0)}\n"
        f"  With errors : {jobs.get('completed_with_errors',0)}\n"
        f"  Failed      : {jobs.get('failed',0)}\n"
        f"  Queued      : {jobs.get('queued',0)}\n"
        f"  Processing  : {jobs.get('processing',0)}\n"
        f"  Success rate: {sr_str}\n"
        f"  Instances   : {jobs.get('total_instances',0)}\n"
        f"  Last 24h    : {jobs.get('last_24h',0)}\n\n"
        f"── Orthanc ───────────────────\n"
        f"  Reachable   : {orth.get('reachable','?')}\n"
        f"  Version     : {orth.get('version','?')}\n"
        f"  Studies     : {orth.get('studies','?')}\n"
        f"  Instances   : {orth.get('instances','?')}\n\n"
        f"── Redis ─────────────────────\n"
        f"  Reachable   : {redis.get('reachable','?')}\n\n"
        f"── PACS Configs ──────────────\n"
        f"  Configured  : {d.get('pacs_configs',0)}\n"
    )
    dpg.set_value("stats_text", text)

def _fetch_pacs():
    data, err = api_get("/admin/pacs")
    if err:
        log(f"PACS list error: {err}")
        return
    state["pacs_configs"] = data or []
    _rebuild_pacs_table()

def _rebuild_pacs_table():
    if not dpg.does_item_exist("pacs_table"):
        return
    dpg.delete_item("pacs_table", children_only=True)
    for col in ["Name", "URL", "Actions"]:
        dpg.add_table_column(label=col, parent="pacs_table")
    for cfg in state["pacs_configs"]:
        with dpg.table_row(parent="pacs_table"):
            dpg.add_text(cfg.get("name",""))
            dpg.add_text(cfg.get("url",""))
            with dpg.group(horizontal=True):
                dpg.add_button(label="Test",   width=50, callback=lambda s,a,u=cfg["id"]: _test_pacs(u))
                dpg.add_button(label="Delete", width=60, callback=lambda s,a,u=cfg["id"]: _delete_pacs(u))

def _test_pacs(pacs_id):
    def _do():
        set_status("Testing PACS...")
        data, err = api_get(f"/admin/pacs/{pacs_id}/test")
        if err:
            set_status(f"Test error: {err}", error=True)
            return
        if data.get("reachable"):
            msg = f"PACS OK — v{data.get('orthanc_version','?')} — {data.get('latency_ms','?')}ms"
            set_status(msg)
            log(msg)
        else:
            msg = f"PACS unreachable: {data.get('error', data.get('status_code','?'))}"
            set_status(msg, error=True)
            log(msg)
    threading.Thread(target=_do, daemon=True).start()

def _delete_pacs(pacs_id):
    def _do():
        _, err = api_delete(f"/admin/pacs/{pacs_id}")
        if err:
            set_status(f"Delete error: {err}", error=True)
        else:
            set_status("PACS config deleted.")
            log(f"Deleted PACS config {pacs_id}")
            _fetch_pacs()
    threading.Thread(target=_do, daemon=True).start()

def _open_add_pacs_dialog():
    if dpg.does_item_exist("add_pacs_dialog"):
        dpg.delete_item("add_pacs_dialog")
    with dpg.window(label="Add PACS Config", tag="add_pacs_dialog",
                    modal=True, width=440, height=280, pos=[220, 180]):
        dpg.add_text("Name:");     dpg.add_input_text(tag="new_pacs_name", width=400)
        dpg.add_text("URL:");      dpg.add_input_text(tag="new_pacs_url",  default_value="http://", width=400)
        dpg.add_text("Username:"); dpg.add_input_text(tag="new_pacs_user", default_value="orthanc", width=400)
        dpg.add_text("Password:"); dpg.add_input_text(tag="new_pacs_pass", default_value="orthanc", password=True, width=400)
        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Add", width=80, callback=_submit_add_pacs)
            dpg.add_button(label="Cancel", width=80, callback=lambda: dpg.delete_item("add_pacs_dialog"))

def _submit_add_pacs():
    body = {
        "name":     dpg.get_value("new_pacs_name"),
        "url":      dpg.get_value("new_pacs_url"),
        "username": dpg.get_value("new_pacs_user"),
        "password": dpg.get_value("new_pacs_pass"),
    }
    if dpg.does_item_exist("add_pacs_dialog"):
        dpg.delete_item("add_pacs_dialog")
    def _do():
        data, err = api_post("/admin/pacs", json_body=body)
        if err:
            set_status(f"Add PACS error: {err}", error=True)
        else:
            set_status(f"PACS added: {body['name']}")
            log(f"Added PACS config: {body['name']} → {data.get('id')}")
            _fetch_pacs()
    threading.Thread(target=_do, daemon=True).start()

def _fetch_audit():
    data, err = api_get("/admin/audit?limit=30")
    if err:
        return
    state["audit"] = data or []
    _rebuild_audit_table()

def _rebuild_audit_table():
    if not dpg.does_item_exist("audit_table"):
        return
    dpg.delete_item("audit_table", children_only=True)
    for col in ["Type","Status","Instances","Errors","Anonymized","Created","Target PACS"]:
        dpg.add_table_column(label=col, parent="audit_table")
    for entry in state["audit"]:
        status = entry.get("status","")
        color  = [60,200,100] if status=="completed" else [220,60,60] if "failed" in status else [220,180,60]
        with dpg.table_row(parent="audit_table"):
            dpg.add_text(entry.get("type","-"))
            dpg.add_text(status, color=color)
            dpg.add_text(str(entry.get("instances",0)))
            dpg.add_text(str(entry.get("errors",0)))
            dpg.add_text("Da" if entry.get("anonymized") else "Nu")
            dpg.add_text(entry.get("created_at","")[:19].replace("T"," "))
            dpg.add_text((entry.get("target_pacs") or "-")[:30])

def _fetch_workers():
    data, err = api_get("/admin/workers")
    if err:
        return
    state["workers"] = data.get("workers", [])
    _render_workers(data)

def _render_workers(d):
    if not dpg.does_item_exist("workers_text"):
        return
    workers = d.get("workers", [])
    if not workers:
        note = d.get("note") or d.get("error") or "No workers online."
        dpg.set_value("workers_text", note)
        return
    text = f"Online workers: {d.get('total_online', len(workers))}\n\n"
    for w in workers:
        text += f"  {w['name']}\n"
        text += f"    Status       : {w['status']}\n"
        text += f"    Active tasks : {w['active_tasks']}\n"
        if w.get("tasks"):
            text += f"    Tasks        : {', '.join(w['tasks'])}\n"
        text += "\n"
    dpg.set_value("workers_text", text)

def _purge_jobs(status_filter):
    def _do():
        path = f"/admin/jobs?status={status_filter}" if status_filter else "/admin/jobs"
        data, err = api_delete(path)
        if err:
            set_status(f"Purge error: {err}", error=True)
        else:
            n = data.get("deleted_count", 0)
            set_status(f"Purged {n} jobs.")
            log(f"Purged {n} jobs (filter: {status_filter or 'all'})")
            refresh_jobs()
            _fetch_stats()
    threading.Thread(target=_do, daemon=True).start()

# ── Auto-refresh ──────────────────────────────────────────────────────────────
def _auto_refresh():
    while True:
        time.sleep(10)
        check_health()

# ── Main GUI ──────────────────────────────────────────────────────────────────
def main():
    dpg.create_context()

    with dpg.window(tag="main_window", label="MSV-med — PACS Manager"):

        # Top bar
        with dpg.group(horizontal=True):
            dpg.add_text("MSV-med PACS Manager", color=[120, 180, 255])
            dpg.add_spacer(width=30)
            dpg.add_text("●", tag="health_api",  color=[100,100,100])
            dpg.add_text("●", tag="health_pacs", color=[100,100,100])
            dpg.add_spacer(width=20)
            dpg.add_button(label="Check Health", callback=check_health, width=110)
        dpg.add_separator()

        with dpg.tab_bar():

            # ══ STUDIES ═══════════════════════════════════════════════════════
            with dpg.tab(label="📋  Studies"):
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Refresh", callback=refresh_studies, width=100)
                    dpg.add_button(label="Ingest All → AI", callback=ingest_all, width=130)
                dpg.add_spacer(height=6)
                with dpg.group(horizontal=True):
                    with dpg.child_window(width=600, height=480, border=True):
                        dpg.add_text("Studies in PACS", color=[180,180,180])
                        dpg.add_separator()
                        with dpg.table(tag="studies_table", header_row=True,
                                       borders_innerH=True, borders_outerH=True,
                                       borders_outerV=True, scrollY=True, height=430,
                                       policy=dpg.mvTable_SizingFixedFit):
                            pass
                    dpg.add_spacer(width=8)
                    with dpg.child_window(width=430, height=480, border=True):
                        dpg.add_text("Study Details", color=[180,180,180])
                        dpg.add_separator()
                        dpg.add_input_text(tag="study_detail_text", multiline=True,
                                           readonly=True, width=410, height=450,
                                           default_value="Select a study.")

            # ══ JOBS ══════════════════════════════════════════════════════════
            with dpg.tab(label="⚙️  Jobs"):
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Refresh", callback=refresh_jobs, width=100)
                dpg.add_spacer(height=6)
                with dpg.group(horizontal=True):
                    with dpg.child_window(width=600, height=480, border=True):
                        dpg.add_text("Job Queue", color=[180,180,180])
                        dpg.add_separator()
                        with dpg.table(tag="jobs_table", header_row=True,
                                       borders_innerH=True, borders_outerH=True,
                                       borders_outerV=True, scrollY=True, height=430,
                                       policy=dpg.mvTable_SizingFixedFit):
                            pass
                    dpg.add_spacer(width=8)
                    with dpg.child_window(width=430, height=480, border=True):
                        dpg.add_text("Job Details", color=[180,180,180])
                        dpg.add_separator()
                        dpg.add_input_text(tag="job_detail_text", multiline=True,
                                           readonly=True, width=410, height=450,
                                           default_value="Click Details on a job.")

            # ══ AI SEARCH ════════════════════════════════════════════════════
            with dpg.tab(label="🔍  AI Search"):
                dpg.add_text("Semantic search over indexed studies", color=[180,180,180])
                dpg.add_spacer(height=6)
                with dpg.group(horizontal=True):
                    dpg.add_text("Query:")
                    dpg.add_input_text(tag="search_query", width=380, hint="CT torace cu noduli")
                    dpg.add_text("Modality:")
                    dpg.add_input_text(tag="search_modality", width=70, hint="CT")
                    dpg.add_button(label="Search", callback=do_search, width=80)
                dpg.add_spacer(height=8)
                with dpg.child_window(height=430, border=True):
                    with dpg.table(tag="search_table", header_row=True,
                                   borders_innerH=True, borders_outerH=True,
                                   borders_outerV=True, scrollY=True, height=420,
                                   policy=dpg.mvTable_SizingStretchProp):
                        pass

            # ══ ADMIN ════════════════════════════════════════════════════════
            with dpg.tab(label="🛠️  Admin"):
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Refresh All", callback=refresh_admin, width=110)
                dpg.add_spacer(height=8)

                with dpg.tab_bar(tag="admin_tabs"):

                    # ── Overview ─────────────────────────────────────────────
                    with dpg.tab(label="Overview"):
                        with dpg.group(horizontal=True):
                            with dpg.child_window(width=340, height=420, border=True):
                                dpg.add_text("System Stats", color=[180,180,180])
                                dpg.add_separator()
                                dpg.add_input_text(tag="stats_text", multiline=True,
                                                   readonly=True, width=320, height=380,
                                                   default_value="Click Refresh All.")
                            dpg.add_spacer(width=8)
                            with dpg.child_window(width=680, height=420, border=True):
                                dpg.add_text("Celery Workers", color=[180,180,180])
                                dpg.add_separator()
                                dpg.add_input_text(tag="workers_text", multiline=True,
                                                   readonly=True, width=660, height=380,
                                                   default_value="Click Refresh All.")

                    # ── PACS Config ──────────────────────────────────────────
                    with dpg.tab(label="PACS Config"):
                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Add PACS", callback=_open_add_pacs_dialog, width=100)
                            dpg.add_button(label="Refresh",  callback=_fetch_pacs,            width=90)
                        dpg.add_spacer(height=6)
                        with dpg.child_window(height=400, border=True):
                            with dpg.table(tag="pacs_table", header_row=True,
                                           borders_innerH=True, borders_outerH=True,
                                           borders_outerV=True, scrollY=True, height=390,
                                           policy=dpg.mvTable_SizingFixedFit):
                                pass

                    # ── Audit Log ────────────────────────────────────────────
                    with dpg.tab(label="Audit Log"):
                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Refresh",             callback=_fetch_audit,                    width=90)
                            dpg.add_button(label="Purge failed",        callback=lambda: _purge_jobs("failed"),   width=110)
                            dpg.add_button(label="Purge completed",     callback=lambda: _purge_jobs("completed"),width=130)
                            dpg.add_button(label="Purge ALL",           callback=lambda: _purge_jobs(None),       width=90)
                        dpg.add_spacer(height=6)
                        with dpg.child_window(height=400, border=True):
                            with dpg.table(tag="audit_table", header_row=True,
                                           borders_innerH=True, borders_outerH=True,
                                           borders_outerV=True, scrollY=True, height=390,
                                           policy=dpg.mvTable_SizingStretchProp):
                                pass

            # ══ LOG ══════════════════════════════════════════════════════════
            with dpg.tab(label="📝  Log"):
                dpg.add_text("Activity Log", color=[180,180,180])
                dpg.add_separator()
                dpg.add_input_text(tag="log_box", multiline=True, readonly=True,
                                   width=-1, height=490, default_value="Waiting...\n")
                dpg.add_button(label="Clear", callback=lambda: dpg.set_value("log_box",""), width=80)

        dpg.add_separator()
        dpg.add_text("Ready.", tag="status_bar", color=[60,200,100])

    dpg.create_viewport(title="MSV-med PACS Manager", width=1150, height=740, resizable=True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)

    check_health()
    refresh_studies()
    refresh_admin()

    threading.Thread(target=_auto_refresh, daemon=True).start()

    dpg.start_dearpygui()
    dpg.destroy_context()

if __name__ == "__main__":
    main()
