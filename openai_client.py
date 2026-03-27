"""
OpenAI клиент с встроенным поиском OpenAI (Responses API).
Тот же поиск что используется в ChatGPT — читает страницы целиком,
перекрёстно проверяет источники, показывает ссылки.
"""
import os
import logging
import tempfile
import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты умный и добрый помощник по имени Макс. Отвечай на русском языке, объясняй просто и понятно, как будто объясняешь близкому человеку. Будь вежливым и терпеливым. Если не знаешь ответа — честно скажи об этом.",
)


async def ask_gpt(messages: list[dict]) -> str:
    """
    Отправить запрос через Responses API с встроенным поиском OpenAI.
    GPT сам решает когда нужен поиск — поведение идентично ChatGPT.
    """
    # Конвертируем историю диалога в единый текст для Responses API
    # (Responses API принимает input как строку или список)
    try:
        response = await client.responses.create(
            model="gpt-4o",
            instructions=SYSTEM_PROMPT,
            input=_messages_to_input(messages),
            tools=[{"type": "web_search_preview"}],
        )
        # Извлечь текст из ответа
        return _extract_text(response)
    except Exception as e:
        # Если Responses API недоступен — fallback на Chat Completions без поиска
        logger.warning("Responses API недоступен (%s), fallback на Chat Completions", e)
        return await _ask_gpt_fallback(messages)


def _messages_to_input(messages: list[dict]) -> list[dict]:
    """Конвертировать историю в формат Responses API."""
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Пропускаем tool-сообщения (не нужны в Responses API)
        if role in ("user", "assistant"):
            if isinstance(content, str):
                result.append({"role": role, "content": content})
            elif isinstance(content, list):
                # Мультимодальный контент (фото) — берём только текст для истории
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                if text_parts:
                    result.append({"role": role, "content": " ".join(text_parts)})
    return result if result else [{"role": "user", "content": "Привет"}]


def _extract_text(response) -> str:
    """Извлечь текстовый ответ из объекта Responses API."""
    text_parts = []
    for item in response.output:
        if hasattr(item, "type") and item.type == "message":
            for part in item.content:
                if hasattr(part, "type") and part.type == "output_text":
                    text_parts.append(part.text)
    return "\n".join(text_parts).strip() or "Не удалось получить ответ."


async def _ask_gpt_fallback(messages: list[dict]) -> str:
    """Fallback: Chat Completions без поиска."""
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        m for m in messages if m.get("role") in ("user", "assistant")
    ]
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=full_messages,
        max_tokens=1500,
    )
    return response.choices[0].message.content.strip()


async def transcribe_voice(audio_url: str, bot_token: str) -> str:
    """Скачать голосовое из MAX и расшифровать через Whisper."""
    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.get(
            audio_url,
            headers={"Authorization": bot_token},
            follow_redirects=True,
        )
        resp.raise_for_status()
        audio_bytes = resp.content

    content_type = resp.headers.get("content-type", "")
    if "mpeg" in content_type or "mp3" in content_type:
        suffix = ".mp3"
    elif "mp4" in content_type or "aac" in content_type:
        suffix = ".mp4"
    elif "webm" in content_type:
        suffix = ".webm"
    else:
        suffix = ".ogg"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru",
            )
        return transcript.text.strip()
    finally:
        os.unlink(tmp_path)


async def describe_image(image_url: str, user_text: str | None = None) -> str:
    """Проанализировать изображение через GPT-4o Vision (Chat Completions)."""
    question = user_text if user_text else "Что изображено на этом фото? Опиши подробно."
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        max_tokens=1500,
    )
    return response.choices[0].message.content.strip()
