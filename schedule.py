#!/usr/bin/env python3
"""Run ingestion on a schedule:  python schedule.py

Defaults to every 6 hours. Requires apscheduler (in requirements.txt).
Run this alongside `python run.py` (the dashboard) in a separate process.
"""
from apscheduler.schedulers.blocking import BlockingScheduler

from app.ingest import run_ingest

INTERVAL_HOURS = 6

if __name__ == "__main__":
    print(f"Scheduler started — ingesting now, then every {INTERVAL_HOURS}h. Ctrl-C to stop.")
    run_ingest(verbose=True)
    sched = BlockingScheduler()
    sched.add_job(run_ingest, "interval", hours=INTERVAL_HOURS, kwargs={"verbose": True})
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nScheduler stopped.")
