"""Deep-dive resume tailoring via Google Gemini (LangChain).

Given the JD, the resume, and the deterministic gap list, ask Gemini for
concrete, ATS-maximizing edits — specific before/after rewrites tied to real
experience, plus honest flags for genuine gaps.

Enable it with:
    pip install "langchain-google-genai>=2.0"
    export GEMINI_API_KEY=...          # or GOOGLE_API_KEY
Optionally set GEMINI_MODEL (default: gemini-2.5-flash). Model names change
over time — set this to whatever is current for your account if the default
isn't available.
"""
from __future__ import annotations

import os

SYSTEM = (
    "You are an expert technical resume coach and ATS optimization specialist. "
    "You help candidates rewrite resume bullets to pass ATS keyword screening "
    "and win interviews, WITHOUT ever inventing experience."
)

RULES = """Hard rules:
- Only use experience the candidate genuinely has. Never invent skills, tools, employers, dates, or metrics.
- If a required keyword can't be added truthfully, say so plainly and mark it a REAL GAP.
- Keep phrasing ATS-parseable: plain text, standard section names, no tables or graphics.
- Match the job's exact terminology where truthful (e.g. write "CI/CD" if the JD does)."""

TASK = """Produce, in markdown:
1. **Priority edits** — for each high-impact missing keyword that CAN be added truthfully,
   give the exact resume bullet BEFORE and a rewritten AFTER, and name the section it's in.
2. **Real gaps** — keywords the candidate genuinely lacks; do not fake these.
3. **Quick wins** — small wording/format changes that raise ATS parse-ability.
Keep it concise and specific. Prefer editing existing bullets over adding new ones."""


def available() -> bool:
    try:
        import langchain_google_genai  # noqa: F401
        return bool(_api_key())
    except Exception:
        return False


def _api_key() -> str:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


def _gaps_block(analysis: dict) -> str:
    lines = []
    for m in (analysis.get("missing_keywords") or [])[:20]:
        tag = " [required]" if m.get("in_requirements") else ""
        near = "; ".join(s["bullet"][:80] for s in (m.get("spots") or [])[:2])
        lines.append(f"- {m['keyword']}{tag}" + (f"  (nearest bullets: {near})" if near else ""))
    return "\n".join(lines) or "(none detected)"


def deep_dive(resume_text: str, jd_text: str, analysis: dict,
              job: dict | None = None) -> dict:
    """Return {ok, provider, model, markdown} or {ok:False, error, hint}."""
    if not _api_key():
        return {"ok": False, "error": "no_api_key",
                "hint": "Set GEMINI_API_KEY (or GOOGLE_API_KEY) in your .env to enable the Gemini deep dive."}
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
    except Exception:
        return {"ok": False, "error": "not_installed",
                "hint": 'Run: pip install "langchain-google-genai>=2.0"'}

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    matched = ", ".join(analysis.get("matched_keywords", [])) or "(none)"
    role = f"{(job or {}).get('title','')} at {(job or {}).get('company','')}".strip(" at")

    human = f"""{RULES}

ROLE: {role}
DETERMINISTIC ATS SCORE: {round(analysis.get('score', 0))}%  |  required keywords covered: {analysis.get('required_matched',0)}/{analysis.get('required_total',0)}

JOB DESCRIPTION:
{jd_text.strip()}

ALREADY COVERED (don't re-add): {matched}

MISSING KEYWORDS (ranked, from my keyword tool):
{_gaps_block(analysis)}

MY RESUME:
{resume_text.strip()}

{TASK}"""

    try:
        llm = ChatGoogleGenerativeAI(model=model, temperature=0.2, api_key=_api_key())
        resp = llm.invoke([SystemMessage(content=SYSTEM), HumanMessage(content=human)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        return {"ok": True, "provider": "gemini", "model": model, "markdown": text}
    except Exception as e:
        return {"ok": False, "error": "call_failed", "hint": f"{type(e).__name__}: {e}",
                "model": model}
