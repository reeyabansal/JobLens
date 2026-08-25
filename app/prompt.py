"""Assemble the ready-to-paste Claude prompt. Pure string work, no AI call."""
from __future__ import annotations

RULES = """Hard rules:
- Only surface experience I genuinely have. Never invent skills, tools, employers, dates, or metrics.
- If a required keyword can't be added truthfully, say so explicitly instead of forcing it.
- Keep phrasing ATS-parseable: plain text, standard section names, no tables or graphics.
- Match the job's terminology exactly where it's truthful (e.g. write "CI/CD" if the JD does).
"""

TASK = """For each missing keyword: tell me whether I can add it truthfully, and if so give
me the exact before/after for the specific bullet, plus which resume location.
Flag anything I genuinely lack so I know it's a real gap, not a wording gap."""


def build_prompt(job: dict, analysis: dict, resume: str = "",
                 include_resume: bool = True, include_rules: bool = True) -> str:
    """Build the tailoring prompt.

    Set include_resume=False / include_rules=False when pasting into a Claude
    Project that already holds the resume and rules as knowledge/instructions.
    """
    matched = ", ".join(analysis.get("matched_keywords", [])) or "(none detected)"

    missing_lines = []
    spot_lines = []
    for m in analysis.get("missing_keywords", []):
        tag = " [required]" if m.get("in_requirements") else ""
        missing_lines.append(f"- {m['keyword']}{tag}")
        spots = m.get("spots", [])
        if spots:
            near = "; ".join(f'"{s["bullet"][:90]}"' for s in spots[:2])
            spot_lines.append(f"- {m['keyword']} -> nearest bullets: {near}")
    missing_block = "\n".join(missing_lines) or "(none — strong keyword coverage)"
    spot_block = "\n".join(spot_lines) or "(no close bullets found — may be a genuine gap)"

    parts = [
        "You are helping me tailor my resume to pass ATS screening and get an interview.",
        "",
    ]
    if include_rules:
        parts += [RULES, ""]
    parts += [
        f"ROLE: {job.get('title','')} at {job.get('company','')}",
        f"ATS match score (my tool): {round(analysis.get('score', 0))}%",
        "",
        "JOB DESCRIPTION:",
        (job.get("description") or "").strip(),
        "",
        f"ALREADY COVERED (don't re-add): {matched}",
        "",
        "MISSING KEYWORDS (ranked by importance):",
        missing_block,
        "",
        "LIKELY SPOTS TO UPDATE (my tool's guess — keyword -> nearest existing bullets):",
        spot_block,
        "",
    ]
    if include_resume and resume.strip():
        parts += ["MY RESUME:", resume.strip(), ""]
    parts += [TASK]
    return "\n".join(parts)
