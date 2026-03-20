"""Telegram bot that connects user media to ModelsLab motion control."""

import asyncio
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

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

SORA_API_URL = "https://modelslab.com/api/v7/video-fusion/text-to-video"
SORA_MODEL_ID = "sora-2-pro-t2v"
SORA_ASPECT_RATIOS = {
    "9:16": "720x1280",
    "16:9": "1280x720",
}
SORA_DURATIONS = ("4", "8", "12")
MENU_BACK_CALLBACK = "menu_back"

T2I_API_URL = "https://modelslab.com/api/v7/images/text-to-image"
T2I_MODEL_ID = "gemini-3.1-t2i"
T2I_ASPECT_RATIOS = (
    "1:1",
    "9:16",
    "2:3",
    "3:4",
    "4:5",
    "5:4",
    "4:3",
    "3:2",
    "16:9",
    "21:9",
)

I2I_API_URL = "https://modelslab.com/api/v7/images/image-to-image"
I2I_MODEL_ID = "gemini-3.1-i2i"

(
    WAITING_CODE,
    WAITING_IMAGE,
    WAITING_VIDEO,
    WAITING_PROMPT,
    WAITING_LTX_PROMPT,
    WAITING_LTX_RESOLUTION,
    WAITING_SORA_PROMPT,
    WAITING_SORA_ASPECT_RATIO,
    WAITING_SORA_DURATION,
    WAITING_T2I_PROMPT,
    WAITING_T2I_ASPECT_RATIO,
    WAITING_I2I_IMAGE,
    WAITING_I2I_PROMPT,
    WAITING_I2I_ASPECT_RATIO,
) = range(14)

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
        "Nano Banana 2 Text-to-Image (/t2i)\n"
        "1) Enter prompt\n"
        "2) Choose aspect ratio\n\n"
        "Nano Banana 2 Image Edit (/imgedit)\n"
        "1) Upload source image\n"
        "2) Enter edit instruction prompt\n"
        "3) Choose aspect ratio\n\n"
        "Kling Motion Control (/generate)\n"
        "1) Upload character image (PNG/JPG)\n"
        "2) Upload reference motion video (MP4/MOV)\n"
        "3) Enter prompt\n\n"
        "LTX 2.3 Text-to-Video (/ltx)\n"
        "1) Enter prompt\n"
        "2) Choose aspect ratio (1:1 / 16:9 / 9:16)\n\n"
        "Sora 2 Pro Text-to-Video (/sora)\n"
        "1) Enter prompt\n"
        "2) Choose aspect ratio (9:16 / 16:9)\n"
        "3) Choose duration (4s / 8s / 12s)\n\n"
        "Open main menu anytime with /menu\n\n"
        "The bot sends your request to ModelsLab and returns the generated video."
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🖼 Text to Image (Nano Banana 2)", callback_data="menu_t2i")],
            [InlineKeyboardButton("🪄 Image Edit (Nano Banana 2)", callback_data="menu_i2i")],
            [InlineKeyboardButton("🎬 Text to Video", callback_data="menu_t2v")],
            [InlineKeyboardButton("🧷 Image to Video", callback_data="menu_i2v")],
        ]
    )


def text_to_video_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("LTX 2.3 (Text to Video)", callback_data="menu_start_ltx")],
            [InlineKeyboardButton("Sora 2 Pro (Text to Video)", callback_data="menu_start_sora")],
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


def call_modelslab_sora(settings: Settings, payload: dict) -> dict:
    response = requests.post(
        SORA_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "model_id": SORA_MODEL_ID,
            "aspect_ratio": payload["aspect_ratio"],
            "duration": payload["duration"],
            "track_id": None,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def call_modelslab_t2i(settings: Settings, payload: dict) -> dict:
    response = requests.post(
        T2I_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "model_id": T2I_MODEL_ID,
            "aspect_ratio": payload["aspect_ratio"],
            "track_id": None,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def call_modelslab_i2i(settings: Settings, payload: dict) -> dict:
    response = requests.post(
        I2I_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "model_id": I2I_MODEL_ID,
            "init_image": payload["init_image"],
            "aspect_ratio": payload["aspect_ratio"],
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


def fetch_result_t2i(settings: Settings, request_id: str) -> dict:
    """Try common fetch endpoints used by ModelsLab image APIs."""
    endpoints = (
        (
            f"https://modelslab.com/api/v7/images/fetch/{request_id}",
            {"key": settings.modelslab_api_key},
        ),
        (
            "https://modelslab.com/api/v6/images/fetch",
            {"key": settings.modelslab_api_key, "request_id": request_id},
        ),
        (
            f"https://modelslab.com/api/v6/images/fetch/{request_id}",
            {"key": settings.modelslab_api_key},
        ),
    )

    last_error: Optional[Exception] = None
    for endpoint, body in endpoints:
        try:
            response = requests.post(endpoint, json=body, timeout=30)
            if response.status_code >= 400:
                continue
            return response.json()
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    raise RuntimeError(
        "Failed to fetch image result from known endpoints"
    ) from last_error


async def poll_result(
    settings: Settings,
    request_id: str,
    fetch_fn: Callable[[Settings, str], dict],
    progress_callback: Optional[Callable[[int, str], Awaitable[None]]] = None,
    poll_interval: int = 10,
    max_wait: int = 420,
) -> Optional[str]:
    deadline = time.time() + max_wait
    started_at = time.time()
    while time.time() < deadline:
        try:
            data = await asyncio.to_thread(fetch_fn, settings, request_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetch polling error: %s", exc)
            if progress_callback:
                elapsed = int(time.time() - started_at)
                await progress_callback(elapsed, "retrying")
            await asyncio.sleep(poll_interval)
            continue

        status = str(data.get("status", "")).lower()
        if progress_callback:
            elapsed = int(time.time() - started_at)
            await progress_callback(elapsed, status or "processing")

        if status == "success":
            output = data.get("output") or []
            return output[0] if output else None
        if status in {"failed", "error"}:
            logger.error("ModelsLab generation failed: %s", data)
            return None
        await asyncio.sleep(poll_interval)
    return None


def _humanize_status(raw_status: str) -> str:
    mapping = {
        "processing": "Processing",
        "pending": "Pending",
        "queued": "Queued",
        "in progress": "In Progress",
        "in_progress": "In Progress",
        "retrying": "Retrying",
        "success": "Completed",
    }
    normalized = raw_status.strip().lower()
    if normalized in mapping:
        return mapping[normalized]
    if not normalized:
        return "Processing"
    return normalized.replace("_", " ").title()


def make_progress_callback(
    context: ContextTypes.DEFAULT_TYPE,
    status_message,
    job_title: str,
) -> Callable[[int, str], Awaitable[None]]:
    state = {"last_text": ""}

    async def _progress(elapsed_seconds: int, status: str) -> None:
        text = (
            f"⏳ {job_title}\n"
            f"Status: {_humanize_status(status)}\n"
            f"Elapsed: {elapsed_seconds}s"
        )
        if text == state["last_text"]:
            return
        try:
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text=text,
            )
            state["last_text"] = text
        except Exception:  # noqa: BLE001
            # Message may be unchanged/expired; do not break generation flow.
            pass

    return _progress


async def finalize_progress_message(
    context: ContextTypes.DEFAULT_TYPE,
    status_message,
    final_text: str,
) -> None:
    try:
        await context.bot.edit_message_text(
            chat_id=status_message.chat_id,
            message_id=status_message.message_id,
            text=final_text,
        )
    except Exception:  # noqa: BLE001
        pass


def truncate_text(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return value[:max_len]
    return value[: max_len - 1] + "…"


def media_caption(prompt: str, details: list[str]) -> str:
    base = "Prompt: " + prompt + "\n" + "\n".join(details)
    return truncate_text(base, 1024)


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


async def t2i_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text("Text to Image Step 1/2: Enter your prompt text.")
    return WAITING_T2I_PROMPT


async def t2i_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text("Text to Image Step 1/2: Enter your prompt text.")
    return WAITING_T2I_PROMPT


async def receive_t2i_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_T2I_PROMPT

    context.user_data["prompt"] = prompt
    keyboard = [
        [
            InlineKeyboardButton("1:1", callback_data="t2i_ar_1:1"),
            InlineKeyboardButton("16:9", callback_data="t2i_ar_16:9"),
            InlineKeyboardButton("9:16", callback_data="t2i_ar_9:16"),
        ],
        [
            InlineKeyboardButton("4:5", callback_data="t2i_ar_4:5"),
            InlineKeyboardButton("3:4", callback_data="t2i_ar_3:4"),
            InlineKeyboardButton("2:3", callback_data="t2i_ar_2:3"),
        ],
    ]
    await update.message.reply_text(
        "Text to Image Step 2/2: Choose aspect ratio.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_T2I_ASPECT_RATIO


async def receive_t2i_aspect_ratio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    aspect_ratio = query.data.replace("t2i_ar_", "", 1)
    if aspect_ratio not in T2I_ASPECT_RATIOS:
        await query.edit_message_text("Unsupported aspect ratio. Send /t2i to start again.")
        return ConversationHandler.END

    context.user_data["aspect_ratio"] = aspect_ratio
    await query.edit_message_text("Generating image with Nano Banana 2. Please wait...")

    payload = dict(context.user_data)
    status_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⏳ Nano Banana 2 Text-to-Image\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title="Nano Banana 2 Text-to-Image",
    )
    try:
        created = await asyncio.to_thread(call_modelslab_t2i, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await finalize_progress_message(
                    context,
                    status_message,
                    "✅ Text-to-image completed. Sending image...",
                )
                await send_image_result(
                    context,
                    query.message.chat_id,
                    output[0],
                    payload,
                    model_name=f"Nano Banana 2 ({aspect_ratio})",
                )
                return ConversationHandler.END

        request_id = created.get("id") or created.get("request_id")
        if not request_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Unexpected ModelsLab response: {created}",
            )
            return ConversationHandler.END

        image_url = await poll_result(
            settings,
            request_id=request_id,
            fetch_fn=fetch_result_t2i,
            progress_callback=progress_callback,
            max_wait=240,
        )
        if not image_url:
            await finalize_progress_message(
                context,
                status_message,
                "❌ Text-to-image failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Image generation failed or timed out. Please try /t2i again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            "✅ Text-to-image completed. Sending image...",
        )
        await send_image_result(
            context,
            query.message.chat_id,
            image_url,
            payload,
            model_name=f"Nano Banana 2 ({aspect_ratio})",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("T2I API call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Text-to-image API error: {exc}",
        )
        return ConversationHandler.END


async def imgedit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text("Image Edit Step 1/3: Send source image (JPG/PNG).")
    return WAITING_I2I_IMAGE


async def imgedit_start_from_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text("Image Edit Step 1/3: Send source image (JPG/PNG).")
    return WAITING_I2I_IMAGE


async def receive_i2i_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    image_file = None
    if update.message.photo:
        image_file = update.message.photo[-1]
    elif update.message.document and str(update.message.document.mime_type).startswith("image/"):
        image_file = update.message.document

    if image_file is None:
        await update.message.reply_text("Please send a JPG/PNG image.")
        return WAITING_I2I_IMAGE

    tg_file = await context.bot.get_file(image_file.file_id)
    context.user_data["init_image"] = [telegram_file_url(settings, tg_file.file_path)]
    await update.message.reply_text("Image Edit Step 2/3: Enter edit instruction prompt.")
    return WAITING_I2I_PROMPT


async def receive_i2i_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_I2I_PROMPT

    context.user_data["prompt"] = prompt
    keyboard = [
        [
            InlineKeyboardButton("1:1", callback_data="i2i_ar_1:1"),
            InlineKeyboardButton("16:9", callback_data="i2i_ar_16:9"),
            InlineKeyboardButton("9:16", callback_data="i2i_ar_9:16"),
        ],
        [
            InlineKeyboardButton("4:5", callback_data="i2i_ar_4:5"),
            InlineKeyboardButton("3:4", callback_data="i2i_ar_3:4"),
            InlineKeyboardButton("2:3", callback_data="i2i_ar_2:3"),
        ],
    ]
    await update.message.reply_text(
        "Image Edit Step 3/3: Choose aspect ratio.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_I2I_ASPECT_RATIO


async def receive_i2i_aspect_ratio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    aspect_ratio = query.data.replace("i2i_ar_", "", 1)
    if aspect_ratio not in T2I_ASPECT_RATIOS:
        await query.edit_message_text("Unsupported aspect ratio. Send /imgedit to start again.")
        return ConversationHandler.END

    context.user_data["aspect_ratio"] = aspect_ratio
    await query.edit_message_text("Editing image with Nano Banana 2. Please wait...")

    payload = dict(context.user_data)
    status_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⏳ Nano Banana 2 Image Edit\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title="Nano Banana 2 Image Edit",
    )
    try:
        created = await asyncio.to_thread(call_modelslab_i2i, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await finalize_progress_message(
                    context,
                    status_message,
                    "✅ Image edit completed. Sending image...",
                )
                await send_image_result(
                    context,
                    query.message.chat_id,
                    output[0],
                    payload,
                    model_name=f"Nano Banana 2 Image Edit ({aspect_ratio})",
                )
                return ConversationHandler.END

        request_id = created.get("id") or created.get("request_id")
        if not request_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Unexpected ModelsLab response: {created}",
            )
            return ConversationHandler.END

        image_url = await poll_result(
            settings,
            request_id=request_id,
            fetch_fn=fetch_result_t2i,
            progress_callback=progress_callback,
            max_wait=240,
        )
        if not image_url:
            await finalize_progress_message(
                context,
                status_message,
                "❌ Image edit failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Image edit failed or timed out. Please try /imgedit again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            "✅ Image edit completed. Sending image...",
        )
        await send_image_result(
            context,
            query.message.chat_id,
            image_url,
            payload,
            model_name=f"Nano Banana 2 Image Edit ({aspect_ratio})",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("Image edit API call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Image edit API error: {exc}",
        )
        return ConversationHandler.END


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
    status_message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text="⏳ Kling 3.0 Motion Control\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title="Kling 3.0 Motion Control",
    )
    try:
        created = await asyncio.to_thread(call_modelslab_kling, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await finalize_progress_message(
                    context,
                    status_message,
                    "✅ Kling 3.0 completed. Sending video...",
                )
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
            progress_callback=progress_callback,
        )
        if not video_url:
            await finalize_progress_message(
                context,
                status_message,
                "❌ Kling 3.0 failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text="Generation failed or timed out. Please try /generate again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            "✅ Kling 3.0 completed. Sending video...",
        )
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
    status_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⏳ LTX 2.3 Text-to-Video\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title="LTX 2.3 Text-to-Video",
    )
    try:
        created = await asyncio.to_thread(call_modelslab_ltx, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await finalize_progress_message(
                    context,
                    status_message,
                    "✅ LTX completed. Sending video...",
                )
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
            progress_callback=progress_callback,
        )
        if not video_url:
            await finalize_progress_message(
                context,
                status_message,
                "❌ LTX failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="LTX generation failed or timed out. Please try /ltx again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            "✅ LTX completed. Sending video...",
        )
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


async def sora_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text("Sora 2 Pro Step 1/3: Enter your prompt text.")
    return WAITING_SORA_PROMPT


async def sora_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text("Sora 2 Pro Step 1/3: Enter your prompt text.")
    return WAITING_SORA_PROMPT


async def receive_sora_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_SORA_PROMPT

    context.user_data["prompt"] = prompt
    keyboard = [[
        InlineKeyboardButton("9:16", callback_data="sora_ar_9x16"),
        InlineKeyboardButton("16:9", callback_data="sora_ar_16x9"),
    ]]
    await update.message.reply_text(
        "Sora 2 Pro Step 2/3: Choose aspect ratio.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_SORA_ASPECT_RATIO


async def receive_sora_aspect_ratio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    token = query.data.replace("sora_ar_", "", 1)
    if token == "9x16":
        label = "9:16"
    elif token == "16x9":
        label = "16:9"
    else:
        await query.edit_message_text("Unsupported aspect ratio. Send /sora to start again.")
        return ConversationHandler.END

    context.user_data["aspect_ratio"] = SORA_ASPECT_RATIOS[label]
    context.user_data["aspect_ratio_label"] = label

    keyboard = [[
        InlineKeyboardButton("4s", callback_data="sora_dur_4"),
        InlineKeyboardButton("8s", callback_data="sora_dur_8"),
        InlineKeyboardButton("12s", callback_data="sora_dur_12"),
    ]]
    await query.edit_message_text(
        "Sora 2 Pro Step 3/3: Choose duration.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_SORA_DURATION


async def receive_sora_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    duration = query.data.replace("sora_dur_", "", 1)
    if duration not in SORA_DURATIONS:
        await query.edit_message_text("Unsupported duration. Send /sora to start again.")
        return ConversationHandler.END

    context.user_data["duration"] = duration
    await query.edit_message_text("Generating Sora 2 Pro video. Please wait...")

    payload = dict(context.user_data)
    status_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⏳ Sora 2 Pro Text-to-Video\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title="Sora 2 Pro Text-to-Video",
    )

    try:
        created = await asyncio.to_thread(call_modelslab_sora, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await finalize_progress_message(
                    context,
                    status_message,
                    "✅ Sora 2 Pro completed. Sending video...",
                )
                await send_video_result(
                    context,
                    query.message.chat_id,
                    output[0],
                    payload,
                    model_name=(
                        f"Sora 2 Pro ({payload.get('aspect_ratio_label', '?')}, {duration}s)"
                    ),
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
            fetch_fn=fetch_result_v7,
            progress_callback=progress_callback,
        )
        if not video_url:
            await finalize_progress_message(
                context,
                status_message,
                "❌ Sora 2 Pro failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Sora generation failed or timed out. Please try /sora again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            "✅ Sora 2 Pro completed. Sending video...",
        )
        await send_video_result(
            context,
            query.message.chat_id,
            video_url,
            payload,
            model_name=f"Sora 2 Pro ({payload.get('aspect_ratio_label', '?')}, {duration}s)",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("Sora API call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Sora API error: {exc}",
        )
        return ConversationHandler.END


async def send_video_result(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    video_url: str,
    payload: dict,
    model_name: str,
) -> None:
    caption = media_caption(
        str(payload.get("prompt", "")),
        [
            "Result: Video",
            f"Model: {model_name}",
        ],
    )
    try:
        await context.bot.send_video(
            chat_id=chat_id,
            video=video_url,
            caption=caption,
        )
        return
    except Exception as direct_send_error:  # noqa: BLE001
        logger.warning("Direct video URL send failed: %s", direct_send_error)

    local_file_path: Optional[str] = None
    try:
        local_file_path = await asyncio.to_thread(download_video_to_tempfile, video_url)
        with open(local_file_path, "rb") as video_file:
            await context.bot.send_video(
                chat_id=chat_id,
                video=video_file,
                caption=caption,
            )
        return
    except Exception as upload_error:  # noqa: BLE001
        logger.warning("Downloaded video upload failed: %s", upload_error)
    finally:
        if local_file_path and os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
            except OSError:
                logger.warning("Failed to remove temp file: %s", local_file_path)

    try:
        await context.bot.send_document(
            chat_id=chat_id,
            document=video_url,
            caption=caption,
        )
        return
    except Exception as document_error:  # noqa: BLE001
        logger.warning("Document send fallback failed: %s", document_error)

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Video ready: {video_url}\n\n{caption}",
        )
    except Exception as message_error:  # noqa: BLE001
        logger.error("Final text fallback failed: %s", message_error)


def download_video_to_tempfile(video_url: str) -> str:
    response = requests.get(video_url, stream=True, timeout=120)
    response.raise_for_status()

    suffix = Path(urlparse(video_url).path).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        for chunk in response.iter_content(chunk_size=1024 * 512):
            if chunk:
                temp_file.write(chunk)
        return temp_file.name


async def send_image_result(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    image_url: str,
    payload: dict,
    model_name: str,
) -> None:
    caption = media_caption(
        str(payload.get("prompt", "")),
        [
            "Result: Image",
            f"Aspect Ratio: {payload.get('aspect_ratio', '?')}",
            f"Model: {model_name}",
        ],
    )
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=image_url,
            caption=caption,
        )
        return
    except Exception as photo_error:  # noqa: BLE001
        logger.warning("Direct image URL send failed: %s", photo_error)

    try:
        await context.bot.send_document(
            chat_id=chat_id,
            document=image_url,
            caption=caption,
        )
        return
    except Exception as document_error:  # noqa: BLE001
        logger.warning("Document image fallback failed: %s", document_error)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Image ready: {image_url}\n\n{caption}",
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

    sora_conv = ConversationHandler(
        entry_points=[
            CommandHandler("sora", sora_start),
            CommandHandler("sora2", sora_start),
            CallbackQueryHandler(sora_start_from_menu, pattern=r"^menu_start_sora$"),
        ],
        states={
            WAITING_SORA_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_sora_prompt)],
            WAITING_SORA_ASPECT_RATIO: [
                CallbackQueryHandler(receive_sora_aspect_ratio, pattern=r"^sora_ar_")
            ],
            WAITING_SORA_DURATION: [
                CallbackQueryHandler(receive_sora_duration, pattern=r"^sora_dur_")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, fallback_msg),
        ],
        allow_reentry=True,
    )

    t2i_conv = ConversationHandler(
        entry_points=[
            CommandHandler("t2i", t2i_start),
            CommandHandler("text2image", t2i_start),
            CallbackQueryHandler(t2i_start_from_menu, pattern=r"^menu_t2i$"),
        ],
        states={
            WAITING_T2I_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_t2i_prompt)],
            WAITING_T2I_ASPECT_RATIO: [
                CallbackQueryHandler(receive_t2i_aspect_ratio, pattern=r"^t2i_ar_")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, fallback_msg),
        ],
        allow_reentry=True,
    )

    i2i_conv = ConversationHandler(
        entry_points=[
            CommandHandler("imgedit", imgedit_start),
            CommandHandler("imageedit", imgedit_start),
            CallbackQueryHandler(imgedit_start_from_menu, pattern=r"^menu_i2i$"),
        ],
        states={
            WAITING_I2I_IMAGE: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_i2i_image)],
            WAITING_I2I_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_i2i_prompt)],
            WAITING_I2I_ASPECT_RATIO: [
                CallbackQueryHandler(receive_i2i_aspect_ratio, pattern=r"^i2i_ar_")
            ],
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
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu_(t2v|i2v|back)$"))
    app.add_handler(t2i_conv)
    app.add_handler(i2i_conv)
    app.add_handler(gen_conv)
    app.add_handler(ltx_conv)
    app.add_handler(sora_conv)

    logger.info("Bot started. Access code enabled: %s", settings.access_required)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
