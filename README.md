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
- `/generate` - Kling 3.0 motion-control flow
- `/ltx` - LTX 2.3 text-to-video flow
- `/generate_ltx` - alias of `/ltx`
- `/cancel` - cancel current flow

## Kling generation flow (`/generate`)

1. Send `/generate`
2. Upload JPG/PNG image
3. Upload MP4/MOV reference video
4. Enter prompt
5. Bot sends request to ModelsLab v7 motion-control endpoint
6. Bot polls fetch endpoint until completion
7. Bot sends the output video when generation succeeds

## LTX generation flow (`/ltx`)

1. Send `/ltx`
2. Enter text prompt
3. Choose aspect ratio (`1:1`, `16:9`, `9:16`)
4. Bot sends request to ModelsLab `v6/video/text2video_ultra` with `model_id=ltx-2.3`
5. Bot polls fetch endpoint and returns video when ready