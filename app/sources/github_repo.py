"""Parse community job-tracker repos.

Each entry in `repos:` can be either:

  1. "owner/repo"                              → whole repo. Tries the
     SimplifyJobs-style .github/scripts/listings.json feed first, then falls
     back to parsing the README's markdown table.

  2. "owner/repo/blob/<branch>/<path.md>"      → one exact markdown file on a
     specific branch. Useful for region-specific lists, e.g.
       speedyapply/2027-SWE-College-Jobs/blob/main/NEW_GRAD_INTL.md
       vanshb03/New-Grad-2027/blob/dev/Canada.md
     A leading https://github.com/ (or the raw host URL) is accepted too.

Everything is fetched from public endpoints (GitHub API + raw host), no scraping.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone

from .base import Source
from ..models import Job

README_API = "https://api.github.com/repos/{repo}/readme"
RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"
LISTINGS_PATH = ".github/scripts/listings.json"
BRANCHES = ("main", "master")

LINK_MD = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HREF = re.compile(r'href="([^"]+)"', re.I)
YEAR = re.compile(r"20\d{2}")
# owner/repo/blob/<branch>/<path>, tolerant of github.com / raw host prefixes
BLOB = re.compile(
    r"^(?:https?://)?(?:github\.com/|raw\.githubusercontent\.com/)?"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:blob/|raw/)?(?P<branch>[^/]+)/(?P<path>.+\.md)$",
    re.I,
)


class GithubRepoSource(Source):
    name = "github_repo"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        cap = int(self.config.get("max_per_repo", 300))
        for entry in self.config.get("repos", []):
            owner_repo, branch, path = self._parse_entry(entry)
            if path:  # exact markdown file
                jobs.extend(self._from_markdown_file(owner_repo, branch, path, cap))
                continue
            feed = self._fetch_listings_json(owner_repo)
            if feed is not None:
                jobs.extend(self._from_listings(feed, owner_repo, cap))
            else:
                jobs.extend(self._from_markdown(owner_repo, cap))
        return jobs

    @staticmethod
    def _parse_entry(entry: str):
        """→ (owner/repo, branch|None, path|None). path is set only for files.

        A plain "owner/repo" has too few segments to match BLOB, so it falls
        through to the repo form. Anything ending in .md with a branch and path
        is treated as an exact file.
        """
        m = BLOB.match(entry.strip())
        if m:
            return f"{m.group('owner')}/{m.group('repo')}", m.group("branch"), m.group("path")
        return entry.strip(), None, None

    # ---- strategy 1: structured JSON feed ----
    def _fetch_listings_json(self, repo: str):
        for branch in BRANCHES:
            url = RAW.format(repo=repo, branch=branch, path=LISTINGS_PATH)
            try:
                r = self._get(url)
                if r.status_code == 200 and r.text.lstrip().startswith("["):
                    data = json.loads(r.text)
                    if data and isinstance(data, list) and "company_name" in data[0]:
                        return data
            except Exception:
                continue
        return None

    def _from_listings(self, data: list, repo: str, cap: int) -> list[Job]:
        active = [x for x in data if x.get("active") and x.get("is_visible")]
        active.sort(key=lambda x: x.get("date_posted", 0), reverse=True)
        jobs = []
        for x in active[:cap]:
            locs = x.get("locations") or []
            loc = ", ".join(locs) if isinstance(locs, list) else str(locs)
            posted = x.get("date_posted")
            posted_iso = None
            if isinstance(posted, (int, float)):
                posted_iso = datetime.fromtimestamp(posted, timezone.utc).date().isoformat()
            spons = x.get("sponsorship", "")
            degrees = ", ".join(x.get("degrees") or [])
            jobs.append(Job(
                source=self.name,
                source_job_id=str(x.get("id") or f"{repo}:{x.get('company_name')}:{x.get('title')}"),
                title=x.get("title", ""),
                company=x.get("company_name", ""),
                location=loc,
                remote="remote" in loc.lower(),
                url=x.get("url", "") or f"https://github.com/{repo}",
                description=(f"{x.get('title','')} at {x.get('company_name','')}. "
                             f"Category: {x.get('category','')}. Locations: {loc}. "
                             f"Sponsorship: {spons}. Degrees: {degrees}. "
                             f"Source: {repo} (community tracker)."),
                posted_at=posted_iso,
            ))
        return jobs

    # ---- strategy 2: markdown table (README or a specific file) ----
    def _fetch_readme(self, repo: str) -> str | None:
        headers = {"Accept": "application/vnd.github+json"}
        token = self.secrets.get("github_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            r = self._get(README_API.format(repo=repo), headers=headers)
            if r.status_code == 200:
                return base64.b64decode(r.json().get("content", "")).decode("utf-8", "ignore")
        except Exception:
            pass
        for branch in BRANCHES:
            try:
                r = self._get(RAW.format(repo=repo, branch=branch, path="README.md"))
                if r.status_code == 200:
                    return r.text
            except Exception:
                continue
        return None

    def _fetch_file(self, repo: str, branch: str, path: str) -> str | None:
        # try the requested branch first, then the usual defaults
        for br in [branch] + [b for b in BRANCHES if b != branch]:
            try:
                r = self._get(RAW.format(repo=repo, branch=br, path=path))
                if r.status_code == 200 and r.text.strip():
                    return r.text
            except Exception:
                continue
        return None

    def _from_markdown(self, repo: str, cap: int) -> list[Job]:
        md = self._fetch_readme(repo)
        if not md:
            return []
        year = int(YEAR.search(repo).group()) if YEAR.search(repo) else None
        return self._parse_table(md, label=repo, url_fallback=f"https://github.com/{repo}",
                                 id_prefix=repo, year_hint=year, cap=cap)

    def _from_markdown_file(self, repo: str, branch: str, path: str, cap: int) -> list[Job]:
        md = self._fetch_file(repo, branch, path)
        if not md:
            return []
        text = f"{repo} {path}"
        year = int(YEAR.search(text).group()) if YEAR.search(text) else None
        blob = f"https://github.com/{repo}/blob/{branch}/{path}"
        return self._parse_table(md, label=f"{repo}/{path}", url_fallback=blob,
                                 id_prefix=f"{repo}/{path}", year_hint=year, cap=cap)

    def _parse_table(self, markdown: str, label: str, url_fallback: str,
                     id_prefix: str, year_hint: int | None, cap: int) -> list[Job]:
        jobs: list[Job] = []
        last_company = ""
        col: dict = {}
        for line in markdown.splitlines():
            if not line.strip().startswith("|"):
                col = {}
                continue
            cells = line.strip().strip("|").split("|")
            if len(cells) < 3:
                continue
            header = [self._clean(c).lower() for c in cells]
            if not col and any("company" in h for h in header):
                for i, h in enumerate(header):
                    if "company" in h:
                        col["company"] = i
                    elif any(k in h for k in ("role", "position", "title", "job")):
                        col["role"] = i
                    elif "location" in h:
                        col["location"] = i
                    elif any(k in h for k in ("link", "application", "apply", "posting")):
                        col["link"] = i
                    elif "date" in h or "age" in h:
                        col["date"] = i
                continue
            if not col:
                continue
            if set(self._clean(c) for c in cells) <= {"", "-", "---", "-----", ":---:", ":---"}:
                continue

            def cell(key):
                i = col.get(key)
                return cells[i] if i is not None and i < len(cells) else ""

            company = self._clean(cell("company"))
            if company in {"↳", "->", "»", ""}:
                company = last_company
            else:
                last_company = company
            role = self._clean(cell("role"))
            if not role or not company:
                continue
            location = self._clean(cell("location"))
            url = self._first_url(cell("link")) or self._first_url(cell("company"))
            ym = YEAR.search(f"{role} {self._clean(cell('date'))}")
            year = int(ym.group()) if ym else year_hint
            jobs.append(Job(
                source=self.name,
                source_job_id=f"{id_prefix}:{company}:{role}:{location}"[:200],
                title=role, company=company, location=location,
                remote="remote" in location.lower(),
                url=url or url_fallback,
                description=f"{role} at {company}. Location: {location}. Source: {label}.",
                start_year=year,
            ))
            if len(jobs) >= cap:
                break
        return jobs

    @staticmethod
    def _clean(cell: str) -> str:
        cell = cell.strip()
        m = LINK_MD.search(cell)
        if m:
            cell = m.group(1)
        cell = re.sub(r"[*_`]", "", cell)
        cell = re.sub(r"</?(details|summary|br)[^>]*>", " ", cell, flags=re.I)
        return re.sub(r"<[^>]+>", "", cell).strip().strip("|").strip()

    @staticmethod
    def _first_url(cell: str) -> str:
        h = HREF.search(cell)
        if h:
            return h.group(1)
        m = LINK_MD.search(cell)
        return m.group(2) if m else ""
