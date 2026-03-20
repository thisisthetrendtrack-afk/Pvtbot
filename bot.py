import os
import logging
import requests
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
Application,
CommandHandler,
MessageHandler,
CallbackQueryHandler,
ConversationHandler,
ContextTypes,
filters,
)

logging.basicConfig(
format=”%(asctime)s - %(name)s - %(levelname)s - %(message)s”,
level=logging.INFO,
)
logger = logging.getLogger(**name**)

TELEGRAM_TOKEN    = os.environ[“8783783821:AAG_pw_UfKl5wAL8IGpHC9fnHFMZatyC3eU”]
MODELSLAB_API_KEY = os.environ[“DehOCA2JIkE0hpPD3cz54qPgt7z2PSMI2vF8621DTIFDqOE93R1rkZwTis7K”]
ACCESS_CODE       = os.environ.get(“ACCESS_CODE”, “KLING2025”)

(
WAITING_CODE,
WAITING_IMAGE,
WAITING_VIDEO,
WAITING_PROMPT,
WAITING_DURATION,
WAITING_MODE,
) = range(6)

API_URL   = “https://modelslab.com/api/v6/video/kling_motion_control”
FETCH_URL = “https://modelslab.com/api/v6/video/fetch”

VERIFIED_USERS: set = set()

def is_verified(user_id: int) -> bool:
return user_id in VERIFIED_USERS

def show_menu_text() -> str:
return (
“✅ *Access granted!* Welcome to the bot.\n\n”
“🎬 *Kling 3.0 Motion Control Bot*\n”
“Bring your photos to life with AI!\n\n”
“Commands:\n”
“• /generate — Start a new video\n”
“• /help — How to use\n”
“• /cancel — Cancel current session”
)

def call_modelslab(image_url, video_url, prompt, duration, mode) -> dict:
payload = {
“key”: MODELSLAB_API_KEY,
“prompt”: prompt,
“init_image”: image_url,
“motion_video”: video_url,
“duration”: duration,
“motion_mode”: mode,
“webhook”: None,
“track_id”: None,
}
resp = requests.post(API_URL, json=payload, timeout=60)
resp.raise_for_status()
return resp.json()

def poll_result(request_id: str, max_wait: int = 300):
deadline = time.time() + max_wait
while time.time() < deadline:
time.sleep(10)
r = requests.post(
FETCH_URL,
json={“key”: MODELSLAB_API_KEY, “request_id”: request_id},
timeout=30,
)
data = r.json()
status = data.get(“status”)
if status == “success”:
output = data.get(“output”, [])
return output[0] if output else None
elif status in (“failed”, “error”):
logger.error(“Generation failed: %s”, data)
return None
return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_id = update.effective_user.id

```
if is_verified(user_id):
    await update.message.reply_text(show_menu_text(), parse_mode="Markdown")
    return ConversationHandler.END

await update.message.reply_text(
    "🔐 *Welcome!*\n\n"
    "This bot is private. Please enter the *access code* to continue:",
    parse_mode="Markdown",
)
return WAITING_CODE
```

async def check_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
entered = update.message.text.strip()
user_id = update.effective_user.id

```
if entered == ACCESS_CODE:
    VERIFIED_USERS.add(user_id)
    await update.message.reply_text(show_menu_text(), parse_mode="Markdown")
    return ConversationHandler.END
else:
    await update.message.reply_text(
        "❌ *Wrong code.* Try again or contact the bot owner.",
        parse_mode="Markdown",
    )
    return WAITING_CODE
```

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
if not is_verified(update.effective_user.id):
await update.message.reply_text(“🔐 Please send /start and enter the access code first.”)
return

```
text = (
    "📖 *How it works:*\n\n"
    "1. Send /generate\n"
    "2. Upload your *character image* (PNG/JPG)\n"
    "3. Upload a *reference motion video* (MP4/MOV)\n"
    "4. Type a *prompt* describing the scene\n"
    "5. Choose *duration* (5 or 10 seconds)\n"
    "6. Choose *quality mode* (Standard / Pro)\n\n"
    "The bot will generate a video where your character performs the motions "
    "from the reference video! ✨\n\n"
    "⚠️ Generation takes 2-5 minutes. Please be patient."
)
await update.message.reply_text(text, parse_mode="Markdown")
```

async def generate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
if not is_verified(update.effective_user.id):
await update.message.reply_text(“🔐 Please send /start and enter the access code first.”)
return ConversationHandler.END

```
context.user_data.clear()
await update.message.reply_text(
    "📸 *Step 1/5* — Send your *character image* (JPG or PNG).\n\n"
    "This is the photo whose character will perform the motion.",
    parse_mode="Markdown",
)
return WAITING_IMAGE
```

async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
photo = update.message.photo or (
[update.message.document]
if update.message.document
and update.message.document.mime_type in (“image/jpeg”, “image/png”)
else None
)
if not photo:
await update.message.reply_text(“❌ Please send a JPG or PNG image.”)
return WAITING_IMAGE

```
file_obj = photo[-1] if update.message.photo else photo[0]
file = await context.bot.get_file(file_obj.file_id)
context.user_data["image_url"] = file.file_path

await update.message.reply_text(
    "🎥 *Step 2/5* — Now send the *reference motion video* (MP4 or MOV, max 100 MB).\n\n"
    "The character in your image will copy the motions from this video.",
    parse_mode="Markdown",
)
return WAITING_VIDEO
```

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
video = update.message.video or update.message.document
if not video:
await update.message.reply_text(“❌ Please send a video file (MP4 or MOV).”)
return WAITING_VIDEO

```
file = await context.bot.get_file(video.file_id)
context.user_data["video_url"] = file.file_path

await update.message.reply_text(
    "✍️ *Step 3/5* — Type your *scene prompt*.\n\n"
    "_Example: A girl dancing on a rooftop at sunset, cinematic, slow motion_",
    parse_mode="Markdown",
)
return WAITING_PROMPT
```

async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
context.user_data[“prompt”] = update.message.text.strip()

```
keyboard = [[
    InlineKeyboardButton("⏱ 5 seconds", callback_data="dur_5"),
    InlineKeyboardButton("⏱ 10 seconds", callback_data="dur_10"),
]]
await update.message.reply_text(
    "⏱ *Step 4/5* — Choose video *duration*:",
    parse_mode="Markdown",
    reply_markup=InlineKeyboardMarkup(keyboard),
)
return WAITING_DURATION
```

async def receive_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
context.user_data[“duration”] = int(query.data.split(”_”)[1])

```
keyboard = [[
    InlineKeyboardButton("⚡ Standard (faster)", callback_data="mode_std"),
    InlineKeyboardButton("✨ Pro (better quality)", callback_data="mode_pro"),
]]
await query.edit_message_text(
    "🎨 *Step 5/5* — Choose *quality mode*:\n\n"
    "• *Standard* — faster, cheaper\n"
    "• *Pro* — higher quality, more realistic",
    parse_mode="Markdown",
    reply_markup=InlineKeyboardMarkup(keyboard),
)
return WAITING_MODE
```

async def receive_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
mode = query.data.split(”_”)[1]
context.user_data[“mode”] = mode

```
await query.edit_message_text(
    "🚀 All set! Generating your video...\n\n"
    "⏳ This takes 2-5 minutes. I will message you when it is ready!"
)

ud = context.user_data
try:
    result = call_modelslab(
        image_url=ud["image_url"],
        video_url=ud["video_url"],
        prompt=ud["prompt"],
        duration=ud["duration"],
        mode=ud["mode"],
    )
except Exception as e:
    logger.error("API error: %s", e)
    await context.bot.send_message(
        query.message.chat_id,
        "❌ API error. Please check your ModelsLab API key and try again.",
    )
    return ConversationHandler.END

status = result.get("status")

if status == "success":
    output = result.get("output", [])
    if output:
        await send_video_result(context.bot, query.message.chat_id, output[0], ud)
        return ConversationHandler.END

request_id = result.get("id") or result.get("request_id")
if not request_id:
    await context.bot.send_message(
        query.message.chat_id,
        "❌ Unexpected API response: " + str(result),
    )
    return ConversationHandler.END

video_url = poll_result(request_id)
if video_url:
    await send_video_result(context.bot, query.message.chat_id, video_url, ud)
else:
    await context.bot.send_message(
        query.message.chat_id,
        "⏰ Generation timed out or failed. Please try again with /generate.",
    )

return ConversationHandler.END
```

async def send_video_result(bot, chat_id, video_url, ud):
caption = (
“✅ *Your video is ready!*\n\n”
“📝 Prompt: *” + ud.get(“prompt”, “”) + “*\n”
“⏱ Duration: “ + str(ud.get(“duration”, “?”)) + “s | Mode: “ + ud.get(“mode”, “?”).upper()
)
try:
await bot.send_video(chat_id, video=video_url, caption=caption, parse_mode=“Markdown”)
except Exception:
await bot.send_message(
chat_id,
“✅ Video ready!\n🔗 “ + video_url + “\n\n” + caption,
parse_mode=“Markdown”,
)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
context.user_data.clear()
await update.message.reply_text(“❌ Cancelled. Send /generate to start again.”)
return ConversationHandler.END

async def fallback_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(“Please follow the steps, or send /cancel to stop.”)

def main():
app = Application.builder().token(TELEGRAM_TOKEN).build()

```
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
        WAITING_IMAGE:    [MessageHandler(filters.PHOTO | filters.Document.ALL, receive_image)],
        WAITING_VIDEO:    [MessageHandler(filters.VIDEO | filters.Document.ALL, receive_video)],
        WAITING_PROMPT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)],
        WAITING_DURATION: [CallbackQueryHandler(receive_duration, pattern="^dur_")],
        WAITING_MODE:     [CallbackQueryHandler(receive_mode, pattern="^mode_")],
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

logger.info("Bot started. Access code: %s", ACCESS_CODE)
app.run_polling(drop_pending_updates=True)
```

if **name** == “**main**”:
main()
