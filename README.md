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
- `/llm` - LLM chat flow (best model selector)
- `/chat` - alias of `/llm`
- `/uncensored` - uncensored chat shortcut (direct prompt mode)
- `/llmclear` - clear saved LLM conversation memory
- `/newchat` - alias of `/llmclear`
- `/t2i` - Nano Banana 2 text-to-image flow
- `/text2image` - alias of `/t2i`
- `/imgedit` - Nano Banana 2 image-edit flow
- `/imageedit` - alias of `/imgedit`
- `/refimg` - reference-image toolkit flow (multiple models)
- `/reference` - alias of `/refimg`
- `/styleclone` - image prompt analyzer flow (single image)
- `/cloneimg` - alias of `/styleclone`
- `/faceswap` - face swap flow (single face swap)
- `/swapface` - alias of `/faceswap`
- `/nsfwcheck` - NSFW image safety checker
- `/nsfw` - alias of `/nsfwcheck`
- `/i2v` - image-to-video model toolkit (all available i2v models)
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
- **LLM Chat**
- **Uncensored Chat**
- **Image Edit**
- **Reference Image Generate**
- **Image Prompt Analyzer**
- **Face Swap**
- **NSFW Image Check**
- **Text to Video**
- **Image to Video**

All options are connected to working ModelsLab flows.

Each generation flow now shows live progress updates in chat
(Submitted, Processing, Retrying, Completed/Failed with elapsed time).

The bot also includes generation UX improvements:
- **Regenerate** and **Variation** buttons on every result (image/video)
- **Remember last settings** per user (last model, aspect ratio, duration)
- Menus now show model speed/quality hints (Fast / Balanced / Highest quality)

## LLM chat flow (`/llm`)

1. Send `/llm` (or choose **LLM Chat** in menu)
2. Choose LLM family:
   - Best Available (Auto)
   - ChatGPT (OpenAI)
   - Claude (Anthropic)
   - DeepSeek R1
   - Meta Llama 3.1 70B
   - Qwen 2.5 72B
   - Mistral 8x7B
3. Send your question/prompt
4. Bot calls ModelsLab chat-completions endpoint and returns the reply
5. Conversation memory is saved per user + model for continuity
6. Use `/llmclear` to reset memory at any time
7. Memory is kept in bot runtime (clears when bot restarts)
8. Strict mode: if provider returns a different model than selected, bot blocks that reply (no random switching)

## Uncensored chat flow (`/uncensored`)

1. Send `/uncensored` (or choose **Uncensored Chat** in menu)
2. Send your message directly (no model picker)
3. Bot uses uncensored Llama model with memory support
4. Use `/llmclear` to reset memory

## Best LLMs on ModelsLab (recommended)

From ModelsLab LLM categories, these are strong picks:
- **DeepSeek R1** - strong reasoning
- **Meta Llama 3/4 family** - balanced quality and reliability
- **Qwen family** - strong coding and multilingual quality
- **Mistral family** - fast and efficient
- **Best Available (Auto)** - simplest default for most users
- **ChatGPT (OpenAI)** - strong general assistant quality
- **Claude (Anthropic)** - strong writing and long-context behavior

## Text-to-image flow (`/t2i`)

1. Send `/t2i` (or choose **Text to Image** in menu)
2. Choose model:
   - Nano Banana 2
   - Qwen Image 2.0 Pro
   - Seedream 5.0 Lite
3. Enter prompt
4. Choose aspect ratio
5. Bot calls model endpoint and sends generated image

## Image-edit flow (`/imgedit`)

1. Send `/imgedit` (or choose **Image Edit** in menu)
2. Upload source image
3. Enter edit instruction prompt
4. Choose aspect ratio
5. Bot calls Nano Banana 2 image-edit endpoint (`v7/images/image-to-image`)
6. Bot sends edited image

## Reference-image generation flow (`/refimg`)

1. Send `/refimg` (or choose **Reference Image Generate** in menu)
2. Choose model:
   - Nano Banana 2 Reference
   - Qwen Edit 2509
   - Qwen Edit 2511
   - Flux Kontext Dev
   - Realtime Image-to-Image
   - FaceGen
   - Outpaint
   - Image Mixer
3. Upload source/reference image
4. Enter prompt for what to generate while keeping style/identity
5. Choose aspect ratio
6. Bot calls the selected reference endpoint and sends generated image

## Image prompt analyzer flow (`/styleclone`)

1. Send `/styleclone` (or choose **Image Prompt Analyzer** in menu)
2. Upload one image
3. Bot analyzes style/depth/realism with advanced LLM (`GPT-5.4` requested, fallback `GPT-4o` when unavailable)
4. Bot returns a detailed reusable prompt (lighting, texture, camera feel, composition, realism)
5. No reference image or generation step is required in this mode

## Face swap flow (`/faceswap`)

1. Send `/faceswap` (or choose **Face Swap** in menu)
2. Upload base image (face to replace)
3. Upload target image (face source to insert)
4. Upload reference image (which face in base image to swap)
5. Bot calls ModelsLab `v6/faceswap/single_face_swap`
6. Bot sends swapped image

## NSFW image check flow (`/nsfwcheck`)

1. Send `/nsfwcheck` (or choose **NSFW Image Check** in menu)
2. Upload image
3. Bot calls ModelsLab `v3/nsfw_image_check`
4. Bot returns safety result

## Kling generation flow (`/generate`)

1. Send `/generate`
2. Upload JPG/PNG image
3. Upload MP4/MOV reference video
4. Enter prompt
5. Bot sends request to ModelsLab v7 motion-control endpoint
6. Bot polls fetch endpoint until completion
7. Bot sends the output video when generation succeeds

## Image-to-video toolkit (`/i2v`)

1. Send `/i2v` (or choose **Image to Video** in menu)
2. Choose model:
   - Kling V3.0 Image-to-Video
   - LTX 2.3 Pro Image-to-Video
   - LTX 2.3 Image-to-Video
   - Grok Imagine Image-to-Video
3. Upload source image
4. Enter prompt
5. Bot sends request to model endpoint and returns generated video

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