"""Orchestrate a full ingestion pass. Used by the CLI and the scheduler.

Every newly ingested job is scored against your resume right away (deterministic,
offline), so the dashboard can sort by match without you clicking anything.
"""
from __future__ import annotations

from pathlib import Path

from . import db, notify, scoring
from .config import load_config
from .normalize import infer_start, passes_filters
from .resume import read_resume
from .sources import REGISTRY


def _load_resume(cfg) -> str:
    path = Path(cfg.get("resume_path", "sample/resume.txt"))
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    try:
        return read_resume(path)
    except Exception:
        return ""


def run_ingest(verbose: bool = True) -> dict:
    cfg = load_config()
    db.init_db()
    conn = db.connect()
    filters = cfg.get("filters", {})
    secrets = cfg.get("secrets", {})
    resume = _load_resume(cfg)

    fetched = inserted = skipped = analyzed = 0
    per_source: dict[str, int] = {}
    new_jobs: list[tuple[str, str]] = []   # (job_id, description)

    for name, source_cfg in cfg.get("sources", {}).items():
        if not source_cfg.get("enabled"):
            continue
        cls = REGISTRY.get(name)
        if not cls:
            continue
        # pass filter keywords through to keyword-driven sources (adzuna)
        merged = dict(source_cfg)
        merged.setdefault("keywords", filters.get("role_keywords", filters.get("keywords", [])))
        adapter = cls(merged, secrets)
        try:
            jobs = adapter.fetch()
        except Exception as e:  # never let one source kill the run
            if verbose:
                print(f"  ! {name} failed: {e}")
            continue

        added_here = 0
        for job in jobs:
            fetched += 1
            job = infer_start(job)
            if not passes_filters(job, filters):
                skipped += 1
                continue
            new_id = db.insert_job(conn, job)
            if new_id:
                inserted += 1
                added_here += 1
                new_jobs.append((new_id, job.description or ""))
        per_source[name] = added_here
        if verbose:
            print(f"  · {name}: fetched {len(jobs)}, added {added_here}")

    # ── auto match-analysis for every newly ingested job ──────────────────
    # Deterministic + offline (no network), so bulk scoring stays fast. Board
    # sources carry full JDs; thin listings (github/adzuna) score lower and can
    # be sharpened later via the "paste full JD" box on the job.
    if resume and new_jobs:
        for jid, desc in new_jobs:
            try:
                result = scoring.analyze(resume, desc)
                result.jd_source = "full posting" if len(desc) >= 600 else "listing summary"
                db.save_analysis(conn, jid, result.score, result.to_dict())
                analyzed += 1
            except Exception:
                pass
    elif not resume and verbose and new_jobs:
        print("  (no resume configured — skipped match analysis)")

    # notify on anything new + unnotified
    sent = 0
    if cfg.get("notify", {}).get("channel", "none") != "none":
        for job in db.unnotified(conn):
            if notify.send(job, cfg):
                db.mark_notified(conn, job["id"])
                sent += 1
    else:
        # mark as notified so they don't queue up when a channel is later enabled
        for job in db.unnotified(conn):
            db.mark_notified(conn, job["id"])

    conn.close()
    summary = {"fetched": fetched, "inserted": inserted, "analyzed": analyzed,
               "skipped": skipped, "notified": sent, "per_source": per_source}
    if verbose:
        print(f"Done: +{inserted} new, {analyzed} analyzed, {skipped} filtered out, {sent} notified.")
    return summary


if __name__ == "__main__":
    run_ingest()
