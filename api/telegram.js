// pages/api/telegram.js
export const config = {
  api: { bodyParser: false },
};

import fetch from "node-fetch";

// --- В памяти ---
const sessions = {};
const stats = {};
const feedbackSessions = {};


// --- Переменные окружения (обязательно установить на Vercel) ---
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY || "";
const OWNER_ID = String(process.env.MY_TELEGRAM_ID || "");

// Безопасные лимиты (Telegram: ~4096 символов в сообщении)
const TELEGRAM_SEND_MAX = 3900;

// ---- Утилиты ----
function readRawBody(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (chunk) => (data += chunk));
    req.on("end", () => resolve(data));
  });
}

function chunkString(str, size = TELEGRAM_SEND_MAX) {
  const chunks = [];
  for (let i = 0; i < str.length; i += size) {
    chunks.push(str.slice(i, i + size));
  }
  return chunks;
}

function safeJson(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch (e) {
    return String(obj);
  }
}









// ---- Основной обработчик ----
export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(200).send("OK");

  const raw = await readRawBody(req);
  let update;
  try {
    update = JSON.parse(raw.toString());
  } catch (e) {
    console.error("Bad JSON:", e);
    return res.status(400).send("Bad JSON");
  }

  console.log("📩 Получен update:", update?.update_id);

  // 1) Если это сообщение от владельца — проверим /reply
  const fromId = String(
    update?.message?.from?.id ??
      update?.edited_message?.from?.id ??
      update?.callback_query?.from?.id ??
      update?.inline_query?.from?.id ??
      ""
  );

  const isOwner = fromId && OWNER_ID && fromId === OWNER_ID;

  const msgText =
    update?.message?.text ??
    update?.edited_message?.text ??
    update?.callback_query?.data ??
    update?.inline_query?.query ??
    "";

  // Обработка команды /reply от владельца
  if (isOwner && typeof msgText === "string" && msgText.startsWith("/reply ")) {
    const parts = msgText.split(" ");
    const targetId = parts[1];
    const replyText = parts.slice(2).join(" ");
    if (!targetId || !replyText) {
      await sendMessage(OWNER_ID, "⚠ Формат: /reply <chat_id> <текст>");
    } else {
      await sendMessage(targetId, replyText);
      await sendMessage(OWNER_ID, `✅ Сообщение отправлено пользователю ${targetId}`);
    }
    // чтобы не запутывать — не пересылаем owner's /reply владельцу
    return res.status(200).send("ok");
  }

  // 2) Пересылаем владельцу полный JSON апдейта (если апдейт не от владельца)
  if (!isOwner && OWNER_ID) {
    const header = `📡 Новое событие (update_id: ${update.update_id ?? "—"})\nСодержимое апдейта (JSON):\n`;
    const body = safeJson(update);
    const payload = header + body;
    const chunks = chunkString(payload, TELEGRAM_SEND_MAX);
    for (const c of chunks) {
      // Отправляем как моно-кодный блок, используем Markdown (кодовый блок)
      // Но экранирование тройных backticks не нужно, мы просто шлем куски.
      // Если parse_mode вызывает проблемы с символами — можно убрать parse_mode или использовать "HTML".
      await sendMessage(OWNER_ID, "```json\n" + c + "\n```", null, "Markdown");
    }
  }

  // 3) Обработка игрового поведения (message, edited_message, callback_query)
  // Используем текст/данные как событие для игры.
  // Поддержаны: message.text, edited_message.text, callback_query.data
  const chatId =
    update?.message?.chat?.id ??
    update?.edited_message?.chat?.id ??
    update?.callback_query?.message?.chat?.id ??
    null;

  // Если есть callback_query — ответим на неё чтобы убрать "крутилку"
  if (update.callback_query) {
    const cqid = update.callback_query.id;
    try {
      await answerCallbackQuery(cqid);
    } catch (e) {
      // игнорируем ошибку
    }
  }

  if (chatId) {
    const chat_id_str = String(chatId);
    const text =
      update?.message?.text ??
      update?.edited_message?.text ??
      update?.callback_query?.data ??
      "";

    // запускаем игровую логику (в памяти)
    try {
      await processGameLogic(chat_id_str, String(text || ""));
    } catch (e) {
      console.error("processGameLogic error:", e);
    }
  }

  return res.status(200).send("ok");
}

// ---- sendMessage wrapper ----
async function sendMessage(chatId, text, reply_markup = null, parse_mode = "Markdown") {
  const body = {
    chat_id: String(chatId),
    text: String(text),
  };
  if (reply_markup) body.reply_markup = reply_markup;
  if (parse_mode) body.parse_mode = parse_mode;

  try {
    const r = await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return r;
  } catch (e) {
    console.error("sendMessage error:", e);
    throw e;
  }
}

async function answerCallbackQuery(callback_query_id) {
  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/answerCallbackQuery`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_query_id }),
    });
  } catch (e) {
    console.error("answerCallbackQuery error:", e);
  }
}








// ---- Игровая логика (вся, как у тебя) ----
async function processGameLogic(chat_id, text) {
  const session = sessions[chat_id] || {};

  function updateStats(localChatId, game, win) {
    if (!stats[localChatId]) stats[localChatId] = {};
    if (!stats[localChatId][game]) stats[localChatId][game] = { played: 0, wins: 0 };
    stats[localChatId][game].played++;
    if (win) stats[localChatId][game].wins++;
  }


  // Feedback кнопка
  if (text === "/feedback") {
    feedbackSessions[chat_id] = true;
    await sendMessage(chat_id, "📝 Пожалуйста, введите ваш комментарий одним сообщением:");
    return;
  }

  // Приём отзыва
  if (feedbackSessions[chat_id]) {
    delete feedbackSessions[chat_id];
    const { firstName, username } = sessions[chat_id] || {};
    await sendMessage(
      OWNER_ID,
      `💬 Отзыв от ${firstName || "Без имени"} (@${username || "нет"})\nID: ${chat_id}\nТекст: ${text}`
      
    );



    await sendMessage(
      OWNER_ID,
      `/reply ${chat_id}`
      
    );

    await sendMessage(chat_id, "✅ Ваш комментарий отправлен скоро с вами свяжется!");
    return;
  }


  
  // /start
  if (text === "/start") {
    sessions[chat_id] = {};
    await sendMessage(chat_id, "👋 Привет! Выбери тему для теста или игру:", {
      keyboard: [
        [{ text: "История" }, { text: "Математика" }],
        [{ text: "Английский" }, { text: "Игры 🎲" }],
        [{ text: "/feedback" }]
        
      ],
      resize_keyboard: true,
    });
    return;
  }


  
  
  // /stats - показать статистику
  if (text === "/stats") {
    const userStats = stats[chat_id];
    if (!userStats) {
      await sendMessage(chat_id, "Ты ещё не играл ни в одну игру.");
      return;
    }

    let msg = "📊 Твоя статистика:\n\n";
    for (const game in userStats) {
      const s = userStats[game];
      msg += `• ${game}: сыграно ${s.played}, побед ${s.wins}\n`;
    }
    await sendMessage(chat_id, msg);
    return;
  }

  // Игры меню
  if (text === "Игры 🎲") {
    await sendMessage(chat_id, "Выбери игру:", {
      keyboard: [
        [{ text: "Угадай слово" }, { text: "Найди ложь" }],
        [{ text: "Продолжи историю" }, { text: "Шарада" }],
        [{ text: "/start" }, { text: "/stats" }],
      ],
      resize_keyboard: true,
    });
    return;
  }

  // Проверка ответа для тестов (История, Математика, Английский)
  if (session.correctAnswer) {
    const userAnswer = text.trim().toUpperCase();
    const correct = session.correctAnswer.toUpperCase();
    delete sessions[chat_id].correctAnswer;

    if (userAnswer === correct) {
      await sendMessage(chat_id, "✅ Правильно! Хочешь ещё вопрос?", {
        keyboard: [
          [{ text: "История" }, { text: "Математика" }],
          [{ text: "Английский" }, { text: "Игры 🎲" }],
        ],
        resize_keyboard: true,
      });
    } else {
      await sendMessage(
        chat_id,
        `❌ Неправильно. Правильный ответ: ${correct}\nПопробуешь ещё?`,
        {
          keyboard: [
            [{ text: "История" }, { text: "Математика" }],
            [{ text: "Английский" }, { text: "Игры 🎲" }],
          ],
          resize_keyboard: true,
        }
      );
    }
    return;
  }

  // Выбор темы для теста
  if (["История", "Математика", "Английский"].includes(text)) {
    const topic = text;
    const prompt = `
Задай один тестовый вопрос с 4 вариантами ответа по теме "${topic}".
Формат:
Вопрос: ...
A) ...
B) ...
C) ...
D) ...
Правильный ответ: ... (A-D)
    `.trim();

    const reply = await askGPT(prompt);
    const match = reply.match(/Правильный ответ:\s*([A-D])/i);
    const correctAnswer = match ? match[1].trim().toUpperCase() : null;

    if (!correctAnswer) {
      await sendMessage(chat_id, "⚠️ Не удалось сгенерировать вопрос. Попробуй снова.");
      return;
    }

    const questionWithoutAnswer = reply.replace(/Правильный ответ:\s*[A-D]/i, "").trim();
    sessions[chat_id] = { correctAnswer };
    await sendMessage(chat_id, `📚 Вопрос по теме *${topic}*:\n\n${questionWithoutAnswer}`, {
      parse_mode: "Markdown",
    });
    return;
  }

  // ===== Игры: Угадай слово =====
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
    const description = reply.replace(/Загаданное слово:\s*.+/i, "").replace(/Описание:\s*/i, "").trim();

    if (!hiddenWord) {
      await sendMessage(chat_id, "⚠️ Не удалось сгенерировать описание. Попробуй ещё.");
      return;
    }

    sessions[chat_id] = { game: "Угадай слово", answer: hiddenWord };
    await sendMessage(chat_id, `🧠 Угадай слово:\n\n${description}`);
    return;
  }

  if (session.game === "Угадай слово") {
    const userGuess = (text || "").trim().toUpperCase();
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

    await sendMessage(chat_id, replyText, {
      keyboard: [[{ text: "Игры 🎲" }], [{ text: "/start" }]],
      resize_keyboard: true,
    });
    return;
  }

  // ===== Игры: Найди ложь =====
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
      await sendMessage(chat_id, "⚠️ Не удалось сгенерировать утверждения. Попробуй ещё.");
      return;
    }

    const statementText = reply.replace(/Ложь:\s*№?[1-3]/i, "").trim();
    sessions[chat_id] = { game: "Найди ложь", answer: falseIndex };

    await sendMessage(chat_id, `🕵️ Найди ложь:\n\n${statementText}\n\nОтвет введи цифрой (1, 2 или 3).`);
    return;
  }

  if (session.game === "Найди ложь") {
    const guess = (text || "").trim();
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

    await sendMessage(chat_id, replyText, {
      keyboard: [[{ text: "Игры 🎲" }], [{ text: "/start" }]],
      resize_keyboard: true,
    });
    return;
  }

  // ===== Игры: Продолжи историю =====
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
      await sendMessage(chat_id, "⚠️ Не удалось сгенерировать историю. Попробуй ещё.");
      return;
    }

    sessions[chat_id] = { game: "Продолжи историю" };
    await sendMessage(chat_id, `📖 Продолжи историю:\n\n${reply}\n\nВыбери номер продолжения (1, 2 или 3).`);
    return;
  }

  if (session.game === "Продолжи историю") {
    const choice = (text || "").trim();
    const win = ["1", "2", "3"].includes(choice);
    delete sessions[chat_id];
    updateStats(chat_id, "Продолжи историю", win);

    let replyText = win ? "🎉 Классное продолжение!" : "❌ Не похоже на вариант из списка.";

    if (win && stats[chat_id]["Продолжи история"].wins >= 5) {
      replyText += "\n🏅 Ачивка: «Сказочник»!";
    }

    await sendMessage(chat_id, replyText, {
      keyboard: [[{ text: "Игры 🎲" }], [{ text: "/start" }]],
      resize_keyboard: true,
    });
    return;
  }

  // ===== Игры: Шарада =====
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
      await sendMessage(chat_id, "⚠️ Не удалось сгенерировать шараду. Попробуй ещё.");
      return;
    }

    const riddleText = reply.replace(/Ответ:\s*.+/i, "").trim();
    sessions[chat_id] = { game: "Шарада", answer };
    await sendMessage(chat_id, `🧩 Шарада:\n\n${riddleText}\n\nНапиши свой ответ.`);
    return;
  }

  if (session.game === "Шарада") {
    const guess = (text || "").trim().toUpperCase();
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

    await sendMessage(chat_id, replyText, {
      keyboard: [[{ text: "Игры 🎲" }], [{ text: "/start" }]],
      resize_keyboard: true,
    });
    return;
  }

  // Если ничего не подошло
  await sendMessage(chat_id, "⚠️ Напиши /start, чтобы начать сначала или выбери команду из меню.");
}

// ---- askGPT через OpenRouter (как у тебя) ----
async function askGPT(prompt) {
  if (!OPENROUTER_API_KEY) return "Ошибка: нет OPENROUTER_API_KEY";

  try {
    const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${OPENROUTER_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "openai/gpt-3.5-turbo",
        messages: [{ role: "user", content: prompt }],
        temperature: 0.7,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      console.error("OpenRouter API error:", data);
      return "Ошибка генерации: " + (data.error?.message || "неизвестная ошибка");
    }
    return data.choices?.[0]?.message?.content || "Ошибка генерации.";
  } catch (e) {
    console.error("askGPT error:", e);
    return "Ошибка генерации.";
  }
}
