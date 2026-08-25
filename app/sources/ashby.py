"""Ashby public job board API — free JSON.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{company}?includeCompensation=true
`company` is the job board name slug.
"""
from __future__ import annotations

import re

from .base import Source
from ..models import Job

BASE = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


class AshbySource(Source):
    name = "ashby"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for slug in self.config.get("companies", []):
            try:
                r = self._get(BASE.format(slug=slug), params={"includeCompensation": "true"})
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception:
                continue
            for item in data.get("jobs", []):
                loc = item.get("location", "") or ""
                jobs.append(Job(
                    source=self.name,
                    source_job_id=str(item.get("id") or item.get("jobId") or item.get("title")),
                    title=item.get("title", ""),
                    company=slug,
                    location=loc,
                    remote=bool(item.get("isRemote")) or "remote" in loc.lower(),
                    url=item.get("jobUrl", "") or item.get("applyUrl", ""),
                    description=_strip_html(item.get("descriptionHtml") or item.get("descriptionPlain", "")),
                    posted_at=(item.get("publishedAt") or "")[:10] or None,
                ))
        return jobs
