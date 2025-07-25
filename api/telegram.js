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

  // Старт
  if (text === "/start") {
    sessions[chat_id] = {};
    return await sendMessage("👋 Привет! Выбери тему для теста:", {
      keyboard: [
        [{ text: "История" }, { text: "Математика" }],
        [{ text: "Английский" }]
      ],
      resize_keyboard: true,
    }).then(() => res.send("OK"));
  }

  // Проверка ответа пользователя
  if (session.correctAnswer) {
    const userAnswer = text.trim().toUpperCase();
    const correct = session.correctAnswer.toUpperCase();
    delete sessions[chat_id].correctAnswer;

    if (userAnswer === correct) {
      await sendMessage("✅ Правильно! Хочешь ещё вопрос?", {
        keyboard: [
          [{ text: "История" }, { text: "Математика" }],
          [{ text: "Английский" }]
        ],
        resize_keyboard: true,
      });
    } else {
      await sendMessage(`❌ Неправильно. Правильный ответ: ${correct}\nПопробуешь ещё?`, {
        keyboard: [
          [{ text: "История" }, { text: "Математика" }],
          [{ text: "Английский" }]
        ],
        resize_keyboard: true,
      });
    }

    return res.send("OK");
  }

  // Выбор темы
  if (["История", "Математика", "Английский"].includes(text)) {
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
    const correctAnswer = match ? match[1].trim().toUpperCase() : null;

    if (!correctAnswer) {
      await sendMessage("⚠️ Не удалось сгенерировать вопрос. Попробуй снова.");
      return res.send("OK");
    }

    const questionWithoutAnswer = reply.replace(/Правильный ответ:\s*[A-D]/i, "").trim();

    sessions[chat_id] = { correctAnswer };
    await sendMessage(`📚 Вопрос по теме *${topic}*:\n\n${questionWithoutAnswer}`, {
      parse_mode: "Markdown",
    });

    return res.send("OK");
  }

  // Неизвестная команда
  await sendMessage("⚠️ Напиши /start, чтобы начать сначала.");
  return res.send("OK");
};

// GPT через OpenRouter
async function askGPT(prompt) {
  const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENROUTER_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: "openai/gpt-3.5-turbo",
      messages: [{ role: "user", content: prompt }],
      temperature: 0.7
    })
  });

  const data = await res.json();

  if (!res.ok) {
    console.error("OpenRouter API error:", data);
    return "Ошибка генерации: " + (data.error?.message || "неизвестная ошибка");
  }

  return data.choices?.[0]?.message?.content || "Ошибка генерации.";
}
