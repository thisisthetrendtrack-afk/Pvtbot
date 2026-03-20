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
- `/menu` - open professional feature menu
- `/help` - usage instructions
- `/t2i` - Nano Banana 2 text-to-image flow
- `/text2image` - alias of `/t2i`
- `/imgedit` - Nano Banana 2 image-edit flow
- `/imageedit` - alias of `/imgedit`
- `/generate` - Kling 3.0 motion-control flow
- `/ltx` - LTX 2.3 text-to-video flow
- `/generate_ltx` - alias of `/ltx`
- `/klingt2v` - Kling V3.0 text-to-video flow
- `/kling_v3_t2v` - alias of `/klingt2v`
- `/sora` - Sora 2 Pro text-to-video flow
- `/sora2` - alias of `/sora`
- `/cancel` - cancel current flow

## Main menu

The bot now opens with a professional inline menu containing:
- **Text to Image**
- **Image Edit**
- **Text to Video**
- **Image to Video**

All options are connected to working ModelsLab flows.

Each generation flow now shows live progress updates in chat
(Submitted, Processing, Retrying, Completed/Failed with elapsed time).

## Text-to-image flow (`/t2i`)

1. Send `/t2i` (or choose **Text to Image** in menu)
2. Enter text prompt
3. Choose aspect ratio
4. Bot calls Nano Banana 2 endpoint (`v7/images/text-to-image`)
5. Bot sends generated image

## Image-edit flow (`/imgedit`)

1. Send `/imgedit` (or choose **Image Edit** in menu)
2. Upload source image
3. Enter edit instruction prompt
4. Choose aspect ratio
5. Bot calls Nano Banana 2 image-edit endpoint (`v7/images/image-to-image`)
6. Bot sends edited image

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

## Kling V3.0 text-to-video flow (`/klingt2v`)

1. Send `/klingt2v`
2. Enter text prompt
3. Choose aspect ratio (`1:1`, `9:16`, `16:9`)
4. Choose duration (`5s`, `10s`)
5. Bot sends request to ModelsLab `v7/video-fusion/text-to-video` with `model_id=kling-v3-t2v`
6. Bot polls fetch endpoint and returns video when ready

## Sora generation flow (`/sora`)

1. Send `/sora`
2. Enter text prompt
3. Choose aspect ratio (`9:16` or `16:9`)
4. Choose duration (`4s`, `8s`, `12s`)
5. Bot sends request to ModelsLab `v7/video-fusion/text-to-video` with `model_id=sora-2-pro-t2v`
6. Bot polls fetch endpoint and returns video when ready