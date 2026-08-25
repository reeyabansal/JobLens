"""Fetch the full job description from a posting URL.

Tracker/aggregator sources only give a short summary, which makes the ATS
analysis weak. This pulls the real JD so scoring runs on the actual posting.

Strategy, best signal first:
  1. Known ATS (Greenhouse / Lever) -> their structured JSON endpoint.
  2. schema.org JobPosting JSON-LD embedded in the page (very common).
  3. Plain-text extraction from the page HTML.
Returns (text, source_label). source_label is "" when nothing usable was found.
"""
from __future__ import annotations

import html
import json
import re

import requests

UA = "jobhunt/1.0 (personal job search tool)"
GH_JOB = re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?]+).*?jobs/(\d+)", re.I)
GH_HOST = re.compile(r"(?:^|//)([^./]+)\.greenhouse\.io", re.I)
LEVER_JOB = re.compile(r"jobs\.lever\.co/([^/]+)/([0-9a-f\-]{36})", re.I)


def _strip_html(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _session(session=None) -> requests.Session:
    if session:
        return session
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def _greenhouse(url: str, s: requests.Session) -> str:
    m = GH_JOB.search(url)
    board = job_id = None
    if m:
        board, job_id = m.group(1), m.group(2)
    else:
        hm = GH_HOST.search(url)
        im = re.search(r"jobs/(\d+)", url)
        if hm and im:
            board, job_id = hm.group(1), im.group(1)
    if not (board and job_id):
        return ""
    api = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}?content=true"
    r = s.get(api, timeout=20)
    if r.status_code == 200:
        return _strip_html(r.json().get("content", ""))
    return ""


def _lever(url: str, s: requests.Session) -> str:
    m = LEVER_JOB.search(url)
    if not m:
        return ""
    api = f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}"
    r = s.get(api, timeout=20)
    if r.status_code == 200:
        d = r.json()
        return d.get("descriptionPlain") or _strip_html(d.get("description", ""))
    return ""


def _json_ld(page_html: str) -> str:
    """Pull description out of a schema.org JobPosting block if present."""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                         page_html, re.I | re.S):
        block = m.group(1).strip()
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for obj in (data if isinstance(data, list) else [data]):
            graph = obj.get("@graph", [obj]) if isinstance(obj, dict) else [obj]
            for node in graph:
                if isinstance(node, dict) and "JobPosting" in str(node.get("@type", "")):
                    desc = node.get("description", "")
                    if desc:
                        return _strip_html(desc)
    return ""


def fetch_full_jd(url: str, session=None) -> tuple[str, str]:
    if not url or not url.startswith("http"):
        return "", ""
    s = _session(session)
    try:
        if "greenhouse.io" in url:
            txt = _greenhouse(url, s)
            if len(txt) > 200:
                return txt, "greenhouse"
        if "lever.co" in url:
            txt = _lever(url, s)
            if len(txt) > 200:
                return txt, "lever"
        # generic: fetch page, try JSON-LD, then plain text
        r = s.get(url, timeout=20, headers={"Accept": "text/html"})
        if r.status_code != 200 or not r.text:
            return "", ""
        ld = _json_ld(r.text)
        if len(ld) > 200:
            return ld, "json-ld"
        txt = _strip_html(r.text)
        if len(txt) > 400:
            return txt, "html"
    except Exception:
        return "", ""
    return "", ""
