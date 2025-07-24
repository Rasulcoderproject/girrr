const fetch = require("node-fetch");
const cheerio = require("cheerio");

const sessions = {};

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).send("Method Not Allowed");

  const token = process.env.TELEGRAM_BOT_TOKEN;
  const body = req.body;
  const msg = body.message || body.callback_query?.message;
  const text = body.message?.text;
  const callbackData = body.callback_query?.data;
  const chat_id = msg?.chat?.id;

  const sendMessage = (text, keyboard = null) => {
    return fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id,
        text,
        reply_markup: keyboard ? { inline_keyboard: keyboard } : undefined,
      }),
    });
  };

  if (!chat_id) return res.status(200).send("No chat_id");

  // Обработка команды /start
  if (text === "/start") {
    sessions[chat_id] = { step: null };
    await sendMessage("👋 Привет! Я помогу вам узнать статус вашей заявки.", [
      [{ text: "🔍 Проверить статус заявки", callback_data: "check_status" }]
    ]);
    return res.status(200).send("OK");
  }

  // Обработка нажатия кнопки
  if (callbackData === "check_status") {
    sessions[chat_id] = { step: "ask_application" };
    await sendMessage("📄 Введите номер вашей заявки (например: UZB-10838/25):");
    return res.status(200).send("OK");
  }

  const session = sessions[chat_id];

  if (session?.step === "ask_application") {
    if (!/^UZB-\d+\/\d+$/.test(text)) {
      await sendMessage("⚠️ Неверный формат. Пример: UZB-10838/25");
      return res.status(200).send("OK");
    }

    session.applicationNumber = text;
    session.step = "ask_email";
    await sendMessage("✉️ Теперь введите ваш адрес электронной почты:");
    return res.status(200).send("OK");
  }

  if (session?.step === "ask_email") {
    if (!/^\S+@\S+\.\S+$/.test(text)) {
      await sendMessage("⚠️ Неверный формат email. Пример: example@gmail.com");
      return res.status(200).send("OK");
    }

    session.email = text;
    session.step = "checking";
    await sendMessage("🔍 Проверяю статус вашей заявки...");

    const { applicationNumber, email } = session;
    const url = `https://russia-edu.minobrnauki.gov.ru/application-status?number=${encodeURIComponent(applicationNumber)}&email=${encodeURIComponent(email)}`;

    try {
      const response = await fetch(url);
      const html = await response.text();
      const $ = cheerio.load(html);

      const status = $("#status").text().trim() || "❗ Статус не найден. Проверьте данные.";
      await sendMessage(`📄 Статус заявки:\n${status}`);
    } catch (err) {
      await sendMessage("❗ Ошибка при запросе. Попробуйте позже.");
    }

    delete sessions[chat_id];
    return res.status(200).send("OK");
  }

  // Если нет команды
  await sendMessage("❓ Нажмите /start для начала.");
  return res.status(200).send("OK");
};
