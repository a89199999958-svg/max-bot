"""
Обработчики сообщений с проверкой доступа и обращением по имени.
"""
import os
import logging
from collections import defaultdict, deque

from max_api import send_text, send_typing
from openai_client import ask_gpt, transcribe_voice, describe_image
from user_registry import check_access, get_admin_ids, approve_user, list_pending

logger = logging.getLogger(__name__)

HISTORY_LENGTH = int(os.getenv("HISTORY_LENGTH", "20"))
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")

_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))


def _get_history(chat_id: int) -> list[dict]:
    return list(_history[chat_id])


def _add_to_history(chat_id: int, role: str, content) -> None:
    _history[chat_id].append({"role": role, "content": content})


# ── Уведомление администраторов ───────────────────────────────────────────────

async def _notify_admins(text: str) -> None:
    """Отправить уведомление всем администраторам."""
    admin_ids = get_admin_ids()
    if not admin_ids:
        logger.warning("Нет зарегистрированных администраторов для уведомления!")
        return
    for admin_id in admin_ids:
        await send_text(admin_id, text)


# ── Точка входа: проверка доступа ─────────────────────────────────────────────

async def dispatch(chat_id: int, display_name: str, message_type: str, **kwargs) -> None:
    """
    Проверить доступ пользователя, затем передать сообщение нужному обработчику.
    message_type: 'text' | 'voice' | 'image' | 'start'
    """
    allowed, label, is_new, is_admin = check_access(chat_id, display_name)

    if not allowed:
        # Сообщение незнакомцу
        await send_text(
            chat_id,
            "Извини, этот бот только для семьи. 🔒\n\n"
            "Если ты думаешь, что это ошибка — напиши Андрею."
        )
        # Уведомление администратору
        await _notify_admins(
            f"⚠️ Попытка доступа!\n\n"
            f"Пользователь: {display_name}\n"
            f"MAX user_id: {chat_id}\n\n"
            f"Чтобы добавить — напиши боту:\n/approve {chat_id}"
        )
        return

    # Первый раз — приветствие
    if is_new and message_type == "start":
        await _greet(chat_id, label)
        return

    # Обработка по типу сообщения
    if message_type == "start":
        await _greet(chat_id, label)
    elif message_type == "text":
        text = kwargs.get("text", "")
        # Команды администратора
        if is_admin and text.startswith("/"):
            await _handle_admin_command(chat_id, text, label)
        else:
            await handle_text(chat_id, text, label)
    elif message_type == "voice":
        await handle_voice(chat_id, kwargs.get("audio_url", ""), label)
    elif message_type == "image":
        await handle_image(chat_id, kwargs.get("image_url", ""), label, kwargs.get("caption"))


# ── Приветствие ───────────────────────────────────────────────────────────────

async def _greet(chat_id: int, label: str) -> None:
    greeting = (
        f"Привет, {label}! 👋\n\n"
        "Я — Макс, твой умный помощник. Вот что я умею:\n\n"
        "✉️ Отвечаю на любые вопросы\n"
        "🎤 Понимаю голосовые сообщения\n"
        "📷 Анализирую фотографии\n\n"
        "Просто напиши или скажи что тебя интересует!"
    )
    await send_text(chat_id, greeting)


# ── Команды администратора ────────────────────────────────────────────────────

async def _handle_admin_command(chat_id: int, text: str, label: str) -> None:
    parts = text.strip().split()
    cmd = parts[0].lower()

    if cmd == "/approve" and len(parts) == 2:
        try:
            target_id = int(parts[1])
        except ValueError:
            await send_text(chat_id, "Используй: /approve <user_id>")
            return
        name = approve_user(target_id)
        if name:
            await send_text(chat_id, f"✅ Пользователь {name} (id {target_id}) одобрен!")
            await send_text(target_id, f"Привет! Андрей добавил тебя — теперь я в твоём распоряжении! 🎉\n\nПиши мне что угодно, я помогу!")
        else:
            await send_text(chat_id, f"Пользователь с id {target_id} не найден в реестре.")

    elif cmd == "/pending":
        pending = list_pending()
        if not pending:
            await send_text(chat_id, "Нет пользователей, ожидающих одобрения.")
        else:
            lines = [f"Ожидают одобрения ({len(pending)}):\n"]
            for p in pending:
                lines.append(f"• {p['name']} — /approve {p['user_id']}")
            await send_text(chat_id, "\n".join(lines))

    elif cmd == "/help":
        await send_text(chat_id,
            "Команды администратора:\n\n"
            "/pending — список ожидающих\n"
            "/approve <id> — одобрить пользователя\n"
            "/help — эта справка\n\n"
            "Все остальные сообщения обрабатывает GPT как обычно."
        )
    else:
        # Обычный текст который начинается с /? Отдаём GPT
        await handle_text(chat_id, text, label)


# ── GPT обработчики ───────────────────────────────────────────────────────────

async def handle_text(chat_id: int, text: str, label: str) -> None:
    await send_typing(chat_id)
    _add_to_history(chat_id, "user", text)
    try:
        reply = await ask_gpt(_get_history(chat_id))
        _add_to_history(chat_id, "assistant", reply)
        await send_text(chat_id, reply)
    except Exception as exc:
        logger.exception("GPT error: %s", exc)
        await send_text(chat_id, f"Извини, {label}, произошла ошибка. Попробуй ещё раз.")


async def handle_voice(chat_id: int, audio_url: str, label: str) -> None:
    await send_typing(chat_id)
    try:
        transcribed = await transcribe_voice(audio_url, MAX_BOT_TOKEN)
        if not transcribed:
            await send_text(chat_id, f"Не смог распознать голосовое, {label}. Попробуй ещё раз.")
            return
        logger.info("Voice [%s]: %s", label, transcribed[:100])
        await send_text(chat_id, f"🎤 Распознал: «{transcribed}»")
        _add_to_history(chat_id, "user", transcribed)
        reply = await ask_gpt(_get_history(chat_id))
        _add_to_history(chat_id, "assistant", reply)
        await send_text(chat_id, reply)
    except Exception as exc:
        logger.exception("Voice error: %s", exc)
        await send_text(chat_id, f"Ошибка при обработке голосового, {label}. Попробуй ещё раз.")


async def handle_image(chat_id: int, image_url: str, label: str, caption: str | None = None) -> None:
    await send_typing(chat_id)
    try:
        reply = await describe_image(image_url, caption)
        _add_to_history(chat_id, "user", [
            {"type": "text", "text": caption or "Что на фото?"},
            {"type": "image_url", "image_url": {"url": image_url}},
        ])
        _add_to_history(chat_id, "assistant", reply)
        await send_text(chat_id, reply)
    except Exception as exc:
        logger.exception("Image error: %s", exc)
        await send_text(chat_id, f"Ошибка при обработке фото, {label}. Попробуй ещё раз.")
