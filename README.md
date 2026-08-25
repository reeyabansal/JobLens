<!-- # JobLens

**See your resume through the job's eyes**

> A self-hosted job search and ATS gap analyzer that aggregates new job postings from multiple configurable sources based on keyword filters. All postings are stored in a local database, providing an interactive dashboard to track applications and their status.
The dashboard also allows users to compare their resume against individual job descriptions, generate an ATS compatibility score, and identify missing or relevant keywords. A deep-dive analysis powered by the Gemini LLM provides targeted recommendations, including potential resume substitutions and improvements designed to increase the overall ATS score and better align the resume with the job posting. -->

# JobLens

**See your resume through the job's eyes.**

> A self-hosted job search and ATS gap analyzer for discovering, tracking, and evaluating job applications.

JobLens aggregates new job postings from multiple configurable sources based on keyword filters. All postings are stored in a local database and surfaced through an interactive dashboard for tracking applications and their status.

For each job, JobLens compares your resume against the job description, generates an ATS compatibility score, and identifies missing and relevant keywords. A deep-dive analysis powered by the Gemini LLM provides targeted recommendations, including potential resume substitutions and improvements to better align the resume with the job posting.

---

## What it does
- *Ingest* job postings from company-specific ATS boards, community trackers, and the Adzuna API using legitimate endpoints—no scraping.
- *Filter* opportunities by keywords, posting/start date, and location.
- *Store* all job data in a local SQLite database with application status tracking for each posting.
- *Notify* users of new job postings through Telegram or Slack.
- *Analyze* individual jobs from the dashboard to generate an ATS match score, identify matched keywords, and rank missing or relevant keywords.
- *Deep Dive* into a job using an LLM API call to Gemini to generate targeted recommendations for improving the resume and increasing its ATS match score.

## Dashboard Features
- Add a Job
- Delete a Job
- Analyze ATS Match Score
- Prune Stale Jobs
- Deep Dive
- Re-run Ingestion to pull new on command

---

## Quick Start
```bash
cd jobhunt
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example.env

python ingest.py
python run.py
```

Update `resume_path` in `config.yaml` to your resume. 

---

## Configuration (`config.yaml`)

```yaml
filters:
  keywords: ["analyst", "finance"]
  title_only: true                # match role keywords in the TITLE 
  exclude_titles: ["manager", "director", "principal", "staff", "lead",
                   "senior", "vp", "head of", "architect", "ii", "iii"] # configured for new grad roles
  earliest_start: "2027-05-01"
  remote_ok: true
  locations: []                   # empty = anywhere

sources:
  greenhouse: { enabled: true, companies: ["stripe", "airbnb"] }
  lever:      { enabled: true, companies: ["netflix"] }
  ashby:      { enabled: false, companies: [] }
  github_repo:
    enabled: true
    repos: ["SimplifyJobs/New-Grad-Positions"]
  adzuna:     { enabled: false, country: "us", results: 50 }
```

## Output

- **Match score** with usual ATS bands:
    - under 40 tends to get filtered out
    - 40-60 is borderline
    - 60+ usually passes keyword screening
- **Required Coverage** count and a badge showing whether the analysis ran on the full listing or just a summary of it
- **Already Covered** includes keywords in both the job description and user resume 
- **Ranked Missing Keywords covers** and ranks keywords missing from resume in requirement order

---

## Running it on a schedule

```bash
python schedule.py     # ingests now, then every 6 hours (edit INTERVAL_HOURS)
```

Run it beside `python run.py`. On a server, put each under a process manager (systemd, pm2, supervisor) or wrap ingestion in a cron job.

---

## Directory Structure

### Ingestion & data
- `app/sources/` — one adapter per source (Greenhouse, Lever, Ashby, Adzuna,
  and the GitHub tracker parser), all returning the same `Job` shape via
  `base.py`. `github_repo.py` reads either a whole repo (JSON feed → README
  table) or an exact `blob/<branch>/<file>.md` path.
- `app/models.py` — the `Job` dataclass and the shared status list.
- `app/normalize.py` — start-date inference and the structured, sectioned
  filters (role / level / type / location / start date), each returning a
  human-readable reason when it drops a job.
- `app/geo.py` — infers a country from a free-text location (country names,
  US state / Canadian province codes, remote), powering the location filter.
- `app/ingest.py` — orchestrates a pass: fetch → infer → filter → dedup-insert
  → notify. One source failing never aborts the run.
- `app/jd_fetch.py` — best-effort full-JD fetch (Greenhouse/Lever JSON,
  schema.org JobPosting, then page text) so thin listings still score well.
- `app/db.py` — stdlib SQLite; dedups by source id and by
  company+title+location, tombstones deletes so they aren't re-ingested, and
  caches each job's analysis.

### Analysis
- `app/scoring.py` — the built-in deterministic analyzer: curated skills
  taxonomy + TF-IDF + fuzzy/alias matching, with required/preferred/core
  keyword sections and spot localization. No model downloads, no network.
- `app/ats_score.py` — optional richer scoring via the `ats-resume-scorer`
  library (keyword/title/education/experience/format/readability sub-scores +
  fix-ups). Degrades gracefully to the built-in scorer if it (or its spaCy
  model) isn't installed.
- `app/deepdive.py` — optional "Deep dive" via Google Gemini (LangChain):
  feeds the JD, resume, and gap list, returns concrete before/after edits.
  Returns a friendly hint if `GEMINI_API_KEY` or the package is missing.
- `app/prompt.py` — assembles the copy-paste Claude tailoring prompt.
- `app/resume.py` — reads the resume from txt / md / pdf / docx.

### App & delivery
- `app/config.py` — merges `config.yaml` with `.env` secrets; reports which
  optional capabilities (ATS scorer, Gemini) are available.
- `app/notify.py` — Telegram / Slack alerts, each carrying the DB id + deep link.
- `app/main.py` — FastAPI API (jobs CRUD, analyze, deep dive, prompt, ingest,
  prune) that also serves the dashboard, with a `no-store` header so the browser
  never caches the UI.
- `app/web/` — dependency-free dashboard (no build step, works offline).

---
## Adding a new source

Subclass `Source` in `app/sources/`, implement `fetch() -> list[Job]`, and
register it in `app/sources/__init__.py`. Return the shared `Job` dataclass and
the rest of the pipeline (filtering, dedup, storage, scoring) works unchanged.

## Two ways to analyze a job

Open a job and you get two buttons:

1. **Analyze score** — fast, free, offline. Runs the built-in keyword/skills
   engine (matched vs. missing *skills*, ranked, with likely resume spots) and a job description match score. If the optional `ats-resume-scorer` library is installed,
   it also shows a **Resume ATS audit**: keyword/title/education/experience/
   format/readability sub-scores plus formatting fix-ups. (That audit grades the resume's structure, which is distinct from the job description keyword match. Its parser is strict about section headers, so treat a low structure grade as "check my formatting", not "bad resume".)

2. **Deep dive ✨** — sends the job description, your resume, and the gap list to **Google Gemini** (via LangChain) and returns concrete before/after bullet rewrites, honest "real gap" flags, and quick wins. Requires `GEMINI_API_KEY` in `.env` and `pip install langchain-google-genai`. Set `GEMINI_MODEL` if the default isn't available on your account.

Enable the deep dive options:

```bash
pip install ats-resume-scorer && python -m spacy download en_core_web_sm   # richer score
pip install "langchain-google-genai>=2.0"                                  # deep dive
echo "GEMINI_API_KEY=..." >> .env
```

Both are optional — without them, **Analyze score** still works with the
built-in engine, and **Deep dive** shows a friendly hint on how to enable it.
