const fetch = require("node-fetch");
const cheerio = require("cheerio");

async function getApplicationStatus(appNumber, email) {

  const url = `https://russia-edu.minobrnauki.gov.ru/application-status?number=${appNumber}&email=${email}`;
  const resp = await fetch(url);
  const html = await resp.text();
  const $ = cheerio.load(html);

  const status = $("#status").text().trim() || "Статус не найден";
  return status;
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).send("Method Not Allowed");
    return;
  }

  const body = req.body;
  const token = process.env.TELEGRAM_BOT_TOKEN;

  const sendMessage = (chat_id, text, options = {}) =>
    fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id, text, reply_markup: options }),
    });

  const from = body.callback_query?.from;
  const chat_id = body.message?.chat?.id || body.callback_query?.message?.chat?.id;
  const text = body.message?.text;

  if (body.callback_query) {
    await sendMessage(chat_id, "Введите номер заявки и email через пробел (например: UZB-123456 email@example.com):");
    return res.status(200).json({ ok: true });
  }

  if (text === "/start") {
    const keyboard = { inline_keyboard: [[{ text: "🔍 Проверить заявку", callback_data: "check_application" }]] };
    await sendMessage(chat_id, "Привет! Выберите действие:", keyboard);
    return res.status(200).json({ ok: true });
  }

  const parts = text.split(" ");
  if (parts.length === 2 && /^\d{5,}$/.test(parts[0]) && /\S+@\S+\.\S+/.test(parts[1])) {
    const [appNumber, email] = parts;
    await sendMessage(chat_id, `🔎 Проверяю заявку №${appNumber}...`);
    const status = await getApplicationStatus(appNumber, email);
    await sendMessage(chat_id, `📄 Статус заявки №${appNumber}:\n${status}`);
    return res.status(200).json({ ok: true });
  }

  await sendMessage(chat_id, "Пожалуйста, используй формат: `<номер заявки> <email>`");
  res.status(200).json({ ok: true });
};
