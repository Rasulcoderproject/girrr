const fetch = require("node-fetch");

const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;

const sessions = {};

async function askGPT(prompt) {
  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: "gpt-3.5-turbo",
      messages: [{ role: "user", content: prompt }],
      temperature: 0.7
    })
  });
  const data = await res.json();
  return data.choices?.[0]?.message?.content || "Ошибка генерации.";
}

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).send("Only POST allowed");

  const body = req.body;
  const msg = body.message;
  const chat_id = msg?.chat?.id;
  const text = msg?.text;

  const sendMessage = (text, keyboard) =>
    fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id, text, reply_markup: keyboard })
    });

  const session = sessions[chat_id] || {};

  if (text === "/start") {
    sessions[chat_id] = {};
    await sendMessage("👋 Привет! Выбери тему для теста:", {
      keyboard: [["Математика", "История"], ["Английский язык"]],
      resize_keyboard: true,
      one_time_keyboard: true
    });
    return res.end("OK");
  }

  if (["Математика", "История", "Английский язык"].includes(text)) {
    sessions[chat_id] = { theme: text };
    const prompt = `Создай 1 вопрос с 4 вариантами по теме "${text}", укажи правильный ответ.`;
    const gptResponse = await askGPT(prompt);
    sessions[chat_id].question = gptResponse;
    await sendMessage(`📚 Вопрос по теме *${text}*:\n\n${gptResponse}`, {
      remove_keyboard: true
    });
    return res.end("OK");
  }

  // После вопроса можно добавить проверку ответа и повторную генерацию — позже

  await sendMessage("Нажми /start, чтобы начать заново.");
  return res.end("OK");
};
