# -*- coding: utf-8 -*-
"""
parser.py — парсинг свободного текста администратора в JSON-формат правила
"""
import os, json, requests, logging
from uuid import uuid4
from dotenv import load_dotenv
load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

PROMPT_SYSTEM = (
    "Ты ассистент проекта «Red Button». "
    "Твоя задача — преобразовать текст администратора в структурированный JSON-объект правила поддержки. "
    "Строго соблюдай схему, не добавляй лишних полей, не выдумывай медицинских диагнозов. "
    "Если информации не хватает, аккуратно обобщай. "
    "Выводи ТОЛЬКО JSON без пояснений."
)

PROMPT_USER_TEMPLATE = """Исходный текст администратора:
\"\"\"{text}\"\"\"

Сформируй JSON следующего вида:

{{
  "topic": "auto | anxiety | stimulants | alcohol | opioids | cannabis | gambling | video_games",
  "if": {{
    "summary": "кратко 1–2 предложения",
    "signs": ["признак1","признак2"]
  }},
  "then": {{
    "steps": ["шаг1","шаг2","шаг3"],
    "first_aid": ["что делать сразу"]
  }},
  "emergency": {{
    "when": ["когда вызывать 103/112"],
    "action": "что сказать/сделать"
  }},
  "notes": ["оговорки, ограничения"],
  "tags": ["ключевые слова"],
  "priority": 3,
  "confidence": 0.0,
  "rationale": "почему так распознал"
}}"""

def parse_admin_text(text: str) -> tuple[dict, str]:
    """
    Отправляет текст администратора в OpenAI, получает JSON-правило.
    Возвращает (dict, raw_text) или (None, reason) при ошибке.
    """
    if not OPENAI_KEY:
        return None, "OpenAI API key not задан"

    try:
        payload = {
            "model": OPENAI_MODEL,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": PROMPT_USER_TEMPLATE.format(text=text.strip())}
            ],
            "max_tokens": 500
        }
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=60
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        try:
            parsed = json.loads(content)
            parsed["rule_id"] = str(uuid4())
            parsed["source_text"] = text.strip()
            return parsed, content
        except Exception:
            logging.warning("parse_admin_text: не удалось json.loads — %s", content[:200])
            return None, "Не удалось разобрать JSON: GPT вернул некорректный формат."
    except Exception as e:
        logging.exception("parse_admin_text error: %s", e)
        return None, str(e)

