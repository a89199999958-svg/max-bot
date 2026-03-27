import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response

load_dotenv()

from handlers import dispatch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MAX Bot запущен. Ожидаю сообщения...")
    yield


app = FastAPI(title="MAX GPT-4o Bot", lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)

    update_type = body.get("update_type")

    # ── Пользователь запустил бота ─────────────────────────────────────────
    if update_type == "bot_started":
        chat_id = body.get("chat_id") or body.get("user", {}).get("user_id")
        user_name = body.get("user", {}).get("name", "друг")
        if chat_id:
            await dispatch(int(chat_id), user_name, "start")
        return {"ok": True}

    # ── Новое сообщение ────────────────────────────────────────────────────
    if update_type == "message_created":
        message = body.get("message", {})
        if not message:
            return {"ok": True}

        sender = message.get("sender", {})
        chat_id = message.get("recipient", {}).get("chat_id") or sender.get("user_id")
        if not chat_id:
            return {"ok": True}

        chat_id = int(chat_id)
        display_name = sender.get("name", "Незнакомец")
        body_msg = message.get("body", {})
        text = body_msg.get("text", "").strip()
        attachments = body_msg.get("attachments", [])

        if attachments:
            for att in attachments:
                att_type = att.get("type", "")
                payload = att.get("payload", {})

                if att_type == "audio":
                    audio_url = payload.get("url")
                    if audio_url:
                        await dispatch(chat_id, display_name, "voice", audio_url=audio_url)
                    else:
                        await _unsupported(chat_id, display_name)

                elif att_type == "image":
                    image_url = payload.get("url") or _best_photo(payload)
                    if image_url:
                        await dispatch(chat_id, display_name, "image",
                                       image_url=image_url, caption=text or None)
                    else:
                        await _unsupported(chat_id, display_name)
                else:
                    await _unsupported(chat_id, display_name)

        elif text:
            await dispatch(chat_id, display_name, "text", text=text)

    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok", "bot": "max-gpt4o"}


async def _unsupported(chat_id: int, display_name: str) -> None:
    from user_registry import check_access
    allowed, label, _, _ = check_access(chat_id, display_name)
    if allowed:
        from max_api import send_text
        await send_text(chat_id, f"Извини, {label}, я понимаю только текст, голосовые и фото!")


def _best_photo(payload: dict) -> str | None:
    photos = payload.get("photos", {})
    for size in ("1280", "960", "800", "640", "320"):
        if size in photos:
            return photos[size].get("url")
    return payload.get("url")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=False)
