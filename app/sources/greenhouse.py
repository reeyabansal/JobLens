"""Greenhouse public job board API — free, stable, structured JSON.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true
`company` is the board token (slug), e.g. 'stripe', 'airbnb'.
"""
from __future__ import annotations

import re

from .base import Source
from ..models import Job

BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = text.replace("&amp;", "&").replace("&nbsp;", " ")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
    return re.sub(r"\s+", " ", text).strip()


class GreenhouseSource(Source):
    name = "greenhouse"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for slug in self.config.get("companies", []):
            try:
                r = self._get(BASE.format(slug=slug))
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception:
                continue
            for item in data.get("jobs", []):
                loc = (item.get("location") or {}).get("name", "")
                jobs.append(Job(
                    source=self.name,
                    source_job_id=str(item.get("id")),
                    title=item.get("title", ""),
                    company=slug,
                    location=loc,
                    remote="remote" in loc.lower(),
                    url=item.get("absolute_url", ""),
                    description=_strip_html(item.get("content", "")),
                    posted_at=(item.get("updated_at") or "")[:10] or None,
                ))
        return jobs
