const fetch = require("node-fetch");
const cheerio = require("cheerio");

const sessions = {}; // Временное хранилище данных пользователей

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).send("Method Not Allowed");

  const token = process.env.TELEGRAM_BOT_TOKEN;
  const body = req.body;
  const message = body.message || body.callback_query?.message;
  const chat_id = message?.chat?.id;
  const text = body.message?.text;

  const sendMessage = (text, keyboard = null) => {
    return fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id,
        text,
        reply_markup: keyboard,
      }),
    });
  };

  if (!chat_id) return res.status(200).send("No chat_id");

  const session = sessions[chat_id] || {};

  if (text === "/start") {
    sessions[chat_id] = {}; // сбрасываем сессию
    await sendMessage("👋 Привет! Введите номер вашей заявки (например: UZB-10838/25):");
    return res.status(200).send("OK");
  }

  if (!session.applicationNumber) {
    // сохраняем номер заявки
    sessions[chat_id] = { applicationNumber: text };
    await sendMessage("📧 Теперь введите вашу электронную почту:");
    return res.status(200).send("OK");
  }

  if (!session.email) {
    // сохраняем email
    sessions[chat_id].email = text;

    const { applicationNumber, email } = sessions[chat_id];
    await sendMessage(`🔎 Проверяю заявку:\nНомер: ${applicationNumber}\nEmail: ${email}...`);

    // примерный URL, адаптируй под реальный
    const url = `https://russia-edu.minobrnauki.gov.ru/application-status?number=${encodeURIComponent(applicationNumber)}&email=${encodeURIComponent(email)}`;
    const response = await fetch(url);
    const html = await response.text();
    const $ = cheerio.load(html);

    // предполагаем, что статус находится в #status
    const status = $("#status").text().trim() || "❗ Статус не найден. Проверьте данные.";
    await sendMessage(`📄 Статус вашей заявки:\n${status}`);

    delete sessions[chat_id]; // очищаем сессию после запроса
    return res.status(200).send("OK");
  }

  // если что-то непонятное
  await sendMessage("❓ Пожалуйста, начните с команды /start");
  return res.status(200).send("OK");
};
