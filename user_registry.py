"""
Система доступа: белый список пользователей.
Сопоставление: имя в MAX → разрешённый пользователь.
user_id сохраняются в user_registry.json при первом входе.
"""
import json
import os
import logging

logger = logging.getLogger(__name__)

REGISTRY_FILE = "/opt/messenger-bot/user_registry.json"

# ── Белый список ──────────────────────────────────────────────────────────────
# name     — имя как в профиле MAX (или часть имени, регистр не важен)
# label    — как бот обращается к пользователю
# phones   — номера телефона (справочно, не используются в логике)
# is_admin — получает уведомления о чужих попытках зайти
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_USERS = [
    {"name": "Олеся",      "label": "Олеся",      "phones": ["79161748322"], "is_admin": False},
    {"name": "Андрей",     "label": "Андрей",      "phones": ["79199999958"], "is_admin": True},
    {"name": "Лилия",      "label": "Лилия",       "phones": ["79266919424"], "is_admin": False},
    {"name": "Сергей",     "label": "Сергей",      "phones": ["79262822829"], "is_admin": False},
    {"name": "Серёга",     "label": "Серёга",      "phones": ["79647877110"], "is_admin": False},
    {"name": "Серега",     "label": "Серёга",      "phones": ["79647877110"], "is_admin": False},
    {"name": "Ольга",      "label": "Ольга",       "phones": ["79636511239"], "is_admin": False},
    {"name": "Дашулечка",  "label": "Дашулечка",   "phones": ["79096817443"], "is_admin": False},
    {"name": "Даша",       "label": "Дашулечка",   "phones": ["79096817443"], "is_admin": False},
    {"name": "Дарья",      "label": "Дашулечка",   "phones": ["79096817443"], "is_admin": False},
]


def _load() -> dict:
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(registry: dict) -> None:
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def _match_by_name(display_name: str) -> dict | None:
    """Сопоставить имя профиля MAX с белым списком (нечёткое совпадение)."""
    dn = display_name.strip().lower()
    for user in ALLOWED_USERS:
        allowed = user["name"].lower()
        # точное совпадение, или одно содержит другое, или первое слово совпадает
        if allowed == dn or allowed in dn or dn in allowed:
            return user
        first_word = dn.split()[0] if dn.split() else ""
        if first_word and first_word == allowed:
            return user
    return None


def check_access(user_id: int, display_name: str) -> tuple[bool, str, bool, bool]:
    """
    Проверить доступ пользователя.
    Возвращает: (разрешён, имя_для_обращения, первый_вход, is_admin)
    """
    registry = _load()
    uid = str(user_id)

    # Уже известный пользователь
    if uid in registry:
        entry = registry[uid]
        return (
            entry.get("approved", False),
            entry.get("label", display_name),
            False,
            entry.get("is_admin", False),
        )

    # Новый пользователь — пробуем сопоставить по имени
    matched = _match_by_name(display_name)
    if matched:
        registry[uid] = {
            "label":        matched["label"],
            "max_name":     display_name,
            "approved":     True,
            "is_admin":     matched["is_admin"],
        }
        _save(registry)
        logger.info("Новый пользователь авторизован: %s (id=%s)", matched["label"], uid)
        return True, matched["label"], True, matched["is_admin"]

    # Неизвестный пользователь — блокируем, запоминаем
    registry[uid] = {
        "label":    display_name,
        "max_name": display_name,
        "approved": False,
        "is_admin": False,
    }
    _save(registry)
    logger.warning("Неизвестный пользователь заблокирован: %s (id=%s)", display_name, uid)
    return False, display_name, True, False


def get_admin_ids() -> list[int]:
    """Вернуть MAX user_id всех администраторов из реестра."""
    registry = _load()
    return [int(uid) for uid, data in registry.items() if data.get("is_admin")]


def approve_user(user_id: int) -> str | None:
    """Одобрить пользователя (команда /approve <id> от администратора)."""
    registry = _load()
    uid = str(user_id)
    if uid in registry:
        registry[uid]["approved"] = True
        label = registry[uid].get("label", uid)
        _save(registry)
        return label
    return None


def list_pending() -> list[dict]:
    """Список пользователей, ожидающих одобрения."""
    registry = _load()
    return [
        {"user_id": int(uid), "name": data.get("label", uid)}
        for uid, data in registry.items()
        if not data.get("approved")
    ]
