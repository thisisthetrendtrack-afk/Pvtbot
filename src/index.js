// ─── Kling Motion Control Bot for Cloudflare Workers ───────────────────────
// Requires KV namespace "BOT_KV" bound in wrangler.toml
// Env secrets: BOT_TOKEN, MODELSLAB_API_KEY, ACCESS_CODE

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET") {
      return new Response("Bot is alive!", { status: 200 });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    // ModelsLab calls this when video is ready
    if (url.pathname === "/mlwebhook") {
      return await handleModelsLabWebhook(request, env);
    }

    // Telegram sends messages here
    return await handleTelegramWebhook(request, env);
  }
};

// ─── STEPS ──────────────────────────────────────────────────────────────────

const STEP = {
  WAITING_CODE:     "WAITING_CODE",
  WAITING_IMAGE:    "WAITING_IMAGE",
  WAITING_VIDEO:    "WAITING_VIDEO",
  WAITING_PROMPT:   "WAITING_PROMPT",
  WAITING_DURATION: "WAITING_DURATION",
  WAITING_MODE:     "WAITING_MODE",
};

// ─── KV HELPERS ─────────────────────────────────────────────────────────────

async function getUser(env, userId) {
  const data = await env.BOT_KV.get(`user:${userId}`, "json");
  return data || { verified: false, step: null, data: {} };
}

async function saveUser(env, userId, user) {
  await env.BOT_KV.put(`user:${userId}`, JSON.stringify(user));
}

async function saveJob(env, requestId, payload) {
  await env.BOT_KV.put(`job:${requestId}`, JSON.stringify(payload), {
    expirationTtl: 3600 // auto delete after 1 hour
  });
}

async function getJob(env, requestId) {
  return await env.BOT_KV.get(`job:${requestId}`, "json");
}

// ─── TELEGRAM WEBHOOK HANDLER ────────────────────────────────────────────────

async function handleTelegramWebhook(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return new Response("Bad request", { status: 400 });
  }

  if (body.callback_query) {
    await handleCallback(body.callback_query, env);
  } else if (body.message) {
    await handleMessage(body.message, env);
  }

  return new Response("OK", { status: 200 });
}

// ─── MODELSLAB WEBHOOK HANDLER ───────────────────────────────────────────────

async function handleModelsLabWebhook(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return new Response("Bad request", { status: 400 });
  }

  const requestId = body.id || body.request_id;
  const status    = body.status;
  const output    = body.output || [];

  if (!requestId) return new Response("OK", { status: 200 });

  const job = await getJob(env, requestId);
  if (!job) return new Response("OK", { status: 200 });

  if (status === "success" && output[0]) {
    await sendVideoResult(env, job.chatId, output[0], job.userData);
  } else {
    await sendMessage(env, job.chatId,
      "❌ Video generation failed. Please try /generate again."
    );
  }

  return new Response("OK", { status: 200 });
}

// ─── MESSAGE HANDLER ─────────────────────────────────────────────────────────

async function handleMessage(message, env) {
  const chatId = message.chat.id;
  const userId = message.from.id;
  const text   = message.text || "";

  const user = await getUser(env, userId);

  // ── Commands ──
  if (text === "/start") {
    if (user.verified) {
      await sendMessage(env, chatId, menuText(), "Markdown");
      return;
    }
    user.step = STEP.WAITING_CODE;
    await saveUser(env, userId, user);
    await sendMessage(env, chatId,
      "🔐 *Welcome!*\n\nThis bot is private. Please enter the *access code* to continue:",
      "Markdown"
    );
    return;
  }

  if (text === "/help") {
    if (!user.verified) {
      await sendMessage(env, chatId, "🔐 Please send /start and enter the access code first.");
      return;
    }
    await sendMessage(env, chatId, helpText(), "Markdown");
    return;
  }

  if (text === "/generate") {
    if (!user.verified) {
      await sendMessage(env, chatId, "🔐 Please send /start and enter the access code first.");
      return;
    }
    user.step = STEP.WAITING_IMAGE;
    user.data = {};
    await saveUser(env, userId, user);
    await sendMessage(env, chatId,
      "📸 *Step 1/5* — Send your *character image* (JPG or PNG).\n\n" +
      "This is the photo whose character will perform the motion.",
      "Markdown"
    );
    return;
  }

  if (text === "/cancel") {
    user.step = null;
    user.data = {};
    await saveUser(env, userId, user);
    await sendMessage(env, chatId, "❌ Cancelled. Send /generate to start again.");
    return;
  }

  // ── Conversation steps ──

  if (user.step === STEP.WAITING_CODE) {
    if (text.trim() === env.ACCESS_CODE) {
      user.verified = true;
      user.step     = null;
      await saveUser(env, userId, user);
      await sendMessage(env, chatId, menuText(), "Markdown");
    } else {
      await sendMessage(env, chatId,
        "❌ *Wrong code.* Try again or contact the bot owner.", "Markdown"
      );
    }
    return;
  }

  if (user.step === STEP.WAITING_IMAGE) {
    let fileId = null;

    if (message.photo?.length > 0) {
      fileId = message.photo[message.photo.length - 1].file_id;
    } else if (message.document?.mime_type?.startsWith("image/")) {
      fileId = message.document.file_id;
    }

    if (!fileId) {
      await sendMessage(env, chatId, "❌ Please send a JPG or PNG image.");
      return;
    }

    user.data.image_url = await getFileUrl(env, fileId);
    user.step = STEP.WAITING_VIDEO;
    await saveUser(env, userId, user);
    await sendMessage(env, chatId,
      "🎥 *Step 2/5* — Now send the *reference motion video* (MP4 or MOV).\n\n" +
      "The character in your image will copy the motions from this video.",
      "Markdown"
    );
    return;
  }

  if (user.step === STEP.WAITING_VIDEO) {
    let fileId = null;

    if (message.video) {
      fileId = message.video.file_id;
    } else if (message.document?.mime_type?.startsWith("video/")) {
      fileId = message.document.file_id;
    }

    if (!fileId) {
      await sendMessage(env, chatId, "❌ Please send a video file (MP4 or MOV).");
      return;
    }

    user.data.video_url = await getFileUrl(env, fileId);
    user.step = STEP.WAITING_PROMPT;
    await saveUser(env, userId, user);
    await sendMessage(env, chatId,
      "✍️ *Step 3/5* — Type your *scene prompt*.\n\n" +
      "_Example: A girl dancing on a rooftop at sunset, cinematic, slow motion_",
      "Markdown"
    );
    return;
  }

  if (user.step === STEP.WAITING_PROMPT) {
    user.data.prompt = text.trim();
    user.step = STEP.WAITING_DURATION;
    await saveUser(env, userId, user);
    await sendMessageWithKeyboard(env, chatId,
      "⏱ *Step 4/5* — Choose video *duration*:",
      "Markdown",
      { inline_keyboard: [[
        { text: "⏱ 5 seconds",  callback_data: "dur_5"  },
        { text: "⏱ 10 seconds", callback_data: "dur_10" },
      ]]}
    );
    return;
  }

  // Catch-all
  if (user.step) {
    await sendMessage(env, chatId, "Please follow the steps, or send /cancel to stop.");
  }
}

// ─── CALLBACK HANDLER (button clicks) ────────────────────────────────────────

async function handleCallback(callbackQuery, env) {
  const chatId    = callbackQuery.message.chat.id;
  const userId    = callbackQuery.from.id;
  const data      = callbackQuery.data;
  const messageId = callbackQuery.message.message_id;

  await answerCallback(env, callbackQuery.id);

  const user = await getUser(env, userId);

  if (data.startsWith("dur_") && user.step === STEP.WAITING_DURATION) {
    user.data.duration = parseInt(data.split("_")[1]);
    user.step = STEP.WAITING_MODE;
    await saveUser(env, userId, user);
    await editMessage(env, chatId, messageId,
      "🎨 *Step 5/5* — Choose *quality mode*:\n\n" +
      "• *Standard* — faster, cheaper\n" +
      "• *Pro* — higher quality, more realistic",
      "Markdown",
      { inline_keyboard: [[
        { text: "⚡ Standard (faster)",    callback_data: "mode_std" },
        { text: "✨ Pro (better quality)", callback_data: "mode_pro" },
      ]]}
    );
    return;
  }

  if (data.startsWith("mode_") && user.step === STEP.WAITING_MODE) {
    user.data.mode = data.split("_")[1];
    user.step = null;
    await saveUser(env, userId, user);

    await editMessage(env, chatId, messageId,
      "🚀 All set! Generating your video...\n\n" +
      "⏳ This takes 2–5 minutes. I'll message you when it's ready!",
      "Markdown"
    );

    try {
      const workerUrl = env.WORKER_URL; // e.g. https://your-bot.workers.dev
      const result = await callModelsLab(env, user.data, chatId, workerUrl);
      const status = result.status;

      // Sometimes ready immediately
      if (status === "success" && result.output?.[0]) {
        await sendVideoResult(env, chatId, result.output[0], user.data);
        return;
      }

      // Job queued — webhook will fire when ready
      if (result.id || result.request_id) {
        const requestId = result.id || result.request_id;
        await saveJob(env, requestId, { chatId, userData: user.data });
        await sendMessage(env, chatId,
          "✅ Job submitted! I'll send you the video automatically when it's ready.\n\n" +
          "No need to wait here — I'll ping you! 🔔"
        );
        return;
      }

      await sendMessage(env, chatId,
        `❌ Unexpected response from API:\n${JSON.stringify(result)}`
      );

    } catch (err) {
      await sendMessage(env, chatId, "❌ API error: " + err.message);
    }
  }
}

// ─── MODELSLAB API ───────────────────────────────────────────────────────────

async function callModelsLab(env, data, chatId, workerUrl) {
  const resp = await fetch("https://modelslab.com/api/v6/video/kling_motion_control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      key:          env.MODELSLAB_API_KEY,
      prompt:       data.prompt,
      init_image:   data.image_url,
      motion_video: data.video_url,
      duration:     data.duration,
      motion_mode:  data.mode,
      webhook:      `${workerUrl}/mlwebhook`,
      track_id:     null,
    })
  });
  return await resp.json();
}

// ─── TELEGRAM HELPERS ────────────────────────────────────────────────────────

async function getFileUrl(env, fileId) {
  const res  = await fetch(
    `https://api.telegram.org/bot${env.BOT_TOKEN}/getFile?file_id=${fileId}`
  );
  const data = await res.json();
  return `https://api.telegram.org/file/bot${env.BOT_TOKEN}/${data.result.file_path}`;
}

async function sendMessage(env, chatId, text, parseMode = null) {
  const body = { chat_id: chatId, text };
  if (parseMode) body.parse_mode = parseMode;
  await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

async function sendMessageWithKeyboard(env, chatId, text, parseMode, keyboard) {
  await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId, text, parse_mode: parseMode, reply_markup: keyboard
    })
  });
}

async function editMessage(env, chatId, messageId, text, parseMode, keyboard = null) {
  const body = { chat_id: chatId, message_id: messageId, text, parse_mode: parseMode };
  if (keyboard) body.reply_markup = keyboard;
  await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/editMessageText`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

async function answerCallback(env, callbackId) {
  await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/answerCallbackQuery`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ callback_query_id: callbackId })
  });
}

async function sendVideoResult(env, chatId, videoUrl, data) {
  const caption =
    `✅ *Your video is ready!*\n\n` +
    `📝 Prompt: *${data.prompt}*\n` +
    `⏱ Duration: ${data.duration}s | Mode: ${data.mode.toUpperCase()}`;
  try {
    await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendVideo`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId, video: videoUrl, caption, parse_mode: "Markdown"
      })
    });
  } catch {
    await sendMessage(env, chatId, `✅ Video ready!\n🔗 ${videoUrl}\n\n${caption}`, "Markdown");
  }
}

// ─── TEXT HELPERS ────────────────────────────────────────────────────────────

function menuText() {
  return (
    "✅ *Access granted!* Welcome to the bot.\n\n" +
    "🎬 *Kling 3.0 Motion Control Bot*\n" +
    "Bring your photos to life with AI!\n\n" +
    "Commands:\n" +
    "• /generate — Start a new video\n" +
    "• /help — How to use\n" +
    "• /cancel — Cancel current session"
  );
}

function helpText() {
  return (
    "📖 *How it works:*\n\n" +
    "1. Send /generate\n" +
    "2. Upload your *character image* (PNG/JPG)\n" +
    "3. Upload a *reference motion video* (MP4/MOV)\n" +
    "4. Type a *prompt* describing the scene\n" +
    "5. Choose *duration* (5 or 10 seconds)\n" +
    "6. Choose *quality mode* (Standard / Pro)\n\n" +
    "The bot will generate a video where your character performs the motions " +
    "from the reference video! ✨\n\n" +
    "⚠️ Generation takes 2–5 minutes. I'll message you automatically when ready."
  );
}
