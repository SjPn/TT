"""Optional outbound notifications. No-op when not configured — zero server load."""

from __future__ import annotations

import json
import logging
import smtplib
import threading
import urllib.error
import urllib.request
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger("tasktracker.notify")


def _configured() -> bool:
    email_ok = bool(settings.smtp_host and settings.smtp_from)
    tg_ok = bool(settings.telegram_bot_token and settings.telegram_chat_id)
    return email_ok or tg_ok


def _send_email(to_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_from or not to_email:
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=4) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except Exception:
        logger.exception("email notify failed")


def _send_telegram(text: str) -> None:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        return
    try:
        payload = json.dumps(
            {"chat_id": chat_id, "text": text[:3500], "disable_web_page_preview": True}
        ).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.exception("telegram notify failed")


def push_external(*, email: str | None, title: str, body: str, link: str = "") -> None:
    if not _configured():
        return

    text = title if not body else f"{title}\n{body}"
    if link:
        base = (settings.public_base_url or "").rstrip("/")
        text = f"{text}\n{base}{link}" if base else f"{text}\n{link}"

    def _run() -> None:
        if email:
            _send_email(email, title, text)
        _send_telegram(text)

    threading.Thread(target=_run, daemon=True).start()
