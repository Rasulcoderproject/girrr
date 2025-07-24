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
    await sendMessage("👋 Привет! Я помогу узнать статус вашей заявки.", {
      inline_keyboard: [[{ text: "🔍 Проверить статус", callback_data: "check" }]],
    });
    return res.send("OK");
  }

  if (callback?.data === "check") {
    sessions[chat_id] = { step: "get_number" };
    await sendMessage("📄 Введите номер заявки (пример: UZB-10838/25):");
    return res.send("OK");
  }

  if (sess.step === "get_number") {
    sessions[chat_id].number = text;
    sessions[chat_id].step = "get_email";
    await sendMessage("✉️ Теперь введите ваш email:");
    return res.send("OK");
  }

  if (sess.step === "get_email") {
    sessions[chat_id].email = text;
    await sendMessage("🔍 Ищу информацию...");

    const { number, email } = sessions[chat_id];
    delete sessions[chat_id];

    try {
      // 1. Получить trackingUrl
      const searchRes = await fetch("https://russia-edu.minobrnauki.gov.ru/tracking/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ number, email }),
      });

      const json = await searchRes.json();
      if (!json.trackingUrl) {
        await sendMessage("❗ Не удалось найти заявку. Проверьте номер и почту.");
        return res.send("OK");
      }

      const trackingUrl = "https://russia-edu.minobrnauki.gov.ru" + json.trackingUrl;

      // 2. Получить и распарсить HTML
      const htmlRes = await fetch(trackingUrl);
      const html = await htmlRes.text();
      const $ = cheerio.load(html);

      const name = $(".personal-info strong").first().text().trim() || "Имя не найдено";
      const status = $(".application-status span").first().text().trim() || "Статус не найден";

      await sendMessage(`📋 Заявка: ${number}\n👤 ФИО: ${name}\n📌 Статус: ${status}`);
    } catch (err) {
      await sendMessage("❗ Произошла ошибка. Попробуйте позже.");
    }

    return res.send("OK");
  }

  await sendMessage("Нажмите /start, чтобы начать.");
  return res.send("OK");
};
