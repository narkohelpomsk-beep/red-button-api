#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, random, time, logging, threading, re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
from flask import Flask, request, jsonify
import requests
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

load_dotenv()

PANEL_URL = "http://127.0.0.1:8081/api/message"

def send_to_panel(chat_id, user, text, direction):
    try:
        requests.post(
            PANEL_URL,
            json={
                "chat_id": chat_id,
                "user_id": user.get("id"),
                "username": user.get("username"),
                "name": (user.get("first_name","") + " " + user.get("last_name","")).strip(),
                "direction": direction,
                "text": text
            },
            timeout=3
        )
    except Exception:
        logging.exception("panel send failed")

# --- knowledge modules ---
from knowledge.parser import parse_admin_text
from knowledge.validator import validate_rule_json
from knowledge.writer import save_rule_atomic
import email_notify
import max_notify

_BG_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rb_bg")

# ===================== ENV =====================
TELEGRAM_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
OPENAI_KEY     = (os.getenv("OPENAI_API_KEY") or "").strip()
WEBHOOK_URL    = (os.getenv("WEBHOOK_URL") or "").strip()
DATABASE_URL   = (os.getenv("DATABASE_URL") or "").strip()
PANEL_API_URL     = (os.getenv("PANEL_API_URL") or "").strip()
PANEL_API_SECRET  = (os.getenv("PANEL_API_SECRET") or "").strip()


def _normalize_database_url(url: str) -> str:
    """db.xxx.supabase.co:5432 на Windows часто недоступен (IPv6) → pooler IPv4."""
    from urllib.parse import quote_plus, unquote

    m = re.match(
        r"^postgresql://postgres:([^@]+)@db\.([a-z0-9]+)\.supabase\.co:5432/(\w+)",
        url,
    )
    if m:
        pwd, ref, db = m.groups()
        region = (os.getenv("SUPABASE_REGION") or "eu-central-1").strip()
        prefix = (os.getenv("SUPABASE_POOLER_PREFIX") or "aws-1").strip()
        port = (os.getenv("SUPABASE_POOLER_PORT") or "6543").strip()
        pwd_enc = quote_plus(unquote(pwd))
        url = (
            f"postgresql://postgres.{ref}:{pwd_enc}@"
            f"{prefix}-{region}.pooler.supabase.com:{port}/{db}"
        )
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


DATABASE_URL = _normalize_database_url(DATABASE_URL)

# админы и алерт-чаты
ADMIN_USER_IDS_ENV     = (os.getenv("ADMIN_USER_IDS") or "").strip()  # "123,456"
ADMIN_ALERT_CHAT_ID    = (os.getenv("ADMIN_ALERT_CHAT_ID") or "").strip()
BULLYING_ALERT_CHAT_ID = (os.getenv("BULLYING_ALERT_CHAT_ID") or "").strip()

assert OPENAI_KEY, "OPENAI_API_KEY is empty"
assert DATABASE_URL, "DATABASE_URL is empty (postgres required)"
# TELEGRAM_BOT_TOKEN — для webhook Telegram; для чата на сайте не обязателен

BASE_DIR = os.path.dirname(__file__)
CFG_PATH = os.path.join(BASE_DIR, "config.json")
KB_PATH  = os.path.join(BASE_DIR, "knowledge_base.json")

# ===================== APP =====================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ===================== CONFIG (hot reload) =====================
_cfg_cache: Dict[str, Any] = {}
_cfg_mtime = 0.0


def load_cfg() -> Dict[str, Any]:
    """Reload config.json on change."""
    global _cfg_cache, _cfg_mtime
    try:
        st = os.stat(CFG_PATH).st_mtime
        if not _cfg_cache or st != _cfg_mtime:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                _cfg_cache = json.load(f)
            _cfg_mtime = st
            lvl = _cfg_cache.get("logging", {}).get("level", "INFO").upper()
            logging.getLogger().setLevel(lvl)
            logging.info("Config reloaded")
    except Exception:
        logging.exception("Failed to load config.json")
        if not _cfg_cache:
            _cfg_cache = {}
    return _cfg_cache


# ===================== KB (hot reload + indexes) =====================
_kb_cache: Dict[str, Any] = {}
_kb_mtime = 0.0
ALIAS_INDEX: List = []
RISK_PATTERNS = set()


def _walk_topics(domain):
    for t in domain.get("topics", []):
        yield (domain, t)
        for st in t.get("subtopics", []):
            yield (domain, st)


def _admin_rules_snippet(topic_id: Optional[str]) -> str:
    if not _kb_cache:
        return ""
    rules = _kb_cache.get("admin_rules") or []
    if not isinstance(rules, list):
        return ""
    picked = []
    for r in rules:
        t = (r.get("topic") or "auto")
        if t == "auto" or (topic_id and t == topic_id):
            summary = (r.get("if") or {}).get("summary", "")
            steps = (r.get("then") or {}).get("steps") or []
            step1 = steps[0] if steps else ""
            if summary or step1:
                picked.append(f"ЕСЛИ {summary} ТО {step1}")
    return ("Админские правила: " + " | ".join(picked[:5])) if picked else ""


def build_indexes():
    """Reload knowledge_base.json on change and rebuild alias/risk indexes."""
    global _kb_cache, _kb_mtime, ALIAS_INDEX, RISK_PATTERNS
    try:
        st = os.stat(KB_PATH).st_mtime
        if not _kb_cache or st != _kb_mtime:
            with open(KB_PATH, "r", encoding="utf-8") as f:
                _kb_cache = json.load(f)
            _kb_mtime = st
            ALIAS_INDEX = []
            RISK_PATTERNS = set()
            for d in _kb_cache.get("domains", []):
                for (domain, topic) in _walk_topics(d):
                    for a in (topic.get("aliases") or []):
                        a = a.strip().lower()
                        if a:
                            ALIAS_INDEX.append(
                                (a, {"domain": domain.get("id"), "topic": topic.get("id")})
                            )
                    for r in (topic.get("risk_flags") or []):
                        if isinstance(r, str):
                            RISK_PATTERNS.add(r.lower())
            RISK_PATTERNS.update(
                [
                    "суицид",
                    "передоз",
                    "галлюцинации",
                    "не дышит",
                    "без сознания",
                    "кровь",
                    "судороги",
                ]
            )
            logging.info(
                "KB reloaded: aliases=%d risks=%d", len(ALIAS_INDEX), len(RISK_PATTERNS)
            )
    except Exception:
        logging.exception("Failed to load knowledge_base.json")


def detect_topic(
    text: str,
    cfg: Optional[Dict[str, Any]] = None,
    short_history: str = "",
    current_topic: Optional[str] = None,
    skip_gpt: bool = False,
) -> Optional[str]:
    t = (text or "").lower().strip()
    if not t:
        return None

    # Нюхательный табак / вейп — частый запрос на сайте
    if any(k in t for k in ("снуп", "snuf", "snus", "насвай", "nasvay", "нюхательн", "вейп", "vape", "спрей")):
        logging.info("TOPIC_ALIAS_MATCH text=%r alias=nasvay/snus topic=stimulants", text)
        return "stimulants"

    # 1. Сначала жёсткий alias-match из KB
    for alias, ptr in ALIAS_INDEX:
        if alias in t:
            logging.info(
                "TOPIC_ALIAS_MATCH text=%r alias=%r topic=%s",
                text, alias, ptr["topic"]
            )
            return ptr["topic"]

    if cfg is None:
        cfg = load_cfg()
    for v in (cfg.get("buttons") or {}).values():
        if t == str(v).lower().strip():
            return None
    if t in ("да", "нет", "yes", "no", "начать", "start", "/start", "привет", "здравствуйте"):
        return None
    if len(t) <= 24 and not any(kw in t for kw in ("ломк", "наркот", "алког", "пьян", "булл", "травл", "игром", "зависим", "суицид", "умер", "умру")):
        return None

    # 2. Затем GPT-классификация (на сайте пропускаем — быстрее, хватает regex)
    if not skip_gpt:
        topic_from_gpt = detect_topic_gpt(
            cfg=cfg,
            text=text,
            short_history=short_history,
            current_topic=current_topic,
        )
        if topic_from_gpt:
            return topic_from_gpt

    # 3. И только потом fallback-эвристика
    KW = {
        "alcohol": ["алкоголь", "пью", "бутыл", "похмел", "трезв"],
        "stimulants": ["соль", "мефедрон", "амфетамин", "кокаин", "скорость"],
        "opioids": ["героин", "опиоид", "опий", "морфин", "метадон"],
        "cannabis": ["травк", "марихуан", "гашиш", "план"],
        "gambling": ["казино", "игроман", "ставк", "букмек"],
        "video_games": ["игры", "компьютерные", "онлайн", "дота", "кс"],
        "bullying": [
            "буллинг", "булят", "буллят", "травят", "обижают",
            "издеваются", "гнобят", "унижают", "дразнят",
            "задирают", "чморят", "прессуют"
        ],
    }
    for topic_id, kws in KW.items():
        if any(k in t for k in kws):
            logging.info(
                "TOPIC_KW_MATCH text=%r topic=%s",
                text, topic_id
            )
            return topic_id

    logging.info("TOPIC_NOT_DETECTED text=%r", text)
    return None


def collect_kb_chunks(topic_id: Optional[str], mode: str) -> str:
    if not _kb_cache:
        return ""
    chunks = []
    # базовые блоки по теме (если есть)
    if topic_id:
        for d in _kb_cache.get("domains", []):
            for (domain, topic) in _walk_topics(d):
                if topic.get("id") == topic_id:
                    if "guidelines" in topic:
                        g = topic["guidelines"]
                        if mode == "self" and isinstance(g.get("self"), list):
                            chunks.append("Советы для себя: " + "; ".join(g["self"][:6]))
                        if mode == "relatives" and isinstance(g.get("relatives"), list):
                            chunks.append(
                                "Советы для близких: "
                                + "; ".join(g["relatives"][:6])
                            )
                    if "first_aid" in topic and isinstance(topic["first_aid"], list):
                        chunks.append(
                            "Первая помощь: " + "; ".join(topic["first_aid"][:5])
                        )
                    if "faq" in topic and topic["faq"]:
                        qa = topic["faq"][0]
                        chunks.append(f"FAQ: {qa.get('q','')} → {qa.get('a','')}")
                    if "micro_interventions" in topic and topic["micro_interventions"]:
                        mi = topic["micro_interventions"][0]
                        chunks.append(
                            f"Микро-интервенция: {mi.get('prompt','')}"
                        )
                    break
    # добавим срез админ-правил
    admin_part = _admin_rules_snippet(topic_id)
    if admin_part:
        chunks.append(admin_part)
    return "\n".join(chunks[:6])


def detect_risk(text: str) -> bool:
    t = (text or "").lower()
    for pat in RISK_PATTERNS:
        if pat in t:
            return True
    return False

def get_specialist_phone(topic: Optional[str]) -> str:
    """
    Возвращает номер специалиста по теме из config.json.
    """
    cfg = load_cfg()
    phones = cfg.get("phones", {}) or {}

    default_phone = str(phones.get("default_specialist") or "").strip()
    bullying_phone = str(phones.get("bullying_specialist") or "").strip()

    if topic == "bullying" and bullying_phone:
        return bullying_phone

    return default_phone

def build_phone_block(topic: Optional[str]) -> str:
    """
    Формирует финальный блок с телефоном специалиста.
    """
    specialist = get_specialist_phone(topic)

    return (
        "\n\nВы можете:\n"
        f"• позвонить нашему специалисту сами: {specialist}\n"
        "• или нажать кнопку ниже и отправить свой номер телефона, чтобы мы сами вам перезвонили."
    )

def build_emergency_phone_block(topic: Optional[str]) -> str:
    """
    Формирует блок телефонов для экстренной помощи.
    """
    cfg = load_cfg()
    phones = cfg.get("phones", {}) or {}
    specialist = get_specialist_phone(topic)

    emergency_list = phones.get("emergency") or []
    emergency_text = " или ".join(str(x).strip() for x in emergency_list if str(x).strip())
    if not emergency_text:
        emergency_text = "103 или 112"

    return (
        "\n\nТакже можно срочно связаться с нашим специалистом:\n"
        f"• {specialist}\n"
        f"• Экстренные службы: {emergency_text}"
    )

def extract_phone_number(text: str) -> Optional[str]:
    """
    Распознаёт российский номер телефона в сообщении.
    """
    raw = (text or "").strip()
    digits = re.sub(r"\D", "", raw)

    if len(digits) == 10:
        return "7" + digits

    if len(digits) == 11 and digits[0] in ("7", "8"):
        return digits

    return None


def _normalize_button_text(text: str) -> str:
    raw = (text or "").strip()
    raw = re.sub(r"^[\U0001F300-\U0001FAFF\U00002600-\U000027BF]+\s*", "", raw)
    return raw.lower()


def _is_need_callback(text: str, cfg: Dict[str, Any]) -> bool:
    want = _normalize_button_text(cfg["buttons"]["need_callback"])
    got = _normalize_button_text(text)
    if got == want:
        return True
    return got in (
        "мне нужно чтобы мне позвонили",
        "позвоните мне",
        "перезвоните",
        "перезвоните мне",
        "нужен обратный звонок",
        "хочу чтобы позвонили",
    )


# ===================== Admin utils =====================
def _parse_admin_ids(env_str: str) -> List[str]:
    if not env_str:
        return []
    ids = []
    for raw in env_str.split(","):
        token = raw.split("#", 1)[0].strip()  # отрезаем инлайн-комментарии
        if token:
            ids.append(token)
    return ids


ADMIN_IDS = set(_parse_admin_ids(ADMIN_USER_IDS_ENV))
logging.info(
    "ADMIN_USER_IDS loaded: %s", ",".join(sorted(ADMIN_IDS)) or "<empty>"
)


def is_admin(uid: Any) -> bool:
    return str(uid) in ADMIN_IDS


# ===================== PostgreSQL =====================
POOL_MIN = 1
POOL_MAX = 10
_pg_pool: Optional[ThreadedConnectionPool] = None
_pg_pool_lock = threading.Lock()

# keepalive — чтобы пулер Supabase не «ронял» простаивающие соединения,
# из-за чего раньше падали запросы (server closed the connection unexpectedly).
_PG_CONNECT_KWARGS = dict(
    connect_timeout=10,
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=5,
)


def pg_pool() -> ThreadedConnectionPool:
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                _pg_pool = ThreadedConnectionPool(
                    POOL_MIN, POOL_MAX, dsn=DATABASE_URL, **_PG_CONNECT_KWARGS
                )
                logging.info("Postgres pool created")
    return _pg_pool


def reset_pg_pool() -> None:
    """Полностью пересоздать пул (когда соединения «протухли»)."""
    global _pg_pool
    with _pg_pool_lock:
        old = _pg_pool
        _pg_pool = None
    if old is not None:
        try:
            old.closeall()
        except Exception:
            pass


def pg_exec(sql: str, params=None, fetch=False, _retries: int = 4):
    """Выполнить запрос с авто-восстановлением соединения.

    Пулер Supabase периодически закрывает простаивающие соединения; раньше это
    приводило к OperationalError и падению чата/бота. Теперь мёртвое соединение
    выбрасывается, пул при необходимости пересоздаётся, запрос повторяется.
    """
    last_err: Optional[Exception] = None
    for attempt in range(_retries):
        pool = pg_pool()
        conn = None
        try:
            conn = pool.getconn()
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                result = cur.fetchall() if fetch else None
            pool.putconn(conn)
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_err = e
            # выбрасываем мёртвое соединение из пула
            if conn is not None:
                try:
                    pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = None
            # после первой неудачи пересоздаём весь пул
            if attempt >= 1:
                reset_pg_pool()
            logging.warning(
                "pg_exec повтор %s/%s после %s",
                attempt + 1, _retries, e.__class__.__name__,
            )
            time.sleep(min(1.5 * (attempt + 1), 5.0))
        except Exception:
            if conn is not None:
                try:
                    pool.putconn(conn)
                except Exception:
                    pass
            raise
    # все попытки исчерпаны
    raise last_err if last_err else RuntimeError("pg_exec failed")


def init_db():
    pg_exec(
        """
    CREATE TABLE IF NOT EXISTS users(
      user_id TEXT PRIMARY KEY,
      username TEXT,
      first_name TEXT,
      last_name TEXT,
      is_bot INTEGER DEFAULT 0,
      is_subscribed INTEGER DEFAULT 1,
      created_at INTEGER,
      last_seen_at INTEGER
    );
    """
    )
    pg_exec(
        """
    CREATE TABLE IF NOT EXISTS sessions(
      user_id TEXT PRIMARY KEY,
      mode TEXT,
      stage INTEGER DEFAULT 0,
      max_turns INTEGER DEFAULT 6,
      topic TEXT,
      last_ts INTEGER,
      history TEXT,
      call_state TEXT
    );
    """
    )
    # на всякий случай — добавить колонку для существующих БД
    pg_exec(
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS call_state TEXT;"
    )

    pg_exec(
        """
    CREATE TABLE IF NOT EXISTS messages(
      id SERIAL PRIMARY KEY,
      user_id TEXT,
      role TEXT,
      text TEXT,
      ts INTEGER
    );
    """
    )
    pg_exec(
        """
    CREATE TABLE IF NOT EXISTS broadcasts(
      id SERIAL PRIMARY KEY,
      text TEXT,
      created_at INTEGER,
      created_by TEXT,
      status TEXT DEFAULT 'queued'
    );
    """
    )
    pg_exec(
        """
    CREATE TABLE IF NOT EXISTS processed_updates(
      update_id BIGINT PRIMARY KEY,
      ts INTEGER
    );
    """
    )
    pg_exec(
        """
     CREATE TABLE IF NOT EXISTS admin_states(
      user_id TEXT PRIMARY KEY,
      pending TEXT,
      ts INTEGER
    );
    """
    )
    # отметка последнего экспортированного таймштампа диалога
    pg_exec(
        """
    CREATE TABLE IF NOT EXISTS dialog_exports(
      user_id TEXT PRIMARY KEY,
      last_exported_ts INTEGER DEFAULT 0,
      updated_at INTEGER
    );
    """
    )
    pg_exec(
        """
    CREATE TABLE IF NOT EXISTS phone_leads(
      id SERIAL PRIMARY KEY,
      user_id TEXT,
      phone TEXT NOT NULL,
      topic TEXT,
      platform TEXT,
      username TEXT,
      full_name TEXT,
      email_sent INTEGER DEFAULT 0,
      created_at INTEGER
    );
    """
    )
    logging.info("Postgres schema ensured")


def upsert_user(u: Dict[str, Any]):
    pg_exec(
        """
    INSERT INTO users(user_id, username, first_name, last_name, is_bot, is_subscribed, created_at, last_seen_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (user_id) DO UPDATE SET
      username=EXCLUDED.username,
      first_name=EXCLUDED.first_name,
      last_name=EXCLUDED.last_name,
      is_bot=EXCLUDED.is_bot,
      last_seen_at=EXCLUDED.last_seen_at
    """,
        (
            str(u["id"]),
            u.get("username"),
            u.get("first_name"),
            u.get("last_name"),
            1 if u.get("is_bot") else 0,
            1,
            int(time.time()),
            int(time.time()),
        ),
    )


def set_subscribed(user_id: str, val: int):
    pg_exec(
        "UPDATE users SET is_subscribed=%s, last_seen_at=%s WHERE user_id=%s",
        (val, int(time.time()), str(user_id)),
    )


def load_session(uid) -> Optional[Dict[str, Any]]:
    rows = pg_exec(
        "SELECT mode, stage, max_turns, topic, last_ts, history, call_state FROM sessions WHERE user_id=%s",
        (str(uid),),
        fetch=True,
    )
    if not rows:
        return None
    mode, stage, max_turns, topic, last_ts, hist, call_state = rows[0]
    return {
        "mode": mode,
        "stage": stage,
        "max_turns": max_turns,
        "topic": topic,
        "last_ts": last_ts,
        "history": json.loads(hist or "[]"),
        "call_state": call_state,
    }


def save_session(uid, s: Dict[str, Any]):
    pg_exec(
        """
    INSERT INTO sessions(user_id, mode, stage, max_turns, topic, last_ts, history, call_state)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (user_id) DO UPDATE SET
      mode=EXCLUDED.mode,
      stage=EXCLUDED.stage,
      max_turns=EXCLUDED.max_turns,
      topic=EXCLUDED.topic,
      last_ts=EXCLUDED.last_ts,
      history=EXCLUDED.history,
      call_state=EXCLUDED.call_state
    """,
        (
            str(uid),
            s.get("mode"),
            s.get("stage"),
            s.get("max_turns"),
            s.get("topic"),
            int(time.time()),
            json.dumps(s.get("history", []), ensure_ascii=False),
            s.get("call_state"),
        ),
    )


def save_message(uid, role, text):
    pg_exec(
        "INSERT INTO messages(user_id, role, text, ts) VALUES (%s,%s,%s,%s)",
        (str(uid), role, text, int(time.time())),
    )


def get_subscribed_users() -> List[str]:
    rows = pg_exec(
        "SELECT user_id FROM users WHERE is_subscribed=1", fetch=True
    )
    return [r[0] for r in rows] if rows else []


def mark_update_processed(update_id: int) -> bool:
    try:
        pg_exec(
            "INSERT INTO processed_updates(update_id, ts) VALUES (%s,%s)",
            (int(update_id), int(time.time())),
        )
        return True
    except Exception:
        return False


# --- admin pending state helpers ---
def set_admin_state(user_id: str, pending: Optional[str]):
    if pending:
        pg_exec(
            """
        INSERT INTO admin_states(user_id, pending, ts) VALUES (%s,%s,%s)
        ON CONFLICT (user_id) DO UPDATE SET pending=EXCLUDED.pending, ts=EXCLUDED.ts
        """,
            (str(user_id), pending, int(time.time())),
        )
    else:
        pg_exec("DELETE FROM admin_states WHERE user_id=%s", (str(user_id),))


def get_admin_state(user_id: str) -> Optional[str]:
    rows = pg_exec(
        "SELECT pending FROM admin_states WHERE user_id=%s",
        (str(user_id),),
        fetch=True,
    )
    return rows[0][0] if rows else None


def clear_admin_state(user_id: str):
    pg_exec("DELETE FROM admin_states WHERE user_id=%s", (str(user_id),))


# ======== вспомогательная статистика ========
def get_user_stats():
    """Возвращает (total_users, new_today)"""
    rows = pg_exec("SELECT COUNT(*) FROM users", fetch=True) or [(0,)]
    total = int(rows[0][0] or 0)
    t = time.localtime()
    midnight = int(
        time.mktime(
            (
                t.tm_year,
                t.tm_mon,
                t.tm_mday,
                0,
                0,
                0,
                t.tm_wday,
                t.tm_yday,
                t.tm_isdst,
            )
        )
    )
    rows2 = pg_exec(
        "SELECT COUNT(*) FROM users WHERE created_at >= %s",
        (midnight,),
        fetch=True,
    ) or [(0,)]
    today_new = int(rows2[0][0] or 0)
    return total, today_new


# ===================== TG helpers =====================
def _tg_api_base() -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ===================== Web-chat (сайт = этот же бот) =====================
import re as _re
import uuid as _uuid

_WEB_CAPTURE = None
_WEB_SESSIONS: Dict[str, Dict[str, Any]] = {}
_WEB_SESSION_TTL = 60 * 60 * 24 * 7
WEB_CHAT_CORS = [
    o.strip().rstrip("/")
    for o in (os.getenv("WEB_CHAT_CORS") or "https://redbuttonhelp.ru,http://127.0.0.1:8765").split(",")
    if o.strip()
]


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = _re.sub(r"<br\s*/?>", "\n", text, flags=_re.I)
    text = _re.sub(r"<[^>]+>", "", text)
    return text.replace("&nbsp;", " ").strip()


class _WebCapture:
    def __init__(self):
        self.items: List[Dict[str, Any]] = []
        self.lead_saved = False

    def add(self, text, buttons=None, remove_keyboard=False):
        clean = _strip_html(text or "")
        if remove_keyboard and not clean:
            if self.items:
                self.items[-1]["buttons"] = []
            return
        rows = []
        if buttons and not remove_keyboard:
            for row in buttons:
                labels = []
                for cell in row:
                    label = cell.get("text") if isinstance(cell, dict) else str(cell)
                    label = (label or "").strip()
                    if label:
                        labels.append(label[:64])
                if labels:
                    rows.append(labels)
        awaiting_phone = False
        if buttons and not remove_keyboard:
            for row in buttons:
                for cell in row:
                    if isinstance(cell, dict) and cell.get("request_contact"):
                        awaiting_phone = True
        if clean and ("принято" in clean.lower()) and "свяж" in clean.lower():
            self.lead_saved = True
        if clean or rows:
            self.items.append(
                {"text": clean, "buttons": rows, "awaiting_phone": awaiting_phone}
            )
        elif rows and self.items:
            self.items[-1]["buttons"] = rows

    def flush(self) -> Dict[str, Any]:
        texts = [i["text"] for i in self.items if i.get("text")]
        buttons: List[List[str]] = []
        awaiting = False
        for i in self.items:
            if i.get("buttons"):
                buttons = i["buttons"]
            if i.get("awaiting_phone"):
                awaiting = True
        return {
            "reply": "\n\n".join(texts),
            "buttons": buttons,
            "awaiting_phone": awaiting,
            "lead_saved": self.lead_saved,
        }


def _web_cors(resp):
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and origin in WEB_CHAT_CORS:
        resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


@app.after_request
def _web_chat_cors(resp):
    if request.path.startswith("/api/chat"):
        return _web_cors(resp)
    return resp


def _web_prune_sessions():
    now = int(time.time())
    for sid in [k for k, v in _WEB_SESSIONS.items() if now - v.get("ts", 0) > _WEB_SESSION_TTL]:
        del _WEB_SESSIONS[sid]


def _web_create_session() -> Dict[str, Any]:
    sid = str(_uuid.uuid4())
    uid = random.randint(10**9, 10**10 - 1)
    user = {
        "id": uid,
        "username": "web",
        "first_name": "Сайт",
        "last_name": sid[:8],
        "is_bot": False,
    }
    meta = {
        "session_id": sid,
        "user": user,
        "chat_id": f"web:{sid}",
        "ts": int(time.time()),
    }
    _WEB_SESSIONS[sid] = meta
    return meta


def _web_run(meta: Dict[str, Any], text: str, *, phone: Optional[str] = None) -> Dict[str, Any]:
    global _WEB_CAPTURE
    capture = _WebCapture()
    _WEB_CAPTURE = capture
    try:
        msg = None
        incoming = text
        if phone:
            msg = {"contact": {"phone_number": phone, "user_id": meta["user"]["id"]}}
            incoming = ""
        handle_incoming_message(
            meta["chat_id"],
            "private",
            meta["user"],
            incoming,
            message_id=int(time.time()),
            update_id=int(time.time() * 1000) + random.randint(0, 999),
            msg=msg,
        )
    finally:
        _WEB_CAPTURE = None
    out = capture.flush()
    out["session_id"] = meta["session_id"]
    return out


@app.route("/api/chat/ping", methods=["POST", "OPTIONS", "GET"])
def web_chat_ping():
    if request.method == "OPTIONS":
        return _web_cors(jsonify({"ok": True}))
    return _web_cors(jsonify({"ok": True}))


@app.route("/api/chat/start", methods=["POST", "OPTIONS"])
def web_chat_start():
    if request.method == "OPTIONS":
        return _web_cors(jsonify({"ok": True}))
    try:
        _web_prune_sessions()
        meta = _web_create_session()
        return jsonify(_web_run(meta, "/start"))
    except Exception as exc:
        logging.exception("web_chat_start failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/chat/message", methods=["POST", "OPTIONS"])
def web_chat_message():
    if request.method == "OPTIONS":
        return _web_cors(jsonify({"ok": True}))
    body = request.get_json(silent=True) or {}
    session_id = (body.get("session_id") or "").strip()
    text = (body.get("text") or "").strip()
    phone = (body.get("phone") or "").strip() or None
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    if not text and not phone:
        return jsonify({"error": "text required"}), 400
    meta = _WEB_SESSIONS.get(session_id)
    if not meta:
        return jsonify({"error": "session_expired"}), 200
    meta["ts"] = int(time.time())
    try:
        if phone and not text:
            return jsonify(_web_run(meta, "", phone=phone))
        return jsonify(_web_run(meta, text))
    except Exception as exc:
        logging.exception("web_chat_message failed")
        ack = "Принято, скоро с вами свяжемся. Продолжим пока разговор здесь?"
        if phone or (text and extract_phone_number(text)):
            pn = phone or extract_phone_number(text) or text
            notify_phone_shared(
                meta["user"],
                str(pn),
                None,
                platform="site",
            )
            return jsonify(
                {
                    "session_id": meta["session_id"],
                    "reply": ack,
                    "buttons": [],
                    "awaiting_phone": False,
                    "lead_saved": True,
                }
            )
        return jsonify({"error": str(exc)}), 500


@app.route("/api/chat/lead", methods=["POST", "OPTIONS"])
def web_chat_lead():
    """Прямая передача номера с сайта (упрощённый чат и запасной канал)."""
    if request.method == "OPTIONS":
        return _web_cors(jsonify({"ok": True}))
    body = request.get_json(silent=True) or {}
    raw = (body.get("phone") or body.get("text") or "").strip()
    phone_number = extract_phone_number(raw)
    if not phone_number:
        return jsonify({"error": "invalid_phone"}), 400

    session_id = (body.get("session_id") or "").strip()
    meta = _WEB_SESSIONS.get(session_id) if session_id else None
    topic = body.get("topic")
    if meta:
        user = meta["user"]
        if not topic:
            topic = (_web_load_session_state(meta) or {}).get("topic")
        notify_phone_shared(user, phone_number, topic, platform="site")
    else:
        user = {
            "id": f"web-lead-{int(time.time())}",
            "username": "site",
            "first_name": "Сайт",
            "last_name": "",
        }
        notify_phone_shared(user, phone_number, topic, platform="site")

    logging.info("web_chat_lead phone=%s session=%s", phone_number, session_id or "-")
    return jsonify({"ok": True, "lead_saved": True})


def _web_load_session_state(meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        return load_session(meta["user"]["id"])
    except Exception:
        return None


def panel_headers():
    headers = {}
    if PANEL_API_SECRET:
        headers["X-Panel-Secret"] = PANEL_API_SECRET
    return headers

def send_to_panel(chat_id, user, text, direction, sender_type=None, telegram_message_id=None):
    if not PANEL_API_URL:
        return

    def _post():
        try:
            name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            payload = {
                "chat_id": str(chat_id),
                "user_id": str(user.get("id") or ""),
                "username": f"@{user.get('username')}" if user.get("username") else "",
                "name": name,
                "direction": direction,
                "sender_type": sender_type or ("user" if direction == "in" else "bot"),
                "text": text or "",
                "telegram_message_id": telegram_message_id,
            }
            r = requests.post(
                f"{PANEL_API_URL}/api/message",
                json=payload,
                headers=panel_headers(),
                timeout=5,
            )
            if not r.ok:
                logging.warning("panel api_message failed: %s %s", r.status_code, r.text)
        except Exception:
            logging.exception("panel send failed")

    threading.Thread(target=_post, daemon=True).start()

def panel_bot_enabled(chat_id) -> bool:
    if str(chat_id).startswith("web:"):
        return True
    if not PANEL_API_URL:
        return True
    try:
        r = requests.get(
            f"{PANEL_API_URL}/api/bot_enabled/{chat_id}",
            headers=panel_headers(),
            timeout=5,
        )
        if not r.ok:
            logging.warning("panel bot_enabled failed: %s %s", r.status_code, r.text)
            return True

        data = r.json()
        return bool(data.get("bot_enabled", True))
    except Exception:
        logging.exception("panel bot_enabled check failed")
        return True


def tg_send(chat_id, text, buttons=None, remove_keyboard=False):
    if _WEB_CAPTURE is not None:
        _WEB_CAPTURE.add(text, buttons=buttons, remove_keyboard=remove_keyboard)
        return {"message_id": 1}
    if not TELEGRAM_TOKEN:
        logging.warning("tg_send skipped: TELEGRAM_BOT_TOKEN is empty")
        return None
    try:
        requests.post(
            f"{_tg_api_base()}/sendChatAction",
            data={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
        delay = min(len(text or "") * 0.03, 2.0)
        time.sleep(delay)

        payload = {
            "chat_id": chat_id,
            "text": text or "",
            "parse_mode": "HTML",
        }

        if buttons:
            payload["reply_markup"] = json.dumps(
                {
                    "keyboard": buttons,
                    "resize_keyboard": True,
                    "one_time_keyboard": True,
                },
                ensure_ascii=False,
            )
        elif remove_keyboard:
            payload["reply_markup"] = json.dumps({"remove_keyboard": True})

        r = requests.post(f"{_tg_api_base()}/sendMessage", data=payload, timeout=20)
        if not r.ok:
            logging.warning("sendMessage failed: %s %s", r.status_code, r.text)
            return None

        data = r.json()
        if not data.get("ok"):
            logging.warning("sendMessage api error: %s", data)
            return None

        return data.get("result")
    except Exception as e:
        logging.exception("sendMessage exception: %s", e)
        return None

def tg_send_and_panel(chat_id, user, text, buttons=None, remove_keyboard=False, sender_type="bot"):
    result = tg_send(chat_id, text, buttons=buttons, remove_keyboard=remove_keyboard)
    telegram_message_id = result.get("message_id") if result else None
    send_to_panel(
        chat_id=chat_id,
        user=user,
        text=text,
        direction="out",
        sender_type=sender_type,
        telegram_message_id=telegram_message_id,
    )
    return result


def tg_send_document(
    chat_id: str, bytes_data: bytes, filename: str, caption: str = ""
):
    try:
        files = {"document": (filename, bytes_data)}
        data = {"chat_id": chat_id, "caption": caption}
        r = requests.post(
            f"{_tg_api_base()}/sendDocument",
            data=data,
            files=files,
            timeout=60,
        )
        if not r.ok:
            logging.warning(
                "sendDocument failed: %s %s", r.status_code, r.text
            )
            return False
        return True
    except Exception:
        logging.exception("sendDocument exception")
        return False

def _detect_platform(chat_id: Any, user: Dict[str, Any]) -> str:
    cid = str(chat_id or "")
    if cid.startswith("web:"):
        return "site"
    if (user.get("first_name") or "") == "VK":
        return "vk"
    if (user.get("username") or "").lower() == "web":
        return "site"
    return "telegram"


def _accept_phone_lead(
    user: Dict[str, Any],
    s: Dict[str, Any],
    chat_id: Any,
    phone_number: str,
    display_text: str,
    *,
    _web_chat: bool,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = cfg or load_cfg()
    s["call_state"] = "phone_received"

    if s.get("topic") is None and display_text:
        detected_topic = detect_topic(
            display_text,
            cfg=cfg,
            short_history=short_history_text(s),
            current_topic=s.get("topic"),
            skip_gpt=False,
        )
        if detected_topic:
            s["topic"] = detected_topic

    shown = display_text or phone_number
    push_history(s, "user", shown)
    if _web_chat:
        _BG_EXECUTOR.submit(save_message, user["id"], "user", shown)
    else:
        save_message(user["id"], "user", shown)

    notify_phone_shared(
        user,
        phone_number,
        s.get("topic"),
        platform=_detect_platform(chat_id, user),
    )

    ack_text = "Принято, скоро с вами свяжемся. Продолжим пока разговор здесь?"
    tg_send_and_panel(chat_id, user, ack_text, remove_keyboard=True)
    push_history(s, "assistant", ack_text)
    if _web_chat:
        _BG_EXECUTOR.submit(save_message, user["id"], "assistant", ack_text)
    else:
        save_message(user["id"], "assistant", ack_text)

    save_session(user["id"], s)
    return {"ok": True}


def notify_phone_shared(
    user: Dict[str, Any],
    phone_number: str,
    topic: Optional[str] = None,
    platform: str = "",
):
    """Номер телефона: Telegram + почта + БД (в фоне, не блокирует ответ чата)."""
    _BG_EXECUTOR.submit(
        _notify_phone_shared_impl, user, phone_number, topic, platform
    )


def _notify_phone_shared_impl(
    user: Dict[str, Any],
    phone_number: str,
    topic: Optional[str] = None,
    platform: str = "",
):
    try:
        username = user.get("username") or ""
        first_name = user.get("first_name") or ""
        last_name = user.get("last_name") or ""
        full_name = f"{first_name} {last_name}".strip()

        try:
            pg_exec(
                """
                INSERT INTO phone_leads(user_id, phone, topic, platform, username, full_name, email_sent, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,0,%s)
                """,
                (
                    str(user.get("id") or ""),
                    str(phone_number),
                    topic,
                    platform,
                    username,
                    full_name,
                    int(time.time()),
                ),
            )
        except Exception:
            logging.exception("phone_leads insert failed")

        username_line = f"username: @{username}" if username else "username: -"
        text = (
            "📞 Пользователь оставил номер телефона\n"
            f"user_id: {user.get('id')}\n"
            f"{username_line}\n"
            f"name: {full_name}\n"
            f"phone: {phone_number}\n"
            f"topic: {topic or '-'}"
        )
        if platform:
            text += f"\nplatform: {platform}"

        if ADMIN_ALERT_CHAT_ID and TELEGRAM_TOKEN:
            tg_send(ADMIN_ALERT_CHAT_ID, text)

        if max_notify.max_enabled():
            max_notify.notify_phone_max(
                user, phone_number, topic, platform=platform
            )

        if (
            topic == "bullying"
            and BULLYING_ALERT_CHAT_ID
            and TELEGRAM_TOKEN
            and str(BULLYING_ALERT_CHAT_ID) != str(ADMIN_ALERT_CHAT_ID)
        ):
            tg_send(BULLYING_ALERT_CHAT_ID, text)

        email_ok = email_notify.notify_phone_email(
            user, phone_number, topic, platform=platform
        )
        if email_ok:
            try:
                pg_exec(
                    """
                    UPDATE phone_leads SET email_sent=1
                    WHERE id = (
                      SELECT id FROM phone_leads
                      WHERE phone=%s AND user_id=%s
                      ORDER BY created_at DESC LIMIT 1
                    )
                    """,
                    (str(phone_number), str(user.get("id") or "")),
                )
            except Exception:
                logging.exception("phone_leads email_sent update failed")
        else:
            logging.error(
                "PHONE_EMAIL_NOT_SENT phone=%s user_id=%s platform=%s",
                phone_number,
                user.get("id"),
                platform,
            )
    except Exception:
        logging.exception("notify_phone_shared failed phone=%s", phone_number)


def tg_hide_keyboard(chat_id):
    tg_send(chat_id, " ", remove_keyboard=True)


def tg_send_batch(user_ids: List[str], text: str, batch_size=25, sleep_ms=200):
    for i in range(0, len(user_ids), batch_size):
        for uid in user_ids[i : i + batch_size]:
            try:
                tg_send(uid, text)
            except Exception:
                logging.exception("tg_send failed %s", uid)
        time.sleep(sleep_ms / 1000.0)


def main_menu(cfg):
    return [
        [
            {"text": cfg["buttons"]["mode_self"]},
            {"text": cfg["buttons"]["mode_relative"]}
        ],
        [
            {"text": cfg["buttons"]["need_callback"]}
        ]
    ]


# ===================== GPT =====================
def gpt_reply(
    cfg,
    mode,
    goal,
    short_history,
    kb_chunks,
    risk_detected,
    recent_replies: Optional[List[str]] = None,
    call_state: Optional[str] = None,
    fast: bool = False,
):
    system_prompt = (
        "Ты — Денис, консультант проекта «Red Button». "
        "Ты живой человек, мягкий, спокойный и уважительный. Не называй себя ботом, ИИ или моделью. "
        "Главные задачи: безопасно поддержать, дать простые прикладные шаги из базы, "
        "и мягко предложить анонимный созвон, когда человек готов. "
        "Правила: 2–4 предложения, затем ОДИН контекстный вопрос. "
        "Если мало информации — уточняй. "
        "Если есть риск для жизни — приоритизируй безопасность и предложи звонить 103/112. "
        "Различай режим: self (на «ты») и relatives (на «вы», «он/она»). "
        "Не повторяй шаблонные начала ответов. Не начинай каждый ответ одинаково. "
        "Избегай частого повторения фраз вроде «я понимаю», «важно», «это нормально», "
        "«мне жаль», «постарайтесь». "
        "Если похожая формулировка уже была недавно, начни ответ по-другому. "
        "Не дублируй одну и ту же мысль разными словами в соседних сообщениях. "
        "Пиши естественно, по-человечески, без канцелярита и без однообразных штампов."
    )

    if call_state == "text_only":
        system_prompt += (
            " Пользователь явно просил общаться только текстом и сейчас не готов к звонкам. "
            "Не предлагай созвон и не настаивай на звонке."
        )
    elif call_state == "accepted":
        system_prompt += (
            " Пользователь уже согласился на созвон. Не нужно повторно предлагать звонок, "
            "просто поддерживай его и помогай подготовиться."
        )
    elif call_state == "phone_received":
        system_prompt += (
            " Пользователь уже оставил номер телефона для обратного звонка. "
            "Не предлагай созвон повторно и не проси номер ещё раз. "
            "Можно продолжать разговор только в чате."
        )

    if mode == "self":
        role = "Режим: self — обращайся на «ты»."
    else:
        role = (
            "Режим: relatives — говори на «вы», описывая «он/она», "
            "аккуратно поддерживая родственника."
        )

    recent_replies = recent_replies or []
    banned_starts = extract_banned_starts(recent_replies)

    recent_replies_block = ""
    if recent_replies:
        recent_replies_block = "Недавние ответы консультанта:\n" + "\n".join(
            f"- {x[:180]}" for x in recent_replies[-3:]
        )

    banned_starts_block = ""
    if banned_starts:
        banned_starts_block = (
            "Не начинай новый ответ с этих недавних шаблонов: "
            + ", ".join(banned_starts)
        )

    user_content = (
        f"{role}\n"
        f"Цель шага: {goal}\n"
        f"История (последние):\n{short_history}\n\n"
        f"Тезисы из базы и правила:\n{kb_chunks}\n\n"
        f"{recent_replies_block}\n\n"
        f"{banned_starts_block}\n\n"
        f"{'ВНИМАНИЕ: риск-флаги обнаружены' if risk_detected else ''}\n\n"
        "Дай 2–4 предложения с прикладными советами. "
        "Не повторяй формулировки из недавних ответов консультанта. "
        "Не начинай ответ одинаково с предыдущими сообщениями. "
        "Заверши ОДНИМ контекстным вопросом. "
        "Говори просто, естественно, без канцелярита. Язык — русский."
    )

    payload = {
        "model": (cfg.get("model") or "gpt-4o-mini"),
        "temperature": cfg.get("temperature", 0.4),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 120 if fast else 220,
    }
    attempts = 1 if fast else 2
    req_timeout = 14 if fast else 28
    for attempt in range(attempts):
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=req_timeout,
            )
            r.raise_for_status()
            return (
                r.json()["choices"][0]["message"]["content"]
                .strip()
            )
        except Exception:
            if attempt == 0:
                time.sleep(0.3)
            else:
                raise

def detect_topic_gpt(
    cfg: Dict[str, Any],
    text: str,
    short_history: str = "",
    current_topic: Optional[str] = None,
) -> Optional[str]:
    allowed_topics = [
        "alcohol",
        "stimulants",
        "opioids",
        "cannabis",
        "gambling",
        "video_games",
        "bullying",
        "unknown",
    ]

    system_prompt = (
        "Ты — классификатор тем обращений для проекта Red Button. "
        "Определи ОСНОВНУЮ тему сообщения пользователя. "
        "Верни только JSON без пояснений и markdown. "
        "Допустимые topic: alcohol, stimulants, opioids, cannabis, gambling, video_games, bullying, unknown. "
        "Если тема неочевидна, но есть высокая вероятность школьной травли, унижений, давления со стороны сверстников, "
        "проблем с одноклассниками, конфликтов в школе вокруг ребёнка — выбирай bullying. "
        "Не выдумывай новые topic."
    )

    user_content = (
        f"Текущая тема в сессии: {current_topic or 'None'}\n"
        f"Короткая история:\n{short_history or '-'}\n\n"
        f"Текущее сообщение:\n{text}\n\n"
        "Верни JSON строго такого вида:\n"
        '{"topic":"bullying","confidence":0.91,"reason":"..."}'
    )

    payload = {
        "model": (cfg.get("model") or "gpt-4o-mini"),
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 120,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(2):
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=12,
            )
            r.raise_for_status()

            raw = r.json()["choices"][0]["message"]["content"].strip()
            data = json.loads(raw)

            topic = (data.get("topic") or "").strip()
            confidence = float(data.get("confidence") or 0)
            reason = (data.get("reason") or "").strip()

            if topic not in allowed_topics:
                logging.warning(
                    "TOPIC_GPT_INVALID topic=%r confidence=%s reason=%r text=%r",
                    topic, confidence, reason, text
                )
                return None

            if topic == "unknown" or confidence < 0.55:
                logging.info(
                    "TOPIC_GPT text=%r topic=unknown confidence=%.3f reason=%r",
                    text, confidence, reason
                )
                return None

            logging.info(
                "TOPIC_GPT text=%r topic=%s confidence=%.3f reason=%r",
                text, topic, confidence, reason
            )
            return topic

        except Exception:
            if attempt == 0:
                time.sleep(0.3)
            else:
                logging.exception("TOPIC_GPT_FAILED text=%r", text)
                return None

    return None


# ===================== Dialog helpers =====================
def push_history(s, role, text):
    s.setdefault("history", [])
    s["history"].append({"role": role, "text": text})
    s["history"] = s["history"][-6:]


def short_history_text(s):
    parts = []
    for h in s.get("history", [])[-4:]:
        who = "П" if h["role"] == "user" else "Д"
        parts.append(f"{who}: {h['text']}")
    return "\n".join(parts)

def recent_assistant_replies(s, limit=3) -> List[str]:
    items = []
    for h in reversed(s.get("history", [])):
        if h.get("role") == "assistant":
            txt = (h.get("text") or "").strip()
            if txt:
                items.append(txt)
        if len(items) >= limit:
            break
    return list(reversed(items))


def extract_banned_starts(replies: List[str]) -> List[str]:
    banned = []
    seen = set()

    starters = [
        "я понимаю",
        "понимаю",
        "важно",
        "это нормально",
        "мне жаль",
        "судя по вашему сообщению",
        "давайте разберём",
        "давайте разберем",
        "сейчас лучше",
        "то, что вы описываете",
    ]

    for txt in replies:
        low = txt.lower().strip()
        for s in starters:
            if low.startswith(s) and s not in seen:
                banned.append(s)
                seen.add(s)
    return banned


def diversify_reply(reply: str, recent_replies: List[str]) -> str:
    if not reply:
        return reply

    recent_low = [(x or "").lower().strip() for x in recent_replies if x]
    low = reply.lower().strip()

    replacements = {
        "я понимаю": [
            "Судя по вашей ситуации,",
            "То, что вы описываете,",
            "В такой ситуации",
            "Сейчас лучше сосредоточиться на том, чтобы",
        ],
        "важно": [
            "Сейчас лучше",
            "Полезнее всего сейчас",
            "Первым делом стоит",
            "В такой ситуации стоит",
        ],
        "это нормально": [
            "Такая реакция часто бывает в стрессовой ситуации,",
            "Многие в такой ситуации чувствуют похожее,",
            "На фоне стресса такая реакция возможна,",
        ],
        "мне жаль": [
            "Очень непросто через такое проходить.",
            "Похоже, вам сейчас действительно тяжело.",
            "То, что вы описываете, звучит очень болезненно.",
        ],
        "постарайтесь": [
            "Попробуйте сейчас",
            "Сейчас можно",
            "Для начала стоит",
            "Лучше сейчас",
        ],
    }
    for bad_start, variants in replacements.items():
        if low.startswith(bad_start):
            if any(r.startswith(bad_start) for r in recent_low[-2:]):
                for variant in variants:
                    vlow = variant.lower().strip()
                    if not any(r.startswith(vlow) for r in recent_low[-2:]):
                        rest = reply[len(bad_start):].lstrip(" ,—:-")
                        if variant.endswith((",", "—", ":")):
                            return f"{variant} {rest}".strip()
                        return f"{variant} {rest}".strip()
    return reply

def next_goal(stage):
    goals = [
        "триаж безопасности",
        "уточнить ситуацию",
        "уточнить шаблон/частоту",
        "выявить триггеры",
        "дать микро-шаг на 24ч",
        "подготовить к созвону",
    ]
    return goals[min(stage, len(goals) - 1)]


# ===================== Webhook =====================
def handle_incoming_message(
    chat_id,
    chat_type,
    user,
    text,
    *,
    message_id=None,
    update_id=None,
    msg=None,
):
    cfg = load_cfg()
    build_indexes()

    _web_chat = str(chat_id).startswith("web:")

    if update_id is not None and not _web_chat and not mark_update_processed(update_id):
        return {"ok": True}

    if msg is None:
        msg = {}

    if _web_chat:
        threading.Thread(target=upsert_user, args=(user,), daemon=True).start()
    else:
        upsert_user(user)

    # диагностика
    if text.lower() == "/whoami":
        tg_send(chat_id, f"Ваш user_id: <code>{user.get('id')}</code>")
        return {"ok": True}
    if text.lower() == "/isadmin":
        status = "ДА" if is_admin(user.get("id")) else "НЕТ"
        tg_send(
            chat_id,
            f"is_admin: {status}\nADMIN_IDS: {', '.join(sorted(ADMIN_IDS)) or '<empty>'}",
        )
        return {"ok": True}
    # показать chat_id текущего чата
    if text.lower() == "/here":
        tg_send(chat_id, f"chat_id этого чата: <code>{chat_id}</code>")
        return {"ok": True}
    # статистика по пользователям (только для админов)
    if is_admin(user.get("id")) and text.lower() in ("/stat", "/stats"):
        total, today_new = get_user_stats()
        tg_send(
            chat_id,
            "📊 Статистика по пользователям:\n"
            f"Всего: <b>{total}</b>\n"
            f"Новых за сегодня: <b>{today_new}</b>",
        )
        return {"ok": True}

    # подписка / отписка
    if text.lower() in ["/stop", "стоп", "отписаться"]:
        set_subscribed(user["id"], 0)
        tg_send(
            chat_id,
            "Вы отписались от рассылок. Чтобы вернуться — отправьте /start",
            remove_keyboard=True,
        )
        return {"ok": True}
    if text.lower() in ["/start", "start", "/subscribe"]:
        set_subscribed(user["id"], 1)

    # === ADMIN: старт добавления знаний ===
    if is_admin(user.get("id")) and text.lower() in ("/kb_add", "добавить"):
        set_admin_state(user["id"], "kb_add")
        tg_send(
            chat_id,
            "Ок. Пришли одним сообщением описание ситуации и комментарий в свободной форме. "
            "Я разберу и добавлю в базу знаний.",
        )
        return {"ok": True}

    # === ADMIN: приём текста знания (когда ожидаем) ===
    pending = get_admin_state(user["id"])
    if pending == "kb_add" and is_admin(user.get("id")):
        # возможность отменить режим добавления
        if text.lower() in ("/kb_cancel", "/cancel", "отмена"):
            clear_admin_state(user["id"])
            tg_send(
                chat_id,
                "Ок, отменил добавление знания. Можно начать заново командой /kb_add.",
            )
            return {"ok": True}

        rule, info = parse_admin_text(text)
        if not rule:
            tg_send(chat_id, f"⚠️ Не удалось обработать текст: {info}")
            clear_admin_state(user["id"])
            tg_send(
                chat_id,
                "Режим добавления знаний завершён. Попробуй ещё раз: /kb_add.",
            )
            return {"ok": True}

        ok, reason = validate_rule_json(rule)
        if not ok:
            tg_send(chat_id, f"⚠️ Не удалось сохранить: {reason}")
            clear_admin_state(user["id"])
            tg_send(
                chat_id,
                "Режим добавления знаний завершён. Можно переформулировать и снова /kb_add.",
            )
            return {"ok": True}

        res = save_rule_atomic(rule)
        if res == "duplicate":
            tg_send(
                chat_id,
                "Похоже, такое правило уже есть. Ничего не добавлял.",
            )
        else:
            build_indexes()
            tg_send(
                chat_id,
                "✅ Добавлено новое правило.\n"
                f"ID: {rule.get('rule_id')}\n"
                f"Тема: {rule.get('topic','auto')}",
            )
            if ADMIN_ALERT_CHAT_ID:
                short = (rule.get("if") or {}).get("summary", "")
                steps = ", ".join(
                    (rule.get("then") or {}).get("steps") or []
                )[:200]
                notify = (
                    "🧩 KB: добавлено правило \n"
                    f"ID: {rule.get('rule_id')}\n"
                    f"Тема: {rule.get('topic','auto')}\n"
                    f"IF: {short}\nTHEN: {steps}"
                )
                try:
                    requests.post(
                        f"{_tg_api_base()}/sendMessage",
                        data={
                            "chat_id": ADMIN_ALERT_CHAT_ID,
                            "text": notify,
                        },
                        timeout=15,
                    )
                except Exception:
                    logging.exception("Admin alert send failed")

        clear_admin_state(user["id"])
        return {"ok": True}

    # 🚧 дальше — только приватные диалоги, в группах их игнорируем
    if chat_type != "private":
        return {"ok": True}

    # === кнопка "Нужна помощь специалиста" ===
    #if text == cfg["buttons"]["specialist_help"]:
    #    specialist = get_specialist_phone(None)
    #
    #    tg_send(
    #        chat_id,
    #        f"Вы можете сразу связаться со специалистом: {specialist}\n\n"
    #        "Или нажмите кнопку ниже и отправьте свой номер телефона — "
    #        "мы передадим его специалисту, и вам перезвонят.",
    #        buttons=[
    #            [{"text": cfg["buttons"]["send_contact"], "request_contact": True}]
    #        ],
    #    )
    #    return {"ok": True}

    # === кнопка "Мне нужно чтобы мне позвонили" ===
    if _is_need_callback(text, cfg):
        tg_send_and_panel(
            chat_id,
            user,
            "Нажмите кнопку ниже, чтобы отправить свой номер телефона. "
            "Мы передадим его специалисту, и вам перезвонят.",
            buttons=[
                [{"text": cfg["buttons"]["send_contact"], "request_contact": True}]
            ],
        )
        s_tmp = load_session(user["id"]) or {}
        email_notify.notify_callback_email(
            user,
            s_tmp.get("topic"),
            platform=_detect_platform(chat_id, user),
            note="Кнопка: «Мне нужно чтобы мне позвонили»",
        )
        return {"ok": True}

    # сессия диалога
    s = load_session(user["id"])
    if not s:
        s = {
            "mode": None,
            "stage": 0,
            "max_turns": random.randint(
                cfg.get("max_turns_min", 5),
                cfg.get("max_turns_max", 7),
            ),
            "topic": None,
            "last_ts": int(time.time()),
            "history": [],
            "call_state": None,
        }

    # === если пользователь отправил контакт кнопкой Telegram ===
    if msg.get("contact") and str((msg.get("contact") or {}).get("user_id") or "") in ("", str(user.get("id"))):
        contact_phone = (msg.get("contact") or {}).get("phone_number") or ""
        return _accept_phone_lead(
            user, s, chat_id, contact_phone, contact_phone, _web_chat=_web_chat, cfg=cfg
        )

    # === номер телефона текстом — в любом этапе диалога ===
    phone_early = extract_phone_number(text)
    if phone_early and not msg.get("contact"):
        return _accept_phone_lead(
            user, s, chat_id, phone_early, text, _web_chat=_web_chat, cfg=cfg
        )

    # полный сброс
    if text.lower() in ("/start", "start"):
        s["mode"] = None
        s["stage"] = 0
        s["topic"] = None
        s["max_turns"] = random.randint(
            cfg.get("max_turns_min", 5),
            cfg.get("max_turns_max", 7),
        )
        s["history"] = []
        s["call_state"] = None
        save_session(user["id"], s)
        logging.info(
            "SESSION_SAVED user_id=%s stage=%s topic=%s",
            user.get("id"),
            s.get("stage"),
            s.get("topic"),
        )

        tg_send_and_panel(chat_id, user, cfg["start_message"], buttons=main_menu(cfg))
        return {"ok": True}

    # выбор режима self/relatives
    if s["mode"] is None:
        site_triage_answer = False
        if text == cfg["buttons"]["mode_self"]:
            s["mode"] = "self"
        elif text == cfg["buttons"]["mode_relative"]:
            s["mode"] = "relatives"
        elif _detect_platform(chat_id, user) == "site":
            lower = text.lower().strip()
            btn_yes = cfg["buttons"]["yes"].lower()
            btn_no = cfg["buttons"]["no"].lower()
            if lower in (btn_yes, btn_no):
                # Сессия могла сброситься (мобильный браузер) — это ответ на триаж
                s["mode"] = "self"
                site_triage_answer = True
            else:
                s["mode"] = "self"
                guess = detect_topic(
                    text,
                    cfg=cfg,
                    short_history=short_history_text(s),
                    current_topic=s.get("topic"),
                    skip_gpt=True,
                )
                if guess:
                    s["topic"] = guess
        else:
            tg_send_and_panel(
                chat_id,
                user,
                "Пожалуйста, выберите вариант на кнопках ниже.",
                buttons=main_menu(cfg),
            )
            return {"ok": True}
        save_session(user["id"], s)
        logging.info(
            "SESSION_SAVED user_id=%s stage=%s topic=%s",
            user.get("id"),
            s.get("stage"),
            s.get("topic"),
        )
        if site_triage_answer:
            pass  # ниже — обработка ответа «Да»/«Нет» на триаже
        else:
            lower_site = text.lower().strip()
            btn_yes_site = cfg["buttons"]["yes"].lower()
            btn_no_site = cfg["buttons"]["no"].lower()
            skip_triage = (
                _web_chat
                and len(lower_site) > 8
                and lower_site not in (btn_yes_site, btn_no_site)
            )
            if not skip_triage:
                tg_send_and_panel(
                    chat_id,
                    user,
                    cfg["triage_question"],
                    buttons=[
                        [
                            {"text": cfg["buttons"]["yes"]},
                            {"text": cfg["buttons"]["no"]},
                        ]
                    ],
                    remove_keyboard=True,
                )
                return {"ok": True}

    # === обработка ответов на предложение созвона ===
    if s.get("call_state") == "offered":
        lower = text.lower()
        btn_yes = cfg["buttons"]["call_yes"].lower()
        btn_no = cfg["buttons"]["call_no"].lower()
        text_only_phrases = [
            "пока текстом",
            "давайте пока текстом",
            "давайте текстом",
            "только текстом",
            "без звонка",
            "без созвона",
        ]

        if lower == btn_yes:
            s["call_state"] = "accepted"
            save_session(user["id"], s)
            email_notify.notify_callback_email(
                user,
                s.get("topic"),
                platform=_detect_platform(chat_id, user),
                note="Согласился на анонимный созвон",
            )
            tg_send_and_panel(
                chat_id,
                user,
                cfg.get(
                    "call_yes_reply",
                    "Хорошо, тогда я передам запрос специалисту на анонимный созвон.",
                ),
                remove_keyboard=True,
            )
            return {"ok": True}

        if lower == btn_no or any(p in lower for p in text_only_phrases):
            s["call_state"] = "text_only"
            save_session(user["id"], s)
            tg_send_and_panel(
                chat_id,
                user,
                cfg.get(
                    "call_no_reply",
                    "Хорошо, давайте пока пообщаемся здесь в чате. "
                    "Можете написать, что сейчас больше всего беспокоит?",
                ),
                remove_keyboard=True,
            )
            return {"ok": True}

        # любой другой текст после питча: считаем, что продолжаем только текстом
        s["call_state"] = "text_only"
        save_session(user["id"], s)
        # и дальше пойдём по обычному GPT-пайплайну

    if not panel_bot_enabled(chat_id):
        return {"ok": True}

    def push(role, txt):
        if role == "user" and not _web_chat:
            send_to_panel(
                chat_id,
                user,
                txt,
                "in",
                sender_type="user",
                telegram_message_id=msg.get("message_id"),
            )
        push_history(s, role, txt)
        if _web_chat:
            threading.Thread(
                target=save_message, args=(user["id"], role, txt), daemon=True
            ).start()
        else:
            save_message(user["id"], role, txt)

    push("user", text)

    # первый шаг: триаж безопасности
    if s["stage"] == 0:
        if s["topic"] is None:
            detected_topic = detect_topic(
                text,
                cfg=cfg,
                short_history=short_history_text(s),
                current_topic=s.get("topic"),
                skip_gpt=False,
            )
            logging.info(
                "TOPIC_CHECK user_id=%s text=%r detected=%s",
                user.get("id"),
                text,
                detected_topic
            )
            s["topic"] = detected_topic

        btn_yes = cfg["buttons"]["yes"].lower()
        btn_no = cfg["buttons"]["no"].lower()
        lower = text.lower().strip()
        if detect_risk(text) or lower == btn_yes:
            emergency_text = cfg["safety_hint"] + build_emergency_phone_block(s.get("topic"))
            tg_send_and_panel(chat_id, user, emergency_text)

        web_has_substance = (
            _web_chat
            and len(lower) > 8
            and lower not in (btn_yes, btn_no)
        )
        if web_has_substance:
            s["stage"] = 1
        else:
            tg_send_and_panel(chat_id, user, cfg["what_happened_question"])
            s["stage"] = 1
            save_session(user["id"], s)
            logging.info(
                "SESSION_SAVED user_id=%s stage=%s topic=%s",
                user.get("id"),
                s.get("stage"),
                s.get("topic"),
            )
            return {"ok": True}

    # определяем тему, если ещё нет
    if s["topic"] is None:
        s["topic"] = detect_topic(
            text,
            cfg=cfg,
            short_history=short_history_text(s),
            current_topic=s.get("topic"),
            skip_gpt=_web_chat,
        )

    kb_chunks = collect_kb_chunks(s["topic"], s["mode"])
    risk = detect_risk(text)
    recent_replies = recent_assistant_replies(s, limit=3)

    try:
        reply = gpt_reply(
            cfg=cfg,
            mode=s["mode"],
            goal=next_goal(s["stage"]),
            short_history=short_history_text(s),
            kb_chunks=kb_chunks,
            risk_detected=risk,
            recent_replies=recent_replies,
            call_state=s.get("call_state"),
            fast=_web_chat,
        )
    except Exception:
        logging.exception("GPT error")
        reply = (
            "Я с вами. Давайте шаг за шагом. "
            "Что прямо сейчас сложнее всего?"
        )

    reply = diversify_reply(reply, recent_replies)

    tg_send_and_panel(chat_id, user, reply)
    push("assistant", reply)

    # если достигли лимита ходов и ещё не предлагали созвон — предложить ОДИН РАЗ
    if not s.get("call_state") and s["stage"] >= s["max_turns"] - 1:
        call_text = cfg["call_pitch"]
        if s.get("topic") != "bullying":
            call_text += build_phone_block(s.get("topic"))

        tg_send_and_panel(
            chat_id,
            user,
            call_text,
            buttons=[
                [
                    {"text": cfg["buttons"]["call_yes"]},
                    {"text": cfg["buttons"]["call_no"]},
                ],
                [
                    {"text": cfg["buttons"]["send_contact"], "request_contact": True}
                ]
            ],
        )
        s["call_state"] = "offered"
        save_session(user["id"], s)
        return {"ok": True}

    s["stage"] += 1
    save_session(user["id"], s)
    logging.info(
        "SESSION_SAVED user_id=%s stage=%s topic=%s",
        user.get("id"),
        s.get("stage"),
        s.get("topic"),
    )
    return {"ok": True}


@app.route("/webhook", methods=["POST"])
def webhook():
    upd = request.json or {}
    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        return {"ok": True}
    return handle_incoming_message(
        msg["chat"]["id"],
        msg["chat"].get("type", ""),
        msg["from"],
        (msg.get("text") or "").strip(),
        message_id=msg.get("message_id"),
        update_id=upd.get("update_id"),
        msg=msg,
    )


# ===================== Export finished dialogs (15 min idle) =====================
IDLE_SEC = 15 * 60  # 15 минут


def _get_last_exported_ts(user_id: str) -> int:
    rows = pg_exec(
        "SELECT last_exported_ts FROM dialog_exports WHERE user_id=%s",
        (str(user_id),),
        fetch=True,
    )
    return int(rows[0][0]) if rows else 0


def _set_last_exported_ts(user_id: str, ts_val: int):
    pg_exec(
        """
    INSERT INTO dialog_exports(user_id, last_exported_ts, updated_at)
    VALUES (%s,%s,%s)
    ON CONFLICT (user_id) DO UPDATE SET last_exported_ts=EXCLUDED.last_exported_ts, updated_at=EXCLUDED.updated_at
    """,
        (str(user_id), int(ts_val), int(time.time())),
    )


def _format_dt(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))


def _make_transcript_txt(
    user: Dict[str, Any], msgs: List[tuple], last_ts: int
) -> bytes:
    # msgs: list of (role, text, ts)
    lines = []
    lines.append("=== Red Button: завершающий экспорт диалога ===")
    lines.append(f"user_id: {user.get('user_id')}")
    lines.append(f"username: @{user.get('username') or ''}")
    fn = f"{(user.get('first_name') or '').strip()} {(user.get('last_name') or '').strip()}".strip()
    lines.append(f"name: {fn}")
    lines.append(f"chat_id: {user.get('user_id')}")
    if msgs:
        lines.append(f"start: {_format_dt(msgs[0][2])}")
    lines.append(f"end:   {_format_dt(last_ts)}")
    lines.append("")
    for role, text, ts in msgs:
        tag = (
            "ПОЛЬЗОВАТЕЛЬ"
            if role == "user"
            else ("ДЕНИС" if role == "assistant" else role.upper())
        )
        when = _format_dt(ts)
        lines.append(f"[{when}] {tag}: {text}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_finished_dialogs_once():
    if not ADMIN_ALERT_CHAT_ID and not email_notify.email_enabled():
        return

    now = int(time.time())

    # берём все активные сессии
    rows = pg_exec(
        """
        SELECT s.user_id, s.last_ts, s.topic, u.username, u.first_name, u.last_name
        FROM sessions s
        JOIN users u ON u.user_id = s.user_id
        """,
        fetch=True,
    ) or []

    for user_id, last_ts, topic, username, first_name, last_name in rows:
        if not last_ts:
            continue

        # «диалог завершён»?
        if now - int(last_ts) < IDLE_SEC:
            continue

        last_exported = _get_last_exported_ts(user_id)

        # уже экспортировали этот конец?
        if int(last_ts) <= int(last_exported):
            continue

        # забираем сообщения с момента последнего экспорта (исключительно) до last_ts (включительно)
        msgs = pg_exec(
            """
            SELECT role, text, ts FROM messages
            WHERE user_id=%s AND ts>%s AND ts<=%s
            ORDER BY ts ASC
            """,
            (str(user_id), int(last_exported), int(last_ts)),
            fetch=True,
        ) or []

        if not msgs:
            _set_last_exported_ts(user_id, int(last_ts))
            continue

        # собираем и шлём документ
        user_card = {
            "user_id": str(user_id),
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        }

        body = _make_transcript_txt(
            user_card,
            [(r[0], r[1], int(r[2])) for r in msgs],
            int(last_ts),
        )

        filename = (
            f"dialog_{user_id}_"
            f"{time.strftime('%Y%m%d-%H%M', time.localtime(int(last_ts)))}.txt"
        )

        caption = (
            "Диалог завершён (15+ мин idle)\n"
            f"user_id: {user_id}\n"
            f"username: @{username or ''}\n"
            f"сообщений: {len(msgs)}"
        )

        ok_main = True
        if ADMIN_ALERT_CHAT_ID and TELEGRAM_TOKEN:
            ok_main = tg_send_document(
                ADMIN_ALERT_CHAT_ID, body, filename, caption=caption
            )

        ok_email = email_notify.notify_dialog_email(
            user_card, caption, body, filename, topic
        )

        ok_bullying = True
        if (
            topic == "bullying"
            and BULLYING_ALERT_CHAT_ID
            and str(BULLYING_ALERT_CHAT_ID) != str(ADMIN_ALERT_CHAT_ID)
        ):
            bullying_caption = caption + "\nтема: bullying"
            logging.info(
                "BULLYING_DUPLICATE_DIALOG_SEND user_id=%s chat_id=%s filename=%s",
                user_id,
                BULLYING_ALERT_CHAT_ID,
                filename,
            )
            ok_bullying = tg_send_document(
                BULLYING_ALERT_CHAT_ID, body, filename, caption=bullying_caption
            )
            if not ok_bullying:
                logging.warning(
                    "BULLYING_DIALOG_EXPORT_FAILED user_id=%s chat_id=%s filename=%s",
                    user_id,
                    BULLYING_ALERT_CHAT_ID,
                    filename,
                )

        if ok_main or ok_email:
            _set_last_exported_ts(user_id, int(last_ts))
        else:
            logging.warning(
                "DIALOG_EXPORT_FAILED user_id=%s tg=%s email=%s filename=%s",
                user_id,
                ok_main,
                ok_email,
                filename,
            )

def export_worker():
    while True:
        try:
            export_finished_dialogs_once()
        except Exception:
            logging.exception("export_worker failed")
        time.sleep(60)  # проверяем каждую минуту


# ===================== Health =====================
@app.route("/", methods=["GET"])
def health():
    tg_ok = bool(ADMIN_ALERT_CHAT_ID and TELEGRAM_TOKEN)
    return jsonify(
        {
            "ok": True,
            "email": email_notify.email_enabled(),
            "telegram": tg_ok,
            "max": max_notify.max_enabled(),
        }
    )


# ===================== MAIN =====================
def init_db_resilient(max_attempts: int = 60, delay: float = 10.0) -> None:
    """init_db с повторами: при кратковременной недоступности БД не падаем."""
    for attempt in range(1, max_attempts + 1):
        try:
            init_db()
            if attempt > 1:
                logging.info("init_db успешно с попытки %s", attempt)
            return
        except Exception as e:
            logging.warning(
                "init_db попытка %s/%s не удалась: %s — повтор через %.0fс",
                attempt, max_attempts, e, delay,
            )
            reset_pg_pool()
            time.sleep(delay)
    raise SystemExit("init_db: БД недоступна слишком долго — выходим (перезапустит watchdog)")


if email_notify.email_enabled():
    logging.info(
        "Email notifications ON -> %s",
        ", ".join(email_notify.alert_recipients()),
    )
else:
    logging.warning(
        "Email notifications OFF — задайте SMTP_* и ALERT_EMAIL_TO в Render Environment"
    )

if __name__ == "__main__":
    load_cfg()
    build_indexes()
    init_db_resilient()
    # стартуем фонового экспортёра
    t = threading.Thread(
        target=export_worker, name="export_worker", daemon=True
    )
    t.start()
    port = int(os.getenv("PORT", "8090"))
    host = os.getenv("HOST", "0.0.0.0")
    logging.info("Starting on %s:%s (webhook + /api/chat/*)", host, port)
    app.run(host=host, port=port)


