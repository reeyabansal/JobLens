"""Lever public postings API — free JSON.

Endpoint: https://api.lever.co/v0/postings/{company}?mode=json
`company` is the Lever account slug, e.g. 'netflix'.
"""
from __future__ import annotations

import re

from .base import Source
from ..models import Job

BASE = "https://api.lever.co/v0/postings/{slug}?mode=json"


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


class LeverSource(Source):
    name = "lever"

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
            for item in data:
                cats = item.get("categories", {}) or {}
                loc = cats.get("location", "") or ""
                desc = item.get("descriptionPlain") or _strip_html(item.get("description", ""))
                jobs.append(Job(
                    source=self.name,
                    source_job_id=str(item.get("id")),
                    title=item.get("text", ""),
                    company=slug,
                    location=loc,
                    remote="remote" in (loc + cats.get("commitment", "")).lower(),
                    url=item.get("hostedUrl", ""),
                    description=desc,
                    posted_at=None,
                ))
        return jobs
