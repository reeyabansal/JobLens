"""Adzuna aggregator API — free tier (1,000 calls/month). Needs app id + key.

Get free credentials at https://developer.adzuna.com/ and set:
  ADZUNA_APP_ID, ADZUNA_APP_KEY
"""
from __future__ import annotations

from .base import Source
from ..models import Job

BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


class AdzunaSource(Source):
    name = "adzuna"

    def fetch(self) -> list[Job]:
        app_id = self.secrets.get("adzuna_app_id")
        app_key = self.secrets.get("adzuna_app_key")
        if not app_id or not app_key:
            return []
        country = self.config.get("country", "us")
        results = self.config.get("results", 50)
        keywords = " ".join(self.config.get("keywords", []) or [])

        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": min(results, 50),
            "what": keywords or "software engineer",
            "content-type": "application/json",
        }
        try:
            r = self._get(BASE.format(country=country), params=params)
            if r.status_code != 200:
                return []
            data = r.json()
        except Exception:
            return []

        jobs: list[Job] = []
        for item in data.get("results", []):
            loc = (item.get("location") or {}).get("display_name", "")
            jobs.append(Job(
                source=self.name,
                source_job_id=str(item.get("id")),
                title=item.get("title", ""),
                company=(item.get("company") or {}).get("display_name", ""),
                location=loc,
                remote="remote" in loc.lower(),
                url=item.get("redirect_url", ""),
                description=item.get("description", ""),
                posted_at=(item.get("created") or "")[:10] or None,
            ))
        return jobs
