const fetch = require("node-fetch");

const sessions = {};
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY;

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).send("Method Not Allowed");

  const body = req.body;
  const message = body.message;
  const text = message?.text;
  const chat_id = message?.chat?.id;

  const sendMessage = (text, keyboard) =>
    fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id, text, reply_markup: keyboard }),
    });

  if (text === "/start") {
    sessions[chat_id] = {};
    return await sendMessage("👋 Привет! Выбери тему для теста:", {
      keyboard: [[{ text: "История" }, { text: "Математика" }]],
      resize_keyboard: true,
    }).then(() => res.send("OK"));
  }

  // Выбор темы
  const currentSession = sessions[chat_id] || {};
  if (!currentSession.topic && (text === "История" || text === "Математика")) {
    sessions[chat_id] = { topic: text };
    const prompt = `Задай один интересный тестовый вопрос с 4 вариантами ответа по теме: ${text}, с правильным ответом.`;

    const answer = await askGPT(prompt);
    return await sendMessage(`📚 Вопрос по теме *${text}*:\n\n${answer}`, {
      parse_mode: "Markdown",
      keyboard: [[{ text: "История" }, { text: "Математика" }]],
      resize_keyboard: true,
    }).then(() => res.send("OK"));
  }

  await sendMessage("👋 Напиши /start, чтобы начать сначала.");
  return res.send("OK");
};

// 🧠 GPT через OpenRouter
async function askGPT(prompt) {
  const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENROUTER_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: "openai/gpt-3.5-turbo", // можешь заменить на другую
      messages: [{ role: "user", content: prompt }],
      temperature: 0.7
    })
  });

  const data = await res.json();

  if (!res.ok) {
    console.error("❌ OpenRouter API error:", data);
    return "Ошибка генерации: " + (data.error?.message || "неизвестная ошибка");
  }

  return data.choices?.[0]?.message?.content || "Ошибка генерации.";
}
