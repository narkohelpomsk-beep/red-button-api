# -*- coding: utf-8 -*-
"""
writer.py — запись нового правила в knowledge_base.json
"""
import os, json, time, shutil, tempfile
from typing import Dict

KB_PATH = os.path.join(os.path.dirname(__file__), "..", "knowledge_base.json")

def save_rule_atomic(rule: Dict) -> str:
    """Добавляет правило в knowledge_base.json (секция admin_rules) атомарно."""
    ts = int(time.time())
    rule["created_at"] = ts

    # Бэкап
    backup_path = KB_PATH + f".bak-{time.strftime('%Y%m%d-%H%M%S')}"
    if os.path.exists(KB_PATH):
        shutil.copy2(KB_PATH, backup_path)

    with open(KB_PATH, "r", encoding="utf-8") as f:
        kb = json.load(f)

    rules = kb.get("admin_rules", [])
    # простая дедупликация
    sig = (rule.get("if", {}).get("summary", "") + "".join(rule.get("then", {}).get("steps", [])[:1])).lower()
    for r in rules:
        sig2 = (r.get("if", {}).get("summary", "") + "".join(r.get("then", {}).get("steps", [])[:1])).lower()
        if sig2 == sig:
            return "duplicate"

    rules.append(rule)
    kb["admin_rules"] = rules

    # Атомарная запись
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=".kbtmp_", text=True)
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    shutil.move(tmp_path, KB_PATH)
    return rule["rule_id"]

