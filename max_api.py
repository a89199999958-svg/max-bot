"""
MAX Мессенджер API клиент.
Base URL: https://platform-api.max.ru
Авторизация: заголовок "Authorization: <token>" (без Bearer!)
"""
import os
import logging
import httpx

logger = logging.getLogger(__name__)

MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")
BASE_URL = "https://platform-api.max.ru"


def _headers() -> dict:
    # MAX API: просто токен, без "Bearer"
    return {"Authorization": MAX_BOT_TOKEN}


async def send_text(chat_id: int, text: str) -> None:
    chunks = _split_text(text, max_len=4000)
    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            resp = await client.post(
                f"{BASE_URL}/messages",
                headers=_headers(),
                params={"chat_id": chat_id},
                json={"text": chunk},
            )
            if resp.status_code not in (200, 201):
                logger.error("send_text error %s: %s", resp.status_code, resp.text)


async def send_typing(chat_id: int) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(
                f"{BASE_URL}/chats/{chat_id}/actions",
                headers=_headers(),
                json={"action": "typing_on"},
            )
        except Exception:
            pass


def _split_text(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    return chunks
