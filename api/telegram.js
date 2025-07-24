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

  const session = sessions[chat_id] || {};

  // Начало
  if (text === "/start") {
    sessions[chat_id] = {};
    return await sendMessage("👋 Привет! Выбери тему для теста:", {
      keyboard: [[{ text: "История" }, { text: "Математика" }]],
      resize_keyboard: true,
    }).then(() => res.send("OK"));
  }

  // Проверка ответа
  if (session.correctAnswer) {
    const userAnswer = text.trim().toLowerCase();
    const correct = session.correctAnswer.toLowerCase();
    delete sessions[chat_id].correctAnswer;

    if (userAnswer === correct) {
      await sendMessage("✅ Правильно! Хочешь ещё вопрос?", {
        keyboard: [[{ text: "История" }, { text: "Математика" }]],
        resize_keyboard: true,
      });
    } else {
      await sendMessage(`❌ Неправильно. Правильный ответ: ${session.correctAnswer}\nПопробуешь ещё?`, {
        keyboard: [[{ text: "История" }, { text: "Математика" }]],
        resize_keyboard: true,
      });
    }
    return res.send("OK");
  }

  // Выбор темы
  if (text === "История" || text === "Математика") {
    const topic = text;
    const prompt = `
Задай один тестовый вопрос с 4 вариантами ответа по теме "${topic}".
Формат ответа:
Вопрос: ...
A) ...
B) ...
C) ...
D) ...
Правильный ответ: ... (например: A, B и т.д.)
    `.trim();

    const reply = await askGPT(prompt);
    const match = reply.match(/Правильный ответ:\s*([A-D])/i);
    const correctAnswer = match ? match[1].trim() : null;

    if (!correctAnswer) {
      await sendMessage("⚠️ Не удалось сгенерировать вопрос. Попробуй снова.");
      return res.send("OK");
    }

    sessions[chat_id] = { correctAnswer };
    await sendMessage(`📚 Вопрос по теме *${topic}*:\n\n${reply}`, {
      parse_mode: "Markdown",
    });
    return res.send("OK");
  }

  await sendMessage("⚠️ Напиши /start, чтобы начать сначала.");
  return res.send("OK");
};

// GPT с OpenRouter
async function askGPT(prompt) {
  const res = await fetch("https://openrouter.ai/api/v
