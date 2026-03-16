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

    const replyText = "You said: " + userText;

    await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: replyText })
    });

    return new Response("OK", { status: 200 });
  }
};
