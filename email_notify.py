# -*- coding: utf-8 -*-
"""Почтовые уведомления: номера телефонов, заявки на звонок, диалоги."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _split_addrs(raw: str) -> List[str]:
    out: List[str] = []
    for part in (raw or "").replace(";", ",").split(","):
        addr = part.strip()
        if addr and "@" in addr:
            out.append(addr)
    return out


def alert_recipients(topic: Optional[str] = None) -> List[str]:
    main = _split_addrs(os.getenv("ALERT_EMAIL_TO") or os.getenv("SMTP_TO") or "")
    if topic == "bullying":
        extra = _split_addrs(os.getenv("BULLYING_ALERT_EMAIL_TO") or "")
        if extra:
            return list(dict.fromkeys(extra + main))
    return main


def email_enabled() -> bool:
    if not alert_recipients():
        return False
    host = (os.getenv("SMTP_HOST") or "").strip()
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    return bool(host and user and password)


def _smtp_from() -> str:
    return (
        (os.getenv("SMTP_FROM") or "").strip()
        or (os.getenv("SMTP_USER") or "").strip()
    )


def send_email(
    subject: str,
    body: str,
    *,
    to: Optional[List[str]] = None,
    attachment: Optional[bytes] = None,
    filename: Optional[str] = None,
) -> bool:
    recipients = to or alert_recipients()
    if not recipients:
        return False

    host = (os.getenv("SMTP_HOST") or "smtp.yandex.com").strip()
    port = int((os.getenv("SMTP_PORT") or "465").strip())
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    use_ssl = (os.getenv("SMTP_SSL") or "1").strip().lower() in ("1", "true", "yes")
    use_tls = (os.getenv("SMTP_USE_TLS") or "").strip().lower() in ("1", "true", "yes")

    if not (host and user and password):
        logger.warning("SMTP not configured (SMTP_HOST/USER/PASSWORD)")
        return False

    from_addr = _smtp_from()
    domain = from_addr.split("@")[-1] if "@" in from_addr else "localhost"

    msg = MIMEMultipart()
    msg["Subject"] = subject[:200]
    msg["From"] = formataddr(("Красная кнопка (бот)", from_addr))
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.attach(MIMEText(body or "", "plain", "utf-8"))

    if attachment and filename:
        part = MIMEApplication(attachment, Name=filename)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    try:
        if use_ssl and port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as smtp:
                smtp.login(user, password)
                smtp.sendmail(_smtp_from(), recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=60) as smtp:
                if use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                smtp.login(user, password)
                smtp.sendmail(_smtp_from(), recipients, msg.as_string())
        logger.info("Email sent: %s -> %s", subject, recipients)
        return True
    except Exception:
        logger.exception("Email send failed: %s", subject)
        return False


def _user_block(user: Dict[str, Any], platform: str = "") -> str:
    username = user.get("username") or ""
    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    full_name = f"{first_name} {last_name}".strip()
    uid = user.get("id") or user.get("user_id")
    lines = [
        f"user_id: {uid}",
        f"username: @{username}" if username else "username: -",
        f"name: {full_name or '-'}",
    ]
    if platform:
        lines.append(f"platform: {platform}")
    return "\n".join(lines)


def notify_phone_email(
    user: Dict[str, Any],
    phone_number: str,
    topic: Optional[str] = None,
    platform: str = "",
) -> bool:
    body = (
        "Пользователь оставил номер телефона (Красная кнопка)\n\n"
        f"{_user_block(user, platform)}\n"
        f"phone: {phone_number}\n"
        f"topic: {topic or '-'}\n"
    )
    return send_email(
        subject="[Красная кнопка] Номер телефона",
        body=body,
        to=alert_recipients(topic),
    )


def notify_callback_email(
    user: Dict[str, Any],
    topic: Optional[str] = None,
    platform: str = "",
    note: str = "",
) -> bool:
    body = (
        "Заявка на обратный звонок (Красная кнопка)\n\n"
        f"{_user_block(user, platform)}\n"
        f"topic: {topic or '-'}\n"
    )
    if note:
        body += f"\n{note}\n"
    return send_email(
        subject="[Красная кнопка] Заявка на звонок",
        body=body,
        to=alert_recipients(topic),
    )


def notify_dialog_email(
    user: Dict[str, Any],
    caption: str,
    transcript: bytes,
    filename: str,
    topic: Optional[str] = None,
) -> bool:
    body = caption + "\n\nТранскрипт во вложении."
    uid = user.get("id") or user.get("user_id")
    return send_email(
        subject=f"[Красная кнопка] Диалог {uid}",
        body=body,
        to=alert_recipients(topic),
        attachment=transcript,
        filename=filename,
    )
