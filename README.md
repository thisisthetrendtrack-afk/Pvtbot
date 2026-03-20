# Telegram + ModelsLab Integration Bot

This repository contains a Telegram bot that collects an image, motion video, and prompt from a user, then sends them to the ModelsLab Kling Motion Control API and returns the generated video.

## Required environment variables

- `TELEGRAM_TOKEN` (required): Telegram bot token from BotFather
- `MODELSLAB_API_KEY` (required): ModelsLab API key
- `ACCESS_CODE` (optional): if set, users must pass this code after `/start`

Accepted aliases:
- Telegram token: `BOT_TOKEN`, `TELEGRAM_BOT_TOKEN`
- ModelsLab key: `MODELSLAB_KEY`, `ML_API_KEY`

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export TELEGRAM_TOKEN="your_telegram_bot_token"
export MODELSLAB_API_KEY="your_modelslab_api_key"
export ACCESS_CODE="optional_private_code"

python bot.py
```

Alternative:

```bash
bash start.sh
```

`start.sh` auto-installs missing dependencies before booting the bot.

## Bot commands

- `/start` - begin session (and access-code check if enabled)
- `/help` - usage instructions
- `/generate` - start media-to-video flow
- `/cancel` - cancel current flow

## Generation flow

1. Send `/generate`
2. Upload JPG/PNG image
3. Upload MP4/MOV reference video
4. Enter prompt
5. Choose duration (5/10 sec)
6. Choose mode (standard/pro)
7. Bot sends the output video when ModelsLab returns success