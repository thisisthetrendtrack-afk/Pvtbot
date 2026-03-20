"""Telegram bot that connects user media to ModelsLab motion control."""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

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

KLING_API_URL = "https://modelslab.com/api/v7/video-fusion/motion-control"
KLING_FETCH_URL_TEMPLATE = "https://modelslab.com/api/v7/video-fusion/fetch/{request_id}"
KLING_MODEL_ID = "kling-v3-motion-control"
KLING_CHARACTER_ORIENTATION = "image"

LTX_API_URL = "https://modelslab.com/api/v6/video/text2video_ultra"
LTX_FETCH_URL_TEMPLATE = "https://modelslab.com/api/v6/video/fetch/{request_id}"
LTX_MODEL_ID = "ltx-2.3"
LTX_RESOLUTIONS = ("1:1", "16:9", "9:16")
MENU_BACK_CALLBACK = "menu_back"

(
    WAITING_CODE,
    WAITING_IMAGE,
    WAITING_VIDEO,
    WAITING_PROMPT,
    WAITING_LTX_PROMPT,
    WAITING_LTX_RESOLUTION,
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
        "ModelsLab AI Studio\n"
        "Professional generation menu\n\n"
        "Choose one workflow:"
    )


def help_text() -> str:
    return (
        "How it works:\n\n"
        "Kling Motion Control (/generate)\n"
        "1) Upload character image (PNG/JPG)\n"
        "2) Upload reference motion video (MP4/MOV)\n"
        "3) Enter prompt\n\n"
        "LTX 2.3 Text-to-Video (/ltx)\n"
        "1) Enter prompt\n"
        "2) Choose aspect ratio (1:1 / 16:9 / 9:16)\n\n"
        "Open main menu anytime with /menu\n\n"
        "The bot sends your request to ModelsLab and returns the generated video."
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🖼 Text to Image", callback_data="menu_t2i")],
            [InlineKeyboardButton("🎬 Text to Video", callback_data="menu_t2v")],
            [InlineKeyboardButton("🧷 Image to Video", callback_data="menu_i2v")],
        ]
    )


def text_to_video_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("LTX 2.3 (Text to Video)", callback_data="menu_start_ltx")],
            [InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)],
        ]
    )


def image_to_video_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Kling 3.0 Motion Control", callback_data="menu_start_kling"
                )
            ],
            [InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)],
        ]
    )


def back_only_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)]]
    )


async def send_main_menu(update: Update) -> None:
    if update.message:
        await update.message.reply_text(
            menu_text(),
            reply_markup=main_menu_keyboard(),
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            menu_text(),
            reply_markup=main_menu_keyboard(),
        )


def call_modelslab_kling(settings: Settings, payload: dict) -> dict:
    response = requests.post(
        KLING_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "init_image": payload["image_url"],
            "init_video": payload["video_url"],
            "character_orientation": KLING_CHARACTER_ORIENTATION,
            "model_id": KLING_MODEL_ID,
            "track_id": None,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def call_modelslab_ltx(settings: Settings, payload: dict) -> dict:
    response = requests.post(
        LTX_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "model_id": LTX_MODEL_ID,
            "resolution": payload["resolution"],
            "negative_prompt": payload.get("negative_prompt", ""),
            "webhook": None,
            "track_id": None,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def fetch_result_v7(settings: Settings, request_id: str) -> dict:
    response = requests.post(
        KLING_FETCH_URL_TEMPLATE.format(request_id=request_id),
        json={"key": settings.modelslab_api_key},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_result_v6(settings: Settings, request_id: str) -> dict:
    response = requests.post(
        LTX_FETCH_URL_TEMPLATE.format(request_id=request_id),
        json={"key": settings.modelslab_api_key},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


async def poll_result(
    settings: Settings,
    request_id: str,
    fetch_fn: Callable[[Settings, str], dict],
    poll_interval: int = 10,
    max_wait: int = 420,
) -> Optional[str]:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        data = await asyncio.to_thread(fetch_fn, settings, request_id)
        status = str(data.get("status", "")).lower()
        if status == "success":
            output = data.get("output") or []
            return output[0] if output else None
        if status in {"failed", "error"}:
            logger.error("ModelsLab generation failed: %s", data)
            return None
        await asyncio.sleep(poll_interval)
    return None


def telegram_file_url(settings: Settings, file_path: str) -> str:
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    return f"https://api.telegram.org/file/bot{settings.telegram_token}/{file_path}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id

    if is_verified(user_id, settings):
        await send_main_menu(update)
        return ConversationHandler.END

    await update.message.reply_text("This bot is private. Enter access code:")
    return WAITING_CODE


async def check_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if update.message.text.strip() == settings.access_code:
        VERIFIED_USERS.add(update.effective_user.id)
        await send_main_menu(update)
        return ConversationHandler.END

    await update.message.reply_text("Wrong access code. Try again.")
    return WAITING_CODE


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return
    await update.message.reply_text(help_text())


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return
    await send_main_menu(update)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return

    data = query.data
    if data == "menu_t2i":
        await query.edit_message_text(
            "🖼 Text to Image\n\nThis module is coming soon.",
            reply_markup=back_only_keyboard(),
        )
        return

    if data == "menu_t2v":
        await query.edit_message_text(
            "🎬 Text to Video\n\nChoose a model:",
            reply_markup=text_to_video_keyboard(),
        )
        return

    if data == "menu_i2v":
        await query.edit_message_text(
            "🧷 Image to Video\n\nChoose a model:",
            reply_markup=image_to_video_keyboard(),
        )
        return

    if data == MENU_BACK_CALLBACK:
        await send_main_menu(update)


async def generate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "Step 1/3: Send character image (JPG/PNG)."
    )
    return WAITING_IMAGE


async def generate_start_from_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text(
        "Kling 3.0 Motion Control\n\nStep 1/3: Send character image (JPG/PNG)."
    )
    return WAITING_IMAGE


async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
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
    context.user_data["image_url"] = telegram_file_url(settings, tg_file.file_path)
    await update.message.reply_text("Step 2/3: Send reference motion video (MP4/MOV).")
    return WAITING_VIDEO


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    video_file = None
    if update.message.video:
        video_file = update.message.video
    elif update.message.document and str(update.message.document.mime_type).startswith("video/"):
        video_file = update.message.document

    if video_file is None:
        await update.message.reply_text("Please send a video file (MP4/MOV).")
        return WAITING_VIDEO

    tg_file = await context.bot.get_file(video_file.file_id)
    context.user_data["video_url"] = telegram_file_url(settings, tg_file.file_path)
    await update.message.reply_text("Step 3/3: Enter your prompt text.")
    return WAITING_PROMPT


async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_PROMPT

    context.user_data["prompt"] = prompt
    await update.message.reply_text("Generating video with ModelsLab. Please wait...")

    payload = dict(context.user_data)
    try:
        created = await asyncio.to_thread(call_modelslab_kling, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await send_video_result(
                    context,
                    update.message.chat_id,
                    output[0],
                    payload,
                    model_name="Kling 3.0 Motion Control",
                )
                return ConversationHandler.END

        request_id = created.get("id") or created.get("request_id")
        if not request_id:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=f"Unexpected ModelsLab response: {created}",
            )
            return ConversationHandler.END

        video_url = await poll_result(
            settings,
            request_id=request_id,
            fetch_fn=fetch_result_v7,
        )
        if not video_url:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text="Generation failed or timed out. Please try /generate again.",
            )
            return ConversationHandler.END

        await send_video_result(
            context,
            update.message.chat_id,
            video_url,
            payload,
            model_name="Kling 3.0 Motion Control",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("ModelsLab call failed")
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=f"API error: {exc}",
        )
        return ConversationHandler.END


async def ltx_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text("LTX 2.3 Step 1/2: Enter your prompt text.")
    return WAITING_LTX_PROMPT


async def ltx_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text("LTX 2.3 Step 1/2: Enter your prompt text.")
    return WAITING_LTX_PROMPT


async def receive_ltx_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_LTX_PROMPT

    context.user_data["prompt"] = prompt
    keyboard = [[
        InlineKeyboardButton("1:1", callback_data="ltx_res_1:1"),
        InlineKeyboardButton("16:9", callback_data="ltx_res_16:9"),
        InlineKeyboardButton("9:16", callback_data="ltx_res_9:16"),
    ]]
    await update.message.reply_text(
        "LTX 2.3 Step 2/2: Choose aspect ratio.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_LTX_RESOLUTION


async def receive_ltx_resolution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    resolution = query.data.replace("ltx_res_", "", 1)
    if resolution not in LTX_RESOLUTIONS:
        await query.edit_message_text("Unsupported ratio. Send /ltx to start again.")
        return ConversationHandler.END

    context.user_data["resolution"] = resolution
    await query.edit_message_text("Generating LTX 2.3 video. Please wait...")

    payload = dict(context.user_data)
    try:
        created = await asyncio.to_thread(call_modelslab_ltx, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await send_video_result(
                    context,
                    query.message.chat_id,
                    output[0],
                    payload,
                    model_name=f"LTX 2.3 ({resolution})",
                )
                return ConversationHandler.END

        request_id = created.get("id") or created.get("request_id")
        if not request_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Unexpected ModelsLab response: {created}",
            )
            return ConversationHandler.END

        video_url = await poll_result(
            settings,
            request_id=request_id,
            fetch_fn=fetch_result_v6,
        )
        if not video_url:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="LTX generation failed or timed out. Please try /ltx again.",
            )
            return ConversationHandler.END

        await send_video_result(
            context,
            query.message.chat_id,
            video_url,
            payload,
            model_name=f"LTX 2.3 ({resolution})",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("LTX API call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"LTX API error: {exc}",
        )
        return ConversationHandler.END


async def send_video_result(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_url: str,
    payload: dict,
    model_name: str,
) -> None:
    caption = (
        "Video is ready.\n"
        f"Prompt: {payload.get('prompt', '')}\n"
        f"Model: {model_name}"
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
    await update.message.reply_text("Cancelled. Open /menu to start again.")
    return ConversationHandler.END


async def fallback_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Follow the steps, or send /cancel and reopen /menu.")


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
        entry_points=[
            CommandHandler("generate", generate_start),
            CallbackQueryHandler(generate_start_from_menu, pattern=r"^menu_start_kling$"),
        ],
        states={
            WAITING_IMAGE: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_image)],
            WAITING_VIDEO: [MessageHandler(filters.VIDEO | filters.Document.ALL, receive_video)],
            WAITING_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, fallback_msg),
        ],
        allow_reentry=True,
    )

    ltx_conv = ConversationHandler(
        entry_points=[
            CommandHandler("ltx", ltx_start),
            CommandHandler("generate_ltx", ltx_start),
            CallbackQueryHandler(ltx_start_from_menu, pattern=r"^menu_start_ltx$"),
        ],
        states={
            WAITING_LTX_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ltx_prompt)],
            WAITING_LTX_RESOLUTION: [CallbackQueryHandler(receive_ltx_resolution, pattern=r"^ltx_res_")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, fallback_msg),
        ],
        allow_reentry=True,
    )

    app.add_handler(auth_conv)
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu_(t2i|t2v|i2v|back)$"))
    app.add_handler(gen_conv)
    app.add_handler(ltx_conv)

    logger.info("Bot started. Access code enabled: %s", settings.access_required)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
