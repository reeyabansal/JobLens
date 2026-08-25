"""Normalized job shape that every source adapter returns."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


STATUSES = ["to_apply", "applied", "interviewing", "offer", "rejected", "archived"]


@dataclass
class Job:
    source: str                      # greenhouse | lever | ashby | github_repo | adzuna
    source_job_id: str               # native id from the source (used for dedup)
    title: str
    company: str
    url: str
    location: str = ""
    remote: bool = False
    description: str = ""
    posted_at: Optional[str] = None  # ISO date string
    start_date: Optional[str] = None # parsed/inferred ISO date, or free text season
    start_year: Optional[int] = None # inferred year for filtering (e.g. 2027)

    def dedup_key(self) -> str:
        """Stable key so the same posting from the same source isn't stored twice."""
        raw = f"{self.source}::{self.source_job_id}".lower().strip()
        return hashlib.sha1(raw.encode()).hexdigest()

    def content_key(self) -> str:
        """Cross-source fuzzy-ish key: same role at same company + location."""
        raw = f"{self.company}::{self.title}::{self.location}".lower().strip()
        return hashlib.sha1(raw.encode()).hexdigest()

    def as_dict(self) -> dict:
        return asdict(self)
