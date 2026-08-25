"""Optional richer ATS scoring via the `ats-resume-scorer` library.

If the library (and its spaCy model) are installed, this returns a
multi-factor report: keyword/title/education/experience/format/readability
sub-scores plus formatting recommendations. If not, callers fall back to the
built-in deterministic scorer in scoring.py.

Enable it with:
    pip install ats-resume-scorer
    python -m spacy download en_core_web_sm
"""
from __future__ import annotations

import logging
from pathlib import Path


def available() -> bool:
    try:
        import ats_resume_scorer  # noqa: F401
        import spacy  # noqa: F401
        return True
    except Exception:
        return False


def rich_score(resume_path: str | Path, jd_text: str) -> dict | None:
    """Return a trimmed ats-resume-scorer report, or None if unavailable/failed.

    Needs a resume FILE path (pdf/docx/txt); the library parses it itself.
    """
    try:
        # keep the library's chatty logging out of our output
        logging.getLogger("ats_resume_scorer").setLevel(logging.ERROR)
        from ats_resume_scorer.main import ATSResumeScorer
    except Exception:
        return None

    try:
        scorer = ATSResumeScorer()
        rep = scorer.score_resume(str(resume_path), jd_text, recommendation_level="normal")
    except Exception:
        return None

    jma = rep.get("job_match_analysis", {}) or {}
    return {
        "overall_score": rep.get("overall_score"),
        "grade": rep.get("grade"),
        "breakdown": rep.get("detailed_breakdown", {}),
        "recommendations": rep.get("recommendations", [])[:8],
        "detailed_recommendations": rep.get("detailed_recommendations", [])[:6],
        "improvement_potential": rep.get("improvement_potential", {}),
        "ats_compatibility": rep.get("ats_compatibility", {}),
        "matched_required_skills": jma.get("matched_required_skills", []),
        "missing_required_skills": jma.get("missing_required_skills", []),
        "matched_preferred_skills": jma.get("matched_preferred_skills", []),
        "missing_preferred_skills": jma.get("missing_preferred_skills", []),
        "resume_summary": rep.get("resume_summary", {}),
    }
