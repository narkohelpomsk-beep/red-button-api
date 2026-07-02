# -*- coding: utf-8 -*-
"""Почтовые уведомления: номера телефонов, заявки на звонок, диалоги."""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_ALERT_TO = "rc-impuls@yandex.ru"


def _split_addrs(raw: str) -> List[str]:
    out: List[str] = []
    for part in (raw or "").replace(";", ",").split(","):
        addr = part.strip()
        if addr and "@" in addr:
            out.append(addr)
    return out


def alert_recipients(topic: Optional[str] = None) -> List[str]:
    main = _split_addrs(
        os.getenv("ALERT_EMAIL_TO") or os.getenv("SMTP_TO") or DEFAULT_ALERT_TO
    )
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


def _build_message(
    subject: str,
    body: str,
    recipients: List[str],
    *,
    attachment: Optional[bytes] = None,
    filename: Optional[str] = None,
    simple_from: bool = False,
) -> MIMEMultipart | MIMEText:
    from_addr = _smtp_from()
    domain = from_addr.split("@")[-1] if "@" in from_addr else "yandex.ru"

    if attachment and filename:
        msg: MIMEMultipart | MIMEText = MIMEMultipart()
        msg.attach(MIMEText(body or "", "plain", "utf-8"))
        part = MIMEApplication(attachment, Name=filename)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
    else:
        msg = MIMEText(body or "", "plain", "utf-8")

    msg["Subject"] = Header(subject[:200], "utf-8")
    msg["From"] = from_addr if simple_from else from_addr
    msg["To"] = ", ".join(recipients)
    msg["Reply-To"] = from_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    return msg


def _smtp_send(msg: MIMEMultipart | MIMEText, recipients: List[str], timeout: int = 15) -> None:
    host = (os.getenv("SMTP_HOST") or "smtp.yandex.ru").strip()
    port = int((os.getenv("SMTP_PORT") or "465").strip())
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    use_ssl = (os.getenv("SMTP_SSL") or "1").strip().lower() in ("1", "true", "yes")
    use_tls = (os.getenv("SMTP_USE_TLS") or "").strip().lower() in ("1", "true", "yes")
    from_addr = _smtp_from()

    if use_ssl and port == 465:
        with smtplib.SMTP_SSL(
            host, port, context=ssl.create_default_context(), timeout=timeout
        ) as smtp:
            smtp.login(user, password)
            smtp.sendmail(from_addr, recipients, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, password)
            smtp.sendmail(from_addr, recipients, msg.as_string())


def send_email(
    subject: str,
    body: str,
    *,
    to: Optional[List[str]] = None,
    attachment: Optional[bytes] = None,
    filename: Optional[str] = None,
    phone_fast: bool = False,
) -> bool:
    recipients = to or alert_recipients()
    if not recipients:
        logger.warning("Email: no recipients")
        return False

    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    if not (user and password):
        logger.warning("SMTP not configured (SMTP_USER/SMTP_PASSWORD)")
        return False

    attempts = [(subject, body, False)]
    if phone_fast:
        attempts = [("Красная кнопка: номер телефона", body, True)]
    elif subject != "Red Button: phone":
        attempts.append(("Red Button: phone", body, True))

    smtp_timeout = 8 if phone_fast else 15

    last_err: Optional[Exception] = None
    for subj, text, simple in attempts:
        try:
            msg = _build_message(
                subj,
                text,
                recipients,
                attachment=attachment if not simple else None,
                filename=filename if not simple else None,
                simple_from=simple,
            )
            _smtp_send(msg, recipients, timeout=smtp_timeout)
            logger.info("Email sent: %s -> %s", subj, recipients)
            return True
        except smtplib.SMTPDataError as exc:
            last_err = exc
            code = int(getattr(exc, "smtp_code", 0) or 0)
            logger.warning("Email SMTPDataError (%s): %s -> %s", code, subj, recipients)
            if code != 554:
                break
        except Exception as exc:
            last_err = exc
            logger.exception("Email send failed: %s -> %s", subj, recipients)
            break

    if last_err:
        logger.error("Email NOT delivered to %s: %s", recipients, last_err)
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
        "Номер телефона с сайта/бота «Красная кнопка»\n\n"
        f"{_user_block(user, platform)}\n"
        f"phone: {phone_number}\n"
        f"topic: {topic or '-'}\n"
    )
    ok = send_email(
        subject="Красная кнопка: номер телефона",
        body=body,
        to=alert_recipients(topic),
        phone_fast=True,
    )
    if not ok:
        logger.error(
            "PHONE_EMAIL_FAILED phone=%s user_id=%s platform=%s",
            phone_number,
            user.get("id"),
            platform,
        )
    return ok


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
        subject="Красная кнопка: заявка на звонок",
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
        subject=f"Красная кнопка: диалог {uid}",
        body=body,
        to=alert_recipients(topic),
        attachment=transcript,
        filename=filename,
    )
