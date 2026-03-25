"""Telegram bot that connects user media to ModelsLab motion control."""

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse
from uuid import uuid4

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

KLING_V3_T2V_API_URL = "https://modelslab.com/api/v7/video-fusion/text-to-video"
KLING_V3_T2V_MODEL_ID = "kling-v3-t2v"
KLING_V3_T2V_ASPECT_RATIOS = ("1:1", "9:16", "16:9")
KLING_V3_T2V_DURATIONS = ("5", "10")

I2V_V7_API_URL = "https://modelslab.com/api/v7/video-fusion/image-to-video"
LTX_I2V_API_URL = "https://modelslab.com/api/v6/video/img2video_ultra"
I2V_MODELS = {
    "kling_v3_i2v": {
        "label": "Kling V3.0 Image-to-Video",
        "ux": "Balanced",
        "fetch": "v7",
        "defaults": {"duration": "5", "model_id": "kling-v3-i2v"},
    },
    "ltx_pro_i2v": {
        "label": "LTX 2.3 Pro Image-to-Video",
        "ux": "Highest quality",
        "fetch": "v7",
        "defaults": {
            "resolution": "1920x1080",
            "duration": "6",
            "generate_audio": True,
            "fps": "25",
            "model_id": "ltx-2-3-pro-i2v",
        },
    },
    "ltx_i2v": {
        "label": "LTX 2.3 Image-to-Video",
        "ux": "Fast",
        "fetch": "v6",
        "defaults": {
            "resolution": "16:9",
            "model_id": "ltx-2.3",
            "base64": "false",
        },
    },
    "grok_i2v": {
        "label": "Grok Imagine Image-to-Video",
        "ux": "Creative",
        "fetch": "v7",
        "defaults": {
            "resolution": "720p",
            "duration": "6",
            "model_id": "grok-imagine-video-i2v",
        },
    },
}

SORA_API_URL = "https://modelslab.com/api/v7/video-fusion/text-to-video"
SORA_MODEL_ID = "sora-2-pro-t2v"
SORA_ASPECT_RATIOS = {
    "9:16": "720x1280",
    "16:9": "1280x720",
}
SORA_DURATIONS = ("4", "8", "12")
MENU_BACK_CALLBACK = "menu_back"

LLM_CHAT_API_URL = "https://modelslab.com/api/uncensored-chat/v1/chat/completions"
LLM_MAX_HISTORY_MESSAGES = 14
LLM_MODELS = {
    "best": {
        "label": "Best Available (Auto)",
        "ux": "Recommended",
        "model": "ModelsLab/Llama-3.1-8b-Uncensored-Dare",
    },
    "chatgpt": {
        "label": "ChatGPT (OpenAI)",
        "ux": "Premium",
        "model": "openai/gpt-4o",
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "ux": "Premium",
        "model": "anthropic/claude-3-5-sonnet-20241022",
    },
    "deepseek": {
        "label": "DeepSeek R1",
        "ux": "Reasoning",
        "model": "deepseek-ai/DeepSeek-R1",
    },
    "llama": {
        "label": "Meta Llama 3.1 70B",
        "ux": "Balanced",
        "model": "meta-llama/Meta-Llama-3.1-70B-Instruct",
    },
    "qwen": {
        "label": "Qwen 2.5 72B",
        "ux": "Coding",
        "model": "Qwen/Qwen2.5-72B-Instruct",
    },
    "mistral": {
        "label": "Mistral 8x7B",
        "ux": "Fast",
        "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
    },
}

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
T2I_RATIO_SHORTLIST = ("1:1", "16:9", "9:16")
T2I_MODELS = {
    "nano": {
        "label": "Nano Banana 2",
        "ux": "Balanced",
        "endpoint": "v7",
        "model_id": "gemini-3.1-t2i",
        "field": "aspect_ratio",
    },
    "qwen": {
        "label": "Qwen Image 2.0 Pro",
        "ux": "Highest quality",
        "endpoint": "v7",
        "model_id": "qwen-image-2.0-pro-t2i",
        "field": "size",
        "size_map": {"1:1": "1328*1328", "16:9": "1664*928", "9:16": "928*1664"},
    },
    "seedream": {
        "label": "Seedream 5.0 Lite",
        "ux": "Fast",
        "endpoint": "v7",
        "model_id": "seedream-5-lite-t2i",
        "field": "aspect_ratio",
    },
}

I2I_API_URL = "https://modelslab.com/api/v7/images/image-to-image"
I2I_MODEL_ID = "gemini-3.1-i2i"
I2I_MODE_EDIT = "edit"
I2I_MODE_REFERENCE = "reference"
QWEN_EDIT_API_URL = "https://modelslab.com/api/v6/image_editing/qwen_edit"
FLUX_KONTEXT_API_URL = "https://modelslab.com/api/v6/images/img2img"
REALTIME_IMG2IMG_API_URL = "https://modelslab.com/api/v6/realtime/img2img"
FACE_GEN_API_URL = "https://modelslab.com/api/v6/image_editing/face_gen"
OUTPAINT_API_URL = "https://modelslab.com/api/v6/image_editing/outpaint"
IMG_MIXER_API_URL = "https://modelslab.com/api/v6/image_editing/img_mixer"
FACESWAP_API_URL = "https://modelslab.com/api/v6/faceswap/single_face_swap"
FACESWAP_FETCH_URL_TEMPLATE = "https://modelslab.com/api/v6/faceswap/fetch/{request_id}"
NSFW_IMAGE_CHECK_API_URL = "https://modelslab.com/api/v3/nsfw_image_check"
CAPTION_API_URL = "https://modelslab.com/api/v6/image_editing/caption"
STYLE_ANALYSIS_MODEL_PRIMARY = "openai/gpt-5.4"
STYLE_ANALYSIS_MODEL_FALLBACK = "openai/gpt-4o"
HARDCODED_TELEGRAM_TOKEN = "8783783821:AAG_pw_UfKl5wAL8IGpHC9fnHFMZatyC3eU"
HARDCODED_MODELSLAB_API_KEY = "DehOCA2JIkE0hpPD3cz54qPgt7z2PSMI2vF8621DTIFDqOE93R1rkZwTis7K"
HARDCODED_ACCESS_CODE = "628008"
RATIO_TO_SIZE = {
    "1:1": (1024, 1024),
    "16:9": (1344, 768),
    "9:16": (768, 1344),
    "4:5": (896, 1120),
    "3:4": (896, 1152),
    "2:3": (832, 1216),
}
FACEGEN_RATIO_TO_SIZE = {
    "1:1": (512, 512),
    "16:9": (768, 432),
    "9:16": (432, 768),
    "4:5": (512, 640),
    "3:4": (576, 768),
    "2:3": (512, 768),
}
REF_IMAGE_MODELS = {
    "nano_ref": {
        "label": "Nano Banana 2 Reference",
        "ux": "Balanced",
        "endpoint": "v7_i2i",
    },
    "qwen_edit_2509": {
        "label": "Qwen Edit 2509",
        "ux": "Highest quality",
        "endpoint": "qwen_edit",
        "model_id": "qwen-edit-2509",
    },
    "qwen_edit_2511": {
        "label": "Qwen Edit 2511",
        "ux": "Latest",
        "endpoint": "qwen_edit",
        "model_id": "qwen-edit-2511",
    },
    "flux_kontext": {
        "label": "Flux Kontext Dev",
        "ux": "Style transfer",
        "endpoint": "flux_kontext",
        "model_id": "flux-kontext-dev",
    },
    "realtime_img2img": {
        "label": "Realtime Image-to-Image",
        "ux": "Fast",
        "endpoint": "realtime_img2img",
    },
    "face_gen": {
        "label": "FaceGen",
        "ux": "Identity focus",
        "endpoint": "face_gen",
    },
    "outpaint": {
        "label": "Outpaint",
        "ux": "Canvas expand",
        "endpoint": "outpaint",
    },
    "img_mixer": {
        "label": "Image Mixer",
        "ux": "Blend style",
        "endpoint": "img_mixer",
    },
}

(
    WAITING_CODE,
    WAITING_IMAGE,
    WAITING_VIDEO,
    WAITING_PROMPT,
    WAITING_T2I_MODEL,
    WAITING_LTX_PROMPT,
    WAITING_LTX_RESOLUTION,
    WAITING_I2V_MODEL,
    WAITING_I2V_IMAGE,
    WAITING_I2V_PROMPT,
    WAITING_KLING_V3_T2V_PROMPT,
    WAITING_KLING_V3_T2V_ASPECT_RATIO,
    WAITING_KLING_V3_T2V_DURATION,
    WAITING_SORA_PROMPT,
    WAITING_SORA_ASPECT_RATIO,
    WAITING_SORA_DURATION,
    WAITING_T2I_PROMPT,
    WAITING_T2I_ASPECT_RATIO,
    WAITING_I2I_IMAGE,
    WAITING_I2I_PROMPT,
    WAITING_I2I_ASPECT_RATIO,
    WAITING_REF_MODEL,
    WAITING_LLM_MODEL,
    WAITING_LLM_PROMPT,
    WAITING_FACESWAP_INIT_IMAGE,
    WAITING_FACESWAP_TARGET_IMAGE,
    WAITING_FACESWAP_REFERENCE_IMAGE,
    WAITING_NSFW_IMAGE,
    WAITING_STYLECLONE_SOURCE_IMAGE,
) = range(29)

VERIFIED_USERS: set[int] = set()
RERUN_CALLBACK_PREFIX = "regen_"
VARIATION_CALLBACK_PREFIX = "var_"


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
        telegram_token=(
            _optional_env(
                "TELEGRAM_TOKEN",
                "BOT_TOKEN",
                "TELEGRAM_BOT_TOKEN",
                default="",
            ).strip()
            or HARDCODED_TELEGRAM_TOKEN
        ),
        modelslab_api_key=(
            _optional_env(
                "MODELSLAB_API_KEY",
                "MODELSLAB_KEY",
                "ML_API_KEY",
                default="",
            ).strip()
            or HARDCODED_MODELSLAB_API_KEY
        ),
        access_code=_optional_env("ACCESS_CODE", default=HARDCODED_ACCESS_CODE).strip(),
    )


def is_verified(user_id: int, settings: Settings) -> bool:
    return (not settings.access_required) or user_id in VERIFIED_USERS


def get_user_prefs(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    prefs_by_user = context.bot_data.setdefault("user_prefs", {})
    return prefs_by_user.setdefault(user_id, {})


def get_user_pref(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    key: str,
    default: str = "",
) -> str:
    return str(get_user_prefs(context, user_id).get(key, default))


def set_user_pref(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    key: str,
    value: str,
) -> None:
    get_user_prefs(context, user_id)[key] = value


def get_llm_history(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    model_key: str,
) -> list[dict]:
    all_histories = context.bot_data.setdefault("llm_histories", {})
    by_user = all_histories.setdefault(user_id, {})
    history = by_user.setdefault(model_key, [])
    return history


def save_llm_turn(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    model_key: str,
    user_message: str,
    assistant_message: str,
) -> None:
    history = get_llm_history(context, user_id, model_key)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_message})
    if len(history) > LLM_MAX_HISTORY_MESSAGES:
        del history[: len(history) - LLM_MAX_HISTORY_MESSAGES]


def clear_llm_history(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    model_key: Optional[str] = None,
) -> int:
    all_histories = context.bot_data.setdefault("llm_histories", {})
    by_user = all_histories.setdefault(user_id, {})
    if model_key:
        removed = len(by_user.get(model_key, []))
        by_user[model_key] = []
        return removed
    removed = sum(len(v) for v in by_user.values())
    by_user.clear()
    return removed


def _selected_label(label: str, is_selected: bool) -> str:
    return f"✅ {label}" if is_selected else label


def _model_button_text(model_cfg: dict, is_selected: bool) -> str:
    base = f"{model_cfg['label']} • {model_cfg['ux']}"
    return _selected_label(base, is_selected)


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
        "1) Choose model\n"
        "2) Enter prompt\n"
        "3) Choose aspect ratio\n\n"
        "Nano Banana 2 Image Edit (/imgedit)\n"
        "1) Upload source image\n"
        "2) Enter edit instruction prompt\n"
        "3) Choose aspect ratio\n\n"
        "Reference Image Generate (/refimg)\n"
        "1) Choose reference model\n"
        "2) Upload source image\n"
        "3) Enter prompt to keep style/identity\n"
        "4) Choose aspect ratio\n\n"
        "Image Prompt Analyzer (/styleclone)\n"
        "1) Upload one image\n"
        "2) Bot analyzes with advanced LLM\n"
        "3) Bot returns a detailed reusable prompt\n\n"
        "LLM Chat (/llm)\n"
        "1) Choose model family\n"
        "2) Ask your question (memory stays in this model thread)\n"
        "Use /llmclear anytime to reset LLM memory\n\n"
        "Uncensored Chat (/uncensored)\n"
        "1) Starts instant uncensored chat mode\n"
        "2) Send your message directly (uses uncensored model memory)\n\n"
        "Face Swap (/faceswap)\n"
        "1) Upload base image (face to replace)\n"
        "2) Upload target image (face source)\n"
        "3) Upload reference image (which face in base image)\n\n"
        "NSFW Image Check (/nsfwcheck)\n"
        "1) Upload image\n"
        "2) Bot returns safe/NSFW status\n\n"
        "Image-to-Video tools (/i2v)\n"
        "1) Choose model\n"
        "2) Upload source image\n"
        "3) Enter prompt\n\n"
        "Kling Motion Control (/generate)\n"
        "1) Upload character image (PNG/JPG)\n"
        "2) Upload reference motion video (MP4/MOV)\n"
        "3) Enter prompt\n\n"
        "LTX 2.3 Text-to-Video (/ltx)\n"
        "1) Enter prompt\n"
        "2) Choose aspect ratio (1:1 / 16:9 / 9:16)\n\n"
        "Kling V3.0 Text-to-Video (/klingt2v)\n"
        "1) Enter prompt\n"
        "2) Choose aspect ratio (1:1 / 9:16 / 16:9)\n"
        "3) Choose duration (5s / 10s)\n\n"
        "Sora 2 Pro Text-to-Video (/sora)\n"
        "1) Enter prompt\n"
        "2) Choose aspect ratio (9:16 / 16:9)\n"
        "3) Choose duration (4s / 8s / 12s)\n\n"
        "Open main menu anytime with /menu\n\n"
        "After any result, use Regenerate/Variation buttons to iterate faster.\n\n"
        "The bot sends your request to ModelsLab and returns the generated video."
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🖼 Text to Image (Nano Banana 2)", callback_data="menu_t2i")],
            [InlineKeyboardButton("💬 LLM Chat", callback_data="menu_llm")],
            [InlineKeyboardButton("🔓 Uncensored Chat", callback_data="menu_uncensored")],
            [InlineKeyboardButton("🪄 Image Edit (Nano Banana 2)", callback_data="menu_i2i")],
            [InlineKeyboardButton("🧭 Reference Image Generate", callback_data="menu_refimg")],
            [InlineKeyboardButton("🧠 Image Prompt Analyzer", callback_data="menu_styleclone")],
            [InlineKeyboardButton("🎭 Face Swap", callback_data="menu_faceswap")],
            [InlineKeyboardButton("🧪 NSFW Image Check", callback_data="menu_nsfw")],
            [InlineKeyboardButton("🎬 Text to Video", callback_data="menu_t2v")],
            [InlineKeyboardButton("🧷 Image to Video", callback_data="menu_i2v")],
        ]
    )


def text_to_video_keyboard(selected_key: str = "") -> InlineKeyboardMarkup:
    ltx_label = _selected_label("LTX 2.3 (Fast)", selected_key == "ltx")
    kling_label = _selected_label("Kling V3.0 (Balanced)", selected_key == "kling_v3_t2v")
    sora_label = _selected_label("Sora 2 Pro (Highest quality)", selected_key == "sora")
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(ltx_label, callback_data="menu_start_ltx")],
            [
                InlineKeyboardButton(
                    kling_label,
                    callback_data="menu_start_kling_v3_t2v",
                )
            ],
            [InlineKeyboardButton(sora_label, callback_data="menu_start_sora")],
            [InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)],
        ]
    )


def image_to_video_keyboard(selected_key: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _selected_label("Kling 3.0 Motion Control (Character control)", selected_key == "kling_motion"),
                    callback_data="menu_start_kling",
                )
            ],
            [
                InlineKeyboardButton(
                    _selected_label("Kling V3.0 (Balanced)", selected_key == "kling_v3_i2v"),
                    callback_data="menu_start_i2v_kling_v3",
                )
            ],
            [
                InlineKeyboardButton(
                    _selected_label("LTX 2.3 Pro (Highest quality)", selected_key == "ltx_pro_i2v"),
                    callback_data="menu_start_i2v_ltx_pro",
                )
            ],
            [
                InlineKeyboardButton(
                    _selected_label("LTX 2.3 (Fast)", selected_key == "ltx_i2v"),
                    callback_data="menu_start_i2v_ltx",
                )
            ],
            [
                InlineKeyboardButton(
                    _selected_label("Grok Imagine (Creative)", selected_key == "grok_i2v"),
                    callback_data="menu_start_i2v_grok",
                )
            ],
            [InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)],
        ]
    )


def i2v_model_keyboard(selected_key: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _model_button_text(I2V_MODELS["kling_v3_i2v"], selected_key == "kling_v3_i2v"),
                    callback_data="menu_start_i2v_kling_v3",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(I2V_MODELS["ltx_pro_i2v"], selected_key == "ltx_pro_i2v"),
                    callback_data="menu_start_i2v_ltx_pro",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(I2V_MODELS["ltx_i2v"], selected_key == "ltx_i2v"),
                    callback_data="menu_start_i2v_ltx",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(I2V_MODELS["grok_i2v"], selected_key == "grok_i2v"),
                    callback_data="menu_start_i2v_grok",
                )
            ],
            [InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)],
        ]
    )


def t2i_model_keyboard(selected_key: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _model_button_text(T2I_MODELS["nano"], selected_key == "nano"),
                    callback_data="t2i_model_nano",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(T2I_MODELS["qwen"], selected_key == "qwen"),
                    callback_data="t2i_model_qwen",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(T2I_MODELS["seedream"], selected_key == "seedream"),
                    callback_data="t2i_model_seedream",
                )
            ],
            [InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)],
        ]
    )


def ref_model_keyboard(selected_key: str = "nano_ref") -> InlineKeyboardMarkup:
    order = [
        "nano_ref",
        "qwen_edit_2509",
        "qwen_edit_2511",
        "flux_kontext",
        "realtime_img2img",
        "face_gen",
        "outpaint",
        "img_mixer",
    ]
    rows = []
    for model_key in order:
        cfg = REF_IMAGE_MODELS[model_key]
        rows.append(
            [
                InlineKeyboardButton(
                    _model_button_text(cfg, selected_key == model_key),
                    callback_data=f"ref_model_{model_key}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)])
    return InlineKeyboardMarkup(rows)


def llm_model_keyboard(selected_key: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    _model_button_text(LLM_MODELS["best"], selected_key == "best"),
                    callback_data="llm_model_best",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(LLM_MODELS["chatgpt"], selected_key == "chatgpt"),
                    callback_data="llm_model_chatgpt",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(LLM_MODELS["claude"], selected_key == "claude"),
                    callback_data="llm_model_claude",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(LLM_MODELS["deepseek"], selected_key == "deepseek"),
                    callback_data="llm_model_deepseek",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(LLM_MODELS["llama"], selected_key == "llama"),
                    callback_data="llm_model_llama",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(LLM_MODELS["qwen"], selected_key == "qwen"),
                    callback_data="llm_model_qwen",
                )
            ],
            [
                InlineKeyboardButton(
                    _model_button_text(LLM_MODELS["mistral"], selected_key == "mistral"),
                    callback_data="llm_model_mistral",
                )
            ],
            [InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)],
        ]
    )


def back_only_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅ Back", callback_data=MENU_BACK_CALLBACK)]]
    )


def i2i_mode_title(mode: str) -> str:
    return "Reference Image Generate" if mode == I2I_MODE_REFERENCE else "Image Edit"


def i2i_retry_command(mode: str) -> str:
    return "/refimg" if mode == I2I_MODE_REFERENCE else "/imgedit"


def ref_model_prompt_hint(model_key: str) -> str:
    endpoint = str(REF_IMAGE_MODELS.get(model_key, REF_IMAGE_MODELS["nano_ref"])["endpoint"])
    if endpoint == "outpaint":
        return "Describe what should be expanded around the source image."
    if endpoint == "face_gen":
        return "Describe style/scene while keeping the same face identity."
    if endpoint == "img_mixer":
        return "Describe the blended look you want from this reference style."
    return "Describe what to generate while keeping style/identity."


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


def call_modelslab_kling_v3_t2v(settings: Settings, payload: dict) -> dict:
    response = requests.post(
        KLING_V3_T2V_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "model_id": KLING_V3_T2V_MODEL_ID,
            "aspect_ratio": payload["aspect_ratio"],
            "duration": payload["duration"],
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
    model_key = payload["t2i_model_key"]
    model_cfg = T2I_MODELS[model_key]

    if model_cfg["endpoint"] == "v7":
        body = {
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "model_id": model_cfg["model_id"],
            "track_id": None,
        }
        if model_cfg["field"] == "aspect_ratio":
            body["aspect_ratio"] = payload["aspect_ratio"]
        else:
            body["size"] = model_cfg["size_map"][payload["aspect_ratio"]]

        response = requests.post(T2I_API_URL, json=body, timeout=60)
        response.raise_for_status()
        return response.json()

    raise RuntimeError(f"Unsupported text-to-image endpoint: {model_cfg['endpoint']}")


def call_modelslab_i2i(settings: Settings, payload: dict) -> dict:
    body = {
        "key": settings.modelslab_api_key,
        "prompt": payload["prompt"],
        "model_id": I2I_MODEL_ID,
        "init_image": payload["init_image"],
        "aspect_ratio": payload["aspect_ratio"],
        "track_id": None,
    }
    response = requests.post(I2I_API_URL, json=body, timeout=60)
    if response.status_code == 403:
        logger.warning("v7 image-to-image forbidden; falling back to v6 edit endpoints")
        return call_modelslab_i2i_fallback_v6(settings, payload)
    response.raise_for_status()
    return response.json()


def call_modelslab_i2i_fallback_v6(settings: Settings, payload: dict) -> dict:
    """Fallback chain for accounts without v7 i2i permission."""
    init_images = payload.get("init_image") or []
    init_image = init_images[0] if init_images else ""
    if not init_image:
        raise RuntimeError("Missing init_image for i2i fallback")

    # 1) Try Qwen Edit first (closest semantic replacement for edit/reference flow).
    qwen_response = requests.post(
        QWEN_EDIT_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "init_image": [init_image],
            "model_id": "qwen-edit-2511",
            "safety_checker": True,
            "base64": False,
            "webhook": None,
            "track_id": None,
        },
        timeout=60,
    )
    if qwen_response.status_code < 400:
        return qwen_response.json()

    # 2) Final fallback: image mixer with duplicated source image.
    width, height = RATIO_TO_SIZE.get(str(payload.get("aspect_ratio", "1:1")), (1024, 1024))
    mixer_response = requests.post(
        IMG_MIXER_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "init_image": [init_image, init_image],
            "negative_prompt": "",
            "width": width,
            "height": height,
            "steps": 31,
            "guidance_scale": 8,
            "samples": 1,
            "seed": None,
            "webhook": None,
            "track_id": None,
        },
        timeout=60,
    )
    mixer_response.raise_for_status()
    return mixer_response.json()


def call_modelslab_reference(settings: Settings, payload: dict) -> dict:
    model_key = str(payload.get("ref_model_key", "nano_ref"))
    model_cfg = REF_IMAGE_MODELS.get(model_key, REF_IMAGE_MODELS["nano_ref"])
    endpoint = str(model_cfg["endpoint"])
    width, height = RATIO_TO_SIZE.get(str(payload.get("aspect_ratio", "1:1")), (1024, 1024))
    init_images = payload.get("init_image") or []
    init_image = init_images[0] if init_images else ""
    if not init_image:
        raise RuntimeError("Missing init_image for reference generation")

    if endpoint == "v7_i2i":
        return call_modelslab_i2i(settings, payload)

    if endpoint == "qwen_edit":
        response = requests.post(
            QWEN_EDIT_API_URL,
            json={
                "key": settings.modelslab_api_key,
                "prompt": payload["prompt"],
                "init_image": payload["init_image"],
                "model_id": model_cfg["model_id"],
                "safety_checker": True,
                "base64": False,
                "webhook": None,
                "track_id": None,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    if endpoint == "flux_kontext":
        response = requests.post(
            FLUX_KONTEXT_API_URL,
            json={
                "key": settings.modelslab_api_key,
                "model_id": model_cfg["model_id"],
                "prompt": payload["prompt"],
                "init_image": init_image,
                "negative_prompt": "",
                "num_inference_steps": "28",
                "safety_checker": True,
                "strength": "0.5",
                "guidance": "2.5",
                "enhance_prompt": None,
                "width": width,
                "height": height,
                "samples": 1,
                "webhook": None,
                "track_id": None,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    if endpoint == "realtime_img2img":
        response = requests.post(
            REALTIME_IMG2IMG_API_URL,
            json={
                "key": settings.modelslab_api_key,
                "prompt": payload["prompt"],
                "negative_prompt": "",
                "init_image": init_image,
                "width": width,
                "height": height,
                "samples": 1,
                "safety_checker": False,
                "strength": 0.7,
                "seed": None,
                "webhook": None,
                "track_id": None,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    if endpoint == "face_gen":
        face_w, face_h = FACEGEN_RATIO_TO_SIZE.get(str(payload.get("aspect_ratio", "1:1")), (512, 512))
        response = requests.post(
            FACE_GEN_API_URL,
            json={
                "key": settings.modelslab_api_key,
                "prompt": payload["prompt"],
                "face_image": init_image,
                "negative_prompt": "",
                "width": face_w,
                "height": face_h,
                "samples": 1,
                "num_inference_steps": 21,
                "safety_checker": False,
                "base64": False,
                "seed": None,
                "guidance_scale": 7.5,
                "webhook": None,
                "track_id": None,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    if endpoint == "outpaint":
        response = requests.post(
            OUTPAINT_API_URL,
            json={
                "key": settings.modelslab_api_key,
                "prompt": payload["prompt"],
                "image": init_image,
                "negative_prompt": "",
                "width": width,
                "height": height,
                "overlap_width": 24,
                "num_inference_steps": 20,
                "guidance_scale": 8.0,
                "seed": None,
                "temp": True,
                "base64": False,
                "webhook": None,
                "track_id": None,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    if endpoint == "img_mixer":
        response = requests.post(
            IMG_MIXER_API_URL,
            json={
                "key": settings.modelslab_api_key,
                "prompt": payload["prompt"],
                "init_image": [init_image, init_image],
                "negative_prompt": "",
                "width": width,
                "height": height,
                "steps": 31,
                "guidance_scale": 8,
                "samples": 1,
                "seed": None,
                "webhook": None,
                "track_id": None,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    raise RuntimeError(f"Unsupported reference model endpoint: {endpoint}")


def call_modelslab_i2v(settings: Settings, payload: dict) -> dict:
    model_key = payload["i2v_model_key"]
    model_cfg = I2V_MODELS[model_key]
    defaults = model_cfg["defaults"]

    if model_cfg["fetch"] == "v7":
        body = {
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "init_image": payload["init_image"],
            "track_id": None,
            **defaults,
        }
        response = requests.post(I2V_V7_API_URL, json=body, timeout=60)
        response.raise_for_status()
        return response.json()

    if model_cfg["fetch"] == "v6":
        body = {
            "key": settings.modelslab_api_key,
            "prompt": payload["prompt"],
            "init_image": payload["init_image"],
            "track_id": None,
            **defaults,
        }
        response = requests.post(LTX_I2V_API_URL, json=body, timeout=60)
        response.raise_for_status()
        return response.json()

    raise RuntimeError(f"Unsupported image-to-video fetch mode: {model_cfg['fetch']}")


def call_modelslab_faceswap(settings: Settings, payload: dict) -> dict:
    response = requests.post(
        FACESWAP_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "init_image": payload["init_image"],
            "target_image": payload["target_image"],
            "reference_image": payload["reference_image"],
            "base64": False,
            "webhook": None,
            "track_id": None,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def call_modelslab_nsfw_check(settings: Settings, init_image: str, threshold: float = 0.5) -> dict:
    response = requests.post(
        NSFW_IMAGE_CHECK_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "init_image": init_image,
            "threshold": threshold,
        },
        timeout=45,
    )
    response.raise_for_status()
    return response.json()


def _extract_json_object(value: str) -> Optional[dict]:
    text = value.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:  # noqa: BLE001
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _extract_caption_text(data: dict) -> str:
    candidates: list[str] = []
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip())
    elif isinstance(output, str) and output.strip():
        candidates.append(output.strip())

    for key in ("caption", "message", "result", "description"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())

    meta = data.get("meta")
    if isinstance(meta, dict):
        for key in ("caption", "description", "text"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

    # Keep the longest non-link text candidate.
    candidates = [c for c in candidates if not c.lower().startswith("http")]
    if not candidates:
        return ""
    return max(candidates, key=len)


def call_modelslab_caption(settings: Settings, image_url: str) -> str:
    response = requests.post(
        CAPTION_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "init_image": image_url,
            "length": "long",
            "base64": False,
            "webhook": None,
            "track_id": None,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    caption = _extract_caption_text(data)
    if caption:
        return caption

    status = str(data.get("status", "")).lower()
    request_id = data.get("id") or data.get("request_id")
    if status in {"processing", "queued", "pending"} and request_id:
        deadline = time.time() + 90
        while time.time() < deadline:
            polled = fetch_result_image_editing(settings, str(request_id))
            caption = _extract_caption_text(polled)
            if caption:
                return caption
            polled_status = str(polled.get("status", "")).lower()
            if polled_status in {"failed", "error"}:
                break
            time.sleep(3)
    return ""


def call_style_analysis_llm(settings: Settings, image_url: str, caption_hint: str = "") -> dict:
    system_prompt = (
        "You are a senior visual-style analyst. Analyze image realism and style with strict fidelity.\n"
        "Return JSON only with keys: style_class, visual_notes, fidelity_prompt, quality_rules.\n"
        "style_class should be short (e.g. phone photo, cinematic, editorial, anime, 3d render).\n"
        "visual_notes should be a concise technical summary (lighting, texture, lens feel, noise, realism).\n"
        "fidelity_prompt must be a detailed generation prompt preserving style details while creating a NEW image,\n"
        "not a direct copy. quality_rules must be strict constraints to avoid artificial AI look."
    )
    user_text = (
        "Analyze this style-reference image deeply and produce a high-fidelity prompt that preserves visual authenticity.\n"
        "Focus on lighting, texture realism, camera feel, grain/noise characteristics, dynamic range, color rendering,"
        " depth, and material details.\n"
        "Important: output should feel different from this image (new framing/composition/scene details),"
        " but keep the same style DNA and realism level."
    )
    if caption_hint:
        user_text += (
            "\n\nAdditional image-caption hint extracted from a vision tool:\n"
            f"{caption_hint}\n"
            "Use it to improve specificity, but prioritize image-grounded details."
        )
    payload = {
        "model": STYLE_ANALYSIS_MODEL_PRIMARY,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        "max_tokens": 900,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {settings.modelslab_api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        LLM_CHAT_API_URL,
        headers=headers,
        json=payload,
        timeout=120,
    )
    if response.status_code >= 400:
        # Fallback if primary thinking model is unavailable on current account.
        fallback_payload = dict(payload)
        fallback_payload["model"] = STYLE_ANALYSIS_MODEL_FALLBACK
        response = requests.post(
            LLM_CHAT_API_URL,
            headers=headers,
            json=fallback_payload,
            timeout=120,
        )
    response.raise_for_status()
    return response.json()


def parse_style_analysis_reply(data: dict) -> dict:
    content = extract_llm_reply(data)
    parsed = _extract_json_object(content) if content else None
    if parsed:
        style_class = str(parsed.get("style_class", "")).strip() or "unknown"
        visual_notes = str(parsed.get("visual_notes", "")).strip()
        fidelity_prompt = str(parsed.get("fidelity_prompt", "")).strip()
        quality_rules = parsed.get("quality_rules") or []
        if not isinstance(quality_rules, list):
            quality_rules = [str(quality_rules)]
        quality_rules = [str(item).strip() for item in quality_rules if str(item).strip()]
        if fidelity_prompt:
            return {
                "style_class": style_class,
                "visual_notes": visual_notes,
                "fidelity_prompt": fidelity_prompt,
                "quality_rules": quality_rules,
            }

    return {
        "style_class": "unknown",
        "visual_notes": "",
        "fidelity_prompt": content.strip() if content else "High-fidelity natural reconstruction of source style.",
        "quality_rules": [],
    }


def is_weak_style_analysis(analysis: dict) -> bool:
    style_class = str(analysis.get("style_class", "")).strip().lower()
    fidelity_prompt = str(analysis.get("fidelity_prompt", "")).strip()
    if not fidelity_prompt:
        return True
    if len(fidelity_prompt) < 140:
        return True
    if "high-fidelity natural reconstruction of source style" in fidelity_prompt.lower():
        return True
    if style_class in {"", "unknown"}:
        return True
    return False


def infer_style_class_from_text(text: str) -> str:
    value = text.lower()
    mapping = [
        ("phone photo", ("smartphone", "phone shot", "mobile photo", "iphone", "selfie")),
        ("cinematic", ("cinematic", "film still", "movie scene", "dramatic lighting")),
        ("portrait photography", ("portrait", "headshot", "close-up face", "shallow depth of field")),
        ("street photography", ("street", "urban", "city night", "documentary")),
        ("product photography", ("product", "studio backdrop", "catalog", "packshot")),
        ("editorial fashion", ("fashion", "editorial", "runway", "styled outfit")),
        ("illustration", ("illustration", "drawing", "sketch", "artwork")),
        ("anime", ("anime", "manga", "cel-shaded")),
        ("3d render", ("3d render", "cgi", "rendered")),
    ]
    for label, keywords in mapping:
        if any(keyword in value for keyword in keywords):
            return label
    return "natural photography"


def fallback_analysis_from_caption(caption_hint: str) -> dict:
    style_class = infer_style_class_from_text(caption_hint)
    visual_notes = (
        "Use natural lighting behavior, realistic textures, authentic lens rendering, "
        "and physically plausible shadows/highlights."
    )
    fidelity_prompt = (
        "Create a new, non-duplicated image preserving the same visual style and realism quality. "
        f"Scene details from source: {caption_hint}. "
        "Keep the mood, material texture fidelity, camera feel, and color rendering consistent, "
        "while introducing a fresh composition and clearly different framing."
    )
    return {
        "style_class": style_class,
        "visual_notes": visual_notes,
        "fidelity_prompt": fidelity_prompt,
        "quality_rules": [
            "no plastic or over-smoothed textures",
            "no synthetic AI artifacts",
            "maintain realistic lighting and dynamic range",
            "preserve natural camera feel",
        ],
    }


def build_styleclone_prompt(analysis: dict) -> str:
    style_class = str(analysis.get("style_class", "unknown")).strip()
    visual_notes = str(analysis.get("visual_notes", "")).strip()
    fidelity_prompt = str(analysis.get("fidelity_prompt", "")).strip()
    quality_rules = analysis.get("quality_rules") or []
    details: list[str] = []
    if style_class and style_class.lower() != "unknown":
        details.append(f"Style class: {style_class}")
    if visual_notes:
        details.append(f"Visual notes: {visual_notes}")
    if quality_rules:
        rules = "; ".join(str(rule).strip() for rule in quality_rules if str(rule).strip())
        if rules:
            details.append(f"Quality constraints: {rules}")
    if details:
        return f"{fidelity_prompt}\n\n" + "\n".join(details)
    return fidelity_prompt


def call_modelslab_styleclone(settings: Settings, payload: dict) -> dict:
    style_image = str(payload["style_image"])
    subject_image = str(payload["subject_image"])
    prompt = str(payload["prompt"])
    aspect_ratio = str(payload.get("aspect_ratio", "1:1"))
    # Required path: final generation handled by Nano Banana (gemini-3.1-i2i).
    # First try subject + style references together; fallback to subject-only if provider rejects multi-reference input.
    response = requests.post(
        I2I_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": prompt,
            "model_id": I2I_MODEL_ID,
            "init_image": [subject_image, style_image],
            "aspect_ratio": aspect_ratio,
            "track_id": None,
        },
        timeout=90,
    )
    if response.status_code < 400:
        return response.json()

    # Fallback path: subject image as init; style is already encoded in generated prompt.
    fallback = requests.post(
        I2I_API_URL,
        json={
            "key": settings.modelslab_api_key,
            "prompt": prompt,
            "model_id": I2I_MODEL_ID,
            "init_image": [subject_image],
            "aspect_ratio": aspect_ratio,
            "track_id": None,
        },
        timeout=90,
    )
    fallback.raise_for_status()
    return fallback.json()


def fetch_result_v7(settings: Settings, request_id: str) -> dict:
    response = requests.post(
        KLING_FETCH_URL_TEMPLATE.format(request_id=request_id),
        json={"key": settings.modelslab_api_key},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def call_modelslab_llm(settings: Settings, payload: dict) -> dict:
    model_key = str(payload["llm_model_key"])
    model_cfg = LLM_MODELS[model_key]
    messages = payload.get("messages")
    if not messages:
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant. Give clear, practical answers.",
            },
            {
                "role": "user",
                "content": payload["prompt"],
            },
        ]
    response = requests.post(
        LLM_CHAT_API_URL,
        headers={
            "Authorization": f"Bearer {settings.modelslab_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_cfg["model"],
            "messages": messages,
            "max_tokens": payload.get("max_tokens", 700),
            "temperature": 0.7,
        },
        timeout=90,
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


def fetch_result_faceswap(settings: Settings, request_id: str) -> dict:
    response = requests.post(
        FACESWAP_FETCH_URL_TEMPLATE.format(request_id=request_id),
        json={"key": settings.modelslab_api_key},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_result_image_editing(settings: Settings, request_id: str) -> dict:
    response = requests.post(
        f"https://modelslab.com/api/v6/image_editing/fetch/{request_id}",
        json={"key": settings.modelslab_api_key},
        timeout=30,
    )
    if response.status_code < 400:
        return response.json()
    return fetch_result_t2i(settings, request_id)


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


def _result_action_store(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.bot_data.setdefault("result_actions", {})


def result_action_markup(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    task_type: str,
    payload: dict,
    model_name: str,
) -> InlineKeyboardMarkup:
    token = uuid4().hex[:10]
    store = _result_action_store(context)
    store[token] = {
        "user_id": user_id,
        "chat_id": chat_id,
        "task_type": task_type,
        "payload": dict(payload),
        "model_name": model_name,
    }
    # Keep memory bounded for long-running bots.
    while len(store) > 400:
        store.pop(next(iter(store)))
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔁 Regenerate", callback_data=f"{RERUN_CALLBACK_PREFIX}{token}"),
                InlineKeyboardButton("✨ Variation", callback_data=f"{VARIATION_CALLBACK_PREFIX}{token}"),
            ],
            [InlineKeyboardButton("🏠 Menu", callback_data=MENU_BACK_CALLBACK)],
        ]
    )


def variation_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Create a clearly different variation of the same concept with a new composition,"
        " camera framing, and visual details."
    )


def generation_config_from_task(task_type: str, payload: dict) -> dict:
    if task_type == "kling_motion":
        return {
            "call": call_modelslab_kling,
            "fetch": fetch_result_v7,
            "kind": "video",
            "job_title": "Kling 3.0 Motion Control",
            "max_wait": 420,
        }
    if task_type == "ltx_t2v":
        return {
            "call": call_modelslab_ltx,
            "fetch": fetch_result_v6,
            "kind": "video",
            "job_title": "LTX 2.3 Text-to-Video",
            "max_wait": 420,
        }
    if task_type == "kling_v3_t2v":
        return {
            "call": call_modelslab_kling_v3_t2v,
            "fetch": fetch_result_v7,
            "kind": "video",
            "job_title": "Kling V3.0 Text-to-Video",
            "max_wait": 420,
        }
    if task_type == "sora_t2v":
        return {
            "call": call_modelslab_sora,
            "fetch": fetch_result_v7,
            "kind": "video",
            "job_title": "Sora 2 Pro Text-to-Video",
            "max_wait": 420,
        }
    if task_type == "t2i":
        model_key = str(payload.get("t2i_model_key", "nano"))
        model_label = T2I_MODELS.get(model_key, T2I_MODELS["nano"])["label"]
        return {
            "call": call_modelslab_t2i,
            "fetch": fetch_result_t2i,
            "kind": "image",
            "job_title": f"{model_label} Text-to-Image",
            "max_wait": 240,
        }
    if task_type == "i2i":
        mode = str(payload.get("i2i_mode", I2I_MODE_EDIT))
        if mode == I2I_MODE_REFERENCE:
            ref_key = str(payload.get("ref_model_key", "nano_ref"))
            ref_cfg = REF_IMAGE_MODELS.get(ref_key, REF_IMAGE_MODELS["nano_ref"])
            job_title = f"{ref_cfg['label']} Reference Generate"
            call_fn = call_modelslab_reference
        else:
            job_title = "Nano Banana 2 Image Edit"
            call_fn = call_modelslab_i2i
        return {
            "call": call_fn,
            "fetch": fetch_result_t2i,
            "kind": "image",
            "job_title": job_title,
            "max_wait": 240,
        }
    if task_type == "i2v":
        model_key = str(payload.get("i2v_model_key", ""))
        model_cfg = I2V_MODELS.get(model_key)
        if not model_cfg:
            raise RuntimeError("Unsupported image-to-video model in saved action.")
        return {
            "call": call_modelslab_i2v,
            "fetch": fetch_result_v7 if model_cfg["fetch"] == "v7" else fetch_result_v6,
            "kind": "video",
            "job_title": model_cfg["label"],
            "max_wait": 420,
        }
    if task_type == "faceswap":
        return {
            "call": call_modelslab_faceswap,
            "fetch": fetch_result_faceswap,
            "kind": "image",
            "job_title": "Face Swap",
            "max_wait": 240,
        }
    if task_type == "styleclone":
        return {
            "call": call_modelslab_styleclone,
            "fetch": fetch_result_t2i,
            "kind": "image",
            "job_title": "Style Fidelity Clone",
            "max_wait": 360,
        }
    raise RuntimeError(f"Unsupported saved task type: {task_type}")


async def run_saved_action(
    context: ContextTypes.DEFAULT_TYPE,
    action: dict,
    use_variation: bool,
) -> None:
    settings: Settings = context.bot_data["settings"]
    chat_id = int(action["chat_id"])
    user_id = int(action["user_id"])
    task_type = str(action["task_type"])
    model_name = str(action["model_name"])
    payload = dict(action["payload"])
    if use_variation and str(payload.get("prompt", "")).strip():
        payload["prompt"] = variation_prompt(str(payload["prompt"]).strip())

    config = generation_config_from_task(task_type, payload)
    run_label = "Variation" if use_variation else "Regenerate"
    status_message = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ {config['job_title']} ({run_label})\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title=f"{config['job_title']} ({run_label})",
    )
    try:
        created = await asyncio.to_thread(config["call"], settings, payload)
        output = created.get("output") or []
        result_url: Optional[str] = output[0] if str(created.get("status", "")).lower() == "success" and output else None
        if not result_url:
            request_id = created.get("id") or created.get("request_id")
            if not request_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Unexpected ModelsLab response: {created}",
                )
                return
            result_url = await poll_result(
                settings,
                request_id=request_id,
                fetch_fn=config["fetch"],
                progress_callback=progress_callback,
                max_wait=int(config["max_wait"]),
            )

        if not result_url:
            await finalize_progress_message(
                context,
                status_message,
                f"❌ {config['job_title']} ({run_label}) failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{config['job_title']} {run_label.lower()} failed or timed out.",
            )
            return

        await finalize_progress_message(
            context,
            status_message,
            f"✅ {config['job_title']} ({run_label}) completed. Sending result...",
        )
        if config["kind"] == "video":
            await send_video_result(
                context=context,
                chat_id=chat_id,
                video_url=result_url,
                payload=payload,
                model_name=model_name,
                user_id=user_id,
                task_type=task_type,
            )
        else:
            await send_image_result(
                context=context,
                chat_id=chat_id,
                image_url=result_url,
                payload=payload,
                model_name=model_name,
                user_id=user_id,
                task_type=task_type,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Saved action execution failed")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Action failed: {exc}",
        )


async def result_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    token = query.data.split("_", 1)[1]
    is_variation = query.data.startswith(VARIATION_CALLBACK_PREFIX)
    action = _result_action_store(context).get(token)

    if not action:
        await query.answer("This action expired. Generate again to refresh buttons.", show_alert=True)
        return
    if not is_verified(query.from_user.id, settings):
        await query.answer("Access required. Send /start first.", show_alert=True)
        return
    if int(action["user_id"]) != query.from_user.id:
        await query.answer("Only the original requester can use this action.", show_alert=True)
        return

    await query.answer("Running variation..." if is_variation else "Regenerating...")
    await run_saved_action(context, action, use_variation=is_variation)


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
        last_t2v_model = get_user_pref(context, query.from_user.id, "t2v_model")
        await query.edit_message_text(
            "🎬 Text to Video\n\n"
            "Quick guide:\n"
            "• Fast: LTX 2.3\n"
            "• Balanced: Kling V3.0\n"
            "• Highest quality: Sora 2 Pro\n\n"
            "Choose a model:",
            reply_markup=text_to_video_keyboard(last_t2v_model),
        )
        return

    if data == "menu_i2v":
        last_i2v_model = get_user_pref(context, query.from_user.id, "i2v_last_entry")
        await query.edit_message_text(
            "🧷 Image to Video\n\n"
            "Quick guide:\n"
            "• Character control: Kling Motion\n"
            "• Fast: LTX 2.3\n"
            "• Highest quality: LTX 2.3 Pro\n\n"
            "Choose a model:",
            reply_markup=image_to_video_keyboard(last_i2v_model),
        )
        return

    if data == MENU_BACK_CALLBACK:
        await send_main_menu(update)


def extract_llm_reply(data: dict) -> str:
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        reasoning = message.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning.strip()
    msg = data.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    return ""


def llm_model_matches_selection(selected_key: str, actual_model: str) -> bool:
    if selected_key == "best":
        return True
    normalized = actual_model.strip().lower()
    if not normalized:
        return False
    expected_tokens = {
        "chatgpt": ("gpt", "openai"),
        "claude": ("claude", "anthropic"),
        "deepseek": ("deepseek",),
        "llama": ("llama", "meta"),
        "qwen": ("qwen",),
        "mistral": ("mistral", "mixtral"),
    }
    tokens = expected_tokens.get(selected_key, ())
    return any(token in normalized for token in tokens)


def llm_mismatch_text(selected_key: str, actual_model: str) -> str:
    selected_name = LLM_MODELS.get(selected_key, {}).get("label", selected_key)
    return (
        f"Model mismatch detected.\n"
        f"Selected: {selected_name}\n"
        f"Returned: {actual_model or 'unknown'}\n\n"
        "To avoid random model switching, this reply was blocked.\n"
        "Try another model option (Qwen/Best) or /llmclear."
    )


async def start_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    user = update.effective_user
    if not user:
        return
    if not is_verified(user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return
    context.user_data.clear()
    await send_main_menu(update)


async def uncensored_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    set_user_pref(context, user_id, "llm_model_key", "best")
    context.user_data.clear()
    context.user_data["llm_model_key"] = "best"
    turns = len(get_llm_history(context, user_id, "best")) // 2
    await update.message.reply_text(
        "Uncensored Chat started (Llama 3.1 Uncensored).\n"
        "Send your message now."
        + (f"\nMemory loaded: {turns} turns." if turns else "")
        + "\nUse /llmclear to reset memory."
    )
    return WAITING_LLM_PROMPT


async def uncensored_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    set_user_pref(context, query.from_user.id, "llm_model_key", "best")
    context.user_data.clear()
    context.user_data["llm_model_key"] = "best"
    turns = len(get_llm_history(context, query.from_user.id, "best")) // 2
    await query.edit_message_text(
        "Uncensored Chat started (Llama 3.1 Uncensored).\n"
        "Send your message now."
        + (f"\nMemory loaded: {turns} turns." if turns else "")
        + "\nUse /llmclear to reset memory."
    )
    return WAITING_LLM_PROMPT


async def llm_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    last_model = get_user_pref(context, user_id, "llm_model_key", "best")
    memory_messages = len(get_llm_history(context, user_id, last_model)) if last_model in LLM_MODELS else 0
    context.user_data.clear()
    await update.message.reply_text(
        "LLM Chat Step 1/2: Choose model."
        + (
            f"\nLast used: {LLM_MODELS[last_model]['label']}"
            if last_model in LLM_MODELS
            else ""
        )
        + (f"\nSaved memory: {memory_messages // 2} turns" if memory_messages else "")
        + "\nTip: /llmclear resets memory.",
        reply_markup=llm_model_keyboard(last_model),
    )
    return WAITING_LLM_MODEL


async def llm_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    last_model = get_user_pref(context, query.from_user.id, "llm_model_key", "best")
    memory_messages = (
        len(get_llm_history(context, query.from_user.id, last_model))
        if last_model in LLM_MODELS
        else 0
    )
    context.user_data.clear()
    await query.edit_message_text(
        "LLM Chat Step 1/2: Choose model."
        + (
            f"\nLast used: {LLM_MODELS[last_model]['label']}"
            if last_model in LLM_MODELS
            else ""
        )
        + (f"\nSaved memory: {memory_messages // 2} turns" if memory_messages else "")
        + "\nTip: /llmclear resets memory.",
        reply_markup=llm_model_keyboard(last_model),
    )
    return WAITING_LLM_MODEL


async def receive_llm_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == MENU_BACK_CALLBACK:
        await send_main_menu(update)
        return ConversationHandler.END

    model_key = query.data.replace("llm_model_", "", 1)
    if model_key not in LLM_MODELS:
        await query.edit_message_text("Unsupported LLM model. Send /llm to start again.")
        return ConversationHandler.END

    set_user_pref(context, query.from_user.id, "llm_model_key", model_key)
    context.user_data["llm_model_key"] = model_key
    turns = len(get_llm_history(context, query.from_user.id, model_key)) // 2
    await query.edit_message_text(
        f"LLM Chat Step 2/2: Ask your question for {LLM_MODELS[model_key]['label']}."
        + (f"\nMemory loaded: {turns} turns." if turns else "")
    )
    return WAITING_LLM_PROMPT


async def receive_llm_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_LLM_PROMPT

    model_key = str(context.user_data.get("llm_model_key", "best"))
    if model_key not in LLM_MODELS:
        await update.message.reply_text("Select model again with /llm.")
        return ConversationHandler.END

    history = get_llm_history(context, user_id, model_key)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. Maintain continuity using the prior conversation,"
                " and keep answers practical and concise."
            ),
        },
        *history,
        {"role": "user", "content": prompt},
    ]
    payload = {"llm_model_key": model_key, "prompt": prompt, "messages": messages}
    status_message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=f"⏳ {LLM_MODELS[model_key]['label']}\nStatus: Thinking with memory...",
    )
    try:
        data = await asyncio.to_thread(call_modelslab_llm, settings, payload)
        reply_text = extract_llm_reply(data)
        if not reply_text:
            await finalize_progress_message(
                context,
                status_message,
                "❌ LLM reply failed.",
            )
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=f"LLM API error: {data.get('message') or data}",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            "✅ LLM reply ready.",
        )
        used_model = str(data.get("model") or LLM_MODELS[model_key]["model"])
        if not llm_model_matches_selection(model_key, used_model):
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=llm_mismatch_text(model_key, used_model),
            )
            return WAITING_LLM_PROMPT

        save_llm_turn(
            context,
            user_id,
            model_key,
            truncate_text(prompt, 1200),
            truncate_text(reply_text, 1200),
        )
        turns = len(get_llm_history(context, user_id, model_key)) // 2
        answer = truncate_text(reply_text, 3600)
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=(
                f"🤖 {LLM_MODELS[model_key]['label']}\n"
                f"Model: {used_model}\n"
                f"Memory: {turns} turns\n\n{answer}"
            ),
        )
        return WAITING_LLM_PROMPT
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM API call failed")
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=f"LLM API error: {exc}",
        )
        return WAITING_LLM_PROMPT


async def llm_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user = update.effective_user
    if not user:
        return ConversationHandler.END
    if not is_verified(user.id, settings):
        if update.message:
            await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    model_key = str(context.user_data.get("llm_model_key", "")).strip()
    if model_key in LLM_MODELS:
        removed = clear_llm_history(context, user.id, model_key=model_key)
        if update.message:
            await update.message.reply_text(
                f"Cleared {removed // 2} turns for {LLM_MODELS[model_key]['label']}."
            )
    else:
        removed = clear_llm_history(context, user.id, model_key=None)
        if update.message:
            await update.message.reply_text(
                f"Cleared all LLM memory ({removed // 2} turns)."
            )
    return WAITING_LLM_PROMPT


async def t2i_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    last_model = get_user_pref(context, user_id, "t2i_model_key")
    last_ratio = get_user_pref(context, user_id, "t2i_aspect_ratio")
    last_summary = []
    if last_model in T2I_MODELS:
        last_summary.append(T2I_MODELS[last_model]["label"])
    if last_ratio:
        last_summary.append(last_ratio)

    context.user_data.clear()
    await update.message.reply_text(
        "Text to Image Step 1/3: Choose model."
        + (f"\nLast used: {' | '.join(last_summary)}" if last_summary else ""),
        reply_markup=t2i_model_keyboard(last_model),
    )
    return WAITING_T2I_MODEL


async def t2i_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    last_model = get_user_pref(context, query.from_user.id, "t2i_model_key")
    last_ratio = get_user_pref(context, query.from_user.id, "t2i_aspect_ratio")
    last_summary = []
    if last_model in T2I_MODELS:
        last_summary.append(T2I_MODELS[last_model]["label"])
    if last_ratio:
        last_summary.append(last_ratio)

    context.user_data.clear()
    await query.edit_message_text(
        "Text to Image Step 1/3: Choose model."
        + (f"\nLast used: {' | '.join(last_summary)}" if last_summary else ""),
        reply_markup=t2i_model_keyboard(last_model),
    )
    return WAITING_T2I_MODEL


async def receive_t2i_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    model_key = query.data.replace("t2i_model_", "", 1)
    if model_key not in T2I_MODELS:
        await query.edit_message_text("Unsupported text-to-image model. Send /t2i again.")
        return ConversationHandler.END

    set_user_pref(context, query.from_user.id, "t2i_model_key", model_key)
    context.user_data["t2i_model_key"] = model_key
    await query.edit_message_text(
        f"Text to Image Step 2/3: Enter prompt for {T2I_MODELS[model_key]['label']}."
    )
    return WAITING_T2I_PROMPT


async def receive_t2i_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_T2I_PROMPT

    context.user_data["prompt"] = prompt
    last_ratio = get_user_pref(context, update.effective_user.id, "t2i_aspect_ratio", "1:1")
    keyboard = [
        [
            InlineKeyboardButton(_selected_label("1:1", last_ratio == "1:1"), callback_data="t2i_ar_1:1"),
            InlineKeyboardButton(
                _selected_label("16:9", last_ratio == "16:9"),
                callback_data="t2i_ar_16:9",
            ),
            InlineKeyboardButton(_selected_label("9:16", last_ratio == "9:16"), callback_data="t2i_ar_9:16"),
        ],
    ]
    await update.message.reply_text(
        "Text to Image Step 3/3: Choose aspect ratio. (✅ = last used)",
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
    if aspect_ratio not in T2I_RATIO_SHORTLIST:
        await query.edit_message_text("Unsupported aspect ratio. Send /t2i to start again.")
        return ConversationHandler.END

    model_key = context.user_data.get("t2i_model_key", "nano")
    if model_key not in T2I_MODELS:
        await query.edit_message_text("Unsupported model. Send /t2i to start again.")
        return ConversationHandler.END

    context.user_data["t2i_model_key"] = model_key
    context.user_data["aspect_ratio"] = aspect_ratio
    set_user_pref(context, query.from_user.id, "t2i_aspect_ratio", aspect_ratio)
    await query.edit_message_text(
        f"Generating image with {T2I_MODELS[model_key]['label']}. Please wait..."
    )

    payload = dict(context.user_data)
    status_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⏳ Nano Banana 2 Text-to-Image\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title=f"{T2I_MODELS[model_key]['label']} Text-to-Image",
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
                    model_name=f"{T2I_MODELS[model_key]['label']} ({aspect_ratio})",
                    user_id=query.from_user.id,
                    task_type="t2i",
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
            model_name=f"{T2I_MODELS[model_key]['label']} ({aspect_ratio})",
            user_id=query.from_user.id,
            task_type="t2i",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("T2I API call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Text-to-image API error: {exc}",
        )
        return ConversationHandler.END


async def i2v_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    last_i2v_model = get_user_pref(context, user_id, "i2v_model_key")
    context.user_data.clear()
    await update.message.reply_text(
        "Image-to-Video Step 1/3: Choose model."
        + (f"\nLast used: {I2V_MODELS[last_i2v_model]['label']}" if last_i2v_model in I2V_MODELS else ""),
        reply_markup=i2v_model_keyboard(last_i2v_model),
    )
    return WAITING_I2V_MODEL


async def i2v_start_from_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    model_key: str,
) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    try:
        await query.answer()
    except Exception:  # noqa: BLE001
        pass

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END
    if model_key not in I2V_MODELS:
        await query.edit_message_text("Unsupported image-to-video model.")
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["i2v_model_key"] = model_key
    set_user_pref(context, query.from_user.id, "i2v_model_key", model_key)
    set_user_pref(context, query.from_user.id, "i2v_last_entry", model_key)
    await query.edit_message_text(
        f"{I2V_MODELS[model_key]['label']}\n\nStep 2/3: Send source image (JPG/PNG)."
    )
    return WAITING_I2V_IMAGE


async def i2v_start_kling_v3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await i2v_start_from_menu(update, context, "kling_v3_i2v")


async def i2v_start_ltx_pro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await i2v_start_from_menu(update, context, "ltx_pro_i2v")


async def i2v_start_ltx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await i2v_start_from_menu(update, context, "ltx_i2v")


async def i2v_start_grok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await i2v_start_from_menu(update, context, "grok_i2v")


async def receive_i2v_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == MENU_BACK_CALLBACK:
        await send_main_menu(update)
        return ConversationHandler.END
    if query.data == "menu_start_i2v_kling_v3":
        return await i2v_start_from_menu(update, context, "kling_v3_i2v")
    if query.data == "menu_start_i2v_ltx_pro":
        return await i2v_start_from_menu(update, context, "ltx_pro_i2v")
    if query.data == "menu_start_i2v_ltx":
        return await i2v_start_from_menu(update, context, "ltx_i2v")
    if query.data == "menu_start_i2v_grok":
        return await i2v_start_from_menu(update, context, "grok_i2v")
    await query.edit_message_text("Unsupported option. Send /i2v and choose again.")
    return ConversationHandler.END


async def receive_i2v_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    model_key = context.user_data.get("i2v_model_key")
    if model_key not in I2V_MODELS:
        await update.message.reply_text("Select an image-to-video model again with /i2v.")
        return ConversationHandler.END

    image_file = None
    if update.message.photo:
        image_file = update.message.photo[-1]
    elif update.message.document and str(update.message.document.mime_type).startswith("image/"):
        image_file = update.message.document

    if image_file is None:
        await update.message.reply_text("Please send a JPG/PNG image.")
        return WAITING_I2V_IMAGE

    tg_file = await context.bot.get_file(image_file.file_id)
    context.user_data["init_image"] = telegram_file_url(settings, tg_file.file_path)
    await update.message.reply_text("Image-to-Video Step 3/3: Enter your prompt.")
    return WAITING_I2V_PROMPT


async def receive_i2v_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    model_key = context.user_data.get("i2v_model_key")
    if model_key not in I2V_MODELS:
        await update.message.reply_text("Select an image-to-video model again with /i2v.")
        return ConversationHandler.END

    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_I2V_PROMPT

    context.user_data["prompt"] = prompt
    model_label = I2V_MODELS[model_key]["label"]
    await update.message.reply_text(f"Generating with {model_label}. Please wait...")

    payload = dict(context.user_data)
    status_message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text=f"⏳ {model_label}\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title=model_label,
    )
    try:
        created = await asyncio.to_thread(call_modelslab_i2v, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await finalize_progress_message(
                    context,
                    status_message,
                    f"✅ {model_label} completed. Sending video...",
                )
                await send_video_result(
                    context,
                    update.message.chat_id,
                    output[0],
                    payload,
                    model_name=model_label,
                    user_id=update.effective_user.id,
                    task_type="i2v",
                )
                return ConversationHandler.END

        request_id = created.get("id") or created.get("request_id")
        if not request_id:
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=f"Unexpected ModelsLab response: {created}",
            )
            return ConversationHandler.END

        fetch_fn = fetch_result_v7 if I2V_MODELS[model_key]["fetch"] == "v7" else fetch_result_v6
        video_url = await poll_result(
            settings,
            request_id=request_id,
            fetch_fn=fetch_fn,
            progress_callback=progress_callback,
        )
        if not video_url:
            await finalize_progress_message(
                context,
                status_message,
                f"❌ {model_label} failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text=f"{model_label} failed or timed out. Please try /i2v again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            f"✅ {model_label} completed. Sending video...",
        )
        await send_video_result(
            context,
            update.message.chat_id,
            video_url,
            payload,
            model_name=model_label,
            user_id=update.effective_user.id,
            task_type="i2v",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("Image-to-video API call failed")
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=f"Image-to-video API error: {exc}",
        )
        return ConversationHandler.END


async def imgedit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    last_ratio = get_user_pref(context, user_id, "i2i_aspect_ratio")
    context.user_data.clear()
    context.user_data["i2i_mode"] = I2I_MODE_EDIT
    await update.message.reply_text(
        f"{i2i_mode_title(I2I_MODE_EDIT)} Step 1/3: Send source image (JPG/PNG)."
        + (f"\nLast ratio: {last_ratio}" if last_ratio else "")
    )
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

    last_ratio = get_user_pref(context, query.from_user.id, "i2i_aspect_ratio")
    context.user_data.clear()
    context.user_data["i2i_mode"] = I2I_MODE_EDIT
    await query.edit_message_text(
        f"{i2i_mode_title(I2I_MODE_EDIT)} Step 1/3: Send source image (JPG/PNG)."
        + (f"\nLast ratio: {last_ratio}" if last_ratio else "")
    )
    return WAITING_I2I_IMAGE


async def refimg_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    last_ratio = get_user_pref(context, user_id, "i2i_aspect_ratio")
    last_model = get_user_pref(context, user_id, "ref_model_key", "nano_ref")
    context.user_data.clear()
    context.user_data["i2i_mode"] = I2I_MODE_REFERENCE
    context.user_data["ref_model_key"] = last_model
    await update.message.reply_text(
        f"{i2i_mode_title(I2I_MODE_REFERENCE)} Step 1/4: Choose model."
        + (
            f"\nLast used: {REF_IMAGE_MODELS[last_model]['label']}"
            if last_model in REF_IMAGE_MODELS
            else ""
        )
        + (f"\nLast ratio: {last_ratio}" if last_ratio else ""),
        reply_markup=ref_model_keyboard(last_model),
    )
    return WAITING_REF_MODEL


async def refimg_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    last_ratio = get_user_pref(context, query.from_user.id, "i2i_aspect_ratio")
    last_model = get_user_pref(context, query.from_user.id, "ref_model_key", "nano_ref")
    context.user_data.clear()
    context.user_data["i2i_mode"] = I2I_MODE_REFERENCE
    context.user_data["ref_model_key"] = last_model
    await query.edit_message_text(
        f"{i2i_mode_title(I2I_MODE_REFERENCE)} Step 1/4: Choose model."
        + (
            f"\nLast used: {REF_IMAGE_MODELS[last_model]['label']}"
            if last_model in REF_IMAGE_MODELS
            else ""
        )
        + (f"\nLast ratio: {last_ratio}" if last_ratio else ""),
        reply_markup=ref_model_keyboard(last_model),
    )
    return WAITING_REF_MODEL


async def receive_refimg_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == MENU_BACK_CALLBACK:
        await send_main_menu(update)
        return ConversationHandler.END

    model_key = query.data.replace("ref_model_", "", 1)
    if model_key not in REF_IMAGE_MODELS:
        await query.edit_message_text("Unsupported reference model. Send /refimg again.")
        return ConversationHandler.END

    set_user_pref(context, query.from_user.id, "ref_model_key", model_key)
    context.user_data["i2i_mode"] = I2I_MODE_REFERENCE
    context.user_data["ref_model_key"] = model_key
    await query.edit_message_text(
        f"{REF_IMAGE_MODELS[model_key]['label']}\n\n"
        f"{i2i_mode_title(I2I_MODE_REFERENCE)} Step 2/4: Send source image (JPG/PNG)."
    )
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

    mode = str(context.user_data.get("i2i_mode", I2I_MODE_EDIT))
    model_key = str(context.user_data.get("ref_model_key", "nano_ref"))
    model_label = REF_IMAGE_MODELS.get(model_key, REF_IMAGE_MODELS["nano_ref"])["label"]
    tg_file = await context.bot.get_file(image_file.file_id)
    context.user_data["init_image"] = [telegram_file_url(settings, tg_file.file_path)]
    step_text = (
        f"Step 3/4: Enter prompt for {model_label}. {ref_model_prompt_hint(model_key)}"
        if mode == I2I_MODE_REFERENCE
        else "Step 2/3: Enter edit instruction prompt."
    )
    await update.message.reply_text(f"{i2i_mode_title(mode)} {step_text}")
    return WAITING_I2I_PROMPT


async def receive_i2i_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_I2I_PROMPT

    mode = str(context.user_data.get("i2i_mode", I2I_MODE_EDIT))
    context.user_data["prompt"] = prompt
    last_ratio = get_user_pref(context, update.effective_user.id, "i2i_aspect_ratio", "1:1")
    keyboard = [
        [
            InlineKeyboardButton(_selected_label("1:1", last_ratio == "1:1"), callback_data="i2i_ar_1:1"),
            InlineKeyboardButton(_selected_label("16:9", last_ratio == "16:9"), callback_data="i2i_ar_16:9"),
            InlineKeyboardButton(_selected_label("9:16", last_ratio == "9:16"), callback_data="i2i_ar_9:16"),
        ],
        [
            InlineKeyboardButton(_selected_label("4:5", last_ratio == "4:5"), callback_data="i2i_ar_4:5"),
            InlineKeyboardButton(_selected_label("3:4", last_ratio == "3:4"), callback_data="i2i_ar_3:4"),
            InlineKeyboardButton(_selected_label("2:3", last_ratio == "2:3"), callback_data="i2i_ar_2:3"),
        ],
    ]
    step_title = (
        f"{i2i_mode_title(mode)} Step 4/4: Choose aspect ratio. (✅ = last used)"
        if mode == I2I_MODE_REFERENCE
        else f"{i2i_mode_title(mode)} Step 3/3: Choose aspect ratio. (✅ = last used)"
    )
    await update.message.reply_text(
        step_title,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_I2I_ASPECT_RATIO


async def receive_i2i_aspect_ratio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    mode = str(context.user_data.get("i2i_mode", I2I_MODE_EDIT))
    aspect_ratio = query.data.replace("i2i_ar_", "", 1)
    if aspect_ratio not in T2I_ASPECT_RATIOS:
        await query.edit_message_text(
            f"Unsupported aspect ratio. Send {i2i_retry_command(mode)} to start again."
        )
        return ConversationHandler.END

    context.user_data["aspect_ratio"] = aspect_ratio
    set_user_pref(context, query.from_user.id, "i2i_aspect_ratio", aspect_ratio)
    ref_model_key = str(context.user_data.get("ref_model_key", "nano_ref"))
    ref_cfg = REF_IMAGE_MODELS.get(ref_model_key, REF_IMAGE_MODELS["nano_ref"])
    run_label = (
        f"Generating from reference image with {ref_cfg['label']}"
        if mode == I2I_MODE_REFERENCE
        else "Editing image with Nano Banana 2"
    )
    await query.edit_message_text(f"{run_label}. Please wait...")

    payload = dict(context.user_data)
    if mode == I2I_MODE_REFERENCE:
        job_title = f"{ref_cfg['label']} Reference Generate"
        call_fn = call_modelslab_reference
    else:
        job_title = "Nano Banana 2 Image Edit"
        call_fn = call_modelslab_i2i
    result_model_name = f"{job_title} ({aspect_ratio})"
    success_msg = (
        "✅ Reference generation completed. Sending image..."
        if mode == I2I_MODE_REFERENCE
        else "✅ Image edit completed. Sending image..."
    )
    fail_msg = (
        "Reference generation failed or timed out."
        if mode == I2I_MODE_REFERENCE
        else "Image edit failed or timed out."
    )
    status_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"⏳ {job_title}\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title=job_title,
    )
    try:
        created = await asyncio.to_thread(call_fn, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await finalize_progress_message(
                    context,
                    status_message,
                    success_msg,
                )
                await send_image_result(
                    context,
                    query.message.chat_id,
                    output[0],
                    payload,
                    model_name=result_model_name,
                    user_id=query.from_user.id,
                    task_type="i2i",
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
                f"❌ {fail_msg}",
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"{fail_msg} Please try {i2i_retry_command(mode)} again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            success_msg,
        )
        await send_image_result(
            context,
            query.message.chat_id,
            image_url,
            payload,
            model_name=result_model_name,
            user_id=query.from_user.id,
            task_type="i2i",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("Image edit API call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"{i2i_mode_title(mode)} API error: {exc}",
        )
        return ConversationHandler.END


async def faceswap_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "Face Swap Step 1/3: Send base image (face to replace)."
    )
    return WAITING_FACESWAP_INIT_IMAGE


async def faceswap_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()
    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text(
        "Face Swap Step 1/3: Send base image (face to replace)."
    )
    return WAITING_FACESWAP_INIT_IMAGE


async def receive_faceswap_init_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    image_file = None
    if update.message.photo:
        image_file = update.message.photo[-1]
    elif update.message.document and str(update.message.document.mime_type).startswith("image/"):
        image_file = update.message.document
    if image_file is None:
        await update.message.reply_text("Please send an image.")
        return WAITING_FACESWAP_INIT_IMAGE

    tg_file = await context.bot.get_file(image_file.file_id)
    context.user_data["init_image"] = telegram_file_url(settings, tg_file.file_path)
    await update.message.reply_text(
        "Face Swap Step 2/3: Send target image (face source to insert)."
    )
    return WAITING_FACESWAP_TARGET_IMAGE


async def receive_faceswap_target_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    image_file = None
    if update.message.photo:
        image_file = update.message.photo[-1]
    elif update.message.document and str(update.message.document.mime_type).startswith("image/"):
        image_file = update.message.document
    if image_file is None:
        await update.message.reply_text("Please send an image.")
        return WAITING_FACESWAP_TARGET_IMAGE

    tg_file = await context.bot.get_file(image_file.file_id)
    context.user_data["target_image"] = telegram_file_url(settings, tg_file.file_path)
    await update.message.reply_text(
        "Face Swap Step 3/3: Send reference image (which face in base image to swap)."
    )
    return WAITING_FACESWAP_REFERENCE_IMAGE


async def receive_faceswap_reference_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    image_file = None
    if update.message.photo:
        image_file = update.message.photo[-1]
    elif update.message.document and str(update.message.document.mime_type).startswith("image/"):
        image_file = update.message.document
    if image_file is None:
        await update.message.reply_text("Please send an image.")
        return WAITING_FACESWAP_REFERENCE_IMAGE

    tg_file = await context.bot.get_file(image_file.file_id)
    context.user_data["reference_image"] = telegram_file_url(settings, tg_file.file_path)
    context.user_data["prompt"] = "Face swap"
    payload = dict(context.user_data)

    status_message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text="⏳ Face Swap\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title="Face Swap",
    )
    try:
        created = await asyncio.to_thread(call_modelslab_faceswap, settings, payload)
        output = created.get("output") or []
        image_url: Optional[str] = output[0] if str(created.get("status", "")).lower() == "success" and output else None
        if not image_url:
            request_id = created.get("id") or created.get("request_id")
            if not request_id:
                await context.bot.send_message(
                    chat_id=update.message.chat_id,
                    text=f"Unexpected ModelsLab response: {created}",
                )
                return ConversationHandler.END
            image_url = await poll_result(
                settings,
                request_id=request_id,
                fetch_fn=fetch_result_faceswap,
                progress_callback=progress_callback,
                max_wait=240,
            )
        if not image_url:
            await finalize_progress_message(
                context,
                status_message,
                "❌ Face swap failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=update.message.chat_id,
                text="Face swap failed or timed out. Please try /faceswap again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            "✅ Face swap completed. Sending image...",
        )
        await send_image_result(
            context,
            update.message.chat_id,
            image_url,
            payload,
            model_name="Face Swap",
            user_id=update.effective_user.id,
            task_type="faceswap",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("Face swap API call failed")
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=f"Face swap API error: {exc}",
        )
        return ConversationHandler.END


async def nsfw_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "NSFW Check Step 1/1: Send image to check."
    )
    return WAITING_NSFW_IMAGE


async def nsfw_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()
    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text(
        "NSFW Check Step 1/1: Send image to check."
    )
    return WAITING_NSFW_IMAGE


async def receive_nsfw_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    image_file = None
    if update.message.photo:
        image_file = update.message.photo[-1]
    elif update.message.document and str(update.message.document.mime_type).startswith("image/"):
        image_file = update.message.document
    if image_file is None:
        await update.message.reply_text("Please send an image.")
        return WAITING_NSFW_IMAGE

    tg_file = await context.bot.get_file(image_file.file_id)
    image_url = telegram_file_url(settings, tg_file.file_path)
    status_message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text="⏳ Checking NSFW safety...",
    )
    try:
        data = await asyncio.to_thread(call_modelslab_nsfw_check, settings, image_url, 0.5)
        flags = data.get("has_nsfw_concept") or []
        is_nsfw = any(bool(item) for item in flags) if isinstance(flags, list) else bool(flags)
        score = data.get("nsfw_score") or data.get("score")
        result_text = "⚠️ NSFW detected." if is_nsfw else "✅ Image looks safe."
        details = []
        if score is not None:
            details.append(f"Score: {score}")
        details.append(f"Raw: {truncate_text(str(data), 1200)}")
        await finalize_progress_message(context, status_message, "✅ NSFW check completed.")
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=result_text + "\n" + "\n".join(details),
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("NSFW check API call failed")
        await finalize_progress_message(context, status_message, "❌ NSFW check failed.")
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=f"NSFW check API error: {exc}",
        )
        return ConversationHandler.END


async def styleclone_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "Image Prompt Analyzer Step 1/1: Send one image."
    )
    return WAITING_STYLECLONE_SOURCE_IMAGE


async def styleclone_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()
    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text(
        "Image Prompt Analyzer Step 1/1: Send one image."
    )
    return WAITING_STYLECLONE_SOURCE_IMAGE


async def receive_styleclone_source_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    image_file = None
    if update.message.photo:
        image_file = update.message.photo[-1]
    elif update.message.document and str(update.message.document.mime_type).startswith("image/"):
        image_file = update.message.document
    if image_file is None:
        await update.message.reply_text("Please send an image.")
        return WAITING_STYLECLONE_SOURCE_IMAGE

    tg_file = await context.bot.get_file(image_file.file_id)
    style_image = telegram_file_url(settings, tg_file.file_path)

    status_message = await context.bot.send_message(
        chat_id=update.message.chat_id,
        text="⏳ Analyzing image with advanced LLM (GPT-5.4 thinking, fallback GPT-4o)...",
    )
    try:
        llm_data = await asyncio.to_thread(call_style_analysis_llm, settings, style_image, "")
        analysis = parse_style_analysis_reply(llm_data)
        caption_hint = ""
        if is_weak_style_analysis(analysis):
            caption_hint = await asyncio.to_thread(call_modelslab_caption, settings, style_image)
            if caption_hint:
                llm_data = await asyncio.to_thread(
                    call_style_analysis_llm,
                    settings,
                    style_image,
                    caption_hint,
                )
                improved = parse_style_analysis_reply(llm_data)
                if not is_weak_style_analysis(improved):
                    analysis = improved
                else:
                    analysis = fallback_analysis_from_caption(caption_hint)
            else:
                analysis = fallback_analysis_from_caption(
                    "realistic photo with natural lighting, authentic materials, and camera-true rendering"
                )

        prompt = build_styleclone_prompt(analysis)

        await finalize_progress_message(
            context,
            status_message,
            "✅ Image analysis complete.",
        )
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=(
                f"Detected style: {analysis.get('style_class', 'unknown')}\n\n"
                + (
                    f"Vision hint: {truncate_text(caption_hint, 500)}\n\n"
                    if caption_hint
                    else ""
                )
                +
                "Detailed prompt:\n"
                f"{truncate_text(prompt, 3600)}"
            ),
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("Style analysis failed")
        await finalize_progress_message(
            context,
            status_message,
            "❌ Style analysis failed.",
        )
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=f"Style analysis error: {exc}",
        )
        return ConversationHandler.END


async def generate_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    if not is_verified(update.effective_user.id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    set_user_pref(context, update.effective_user.id, "i2v_last_entry", "kling_motion")
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

    set_user_pref(context, query.from_user.id, "i2v_last_entry", "kling_motion")
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
                    user_id=update.effective_user.id,
                    task_type="kling_motion",
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
            user_id=update.effective_user.id,
            task_type="kling_motion",
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
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    set_user_pref(context, user_id, "t2v_model", "ltx")
    last_ratio = get_user_pref(context, user_id, "ltx_resolution")
    context.user_data.clear()
    await update.message.reply_text(
        "LTX 2.3 Step 1/2: Enter your prompt text."
        + (f"\nLast ratio: {last_ratio}" if last_ratio else "")
    )
    return WAITING_LTX_PROMPT


async def ltx_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    set_user_pref(context, query.from_user.id, "t2v_model", "ltx")
    last_ratio = get_user_pref(context, query.from_user.id, "ltx_resolution")
    context.user_data.clear()
    await query.edit_message_text(
        "LTX 2.3 Step 1/2: Enter your prompt text."
        + (f"\nLast ratio: {last_ratio}" if last_ratio else "")
    )
    return WAITING_LTX_PROMPT


async def receive_ltx_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_LTX_PROMPT

    context.user_data["prompt"] = prompt
    last_ratio = get_user_pref(context, update.effective_user.id, "ltx_resolution", "1:1")
    keyboard = [[
        InlineKeyboardButton(_selected_label("1:1", last_ratio == "1:1"), callback_data="ltx_res_1:1"),
        InlineKeyboardButton(_selected_label("16:9", last_ratio == "16:9"), callback_data="ltx_res_16:9"),
        InlineKeyboardButton(_selected_label("9:16", last_ratio == "9:16"), callback_data="ltx_res_9:16"),
    ]]
    await update.message.reply_text(
        "LTX 2.3 Step 2/2: Choose aspect ratio. (✅ = last used)",
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
    set_user_pref(context, query.from_user.id, "ltx_resolution", resolution)
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
                    user_id=query.from_user.id,
                    task_type="ltx_t2v",
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
            user_id=query.from_user.id,
            task_type="ltx_t2v",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("LTX API call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"LTX API error: {exc}",
        )
        return ConversationHandler.END


async def kling_v3_t2v_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    set_user_pref(context, user_id, "t2v_model", "kling_v3_t2v")
    last_ar = get_user_pref(context, user_id, "kling_v3_aspect_ratio")
    last_dur = get_user_pref(context, user_id, "kling_v3_duration")
    context.user_data.clear()
    await update.message.reply_text(
        "Kling V3.0 Step 1/3: Enter your prompt text."
        + (f"\nLast used: {last_ar or '?'} / {last_dur or '?'}s" if (last_ar or last_dur) else "")
    )
    return WAITING_KLING_V3_T2V_PROMPT


async def kling_v3_t2v_start_from_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    set_user_pref(context, query.from_user.id, "t2v_model", "kling_v3_t2v")
    last_ar = get_user_pref(context, query.from_user.id, "kling_v3_aspect_ratio")
    last_dur = get_user_pref(context, query.from_user.id, "kling_v3_duration")
    context.user_data.clear()
    await query.edit_message_text(
        "Kling V3.0 Step 1/3: Enter your prompt text."
        + (f"\nLast used: {last_ar or '?'} / {last_dur or '?'}s" if (last_ar or last_dur) else "")
    )
    return WAITING_KLING_V3_T2V_PROMPT


async def receive_kling_v3_t2v_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_KLING_V3_T2V_PROMPT

    context.user_data["prompt"] = prompt
    last_ar = get_user_pref(context, update.effective_user.id, "kling_v3_aspect_ratio", "1:1")
    keyboard = [[
        InlineKeyboardButton(_selected_label("1:1", last_ar == "1:1"), callback_data="kv3_ar_1:1"),
        InlineKeyboardButton(_selected_label("9:16", last_ar == "9:16"), callback_data="kv3_ar_9:16"),
        InlineKeyboardButton(_selected_label("16:9", last_ar == "16:9"), callback_data="kv3_ar_16:9"),
    ]]
    await update.message.reply_text(
        "Kling V3.0 Step 2/3: Choose aspect ratio. (✅ = last used)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_KLING_V3_T2V_ASPECT_RATIO


async def receive_kling_v3_t2v_aspect_ratio(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer()

    aspect_ratio = query.data.replace("kv3_ar_", "", 1).strip()
    if aspect_ratio not in KLING_V3_T2V_ASPECT_RATIOS:
        await query.edit_message_text(
            "Unsupported aspect ratio. Send /klingt2v to start again."
        )
        return ConversationHandler.END

    context.user_data["aspect_ratio"] = aspect_ratio
    set_user_pref(context, query.from_user.id, "kling_v3_aspect_ratio", aspect_ratio)
    last_duration = get_user_pref(context, query.from_user.id, "kling_v3_duration", "5")
    keyboard = [[
        InlineKeyboardButton(_selected_label("5s", last_duration == "5"), callback_data="kv3_dur_5"),
        InlineKeyboardButton(_selected_label("10s", last_duration == "10"), callback_data="kv3_dur_10"),
    ]]
    await query.edit_message_text(
        "Kling V3.0 Step 3/3: Choose duration. (✅ = last used)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_KLING_V3_T2V_DURATION


async def receive_kling_v3_t2v_duration(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    duration = query.data.replace("kv3_dur_", "", 1)
    if duration not in KLING_V3_T2V_DURATIONS:
        await query.edit_message_text("Unsupported duration. Send /klingt2v to start again.")
        return ConversationHandler.END

    context.user_data["duration"] = duration
    set_user_pref(context, query.from_user.id, "kling_v3_duration", duration)
    await query.edit_message_text("Generating Kling V3.0 video. Please wait...")

    payload = dict(context.user_data)
    status_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⏳ Kling V3.0 Text-to-Video\nStatus: Submitted\nElapsed: 0s",
    )
    progress_callback = make_progress_callback(
        context=context,
        status_message=status_message,
        job_title="Kling V3.0 Text-to-Video",
    )

    try:
        created = await asyncio.to_thread(call_modelslab_kling_v3_t2v, settings, payload)
        if str(created.get("status", "")).lower() == "success":
            output = created.get("output") or []
            if output:
                await finalize_progress_message(
                    context,
                    status_message,
                    "✅ Kling V3.0 completed. Sending video...",
                )
                await send_video_result(
                    context,
                    query.message.chat_id,
                    output[0],
                    payload,
                    model_name=f"Kling V3.0 ({payload.get('aspect_ratio', '?')}, {duration}s)",
                    user_id=query.from_user.id,
                    task_type="kling_v3_t2v",
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
                "❌ Kling V3.0 failed or timed out.",
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Kling V3.0 generation failed or timed out. Please try /klingt2v again.",
            )
            return ConversationHandler.END

        await finalize_progress_message(
            context,
            status_message,
            "✅ Kling V3.0 completed. Sending video...",
        )
        await send_video_result(
            context,
            query.message.chat_id,
            video_url,
            payload,
            model_name=f"Kling V3.0 ({payload.get('aspect_ratio', '?')}, {duration}s)",
            user_id=query.from_user.id,
            task_type="kling_v3_t2v",
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001
        logger.exception("Kling V3.0 API call failed")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Kling V3.0 API error: {exc}",
        )
        return ConversationHandler.END


async def sora_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    user_id = update.effective_user.id
    if not is_verified(user_id, settings):
        await update.message.reply_text("Send /start and pass access code first.")
        return ConversationHandler.END

    set_user_pref(context, user_id, "t2v_model", "sora")
    last_ar = get_user_pref(context, user_id, "sora_aspect_ratio_label")
    last_dur = get_user_pref(context, user_id, "sora_duration")
    context.user_data.clear()
    await update.message.reply_text(
        "Sora 2 Pro Step 1/3: Enter your prompt text."
        + (f"\nLast used: {last_ar or '?'} / {last_dur or '?'}s" if (last_ar or last_dur) else "")
    )
    return WAITING_SORA_PROMPT


async def sora_start_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings: Settings = context.bot_data["settings"]
    query = update.callback_query
    await query.answer()

    if not is_verified(query.from_user.id, settings):
        await query.edit_message_text("Access required. Send /start first.")
        return ConversationHandler.END

    set_user_pref(context, query.from_user.id, "t2v_model", "sora")
    last_ar = get_user_pref(context, query.from_user.id, "sora_aspect_ratio_label")
    last_dur = get_user_pref(context, query.from_user.id, "sora_duration")
    context.user_data.clear()
    await query.edit_message_text(
        "Sora 2 Pro Step 1/3: Enter your prompt text."
        + (f"\nLast used: {last_ar or '?'} / {last_dur or '?'}s" if (last_ar or last_dur) else "")
    )
    return WAITING_SORA_PROMPT


async def receive_sora_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Prompt cannot be empty. Try again.")
        return WAITING_SORA_PROMPT

    context.user_data["prompt"] = prompt
    last_ar = get_user_pref(context, update.effective_user.id, "sora_aspect_ratio_label", "9:16")
    keyboard = [[
        InlineKeyboardButton(_selected_label("9:16", last_ar == "9:16"), callback_data="sora_ar_9x16"),
        InlineKeyboardButton(_selected_label("16:9", last_ar == "16:9"), callback_data="sora_ar_16x9"),
    ]]
    await update.message.reply_text(
        "Sora 2 Pro Step 2/3: Choose aspect ratio. (✅ = last used)",
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
    set_user_pref(context, query.from_user.id, "sora_aspect_ratio_label", label)
    last_duration = get_user_pref(context, query.from_user.id, "sora_duration", "8")

    keyboard = [[
        InlineKeyboardButton(_selected_label("4s", last_duration == "4"), callback_data="sora_dur_4"),
        InlineKeyboardButton(_selected_label("8s", last_duration == "8"), callback_data="sora_dur_8"),
        InlineKeyboardButton(_selected_label("12s", last_duration == "12"), callback_data="sora_dur_12"),
    ]]
    await query.edit_message_text(
        "Sora 2 Pro Step 3/3: Choose duration. (✅ = last used)",
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
    set_user_pref(context, query.from_user.id, "sora_duration", duration)
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
                    user_id=query.from_user.id,
                    task_type="sora_t2v",
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
            user_id=query.from_user.id,
            task_type="sora_t2v",
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
    user_id: Optional[int] = None,
    task_type: str = "",
) -> None:
    caption = media_caption(
        str(payload.get("prompt", "")),
        [
            "Result: Video",
            f"Model: {model_name}",
        ],
    )
    reply_markup = (
        result_action_markup(context, user_id, chat_id, task_type, payload, model_name)
        if user_id is not None and task_type
        else None
    )
    try:
        await context.bot.send_video(
            chat_id=chat_id,
            video=video_url,
            caption=caption,
            reply_markup=reply_markup,
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
                reply_markup=reply_markup,
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
            reply_markup=reply_markup,
        )
        return
    except Exception as document_error:  # noqa: BLE001
        logger.warning("Document send fallback failed: %s", document_error)

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Video ready: {video_url}\n\n{caption}",
            reply_markup=reply_markup,
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
    user_id: Optional[int] = None,
    task_type: str = "",
) -> None:
    caption = media_caption(
        str(payload.get("prompt", "")),
        [
            "Result: Image",
            f"Aspect Ratio: {payload.get('aspect_ratio', '?')}",
            f"Model: {model_name}",
        ],
    )
    reply_markup = (
        result_action_markup(context, user_id, chat_id, task_type, payload, model_name)
        if user_id is not None and task_type
        else None
    )
    try:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=image_url,
            caption=caption,
            reply_markup=reply_markup,
        )
        return
    except Exception as photo_error:  # noqa: BLE001
        logger.warning("Direct image URL send failed: %s", photo_error)

    try:
        await context.bot.send_document(
            chat_id=chat_id,
            document=image_url,
            caption=caption,
            reply_markup=reply_markup,
        )
        return
    except Exception as document_error:  # noqa: BLE001
        logger.warning("Document image fallback failed: %s", document_error)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Image ready: {image_url}\n\n{caption}",
        reply_markup=reply_markup,
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

    kling_v3_t2v_conv = ConversationHandler(
        entry_points=[
            CommandHandler("klingt2v", kling_v3_t2v_start),
            CommandHandler("kling_v3_t2v", kling_v3_t2v_start),
            CallbackQueryHandler(
                kling_v3_t2v_start_from_menu, pattern=r"^menu_start_kling_v3_t2v$"
            ),
        ],
        states={
            WAITING_KLING_V3_T2V_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_kling_v3_t2v_prompt)
            ],
            WAITING_KLING_V3_T2V_ASPECT_RATIO: [
                CallbackQueryHandler(receive_kling_v3_t2v_aspect_ratio, pattern=r"^kv3_ar_")
            ],
            WAITING_KLING_V3_T2V_DURATION: [
                CallbackQueryHandler(receive_kling_v3_t2v_duration, pattern=r"^kv3_dur_")
            ],
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

    llm_conv = ConversationHandler(
        entry_points=[
            CommandHandler("llm", llm_start),
            CommandHandler("chat", llm_start),
            CommandHandler("uncensored", uncensored_start),
            CallbackQueryHandler(llm_start_from_menu, pattern=r"^menu_llm$"),
            CallbackQueryHandler(uncensored_start_from_menu, pattern=r"^menu_uncensored$"),
        ],
        states={
            WAITING_LLM_MODEL: [
                CallbackQueryHandler(receive_llm_model, pattern=r"^(llm_model_|menu_back)")
            ],
            WAITING_LLM_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_llm_prompt)],
        },
        fallbacks=[
            CommandHandler("llmclear", llm_clear),
            CommandHandler("newchat", llm_clear),
            CommandHandler("cancel", cancel),
        ],
        allow_reentry=True,
    )

    faceswap_conv = ConversationHandler(
        entry_points=[
            CommandHandler("faceswap", faceswap_start),
            CommandHandler("swapface", faceswap_start),
            CallbackQueryHandler(faceswap_start_from_menu, pattern=r"^menu_faceswap$"),
        ],
        states={
            WAITING_FACESWAP_INIT_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_faceswap_init_image)
            ],
            WAITING_FACESWAP_TARGET_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_faceswap_target_image)
            ],
            WAITING_FACESWAP_REFERENCE_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_faceswap_reference_image)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, fallback_msg),
        ],
        allow_reentry=True,
    )

    nsfw_conv = ConversationHandler(
        entry_points=[
            CommandHandler("nsfwcheck", nsfw_start),
            CommandHandler("nsfw", nsfw_start),
            CallbackQueryHandler(nsfw_start_from_menu, pattern=r"^menu_nsfw$"),
        ],
        states={
            WAITING_NSFW_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_nsfw_image)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, fallback_msg),
        ],
        allow_reentry=True,
    )

    styleclone_conv = ConversationHandler(
        entry_points=[
            CommandHandler("styleclone", styleclone_start),
            CommandHandler("cloneimg", styleclone_start),
            CallbackQueryHandler(styleclone_start_from_menu, pattern=r"^menu_styleclone$"),
        ],
        states={
            WAITING_STYLECLONE_SOURCE_IMAGE: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_styleclone_source_image)
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
            WAITING_T2I_MODEL: [CallbackQueryHandler(receive_t2i_model, pattern=r"^t2i_model_")],
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

    i2v_conv = ConversationHandler(
        entry_points=[
            CommandHandler("i2v", i2v_start),
            CallbackQueryHandler(i2v_start_kling_v3, pattern=r"^menu_start_i2v_kling_v3$"),
            CallbackQueryHandler(i2v_start_ltx_pro, pattern=r"^menu_start_i2v_ltx_pro$"),
            CallbackQueryHandler(i2v_start_ltx, pattern=r"^menu_start_i2v_ltx$"),
            CallbackQueryHandler(i2v_start_grok, pattern=r"^menu_start_i2v_grok$"),
        ],
        states={
            WAITING_I2V_MODEL: [
                CallbackQueryHandler(receive_i2v_model, pattern=r"^(menu_back|menu_start_i2v_)")
            ],
            WAITING_I2V_IMAGE: [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_i2v_image)],
            WAITING_I2V_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_i2v_prompt)],
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
            CommandHandler("refimg", refimg_start),
            CommandHandler("reference", refimg_start),
            CallbackQueryHandler(imgedit_start_from_menu, pattern=r"^menu_i2i$"),
            CallbackQueryHandler(refimg_start_from_menu, pattern=r"^menu_refimg$"),
        ],
        states={
            WAITING_REF_MODEL: [
                CallbackQueryHandler(receive_refimg_model, pattern=r"^(ref_model_|menu_back)")
            ],
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
    app.add_handler(
        MessageHandler(filters.Regex(r"(?i)^/?start$"), start_shortcut)
    )
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("llmclear", llm_clear))
    app.add_handler(CommandHandler("newchat", llm_clear))
    app.add_handler(
        CallbackQueryHandler(
            result_action_callback,
            pattern=rf"^({RERUN_CALLBACK_PREFIX}|{VARIATION_CALLBACK_PREFIX})",
        )
    )
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu_(t2v|i2v|back)$"))
    app.add_handler(t2i_conv)
    app.add_handler(i2v_conv)
    app.add_handler(i2i_conv)
    app.add_handler(faceswap_conv)
    app.add_handler(nsfw_conv)
    app.add_handler(styleclone_conv)
    app.add_handler(gen_conv)
    app.add_handler(ltx_conv)
    app.add_handler(kling_v3_t2v_conv)
    app.add_handler(sora_conv)
    # Keep LLM handler after generation handlers so active media flows
    # always capture their own text prompts first.
    app.add_handler(llm_conv)

    logger.info("Bot started. Access code enabled: %s", settings.access_required)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
