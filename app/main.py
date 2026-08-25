"""FastAPI backend + dashboard host."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .config import load_config
from .models import STATUSES
from .prompt import build_prompt
from .resume import read_resume
from .scoring import analyze

WEB = Path(__file__).resolve().parent / "web"

app = FastAPI(title="JobHunt", version="1.0")


@app.middleware("http")
async def _no_cache(request, call_next):
    """Local dev tool: never let the browser cache the UI, so edits to
    app.js / styles.css / index.html always take effect on reload."""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.on_event("startup")
def _startup():
    db.init_db()


def _resume_text() -> str:
    cfg = load_config()
    path = Path(cfg.get("resume_path", "sample/resume.txt"))
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    try:
        return read_resume(path)
    except (FileNotFoundError, ValueError):
        return ""


def _resume_path() -> Path | None:
    cfg = load_config()
    path = Path(cfg.get("resume_path", "sample/resume.txt"))
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path if path.exists() else None


class StatusIn(BaseModel):
    status: str


class DescriptionIn(BaseModel):
    description: str


class JobIn(BaseModel):
    title: str
    company: str
    url: str = ""
    location: str = ""
    description: str = ""
    remote: bool = False
    start_year: int | None = None


@app.get("/api/jobs")
def api_jobs(status: str = "all", order: str = "score"):
    conn = db.connect()
    rows = db.list_jobs(conn, status=status, order_by=order)
    conn.close()
    # trim heavy fields for the list view
    for r in rows:
        r.pop("description", None)
        r.pop("analysis", None)
    return {"jobs": rows, "statuses": STATUSES}


@app.get("/api/job/{job_id}")
def api_job(job_id: str):
    conn = db.connect()
    job = db.get_job(conn, job_id)
    conn.close()
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.post("/api/job/{job_id}/status")
def api_status(job_id: str, body: StatusIn):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    conn = db.connect()
    ok = db.update_status(conn, job_id, body.status)
    conn.close()
    if not ok:
        raise HTTPException(404, "job not found")
    return {"ok": True, "status": body.status}


@app.delete("/api/job/{job_id}")
def api_delete(job_id: str):
    conn = db.connect()
    ok = db.delete_job(conn, job_id)
    conn.close()
    if not ok:
        raise HTTPException(404, "job not found")
    return {"ok": True, "deleted": job_id}


@app.post("/api/job/{job_id}/description")
def api_set_description(job_id: str, body: DescriptionIn):
    """Manually set/replace the job description (e.g. paste the full JD when the
    posting is JavaScript-rendered and auto-fetch can't read it). Analyzing
    afterwards with refetch=false scores against exactly this text."""
    conn = db.connect()
    job = db.get_job(conn, job_id)
    if not job:
        conn.close()
        raise HTTPException(404, "job not found")
    db.update_description(conn, job_id, body.description.strip())
    conn.close()
    return {"ok": True, "length": len(body.description.strip())}


@app.post("/api/prune")
def api_prune():
    """Delete every stored job that no longer passes the current config filters.
    Fixes leftover managerial/off-target/expired rows ingested under old filters.
    Deleted jobs are tombstoned so they won't be re-ingested."""
    from .models import Job
    from .normalize import passes_filters
    cfg = load_config()
    filters = cfg.get("filters", {})
    conn = db.connect()
    removed = []
    for row in db.list_jobs(conn, status="all"):
        job = Job(
            source=row["source"], source_job_id=row["source_job_id"],
            title=row["title"], company=row["company"], url=row["url"],
            location=row.get("location", ""), remote=row.get("remote", False),
            description=row.get("description", "") or "",
            start_year=row.get("start_year"),
        )
        if not passes_filters(job, filters):
            db.delete_job(conn, row["id"])
            removed.append({"title": row["title"], "company": row["company"]})
    conn.close()
    return {"ok": True, "removed": len(removed), "jobs": removed[:50]}


@app.post("/api/job/{job_id}/analyze")
def api_analyze(job_id: str, refetch: bool = True):
    conn = db.connect()
    job = db.get_job(conn, job_id)
    if not job:
        conn.close()
        raise HTTPException(404, "job not found")
    resume = _resume_text()
    if not resume:
        conn.close()
        raise HTTPException(400, "no resume found — set resume_path in config.yaml")

    description = job.get("description", "") or ""
    jd_source = "listing summary" if refetch else "manual paste"
    # thin listing? try to pull the full JD from the posting so scoring is real.
    if refetch and len(description) < 600 and job.get("url"):
        from .jd_fetch import fetch_full_jd
        full, label = fetch_full_jd(job["url"])
        if full and len(full) > len(description):
            description = full
            jd_source = "full posting"
            db.update_description(conn, job_id, description)

    result = analyze(resume, description)
    result.jd_source = jd_source
    payload = result.to_dict()

    # richer multi-factor score via ats-resume-scorer, if installed
    try:
        from . import ats_score
        rp = _resume_path()
        if rp is not None:
            rich = ats_score.rich_score(rp, description)
            if rich:
                payload["ats"] = rich
    except Exception:
        pass

    db.save_analysis(conn, job_id, result.score, payload)
    conn.close()
    return payload


@app.get("/api/job/{job_id}/prompt")
def api_prompt(job_id: str, include_resume: bool = True, include_rules: bool = True):
    conn = db.connect()
    job = db.get_job(conn, job_id)
    conn.close()
    if not job:
        raise HTTPException(404, "job not found")
    analysis = job.get("analysis")
    if not analysis:
        raise HTTPException(400, "run analyze first")
    resume = _resume_text() if include_resume else ""
    text = build_prompt(job, analysis, resume,
                        include_resume=include_resume, include_rules=include_rules)
    return {"prompt": text}


@app.post("/api/job/{job_id}/deepdive")
def api_deepdive(job_id: str):
    """Button 2: send JD + resume + gap list to Gemini (via LangChain) and get
    concrete, ATS-maximizing edit suggestions back."""
    conn = db.connect()
    job = db.get_job(conn, job_id)
    conn.close()
    if not job:
        raise HTTPException(404, "job not found")
    analysis = job.get("analysis")
    if not analysis:
        raise HTTPException(400, "run Analyze Score first")
    resume = _resume_text()
    if not resume:
        raise HTTPException(400, "no resume found — set resume_path in config.yaml")
    from .deepdive import deep_dive
    return deep_dive(resume, job.get("description", "") or "", analysis, job)


@app.post("/api/jobs")
def api_create_job(body: JobIn):
    """Add a job manually (e.g. one you found online and want to track)."""
    import uuid
    from .models import Job
    from .normalize import infer_start
    job = Job(
        source="manual", source_job_id=f"manual:{uuid.uuid4()}",
        title=body.title.strip(), company=body.company.strip(),
        url=body.url.strip(), location=body.location.strip(),
        remote=body.remote, description=body.description.strip(),
        start_year=body.start_year,
    )
    job = infer_start(job)
    conn = db.connect()
    new_id = db.insert_job(conn, job)   # manual adds bypass ingest filters
    conn.close()
    if not new_id:
        raise HTTPException(409, "a matching job is already tracked")
    return {"ok": True, "id": new_id}


@app.post("/api/ingest")
def api_ingest(background: BackgroundTasks):
    from .ingest import run_ingest
    background.add_task(run_ingest, verbose=True)
    return {"ok": True, "message": "ingestion started in background"}


@app.get("/api/config")
def api_config():
    cfg = load_config()
    from . import ats_score, deepdive
    return {
        "filters": cfg.get("filters", {}),
        "resume_path": cfg.get("resume_path", ""),
        "resume_loaded": bool(_resume_text()),
        "notify_channel": cfg.get("notify", {}).get("channel", "none"),
        "sources": {k: v.get("enabled", False) for k, v in cfg.get("sources", {}).items()},
        "capabilities": {
            "ats_scorer": ats_score.available(),
            "gemini_deepdive": deepdive.available(),
        },
    }


# ---- static dashboard ----
@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")