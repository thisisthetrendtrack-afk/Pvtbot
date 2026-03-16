export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Bot is alive!", { status: 200 });
    }

    const body = await request.json();
    const chatId = body?.message?.chat?.id;
    const userText = body?.message?.text;

    if (!chatId || !userText) {
      return new Response("OK", { status: 200 });
    }

    try {
      // Tell user we are generating
      await sendMessage(env.BOT_TOKEN, chatId, "⏳ Generating your image...");

      // Call ModelsLab API
      const mlRes = await fetch("https://modelslab.com/api/v6/realtime/text2img", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key: env.MODELSLAB_API_KEY,
          prompt: userText,
          negative_prompt: "bad quality, blurry, ugly",
          width: "512",
          height: "512",
          samples: "1",
          num_inference_steps: "20",
          guidance_scale: 7.5,
          safety_checker: "no",
          enhance_prompt: "yes",
        })
      });

      const mlData = await mlRes.json();
      console.log("ModelsLab response:", JSON.stringify(mlData));

      // If image is ready immediately
      if (mlData.status === "success" && mlData.output?.[0]) {
        await sendPhoto(env.BOT_TOKEN, chatId, mlData.output[0]);

      // If image is processing (queued)
      } else if (mlData.status === "processing") {
        await sendMessage(env.BOT_TOKEN, chatId, "🔄 Image is queued, check back in 30 seconds...");
        // Optional: poll fetch_result endpoint here

      } else {
        await sendMessage(env.BOT_TOKEN, chatId, "❌ Error: " + (mlData.message || "Something went wrong"));
      }

    } catch (err) {
      await sendMessage(env.BOT_TOKEN, chatId, "❌ Failed: " + err.message);
    }

    return new Response("OK", { status: 200 });
  }
};

// Helper: send text message
async function sendMessage(token, chatId, text) {
  await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text })
  });
}

// Helper: send image
async function sendPhoto(token, chatId, imageUrl) {
  await fetch(`https://api.telegram.org/bot${token}/sendPhoto`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, photo: imageUrl })
  });
}
