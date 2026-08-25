"""Deterministic ATS gap analyzer.

No LLM, no network, no model downloads. Produces, for a (resume, JD) pair:
  - matched_keywords     : JD skills/keywords already in the resume
  - missing_keywords     : ranked list of JD keywords absent from the resume
  - spots                : for each missing keyword, the resume bullets it fits best
  - score                : 0-100 ATS-style coverage score

Ranking uses JD frequency + whether the term sits in a requirements section.
Spot localization uses TF-IDF cosine similarity between the keyword's JD
context and each resume bullet. Fuzzy/alias matching catches near-misses
(k8s->kubernetes, postgres->postgresql, js->javascript, ...).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# --- curated tech skills taxonomy (multi-word aware) -----------------------
# Not exhaustive — it seeds recognition so real skills beat random nouns.
KNOWN_SKILLS = {
    # languages
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang",
    "rust", "ruby", "php", "scala", "kotlin", "swift", "r", "matlab", "sql",
    "bash", "shell", "perl", "objective-c", "dart", "elixir", "haskell",
    # web / frontend
    "react", "react native", "next.js", "vue", "vue.js", "angular", "svelte",
    "redux", "tailwind", "html", "css", "sass", "webpack", "vite", "graphql",
    "rest", "rest api", "restful", "grpc", "websocket",
    # backend / frameworks
    "node.js", "express", "django", "flask", "fastapi", "spring", "spring boot",
    ".net", "asp.net", "rails", "ruby on rails", "laravel", "nestjs",
    # data / ml
    "machine learning", "deep learning", "nlp", "computer vision", "pytorch",
    "tensorflow", "keras", "scikit-learn", "pandas", "numpy", "spark",
    "hadoop", "airflow", "kafka", "data pipeline", "etl", "data engineering",
    "llm", "transformers", "hugging face", "data analysis", "data science",
    # cloud / infra / devops
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "k8s",
    "terraform", "ansible", "jenkins", "ci/cd", "cicd", "github actions",
    "gitlab", "circleci", "linux", "unix", "nginx", "microservices",
    "serverless", "lambda", "ec2", "s3", "helm", "prometheus", "grafana",
    # databases
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch",
    "dynamodb", "cassandra", "sqlite", "snowflake", "bigquery", "redshift",
    # methods / other
    "agile", "scrum", "kanban", "tdd", "oop", "system design", "distributed systems",
    "git", "jira", "unit testing", "integration testing", "object oriented",
    "algorithms", "data structures", "api design", "concurrency",
}

# equivalences: writing one satisfies the other (checked both directions)
ALIASES = {
    "k8s": "kubernetes", "js": "javascript", "ts": "typescript",
    "postgres": "postgresql", "golang": "go", "cicd": "ci/cd",
    "ml": "machine learning", "gcp": "google cloud", "oop": "object oriented",
    "restful": "rest api", "rest": "rest api", "react.js": "react",
    "node": "node.js", "vuejs": "vue", "spring boot": "spring",
    "ruby on rails": "rails", "scikit-learn": "scikit learn",
}

STOPWORDS = set("""
a an the and or but if then else for while of to in on at by with from as is are
was were be been being do does did have has had you your we our they their he she
it its this that these those will would can could should may might must not no yes
about into over under out up down more most some any all each other such than too
very just also team teams work working experience years year role position job
company strong ability able across within including etc via using use used based
who whom which what when where why how our us who’s you’ll we’re
""".split())

REQ_MARKERS = re.compile(
    r"(requirement|require|must have|must-have|qualification|you have|"
    r"minimum|responsibilit|what you|we're looking|were looking|need to have)",
    re.I,
)
# "nice to have" style sections — missing these shouldn't tank the score
PREF_MARKERS = re.compile(
    r"(nice to have|nice-to-have|preferred|bonus|a plus|is a plus|"
    r"desired|good to have|pluses|would be great|ideally)",
    re.I,
)


@dataclass
class Spot:
    bullet_index: int
    bullet: str
    similarity: float


@dataclass
class MissingKeyword:
    keyword: str
    importance: float          # 0-1, higher = the JD leans on it harder
    in_requirements: bool
    section: str = "core"      # required | preferred | core
    spots: list[Spot] = field(default_factory=list)


@dataclass
class Analysis:
    score: float
    match_rate: float
    matched_keywords: list[str]
    missing_keywords: list[MissingKeyword]
    resume_bullets: list[str]
    required_total: int = 0
    required_matched: int = 0
    jd_source: str = "listing"   # "full posting" | "listing summary"

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "match_rate": round(self.match_rate, 1),
            "required_total": self.required_total,
            "required_matched": self.required_matched,
            "jd_source": self.jd_source,
            "matched_keywords": self.matched_keywords,
            "missing_keywords": [
                {
                    "keyword": m.keyword,
                    "importance": round(m.importance, 3),
                    "in_requirements": m.in_requirements,
                    "section": m.section,
                    "spots": [
                        {"bullet_index": s.bullet_index,
                         "bullet": s.bullet,
                         "similarity": round(s.similarity, 3)}
                        for s in m.spots
                    ],
                }
                for m in self.missing_keywords
            ],
            "resume_bullets": self.resume_bullets,
        }


# --- text helpers ----------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _canonical(term: str) -> str:
    t = term.lower().strip()
    return ALIASES.get(t, t)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;\n])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def _resume_bullets(resume: str) -> list[str]:
    """Split a resume into bullet-ish units for spot localization."""
    lines = [ln.strip(" \t•-*–>") for ln in resume.splitlines()]
    bullets = [ln for ln in lines if len(ln) >= 25]  # skip headers/short lines
    if len(bullets) < 3:  # fallback: sentence split
        bullets = [s for s in _sentences(resume) if len(s) >= 25]
    return bullets


# --- keyword extraction ----------------------------------------------------

# structural JD words that are never skills
STRUCTURE_WORDS = {
    "requirements", "requirement", "responsibilities", "responsibility",
    "qualifications", "qualification", "bonus", "plus", "nice", "preferred",
    "desired", "ideally", "must", "skills", "required", "experience",
    "minimum", "preferences", "role", "about", "overview", "benefits",
}
# individual words that appear inside multi-word known skills (e.g. "machine",
# "learning" from "machine learning") — reject them as standalone discovered terms
SKILL_WORDS = {w for s in KNOWN_SKILLS if " " in s for w in s.split()}


def _section_texts(jd: str) -> tuple[str, str]:
    """Assign lines to requirement / preferred sections by header blocks.

    A header line switches the active section; subsequent bullets/lines inherit
    it until the next header. This catches the common layout where the marker
    ("Requirements:") is a header and the skills are bullets beneath it.
    """
    # ordered segments: split on line breaks, then on sentence boundaries so
    # inline JDs ("Requirements: X. Nice to have: Y.") also segment correctly.
    segments: list[str] = []
    for raw in jd.splitlines():
        for seg in re.split(r"(?<=[.;:])\s+", raw.strip()):
            seg = seg.strip()
            if seg:
                segments.append(seg)

    req_lines: list[str] = []
    pref_lines: list[str] = []
    current = "core"
    for seg in segments:
        low = seg.lower()
        if PREF_MARKERS.search(low):
            current = "preferred"
        elif REQ_MARKERS.search(low):
            current = "required"
        elif seg.rstrip().endswith(":") and len(seg) <= 70:
            current = "core"   # a different header resets the section
        if current == "required":
            req_lines.append(low)
        elif current == "preferred":
            pref_lines.append(low)
    return " ".join(req_lines), " ".join(pref_lines)


def _extract_jd_keywords(jd: str) -> dict[str, dict]:
    """Return {canonical_keyword: {count, in_req, importance}}."""
    norm = _normalize(jd)
    req_text, pref_text = _section_texts(jd)

    found: dict[str, dict] = {}

    def _section(pattern: str) -> str:
        in_pref = bool(re.search(pattern, pref_text))
        in_req = bool(re.search(pattern, req_text))
        if in_pref and not in_req:
            return "preferred"
        if in_req:
            return "required"
        return "core"

    # 1) known multi-word + single skills
    for skill in KNOWN_SKILLS:
        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
        count = len(re.findall(pattern, norm))
        if count:
            canon = _canonical(skill)
            entry = found.setdefault(canon, {"count": 0, "in_req": False, "section": "core"})
            entry["count"] += count
            sec = _section(pattern)
            if sec == "required":
                entry["in_req"] = True
            # required wins over preferred wins over core
            if sec == "required" or (sec == "preferred" and entry["section"] == "core"):
                entry["section"] = sec

    # 2) TF-IDF salient unigrams/bigrams not already captured (domain terms)
    try:
        vec = TfidfVectorizer(
            ngram_range=(1, 2), stop_words="english", max_features=40,
            token_pattern=r"[a-zA-Z][a-zA-Z0-9\+\#\.\-]{1,}",
        )
        tfidf = vec.fit_transform([jd])
        scores = tfidf.toarray()[0]
        terms = vec.get_feature_names_out()
        ranked = sorted(zip(terms, scores), key=lambda x: -x[1])[:25]
        kept = 0
        for term, sc in ranked:
            if sc <= 0 or kept >= 12:
                continue
            term = term.strip(" .,-#+/").strip()      # drop punctuation artifacts
            toks = [t.strip(".,-") for t in term.split() if t.strip(".,-")]
            term = " ".join(toks)
            if not term:
                continue
            # reject stopwords, structure words, short tokens, or known-skill tokens
            if any(t in STOPWORDS or t in STRUCTURE_WORDS or len(t) < 3 for t in toks):
                continue
            if any(t in KNOWN_SKILLS or _canonical(t) in found for t in toks):
                continue
            # reject fragments of multi-word known skills (e.g. "machine", "learning")
            if all(t in SKILL_WORDS for t in toks):
                continue
            canon = _canonical(term)
            if canon in found or canon in KNOWN_SKILLS or term.isdigit():
                continue
            sec = "preferred" if (term in pref_text and term not in req_text) else \
                  ("required" if term in req_text else "core")
            found[canon] = {
                "count": norm.count(term),
                "in_req": term in req_text,
                "section": sec,
                "soft": True,  # discovered term, weighted lower than known skills
            }
            kept += 1
    except ValueError:
        pass

    # importance = normalized(count), boosted for requirements, discounted for
    # nice-to-haves so a missing "preferred" keyword doesn't tank the score.
    max_count = max((v["count"] for v in found.values()), default=1) or 1
    for v in found.values():
        base = 0.4 + 0.6 * (v["count"] / max_count)
        if v.get("soft"):
            base *= 0.6
        if v["section"] == "required":
            base = min(1.0, base + 0.25)
        elif v["section"] == "preferred":
            base *= 0.45
        v["importance"] = base
    return found


def _resume_terms(resume: str) -> set[str]:
    norm = _normalize(resume)
    terms: set[str] = set()
    for skill in KNOWN_SKILLS:
        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
        if re.search(pattern, norm):
            terms.add(_canonical(skill))
    # also raw word set for fuzzy checks
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\+\#\.\-]{1,}", norm):
        terms.add(_canonical(w))
    return terms


def _resume_has(keyword: str, resume_terms: set[str], resume_norm: str) -> bool:
    kw = _canonical(keyword)
    if kw in resume_terms:
        return True
    # multi-word phrase or reasonably long token → substring is safe
    if (" " in kw or len(kw) >= 4) and kw in resume_norm:
        return True
    # short single token (go, r, c#, k8s) → require a real word boundary,
    # otherwise "go" matches inside "algorithms", "r" matches everywhere, etc.
    if " " not in kw:
        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", resume_norm):
            return True
    # fuzzy: catch typos / minor variants against single tokens
    if len(kw) >= 5:
        for t in resume_terms:
            if len(t) >= 5 and fuzz.ratio(kw, t) >= 90:
                return True
    return False


# --- spot localization -----------------------------------------------------

def _keyword_context(jd: str, keyword: str) -> str:
    for s in _sentences(jd):
        if keyword.lower() in s.lower():
            return s
    return keyword


def _find_spots(keyword: str, context: str, bullets: list[str], vectorizer,
                bullet_matrix, top_k: int = 3) -> list[Spot]:
    if not bullets:
        return []
    q = vectorizer.transform([f"{keyword} {context}"])
    sims = cosine_similarity(q, bullet_matrix)[0]
    order = sims.argsort()[::-1][:top_k]
    spots = []
    for idx in order:
        if sims[idx] <= 0.01:
            continue
        spots.append(Spot(int(idx), bullets[idx], float(sims[idx])))
    return spots


# --- public entry point ----------------------------------------------------

def analyze(resume: str, jd: str) -> Analysis:
    resume = resume or ""
    jd = jd or ""
    bullets = _resume_bullets(resume)
    resume_terms = _resume_terms(resume)
    resume_norm = _normalize(resume)

    jd_keywords = _extract_jd_keywords(jd)

    # vectorizer over resume bullets for spot matching
    vectorizer = None
    bullet_matrix = None
    if bullets:
        try:
            vectorizer = TfidfVectorizer(stop_words="english",
                                         token_pattern=r"[a-zA-Z][a-zA-Z0-9\+\#\.\-]{1,}")
            bullet_matrix = vectorizer.fit_transform(bullets)
        except ValueError:
            vectorizer = None

    matched: list[str] = []
    missing: list[MissingKeyword] = []

    req_total = req_matched = 0
    for kw, meta in jd_keywords.items():
        is_required = meta.get("section") == "required"
        if is_required:
            req_total += 1
        if _resume_has(kw, resume_terms, resume_norm):
            matched.append(kw)
            if is_required:
                req_matched += 1
        else:
            mk = MissingKeyword(kw, meta["importance"], meta["in_req"],
                                section=meta.get("section", "core"))
            if vectorizer is not None:
                ctx = _keyword_context(jd, kw)
                mk.spots = _find_spots(kw, ctx, bullets, vectorizer, bullet_matrix)
            missing.append(mk)

    # rank: required first, then by importance
    order_rank = {"required": 0, "core": 1, "preferred": 2}
    missing.sort(key=lambda m: (order_rank.get(m.section, 1), -m.importance))
    matched.sort()

    # weighted coverage score
    total_w = sum(m["importance"] for m in jd_keywords.values()) or 1.0
    matched_w = sum(jd_keywords[k]["importance"] for k in matched)
    coverage = matched_w / total_w
    raw_rate = len(matched) / (len(jd_keywords) or 1)

    # semantic bonus: overall resume<->jd tf-idf similarity, small weight
    sem = 0.0
    try:
        v = TfidfVectorizer(stop_words="english")
        m = v.fit_transform([resume, jd])
        sem = float(cosine_similarity(m[0], m[1])[0][0])
    except ValueError:
        sem = 0.0

    score = 100.0 * (0.8 * coverage + 0.2 * sem)
    score = max(0.0, min(100.0, score))

    return Analysis(
        score=score,
        match_rate=100.0 * raw_rate,
        matched_keywords=matched,
        missing_keywords=missing,
        resume_bullets=bullets,
        required_total=req_total,
        required_matched=req_matched,
    )
