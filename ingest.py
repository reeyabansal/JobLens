#!/usr/bin/env python3
"""Run a single ingestion pass from the command line:  python ingest.py"""
from app.ingest import run_ingest

if __name__ == "__main__":
    run_ingest(verbose=True)
