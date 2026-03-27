import os
import logging
from collections import defaultdict, deque

from max_api import send_text, send_typing
from openai_client import ask_gpt, transcribe_voice, describe_image

logger = logging.getLogger(__name__)

HISTORY_LENGTH = int(os.getenv("HISTORY_LENGTH", "20"))
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")

_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))


def _get_history(chat_id: int) -> list[dict]:
    return list(_history[chat_id])


def _add_to_history(chat_id: int, role: str, content) -> None:
    _history[chat_id].append({"role": role, "content": content})


async def handle_text(chat_id: int, text: str) -> None:
    await send_typing(chat_id)
    _add_to_history(chat_id, "user", text)
    try:
        reply = await ask_gpt(_get_history(chat_id))
        _add_to_history(chat_id, "assistant", reply)
        await send_text(chat_id, reply)
    except Exception as exc:
        logger.exception("GPT error: %s", exc)
        await send_text(chat_id, "Произошла ошибка. Попробуй ещё раз чуть позже.")


async def handle_voice(chat_id: int, audio_url: str) -> None:
    await send_typing(chat_id)
    try:
        transcribed = await transcribe_voice(audio_url, MAX_BOT_TOKEN)
        if not transcribed:
            await send_text(chat_id, "Не удалось распознать голосовое. Попробуй ещё раз.")
            return
        logger.info("Voice [chat %s]: %s", chat_id, transcribed[:100])
        await send_text(chat_id, f"🎤 Распознал: «{transcribed}»")
        _add_to_history(chat_id, "user", transcribed)
        reply = await ask_gpt(_get_history(chat_id))
        _add_to_history(chat_id, "assistant", reply)
        await send_text(chat_id, reply)
    except Exception as exc:
        logger.exception("Voice error: %s", exc)
        await send_text(chat_id, "Ошибка при обработке голосового. Попробуй ещё раз.")


async def handle_image(chat_id: int, image_url: str, caption: str | None = None) -> None:
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
        await send_text(chat_id, "Не удалось обработать фото. Попробуй ещё раз.")


async def handle_bot_started(chat_id: int, user_name: str) -> None:
    greeting = (
        f"Привет, {user_name}!\n\n"
        "Я — Макс, твой умный помощник. Вот что я умею:\n\n"
        "✉️ Отвечаю на любые вопросы текстом\n"
        "🎤 Понимаю голосовые сообщения\n"
        "📷 Анализирую фотографии\n\n"
        "Просто напиши или скажи что тебя интересует!"
    )
    await send_text(chat_id, greeting)
