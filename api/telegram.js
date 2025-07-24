const fetch = require("node-fetch");
const cheerio = require("cheerio");
const sessions = {};

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).send("Method Not Allowed");

  const token = process.env.TELEGRAM_BOT_TOKEN;
  const body = req.body;
  const text = body.message?.text;
  const callback = body.callback_query;
  const msg = body.message || callback?.message;
  const chat_id = msg?.chat?.id;

  const sendMessage = (text, keyboard) =>
    fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id, text, reply_markup: keyboard }),
    });

  const sess = sessions[chat_id] || {};

  if (text === "/start") {
    sessions[chat_id] = {};
    await sendMessage("👋 Привет! Хочешь узнать статус заявки?", {
      inline_keyboard: [[{ text: "🔍 Проверить статус", callback_data: "check" }]],
    });
    return res.send("OK");
  }

  if (callback?.data === "check") {
    sessions[chat_id] = { step: "get_number" };
    await sendMessage("📄 Введите ваш номер заявки (пример: UZB-10838/25):");
    return res.send("OK");
  }

  if (sess.step === "get_number") {
    sessions[chat_id].number = text;
    sessions[chat_id].step = "get_email";
    await sendMessage("✉️ Теперь введите вашу почту:");
    return res.send("OK");
  }

  if (sess.step === "get_email") {
    sessions[chat_id].email = text;
    await sendMessage("🔎 Проверяю...");
    const { number, email } = sessions[chat_id];
    delete sessions[chat_id];

    // отправка POST-запроса на форму отслеживания
    const resp = await fetch("https://russia-edu.minobrnauki.gov.ru/...", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ number, email }),
    });
    const html = await resp.text();
    const $ = cheerio.load(html);

    const name = $("#fullName").text().trim() || "Имя не найдено";
    const status = $("#status").text().trim() || "Статус не найден";

    await sendMessage(`📋 Заявка: ${number}\n👤 ФИО: ${name}\n📌 Статус: ${status}`);
    return res.send("OK");
  }

  // default
  await sendMessage("Нажмите /start, чтобы начать.");
  return res.send("OK");
};
