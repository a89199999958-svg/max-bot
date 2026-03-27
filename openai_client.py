"""
OpenAI клиент с поиском в интернете.
GPT-4o сам решает когда нужен поиск — через function calling.
"""
import os
import json
import logging
import tempfile
import httpx
from openai import AsyncOpenAI
from ddgs import DDGS

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты умный и добрый помощник по имени Макс. Отвечай на русском языке, объясняй просто и понятно, как будто объясняешь близкому человеку. Будь вежливым и терпеливым. Если не знаешь ответа — честно скажи об этом.",
)

# ── Инструмент поиска для GPT ─────────────────────────────────────────────────
SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Искать актуальную информацию в интернете. Используй когда нужно узнать: "
            "погоду, новости, курс валют, цены, расписание, события, текущее время/дату, "
            "или любые данные которые могут измениться."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос (лучше на русском)"
                }
            },
            "required": ["query"]
        }
    }
}


def _do_search(query: str) -> str:
    """Выполнить поиск в DuckDuckGo и вернуть результаты как текст."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "Поиск не дал результатов."
        lines = [f"Результаты поиска по запросу «{query}»:\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            body  = r.get("body", "")
            href  = r.get("href", "")
            lines.append(f"{i}. {title}\n   {body}\n   {href}\n")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Ошибка поиска: %s", e)
        return f"Не удалось выполнить поиск: {e}"


async def ask_gpt(messages: list[dict]) -> str:
    """
    Отправить историю диалога в GPT-4o.
    GPT сам решает когда нужен поиск в интернете (function calling).
    """
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    # Цикл: GPT может вызвать поиск несколько раз перед финальным ответом
    for _ in range(5):
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=full_messages,
            tools=[SEARCH_TOOL],
            tool_choice="auto",
            max_tokens=1500,
        )

        choice = response.choices[0]

        # GPT хочет выполнить поиск
        if choice.finish_reason == "tool_calls":
            tool_calls = choice.message.tool_calls
            full_messages.append(choice.message)  # сохраняем ответ ассистента с tool_calls

            for tc in tool_calls:
                if tc.function.name == "search_web":
                    args = json.loads(tc.function.arguments)
                    query = args.get("query", "")
                    logger.info("GPT ищет: %s", query)
                    search_result = _do_search(query)
                    # Возвращаем результат поиска GPT
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": search_result,
                    })
            continue  # следующая итерация — GPT даст ответ на основе поиска

        # GPT дал финальный ответ
        return choice.message.content.strip()

    return "Извини, не смог обработать запрос. Попробуй ещё раз."


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
    """Проанализировать изображение через GPT-4o Vision."""
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
