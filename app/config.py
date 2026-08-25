"""Load config.yaml + environment for secrets. No external deps beyond pyyaml."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


DEFAULT_CONFIG = {
    "filters": {
        "role_keywords": ["software engineer", "backend", "data"],
        "title_only": True,
        "exclude_title_terms": ["manager", "director", "principal", "staff", "lead",
                                "senior", "sr.", "vp", "head of", "president",
                                "architect", "ii", "iii", "iv"],
        "job_level": {"require_entry_level": False},
        "job_type": {"blocked": ["intern", "internship", "co-op", "contract",
                                 "part-time", "temporary", "seasonal", "apprentice"]},
        "location": {
            "remote_ok": True,
            "allowed_countries": ["United States"],
            "blocked_countries": ["India", "Poland", "Vietnam", "Pakistan",
                                  "Philippines", "China", "Singapore", "Canada"],
            "allowed_locations": [],
            "allow_unknown_locations": True,
        },
        "earliest_start": "2027-05-01",
    },
    "sources": {
        "greenhouse": {"enabled": True, "companies": ["stripe", "airbnb"]},
        "lever": {"enabled": True, "companies": ["netflix"]},
        "ashby": {"enabled": True, "companies": []},
        "github_repo": {
            "enabled": True,
            "repos": ["SimplifyJobs/New-Grad-Positions"],
        },
        "adzuna": {"enabled": False, "country": "us", "results": 50},
    },
    "resume_path": "sample/resume.txt",
    "notify": {"channel": "none"},   # none | telegram | slack
}


def load_config() -> dict:
    _load_dotenv()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        user = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        cfg = _deep_merge(cfg, user)
    # secrets always come from env
    cfg["secrets"] = {
        "adzuna_app_id": os.environ.get("ADZUNA_APP_ID", ""),
        "adzuna_app_key": os.environ.get("ADZUNA_APP_KEY", ""),
        "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "slack_webhook_url": os.environ.get("SLACK_WEBHOOK_URL", ""),
        "github_token": os.environ.get("GITHUB_TOKEN", ""),
    }
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
