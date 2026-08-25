"""Orchestrate a full ingestion pass. Used by the CLI and the scheduler."""
from __future__ import annotations

from . import db, notify
from .config import load_config
from .normalize import infer_start, passes_filters
from .sources import REGISTRY


def run_ingest(verbose: bool = True) -> dict:
    cfg = load_config()
    db.init_db()
    conn = db.connect()
    filters = cfg.get("filters", {})
    secrets = cfg.get("secrets", {})

    fetched = inserted = skipped = 0
    per_source: dict[str, int] = {}

    for name, source_cfg in cfg.get("sources", {}).items():
        if not source_cfg.get("enabled"):
            continue
        cls = REGISTRY.get(name)
        if not cls:
            continue
        # pass filter keywords through to keyword-driven sources (adzuna)
        merged = dict(source_cfg)
        merged.setdefault("keywords", filters.get("keywords", []))
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
        per_source[name] = added_here
        if verbose:
            print(f"  · {name}: fetched {len(jobs)}, added {added_here}")

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
    summary = {"fetched": fetched, "inserted": inserted,
               "skipped": skipped, "notified": sent, "per_source": per_source}
    if verbose:
        print(f"Done: +{inserted} new, {skipped} filtered out, {sent} notified.")
    return summary


if __name__ == "__main__":
    run_ingest()
