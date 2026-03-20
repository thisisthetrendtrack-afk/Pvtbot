"""Telegram bot that connects user media to ModelsLab motion control."""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

API_URL = "https://modelslab.com/api/v6/video/kling_motion_control"
FETCH_URL = "https://modelslab.com/api/v6/video/fetch"

(
    WAITING_CODE,
    WAITING_IMAGE,
    WAITING_VIDEO,
    WAITING_PROMPT,
    WAITING_DURATION,
    WAITING_MODE,
) = range(6)

VERIFIED_USERS: set[int] = set()


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    modelslab_api_key: str
    access_code: str

    @property
    def access_required(self) -> bool:
        return bool(self.access_code)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def _required_any_env(*names: str) -> str:
    value = _optional_env(*names, default="")
    if value:
        return value
    raise RuntimeError(
        "Missing required environment variable. Set one of: "
        + ", ".join(names)
    )


def load_dotenv(dotenv_path: str = ".env") -> None:
    """Load KEY=VALUE lines from .env into process env if absent."""
    path = Path(dotenv_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        telegram_token=_required_any_env(
            "TELEGRAM_TOKEN",
            "BOT_TOKEN",
            "TELEGRAM_BOT_TOKEN",
        ),
        modelslab_api_key=_required_any_env(
            "MODELSLAB_API_KEY",
            "MODELSLAB_KEY",
            "ML_API_KEY",
        ),
        access_code=_optional_env("ACCESS_CODE", default="").strip(),
    )


def is_verified(user_id: int, settings: Settings) -> bool:
    return (not settings.access_required) or user_id in VERIFIED_USERS


def menu_text() -> str:
    return (
        "Access granted.\n\n"
        "Kling Motion Control Bot\n"
        "Commands:\n"
        "/generate - Start a new generation\n"
        "/help - How to use\n"
        "/cancel - Cancel current session"
    )


def help_text() -> str:
    return (
        "How it works:\n\n"
        "1) Send /generate\n"
        "2) Upload character image (PNG or JPG)\n"
        "3) Upload reference motion video (MP4/MOV)\n"
        "4) Enter scene prompt\n"
        "5) Choose duration\n"
        "6) Choose mode\n\n"
        "The bot sends the request to ModelsLab and returns the generated video."
    )


def call_modelslab(settings: Settings, payload: dict) -> dict:
    response = requests.post(
        API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "init_image": payload["image_url"],
            "motion_video": payload["video_url"],
            "duration": payload["duration"],
            "motion_mode": payload["mode"],
            "webhook": None,
            "track_id": None,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def fetch_result(settings: Settings, request_id: str) -> dict:
    response = requests.post(
        FETCH_URL,
        json={"key": settings.modelslab_api_key, "request_id": request_id},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


async def poll_result(
    settings: Settings,
    request_id: str,
    poll_interval: int = 10,
    max_wait: int = 420,
) -> Optional[str]:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        data = await asyncio.to_thread(fetch_result, settings, request_id)
        status = str(data.get("status", "")).lower()
        if status == "success":
            output = data.get("output") or []
            return output[0] if output else None
        if status in {"failed", "error"}:
            logger.error("ModelsLab generation failed: %s", data)
            return None
        await asyncio.sleep(poll_interval)
    return None


def mode_display(mode: str) -> str:
    return "PRO" if mode == "pro" else "STANDARD"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id

    if is_verified(user_id, settings):
        await update.message.reply_text(menu_text())
        return ConversationHandler.END

    await update.message.reply_text("This bot is private. Enter access code:")
    return WAITING_CODE


async def check_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if update.message.text.strip() == settings.access_code:
        VERIFIED_USERS.add(update.effective_user.id)
        await update.message.reply_text(menu_text())
        return ConversationHandler.END

    await update.message.reply_text("Wrong access code. Try again.")
    return WAITING_CODE


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return
    await update.message.reply_text(help_text())


async def generate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "Step 1/5: Send character image (JPG/PNG)."
    )
    return WAITING_IMAGE


async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    image_file = None
    if update.message.photo:
        image_file = update.message.photo[-1]
    elif update.message.document and update.message.document.mime_type in {
        "image/jpeg",
        "image/png",
    }:
        image_file = update.message.document

    if image_file is None:
        await update.message.reply_text("Please send a JPG or PNG image.")
        return WAITING_IMAGE

    tg_file = await context.bot.get_file(image_file.file_id)
    context.user_data["image_url"] = tg_file.file_path
    await update.message.reply_text("Step 2/5: Send reference motion video (MP4/MOV).")
    return WAITING_VIDEO


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    video_file = None
    if update.message.video:
        video_file = update.message.video
    elif update.message.document and str(update.message.document.mime_type).startswith("video/"):
        video_file = update.message.document

    if video_file is None:
        await update.message.reply_text("Please send a video file (MP4/MOV).")
        return WAITING_VIDEO

    tg_file = await context.bot.get_file(video_file.file_id)
    context.user_data["video_url"] = tg_file.file_path
    await update.message.reply_text("Step 3/5: Enter your prompt text.")
    return WAITING_PROMPT


async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_PROMPT

    context.user_data["prompt"] = prompt
    keyboard = [[
        InlineKeyboardButton("5 seconds", callback_data="dur_5"),
        InlineKeyboardButton("10 seconds", callback_data="dur_10"),
    ]]
    await update.message.reply_text(
        "Step 4/5: Choose duration.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_DURATION


async def receive_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["duration"] = int(query.data.split("_")[1])

    keyboard = [[
        InlineKeyboardButton("Standard", callback_data="mode_std"),
        InlineKeyboardButton("Pro", callback_data="mode_pro"),
    ]]
    await query.edit_message_text(
        "Step 5/5: Choose quality mode.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_MODE


async def receive_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    chosen = query.data.split("_")[1]
    context.user_data["mode"] = chosen
    await query.edit_message_text("Generating video with ModelsLab. Please wait...")

    payload = dict(context.user_data)
    try:
        created = await asyncio.to_thread(call_modelslab, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await send_video_result(context, query.message.chat_id, output[0], payload)
                return ConversationHandler.END

        request_id = created.get("id") or created.get("request_id")
        if not request_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Unexpected ModelsLab response: {created}",
            )
            return ConversationHandler.END

        video_url = await poll_result(settings, request_id=request_id)
        if not video_url:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Generation failed or timed out. Please try /generate again.",
            )
            return ConversationHandler.END

        await send_video_result(context, query.message.chat_id, video_url, payload)
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("ModelsLab call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"API error: {exc}",
        )
        return ConversationHandler.END


async def send_video_result(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_url: str,
    payload: dict,
) -> None:
    caption = (
        "Video is ready.\n"
        f"Prompt: {payload.get('prompt', '')}\n"
        f"Duration: {payload.get('duration', '?')}s | Mode: {mode_display(payload.get('mode', 'std'))}"
    )
    try:
        await context.bot.send_video(
            chat_id=chat_id,
            video=video_url,
            caption=caption,
        )
    except Exception:  # noqa: BLE001
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Video ready: {video_url}\n\n{caption}",
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Send /generate to start again.")
    return ConversationHandler.END


async def fallback_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Follow the steps or send /cancel.")


def main() -> None:
    try:
        settings = load_settings()
    except RuntimeError as exc:
        logger.error("%s", exc)
        logger.error(
            "Set TELEGRAM_TOKEN (or BOT_TOKEN) and MODELSLAB_API_KEY "
            "(or MODELSLAB_KEY). You can also put them in a .env file."
        )
        raise SystemExit(1) from exc

    app = Application.builder().token(settings.telegram_token).build()
    app.bot_data["settings"] = settings

    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, check_code)
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    gen_conv = ConversationHandler(
        entry_points=[CommandHandler("generate", generate_start)],
        states={
            WAITING_IMAGE: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_image)],
            WAITING_VIDEO: [MessageHandler(filters.VIDEO | filters.Document.ALL, receive_video)],
            WAITING_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)],
            WAITING_DURATION: [CallbackQueryHandler(receive_duration, pattern=r"^dur_")],
            WAITING_MODE: [CallbackQueryHandler(receive_mode, pattern=r"^mode_")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, fallback_msg),
        ],
        allow_reentry=True,
    )

    app.add_handler(auth_conv)
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(gen_conv)

    logger.info("Bot started. Access code enabled: %s", settings.access_required)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
