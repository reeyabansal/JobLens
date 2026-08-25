"""Read resume text from .txt / .md / .pdf / .docx."""
from __future__ import annotations

from pathlib import Path


def read_resume(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"resume not found: {p}")
    ext = p.suffix.lower()
    if ext in {".txt", ".md"}:
        return p.read_text(encoding="utf-8", errors="ignore")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if ext == ".docx":
        import docx
        d = docx.Document(str(p))
        return "\n".join(par.text for par in d.paragraphs)
    raise ValueError(f"unsupported resume format: {ext} (use txt/md/pdf/docx)")
