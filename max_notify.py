# -*- coding: utf-8 -*-
"""Уведомления в мессенджер MAX (platform-api2.max.ru)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://platform-api2.max.ru"


def max_enabled() -> bool:
    token = (os.getenv("MAX_BOT_TOKEN") or "").strip()
    user_id = (os.getenv("MAX_ALERT_USER_ID") or "").strip()
    chat_id = (os.getenv("MAX_ALERT_CHAT_ID") or "").strip()
    return bool(token and (user_id or chat_id))


def _api_base() -> str:
    return (os.getenv("MAX_API_BASE") or DEFAULT_API_BASE).strip().rstrip("/")


def send_max_text(text: str) -> bool:
    token = (os.getenv("MAX_BOT_TOKEN") or "").strip()
    if not token:
        return False

    user_id = (os.getenv("MAX_ALERT_USER_ID") or "").strip()
    chat_id = (os.getenv("MAX_ALERT_CHAT_ID") or "").strip()
    params = {}
    if user_id:
        params["user_id"] = user_id
    elif chat_id:
        params["chat_id"] = chat_id
    else:
        logger.warning("MAX: no MAX_ALERT_USER_ID or MAX_ALERT_CHAT_ID")
        return False

    try:
        r = requests.post(
            f"{_api_base()}/messages",
            params=params,
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
            },
            json={"text": text, "notify": True},
            timeout=15,
        )
        if r.ok:
            logger.info("MAX message sent -> %s", params)
            return True
        logger.warning("MAX send failed %s: %s", r.status_code, r.text[:300])
        return False
    except Exception:
        logger.exception("MAX send exception")
        return False


def notify_phone_max(
    user: Dict[str, Any],
    phone_number: str,
    topic: Optional[str] = None,
    platform: str = "",
) -> bool:
    username = user.get("username") or ""
    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    full_name = f"{first_name} {last_name}".strip()
    lines = [
        "📞 Номер с «Красной кнопки»",
        f"Телефон: {phone_number}",
        f"Имя: {full_name or '-'}",
    ]
    if username:
        lines.append(f"Username: @{username}")
    lines.append(f"user_id: {user.get('id')}")
    if platform:
        lines.append(f"Источник: {platform}")
    if topic:
        lines.append(f"Тема: {topic}")
    return send_max_text("\n".join(lines))
