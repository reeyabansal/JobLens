"""Send new-job alerts to Telegram or Slack. Each message carries the DB id."""
from __future__ import annotations

import requests


def _format(job: dict, dashboard_url: str) -> str:
    loc = job.get("location") or ("Remote" if job.get("remote") else "—")
    start = job.get("start_date") or job.get("start_year") or "n/a"
    return (
        f"🆕 {job['title']} — {job['company']}\n"
        f"📍 {loc}   🗓 start: {start}\n"
        f"🔗 {job.get('url','')}\n"
        f"id: {job['id']}\n"
        f"open: {dashboard_url}/#/job/{job['id']}"
    )


def send(job: dict, cfg: dict) -> bool:
    channel = cfg.get("notify", {}).get("channel", "none")
    secrets = cfg.get("secrets", {})
    dash = cfg.get("notify", {}).get("dashboard_url", "http://localhost:8000")
    text = _format(job, dash)

    if channel == "telegram":
        token = secrets.get("telegram_bot_token")
        chat_id = secrets.get("telegram_chat_id")
        if not token or not chat_id:
            return False
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        return r.status_code == 200

    if channel == "slack":
        url = secrets.get("slack_webhook_url")
        if not url:
            return False
        r = requests.post(url, json={"text": text}, timeout=15)
        return r.status_code == 200

    return False  # channel 'none'
