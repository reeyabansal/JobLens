"""Infer start dates and apply the user's filters.

Most postings don't state a start date, so inference is best-effort and the
date filter only *drops* a job when it can prove the start is too early — it
keeps anything unknown rather than over-filtering.
"""
from __future__ import annotations

import re
from datetime import date

from .models import Job
from .geo import infer_country, is_remote

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
SEASONS = {"spring": 4, "summer": 6, "fall": 9, "autumn": 9, "winter": 1}
YEAR = re.compile(r"\b(20\d{2})\b")


def infer_start(job: Job) -> Job:
    """Fill start_year / start_date from title + description when possible."""
    text = f"{job.title}\n{job.description}".lower()
    if job.start_year:
        return _finalize(job)

    # "May 2027", "Summer 2027", "Fall 2026", "start date: 2027"
    m = re.search(r"(" + "|".join(MONTHS) + r")\s+(20\d{2})", text)
    if m:
        job.start_year = int(m.group(2))
        job.start_date = f"{job.start_year}-{MONTHS[m.group(1)]:02d}-01"
        return _finalize(job)

    m = re.search(r"(" + "|".join(SEASONS) + r")\s+(20\d{2})", text)
    if m:
        job.start_year = int(m.group(2))
        job.start_date = f"{job.start_year}-{SEASONS[m.group(1)]:02d}-01"
        return _finalize(job)

    m = re.search(r"(start|begin|commenc)\w*[^.\n]{0,30}?(20\d{2})", text)
    if m:
        job.start_year = int(m.group(2))
        return _finalize(job)

    # graduation-year language often implies start of that year's grad season
    m = re.search(r"(class of|graduat\w+ in|grad(?:uating)? )\s*(20\d{2})", text)
    if m:
        job.start_year = int(m.group(2))
    return _finalize(job)


def _finalize(job: Job) -> Job:
    if job.start_year and not job.start_date:
        job.start_date = f"{job.start_year}-01-01"
    return job


def _term_in(text: str, term: str) -> bool:
    """Multi-word term -> substring; single word -> word boundary.

    So 'lead' won't match 'leading' and 'data' won't match 'database', but
    'engineering manager' still matches as a phrase.
    """
    term = term.lower().strip()
    if not term:
        return False
    if " " in term:
        return term in text
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def _matches_any(text: str, terms: list[str]) -> bool:
    return any(_term_in(text, t) for t in terms)


# ── Structured, sectioned filtering ────────────────────────────────────────
# Each section returns a human-readable reason string when it REJECTS a job,
# or None when the job passes that section. passes_filters() = no reason.
# Config keys (with backward-compatible fallbacks to the old flat schema):
#
# filters:
#   role_keywords / keywords         role terms that must appear (title by default)
#   title_only                       match role terms in the title only (default true)
#   exclude_title_terms / exclude_titles   seniority terms dropped from the title
#   job_level:
#     require_entry_level            if true, title must carry an entry-level signal
#     entry_signals                  what counts as entry-level
#   job_type:
#     blocked                        title terms that drop the posting (intern, contract…)
#   location:
#     remote_ok                      keep remote roles regardless of country
#     allowed_countries              keep only these (empty = any)
#     blocked_countries              always drop these
#     allowed_locations              extra substring allowances (cities, etc.)
#   earliest_start                   drop roles that PROVABLY start before this

DEFAULT_JOB_TYPE_BLOCKED = [
    "intern", "internship", "co-op", "co op", "coop", "contract", "contractor",
    "part-time", "part time", "temporary", "seasonal", "apprentice",
]
DEFAULT_ENTRY_SIGNALS = [
    "new grad", "new graduate", "graduate", "grad ", "junior", "jr ", "entry level",
    "entry-level", "associate", "university grad", "early career", "campus", "early talent",
]


def _get(filters: dict, *keys, default=None):
    for k in keys:
        if k in filters and filters[k] not in (None, ""):
            return filters[k]
    return default


def filter_reason(job: Job, filters: dict) -> str | None:
    title = (job.title or "").lower()
    desc = (job.description or "").lower()

    # 1) ROLE — the title (by default) must contain a wanted role term
    role_keywords = [k.lower() for k in _get(filters, "role_keywords", "keywords", default=[]) if k]
    if role_keywords:
        hay = title if filters.get("title_only", True) else f"{title} {desc}"
        if not _matches_any(hay, role_keywords):
            return "no role keyword in title"

    # 2) LEVEL — drop senior/managerial titles; optionally require entry-level
    exclude_terms = [e.lower() for e in _get(filters, "exclude_title_terms", "exclude_titles", default=[]) if e]
    if exclude_terms and _matches_any(title, exclude_terms):
        return f"excluded seniority term in title"

    level = filters.get("job_level", {}) or {}
    if level.get("require_entry_level"):
        signals = [s.lower() for s in level.get("entry_signals", DEFAULT_ENTRY_SIGNALS)]
        if not _matches_any(f"{title} {desc}", signals):
            return "no entry-level signal"

    # 3) TYPE — drop internships / contract / part-time unless allowed
    jtype = filters.get("job_type", {}) or {}
    blocked_types = [b.lower() for b in jtype.get("blocked", DEFAULT_JOB_TYPE_BLOCKED)]
    if blocked_types and _matches_any(title, blocked_types):
        return "blocked job type in title"

    # 4) LOCATION — country allow/deny with a remote escape hatch
    loc = filters.get("location", {}) or {}
    remote_ok = loc.get("remote_ok", filters.get("remote_ok", True))
    remote = is_remote(job.location, job.remote)
    country = infer_country(job.location)
    blocked_countries = {c.lower() for c in loc.get("blocked_countries", [])}
    allowed_countries = {c.lower() for c in loc.get("allowed_countries", [])}
    allowed_locations = [a.lower() for a in
                         loc.get("allowed_locations", filters.get("locations", [])) if a]

    if remote and remote_ok:
        pass  # remote roles are always allowed through the location gate
    else:
        if country and blocked_countries and country.lower() in blocked_countries:
            return f"blocked country: {country}"
        if allowed_countries:
            loc_low = (job.location or "").lower()
            allowed_hit = (country and country.lower() in allowed_countries) \
                or any(a in loc_low for a in allowed_locations if a)
            unknown_ok = country is None and loc.get("allow_unknown_locations", True)
            if not (allowed_hit or unknown_ok):
                return f"country not allowed: {country or job.location or 'unknown'}"

    # 5) START DATE — drop only when provably earlier than earliest_start
    earliest = filters.get("earliest_start")
    if earliest and job.start_year:
        try:
            if job.start_year < int(str(earliest)[:4]):
                return f"starts {job.start_year} (before {str(earliest)[:4]})"
        except ValueError:
            pass
    return None


def passes_filters(job: Job, filters: dict) -> bool:
    return filter_reason(job, filters) is None
