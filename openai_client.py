import os
import logging
import tempfile
import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты умный и добрый помощник по имени Макс. Отвечай на русском языке, объясняй просто и понятно.",
)


async def ask_gpt(messages: list[dict]) -> str:
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=full_messages,
        max_tokens=1500,
    )
    return response.choices[0].message.content.strip()


async def transcribe_voice(audio_url: str, bot_token: str) -> str:
    async with httpx.AsyncClient(timeout=60) as http:
        resp = await http.get(
            audio_url,
            headers={"Authorization": f"Bearer {bot_token}"},
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
