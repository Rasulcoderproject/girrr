const fetch = require("node-fetch");

const sessions = {};
const stats = {}; // Статистика по пользователям

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

  // Функция обновления статистики
  function updateStats(chat_id, game, win) {
    if (!stats[chat_id]) stats[chat_id] = {};
    if (!stats[chat_id][game]) stats[chat_id][game] = { played: 0, wins: 0 };

    stats[chat_id][game].played++;
    if (win) stats[chat_id][game].wins++;
  }

  // /start
  if (text === "/start") {
    sessions[chat_id] = {};
    return await sendMessage("👋 Привет! Выбери тему для теста или игру:", {
      keyboard: [
        [{ text: "История" }, { text: "Математика" }],
        [{ text: "Английский" }, { text: "Игры 🎲" }]
      ],
      resize_keyboard: true,
    }).then(() => res.send("OK"));
  }

  // /stats - показать статистику
  if (text === "/stats") {
    const userStats = stats[chat_id];
    if (!userStats) {
      await sendMessage("Ты ещё не играл ни в одну игру.");
      return res.send("OK");
    }

    let msg = "📊 Твоя статистика:\n\n";
    for (const game in userStats) {
      const s = userStats[game];
      msg += `• ${game}: сыграно ${s.played}, побед ${s.wins}\n`;
    }
    await sendMessage(msg);
    return res.send("OK");
  }

  // Игры меню
  if (text === "Игры 🎲") {
    return await sendMessage("Выбери игру:", {
      keyboard: [
        [{ text: "Угадай слово" }, { text: "Найди ложь" }],
        [{ text: "Продолжи историю" }, { text: "Шарада" }],
        [{ text: "/start" }]
      ],
      resize_keyboard: true,
    }).then(() => res.send("OK"));
  }

  // Проверка ответа для тестов (История, Математика, Английский)
  if (session.correctAnswer) {
    const userAnswer = text.trim().toUpperCase();
    const correct = session.correctAnswer.toUpperCase();
    delete sessions[chat_id].correctAnswer;

    if (userAnswer === correct) {
      await sendMessage("✅ Правильно! Хочешь ещё вопрос?", {
        keyboard: [
          [{ text: "История" }, { text: "Математика" }],
          [{ text: "Английский" }, { text: "Игры 🎲" }]
        ],
        resize_keyboard: true,
      });
    } else {
      await sendMessage(`❌ Неправильно. Правильный ответ: ${correct}\nПопробуешь ещё?`, {
        keyboard: [
          [{ text: "История" }, { text: "Математика" }],
          [{ text: "Английский" }, { text: "Игры 🎲" }]
        ],
        resize_keyboard: true,
      });
    }
    return res.send("OK");
  }

  // Выбор темы для теста
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

  // ===== Игры =====

  // Угадай слово
  if (text === "Угадай слово") {
    const prompt = `
Загадай одно существительное (например: тигр, самолёт, лампа и т.д.). Опиши его так, чтобы пользователь попытался угадать, что это. Не называй само слово. В конце добавь: "Загаданное слово: ..." (но это скроем от пользователя).
Формат:
Описание: ...
Загаданное слово: ...
    `.trim();

    const reply = await askGPT(prompt);

    const match = reply.match(/Загаданное слово:\s*(.+)/i);
    const hiddenWord = match ? match[1].trim().toUpperCase() : null;

    const description = reply.replace(/Загаданное слово:\s*.+/i, "").replace("Описание:", "").trim();

    if (!hiddenWord) {
      await sendMessage("⚠️ Не удалось сгенерировать описание. Попробуй ещё.");
      return res.send("OK");
    }

    sessions[chat_id] = { game: "Угадай слово", answer: hiddenWord };

    await sendMessage(`🧠 Угадай слово:\n\n${description}`);
    return res.send("OK");
  }

  if (session.game === "Угадай слово") {
    const userGuess = text.trim().toUpperCase();
    const correctAnswer = session.answer;

    delete sessions[chat_id];

    const win = userGuess === correctAnswer;
    updateStats(chat_id, "Угадай слово", win);

    let replyText = "";
    if (win) {
      replyText = "🎉 Правильно! Хочешь сыграть ещё?";
      if (stats[chat_id]["Угадай слово"].wins >= 5) {
        replyText += "\n🏅 Поздравляем! Ты получил ачивку: «Мастер угадывания»!";
      }
    } else {
      replyText = `❌ Неправильно. Было загадано: ${correctAnswer}\nПопробуешь ещё?`;
    }

    await sendMessage(replyText, {
      keyboard: [
        [{ text: "Игры 🎲" }],
        [{ text: "/start" }]
      ],
      resize_keyboard: true,
    });

    return res.send("OK");
  }

  // Найди ложь
  if (text === "Найди ложь") {
    const prompt = `
Придумай три коротких утверждения на любые темы. Два из них должны быть правдой, одно — ложью. В конце укажи, какое из них ложь (например: "Ложь: №2").
Формат:
1. ...
2. ...
3. ...
Ложь: №...
    `.trim();

    const reply = await askGPT(prompt);
    const match = reply.match(/Ложь:\s*№?([1-3])/i);
    const falseIndex = match ? match[1] : null;

    if (!falseIndex) {
      await sendMessage("⚠️ Не удалось сгенерировать утверждения. Попробуй ещё.");
      return res.send("OK");
    }

    const statementText = reply.replace(/Ложь:\s*№?[1-3]/i, "").trim();
    sessions[chat_id] = { game: "Найди ложь", answer: falseIndex };

    await sendMessage(`🕵️ Найди ложь:\n\n${statementText}\n\nОтвет введи цифрой (1, 2 или 3).`);
    return res.send("OK");
  }

  if (session.game === "Найди ложь") {
    const guess = text.trim();
    const correct = session.answer;

    delete sessions[chat_id];

    const win = guess === correct;
    updateStats(chat_id, "Найди ложь", win);

    let replyText = "";
    if (win) {
      replyText = "🎉 Верно! Ты нашёл ложь!";
      if (stats[chat_id]["Найди ложь"].wins >= 5) {
        replyText += "\n🏅 Ачивка: «Ловкач»!";
      }
    } else {
      replyText = `❌ Нет, ложь была под номером ${correct}. Попробуешь ещё?`;
    }

    await sendMessage(replyText, {
      keyboard: [[{ text: "Игры 🎲" }], [{ text: "/start" }]],
      resize_keyboard: true,
    });

    return res.send("OK");
  }

  // Продолжи историю
  if (text === "Продолжи историю") {
    const prompt = `
Придумай короткое начало истории и три возможных продолжения. Варианты продолжения пронумеруй.
Формат:
Начало: ...
1. ...
2. ...
3. ...
    `.trim();

    const reply = await askGPT(prompt);
    const match = reply.match(/Начало:\s*(.+?)(?:\n|$)/i);
    const intro = match ? match[1].trim() : null;

    if (!intro) {
      await sendMessage("⚠️ Не удалось сгенерировать историю. Попробуй ещё.");
      return res.send("OK");
    }

    sessions[chat_id] = { game: "Продолжи историю" };

    await sendMessage(`📖 Продолжи историю:\n\n${reply}\n\nВыбери номер продолжения (1, 2 или 3).`);
    return res.send("OK");
  }

  if (session.game === "Продолжи историю") {
    const choice = text.trim();

    // Для простоты принимаем любой ответ 1-3 и считаем выигрышом (или можно усложнить)
    const win = ["1", "2", "3"].includes(choice);
    delete sessions[chat_id];

    updateStats(chat_id, "Продолжи историю", win);

    let replyText = win ? "🎉 Классное продолжение!" : "❌ Не похоже на вариант из списка.";

    if (win && stats[chat_id]["Продолжи историю"].wins >= 5) {
      replyText += "\n🏅 Ачивка: «Сказочник»!";
    }

    await sendMessage(replyText, {
      keyboard: [[{ text: "Игры 🎲" }], [{ text: "/start" }]],
      resize_keyboard: true,
    });

    return res.send("OK");
  }

  // Шарада
  if (text === "Шарада") {
    const prompt = `
Придумай одну шараду (загадку), которая состоит из трех частей, каждая часть даёт подсказку, чтобы угадать слово. В конце напиши ответ.
Формат:
1) ...
2) ...
3) ...
Ответ: ...
    `.trim();

    const reply = await askGPT(prompt);
    const match = reply.match(/Ответ:\s*(.+)/i);
    const answer = match ? match[1].trim().toUpperCase() : null;

    if (!answer) {
      await sendMessage("⚠️ Не удалось сгенерировать шараду. Попробуй ещё.");
      return res.send("OK");
    }

    const riddleText = reply.replace(/Ответ:\s*.+/i, "").trim();

    sessions[chat_id] = { game: "Шарада", answer };

    await sendMessage(`🧩 Шарада:\n\n${riddleText}\n\nНапиши свой ответ.`);
    return res.send("OK");
  }

  if (session.game === "Шарада") {
    const guess = text.trim().toUpperCase();
    const correct = session.answer;

    delete sessions[chat_id];

    const win = guess === correct;
    updateStats(chat_id, "Шарада", win);

    let replyText = "";
    if (win) {
      replyText = "🎉 Молодец! Правильно угадал!";
      if (stats[chat_id]["Шарада"].wins >= 5) {
        replyText += "\n🏅 Ачивка: «Шарадист»!";
      }
    } else {
      replyText = `❌ Неправильно. Правильный ответ: ${correct}. Попробуешь ещё?`;
    }

    await sendMessage(replyText, {
      keyboard: [[{ text: "Игры 🎲" }], [{ text: "/start" }]],
      resize_keyboard: true,
    });

    return res.send("OK");
  }

  // Неизвестная команда / сообщение
  await sendMessage("⚠️ Напиши /start, чтобы начать сначала или выбери команду из меню.");
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
