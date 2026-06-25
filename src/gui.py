"""
MSV-med GUI — DearPyGui interface for the PACS backend API.
Run: python gui.py
Requires: pip install dearpygui httpx
"""

import threading
import time
import httpx
import json
import os
from pathlib import Path
import dearpygui.dearpygui as dpg

# ── Config ────────────────────────────────────────────────────────────────────
API_URL    = os.getenv("API_URL",    "http://localhost:8000")
API_TOKEN  = os.getenv("API_TOKEN",  "changeme")
ORTHANC    = os.getenv("ORTHANC_URL","http://localhost:8042")

HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

# ── State ─────────────────────────────────────────────────────────────────────
state = {
    "studies":      [],   # list of orthanc study dicts
    "jobs":         [],   # list of job dicts
    "records":      [],   # indexed records from /query/records
    "search_results": [], # semantic search results
    "selected_study": None,
    "selected_job":   None,
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

# ── Studies tab ───────────────────────────────────────────────────────────────
def refresh_studies():
    def _do():
        set_status("Fetching studies...")
        data, err = api_get("/studies")
        if err:
            set_status(f"Error: {err}", error=True)
            log(f"Studies fetch error: {err}")
            return
        state["studies"] = data if data else []
        _rebuild_studies_table()
        set_status(f"Loaded {len(state['studies'])} studies.")
        log(f"Loaded {len(state['studies'])} studies from PACS.")
    threading.Thread(target=_do, daemon=True).start()

def _rebuild_studies_table():
    if not dpg.does_item_exist("studies_table"):
        return
    dpg.delete_item("studies_table", children_only=True)
    # Header
    for col in ["#", "Study ID (Orthanc)", "Actions"]:
        dpg.add_table_column(label=col, parent="studies_table")

    for i, sid in enumerate(state["studies"]):
        short_id = sid[:24] + "..." if len(sid) > 24 else sid
        with dpg.table_row(parent="studies_table"):
            dpg.add_text(str(i + 1))
            dpg.add_text(short_id, tag=f"study_text_{i}")
            with dpg.group(horizontal=True):
                dpg.add_button(label="Details",
                               callback=lambda s, a, u=sid: show_study_details(u),
                               width=70)
                dpg.add_button(label="Ingest",
                               callback=lambda s, a, u=sid: ingest_study(u),
                               width=60)
                dpg.add_button(label="Forward",
                               callback=lambda s, a, u=sid: open_forward_dialog(u),
                               width=70)

def show_study_details(study_id):
    def _do():
        data, err = api_get(f"/studies/{study_id}")
        if err:
            log(f"Study detail error: {err}")
            return
        state["selected_study"] = data
        _update_study_detail_panel(data, study_id)
    threading.Thread(target=_do, daemon=True).start()

def _update_study_detail_panel(data, study_id):
    if not dpg.does_item_exist("study_detail_text"):
        return
    tags = data.get("MainDicomTags", {})
    patient = data.get("PatientMainDicomTags", {})
    text = (
        f"Study ID:       {study_id}\n"
        f"Patient:        {patient.get('PatientName', 'N/A')}\n"
        f"Patient ID:     {patient.get('PatientID', 'N/A')}\n"
        f"Modality:       {tags.get('Modality', 'N/A')}\n"
        f"Study Date:     {tags.get('StudyDate', 'N/A')}\n"
        f"Description:    {tags.get('StudyDescription', 'N/A')}\n"
        f"Series count:   {len(data.get('Series', []))}\n"
        f"Instances:      {len(data.get('Instances', []))}\n"
    )
    dpg.set_value("study_detail_text", text)

def ingest_study(study_id):
    def _do():
        set_status(f"Ingesting {study_id[:16]}...")
        log(f"Ingesting study {study_id[:16]}...")
        data, err = api_post(f"/query/ingest/{study_id}")
        if err:
            set_status(f"Ingest error: {err}", error=True)
            log(f"Ingest error: {err}")
        else:
            set_status("Study ingested successfully.")
            log(f"Ingested study → DB id {data.get('id')}")
    threading.Thread(target=_do, daemon=True).start()

def ingest_all():
    def _do():
        set_status("Ingesting all studies...")
        log("Starting bulk ingest...")
        data, err = api_post("/query/ingest/all")
        if err:
            set_status(f"Bulk ingest error: {err}", error=True)
            log(f"Bulk ingest error: {err}")
        else:
            ingested = len(data.get("ingested", []))
            skipped  = len(data.get("skipped", []))
            failed   = len(data.get("failed", []))
            set_status(f"Done. Ingested: {ingested}, Skipped: {skipped}, Failed: {failed}")
            log(f"Bulk ingest done — ingested: {ingested}, skipped: {skipped}, failed: {failed}")
    threading.Thread(target=_do, daemon=True).start()

# ── Forward dialog ────────────────────────────────────────────────────────────
def open_forward_dialog(study_id):
    state["selected_study"] = study_id
    if dpg.does_item_exist("forward_dialog"):
        dpg.delete_item("forward_dialog")

    with dpg.window(label=f"Forward Study — {study_id[:20]}...",
                    tag="forward_dialog", modal=True,
                    width=500, height=380,
                    pos=[200, 150]):
        dpg.add_text("Target PACS URL:")
        dpg.add_input_text(tag="fwd_pacs_url", default_value="http://localhost:8042", width=440)
        dpg.add_text("Target PACS User:")
        dpg.add_input_text(tag="fwd_pacs_user", default_value="orthanc", width=440)
        dpg.add_text("Target PACS Password:")
        dpg.add_input_text(tag="fwd_pacs_pass", default_value="orthanc",
                           password=True, width=440)
        dpg.add_checkbox(label="Anonymize", tag="fwd_anon", default_value=False)
        dpg.add_text("Examination Result (optional):")
        dpg.add_input_text(tag="fwd_result", multiline=True,
                           width=440, height=80)
        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Forward", width=100,
                           callback=lambda: submit_forward(study_id))
            dpg.add_button(label="Cancel", width=80,
                           callback=lambda: dpg.delete_item("forward_dialog"))

def submit_forward(study_id):
    body = {
        "source_study_id": study_id,
        "target_pacs_url":  dpg.get_value("fwd_pacs_url"),
        "target_pacs_user": dpg.get_value("fwd_pacs_user"),
        "target_pacs_pass": dpg.get_value("fwd_pacs_pass"),
        "anonymize":        dpg.get_value("fwd_anon"),
        "examination_result": dpg.get_value("fwd_result") or None,
    }
    if dpg.does_item_exist("forward_dialog"):
        dpg.delete_item("forward_dialog")

    def _do():
        set_status("Submitting forward job...")
        data, err = api_post("/forward/study", json_body=body)
        if err:
            set_status(f"Forward error: {err}", error=True)
            log(f"Forward error: {err}")
        else:
            job_id = data.get("job_id", "?")
            set_status(f"Forward job queued: {job_id[:16]}...")
            log(f"Forward job created: {job_id}")
    threading.Thread(target=_do, daemon=True).start()

# ── Jobs tab ──────────────────────────────────────────────────────────────────
def refresh_jobs():
    def _do():
        set_status("Fetching jobs...")
        data, err = api_get("/jobs")
        if err:
            set_status(f"Error: {err}", error=True)
            log(f"Jobs fetch error: {err}")
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
        done  = prog.get("done", 0)
        total = prog.get("total", 0)
        prog_str = f"{done}/{total}" if total else "-"
        created = job.get("created_at", "")[:19].replace("T", " ")
        status = job.get("status", "")
        status_color = [60, 200, 100] if status == "completed" else \
                       [220, 60, 60]  if "failed" in status else \
                       [220, 180, 60]

        with dpg.table_row(parent="jobs_table"):
            dpg.add_text(job.get("type", "-"))
            dpg.add_text(status, color=status_color)
            dpg.add_text(prog_str)
            dpg.add_text(created)
            dpg.add_button(label="Details",
                           callback=lambda s, a, u=job: show_job_details(u),
                           width=70)

def show_job_details(job):
    state["selected_job"] = job
    if not dpg.does_item_exist("job_detail_text"):
        return
    errors = job.get("errors", [])
    instances = job.get("instances", [])
    ok_count  = sum(1 for i in instances if i.get("ok") or i.get("status") == "ok")
    text = (
        f"Job ID:     {job.get('id', '')}\n"
        f"Type:       {job.get('type', '')}\n"
        f"Status:     {job.get('status', '')}\n"
        f"Progress:   {job.get('progress', {}).get('done', 0)}"
        f" / {job.get('progress', {}).get('total', 0)}\n"
        f"Instances:  {len(instances)} total, {ok_count} ok\n"
        f"Errors:     {len(errors)}\n"
        f"Created:    {job.get('created_at', '')[:19]}\n"
        f"Updated:    {job.get('updated_at', '')[:19]}\n"
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
        params = f"?q={query}"
        if modality:
            params += f"&modality={modality}"
        data, err = api_get(f"/query/search{params}")
        if err:
            set_status(f"Search error: {err}", error=True)
            log(f"Search error: {err}")
            return
        state["search_results"] = data or []
        _rebuild_search_table()
        set_status(f"Found {len(state['search_results'])} results.")
        log(f"Search '{query}' → {len(state['search_results'])} results.")
    threading.Thread(target=_do, daemon=True).start()

def _rebuild_search_table():
    if not dpg.does_item_exist("search_table"):
        return
    dpg.delete_item("search_table", children_only=True)
    for col in ["Modality", "Date", "Description", "Comments", "Instances"]:
        dpg.add_table_column(label=col, parent="search_table")

    for r in state["search_results"]:
        desc = (r.get("study_description") or "")[:40]
        comments = (r.get("image_comments") or "")[:50]
        with dpg.table_row(parent="search_table"):
            dpg.add_text(r.get("modality") or "-")
            dpg.add_text(r.get("study_date") or "-")
            dpg.add_text(desc)
            dpg.add_text(comments)
            dpg.add_text(str(r.get("instance_count") or "-"))

# ── Health check ──────────────────────────────────────────────────────────────
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
            dpg.set_value("health_api",  "API:  OK" if api_ok  else "API:  OFFLINE")
            dpg.set_value("health_pacs", "PACS: OK" if pacs_ok else "PACS: OFFLINE")
            dpg.configure_item("health_api",  color=[60,200,100] if api_ok  else [220,60,60])
            dpg.configure_item("health_pacs", color=[60,200,100] if pacs_ok else [220,60,60])
        set_status("Health check done.")
        log(f"Health — API: {'ok' if api_ok else 'offline'}, PACS: {'ok' if pacs_ok else 'offline'}")
    threading.Thread(target=_do, daemon=True).start()

# ── Auto-refresh loop ─────────────────────────────────────────────────────────
def _auto_refresh():
    while True:
        time.sleep(8)
        check_health()

# ── Main GUI ──────────────────────────────────────────────────────────────────
def main():
    dpg.create_context()

    W, H = 1100, 720

    with dpg.font_registry():
        pass

    with dpg.window(tag="main_window", label="MSV-med — PACS Manager"):

        # ── Top bar ──
        with dpg.group(horizontal=True):
            dpg.add_text("MSV-med PACS Manager", color=[120, 180, 255])
            dpg.add_spacer(width=40)
            dpg.add_text("●", tag="health_api",  color=[100, 100, 100])
            dpg.add_text("●", tag="health_pacs", color=[100, 100, 100])
            dpg.add_spacer(width=20)
            dpg.add_button(label="Check Health", callback=check_health, width=110)
        dpg.add_separator()

        with dpg.tab_bar():

            # ══ STUDIES TAB ══════════════════════════════════════════════════
            with dpg.tab(label="📋  Studies"):
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Refresh Studies", callback=refresh_studies, width=130)
                    dpg.add_button(label="Ingest All → AI", callback=ingest_all, width=130)
                dpg.add_spacer(height=6)

                with dpg.group(horizontal=True):
                    # Studies list (left)
                    with dpg.child_window(width=620, height=480, border=True):
                        dpg.add_text("Studies in PACS", color=[180, 180, 180])
                        dpg.add_separator()
                        with dpg.table(tag="studies_table", header_row=True,
                                       borders_innerH=True, borders_outerH=True,
                                       borders_outerV=True, scrollY=True,
                                       height=430, policy=dpg.mvTable_SizingFixedFit):
                            pass  # columns added dynamically

                    dpg.add_spacer(width=8)

                    # Study detail (right)
                    with dpg.child_window(width=420, height=480, border=True):
                        dpg.add_text("Study Details", color=[180, 180, 180])
                        dpg.add_separator()
                        dpg.add_input_text(tag="study_detail_text", multiline=True,
                                           readonly=True, width=400, height=430,
                                           default_value="Select a study to see details.")

            # ══ JOBS TAB ═════════════════════════════════════════════════════
            with dpg.tab(label="⚙️  Jobs"):
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Refresh Jobs", callback=refresh_jobs, width=120)
                dpg.add_spacer(height=6)

                with dpg.group(horizontal=True):
                    with dpg.child_window(width=620, height=480, border=True):
                        dpg.add_text("Job Queue", color=[180, 180, 180])
                        dpg.add_separator()
                        with dpg.table(tag="jobs_table", header_row=True,
                                       borders_innerH=True, borders_outerH=True,
                                       borders_outerV=True, scrollY=True,
                                       height=430, policy=dpg.mvTable_SizingFixedFit):
                            pass

                    dpg.add_spacer(width=8)

                    with dpg.child_window(width=420, height=480, border=True):
                        dpg.add_text("Job Details", color=[180, 180, 180])
                        dpg.add_separator()
                        dpg.add_input_text(tag="job_detail_text", multiline=True,
                                           readonly=True, width=400, height=430,
                                           default_value="Click Details on a job.")

            # ══ SEMANTIC SEARCH TAB ══════════════════════════════════════════
            with dpg.tab(label="AI Search"):
                dpg.add_text("Semantic search over indexed studies", color=[180, 180, 180])
                dpg.add_spacer(height=6)
                with dpg.group(horizontal=True):
                    dpg.add_text("Query:")
                    dpg.add_input_text(tag="search_query", width=400,
                                       hint="e.g. CT torace cu noduli pulmonari")
                    dpg.add_text("Modality:")
                    dpg.add_input_text(tag="search_modality", width=80, hint="CT")
                    dpg.add_button(label="Search", callback=do_search, width=80)
                dpg.add_spacer(height=8)
                with dpg.child_window(height=430, border=True):
                    with dpg.table(tag="search_table", header_row=True,
                                   borders_innerH=True, borders_outerH=True,
                                   borders_outerV=True, scrollY=True,
                                   height=420, policy=dpg.mvTable_SizingStretchProp):
                        pass

            # ══ LOG TAB ══════════════════════════════════════════════════════
            with dpg.tab(label="Log"):
                dpg.add_text("Activity Log", color=[180, 180, 180])
                dpg.add_separator()
                dpg.add_input_text(tag="log_box", multiline=True, readonly=True,
                                   width=-1, height=500,
                                   default_value="Waiting for activity...\n")
                dpg.add_button(label="Clear Log",
                               callback=lambda: dpg.set_value("log_box", ""),
                               width=100)

        dpg.add_separator()
        dpg.add_text("Ready.", tag="status_bar", color=[60, 200, 100])

    dpg.create_viewport(title="MSV-med PACS Manager",
                        width=W, height=H, resizable=True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)

    # Initial load
    check_health()
    refresh_studies()

    # Background health refresh
    threading.Thread(target=_auto_refresh, daemon=True).start()

    dpg.start_dearpygui()
    dpg.destroy_context()

if __name__ == "__main__":
    main()