# -*- coding: utf-8 -*-
"""
validator.py — проверка структуры и безопасности JSON-правила
"""
import re, json

FORBIDDEN = ["антидепрессант", "психиатр", "лекарств", "диагноз", "шизо", "суицид"]

def validate_rule_json(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Не JSON-объект"

    # обязательные поля
    for k in ["if", "then", "topic"]:
        if k not in data:
            return False, f"Отсутствует поле {k}"

    text_blob = json.dumps(data, ensure_ascii=False).lower()
    for bad in FORBIDDEN:
        if bad in text_blob:
            return False, f"Обнаружено запрещённое слово: {bad}"

    # базовые длины
    if len(text_blob) > 8000:
        return False, "Слишком длинный текст (ограничение 8000 символов)"

    return True, ""

