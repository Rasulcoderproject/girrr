import os
import json
import re
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()

# --- В памяти ---
sessions = {}
feed = {}
stats = {}
feedback_sessions = {}

# --- Переменные окружения ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OWNER_ID = str(os.getenv("MY_TELEGRAM_ID", ""))

# Лимит Telegram (~4096)
TELEGRAM_SEND_MAX = 3900

# ---- Утилиты ----
async def read_raw_body(req: Request):
    return await req.body()

def chunk_string(s: str, size=TELEGRAM_SEND_MAX):
    return [s[i:i + size] for i in range(0, len(s), size)]

def safe_json(obj):
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

# ---- Telegram API ----
async def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    payload = {"chat_id": str(chat_id), "text": str(text)}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json=payload)
        except Exception as e:
            print("send_message error:", e)

async def answer_callback_query(callback_query_id):
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                              json={"callback_query_id": callback_query_id})
        except Exception as e:
            print("answer_callback_query error:", e)

# ---- OpenRouter GPT ----
async def ask_gpt(prompt):
    if not OPENROUTER_API_KEY:
        return "Ошибка: нет OPENROUTER_API_KEY"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openai/gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
            )
            data = res.json()
            if not res.is_success:
                print("OpenRouter API error:", data)
                return "Ошибка генерации."
            return data.get("choices", [{}])[0].get("message", {}).get("content", "Ошибка генерации.")
    except Exception as e:
        print("ask_gpt error:", e)
        return "Ошибка генерации."

# ---- Основной webhook ----
@app.post("/api/telegram")
async def telegram_webhook(req: Request):
    raw = await read_raw_body(req)
    try:
        update = json.loads(raw)
    except Exception as e:
        print("Bad JSON:", e)
        return PlainTextResponse("Bad JSON", status_code=400)

    print("📩 Получен update:", update.get("update_id"))

    from_id = str(
        update.get("message", {}).get("from", {}).get("id")
        or update.get("edited_message", {}).get("from", {}).get("id")
        or update.get("callback_query", {}).get("from", {}).get("id")
        or update.get("inline_query", {}).get("from", {}).get("id")
        or ""
    )
    is_owner = from_id and OWNER_ID and from_id == OWNER_ID

    msg_text = (
        update.get("message", {}).get("text")
        or update.get("edited_message", {}).get("text")
        or update.get("callback_query", {}).get("data")
        or update.get("inline_query", {}).get("query")
        or ""
    )

    if is_owner and isinstance(msg_text, str) and msg_text.startswith("/reply "):
        parts = msg_text.split(" ")
        target_id = parts[1] if len(parts) > 1 else None
        reply_text = " ".join(parts[2:]) if len(parts) > 2 else None
        if not target_id or not reply_text:
            await send_message(OWNER_ID, "⚠ Формат: /reply <chat_id> <текст>")
        else:
            await send_message(target_id, reply_text)
            await send_message(OWNER_ID, f"✅ Сообщение отправлено пользователю {target_id}")
        return PlainTextResponse("ok")

    if not is_owner and OWNER_ID:
        header = f"📡 Новое событие (update_id: {update.get('update_id', '—')})\nСодержимое апдейта (JSON):\n"
        body = safe_json(update)
        payload = header + body
        for chunk in chunk_string(payload):
            await send_message(OWNER_ID, f"```json\n{chunk}\n```", parse_mode="Markdown")

    chat_id = (
        update.get("message", {}).get("chat", {}).get("id")
        or update.get("edited_message", {}).get("chat", {}).get("id")
        or update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
        or None
    )

    if update.get("callback_query"):
        await answer_callback_query(update["callback_query"]["id"])

    if chat_id:
        chat_id_str = str(chat_id)
        first_name = (
            update.get("message", {}).get("from", {}).get("first_name")
            or update.get("edited_message", {}).get("from", {}).get("first_name")
            or update.get("callback_query", {}).get("from", {}).get("first_name")
            or ""
        )
        if update.get("message", {}).get("contact"):
            contact = update["message"]["contact"]
            await send_message(chat_id_str, f"✅ Спасибо! Я получил твой номер: +{contact['phone_number']}")
            await send_message(
                OWNER_ID,
                f"📞 Новый контакт:\nИмя: {contact.get('first_name')}\nТелефон: +{contact.get('phone_number')}\nID: {contact.get('user_id')}"
            )
            return PlainTextResponse("ok")

        text = (
            update.get("message", {}).get("text")
            or update.get("edited_message", {}).get("text")
            or update.get("callback_query", {}).get("data")
            or ""
        )

        try:
            await process_game_logic(chat_id_str, text, first_name)
        except Exception as e:
            print("process_game_logic error:", e)

    return PlainTextResponse("ok")


# ---- Игровая логика ----
async def process_game_logic(chat_id, text, first_name):
    def update_stats(local_chat_id, game, win):
        stats.setdefault(local_chat_id, {})
        stats[local_chat_id].setdefault(game, {"played": 0, "wins": 0})
        stats[local_chat_id][game]["played"] += 1
        if win:
            stats[local_chat_id][game]["wins"] += 1

    session = sessions.get(chat_id, {})

    # --- /start ---
    if text == "/start":
        sessions[chat_id] = {"firstName": first_name}
        await send_message(chat_id, f"👋 Привет, {first_name or 'друг'}! Выбери тему для теста или игру:", {
            "keyboard": [
                [{"text": "История"}, {"text": "Математика"}],
                [{"text": "Английский"}, {"text": "Игры 🎲"}],
                [{"text": "/feedback"}, {"text": "📤 Поделиться контактом", "request_contact": True}]
            ],
            "resize_keyboard": True
        })
        return

    # --- Feedback ---
    if text == "/feedback":
        feedback_sessions[chat_id] = True
        await send_message(chat_id, "📝 Пожалуйста, введите ваш комментарий одним сообщением:")
        return

    if feedback_sessions.get(chat_id):
        del feedback_sessions[chat_id]
        fn = session.get("firstName", "")
        await send_message(OWNER_ID, f"💬 Отзыв от {fn or 'Без имени'} (ID: {chat_id})\nТекст: {text}")
        await send_message(chat_id, "✅ Ваш комментарий отправлен, скоро с вами свяжутся!")
        return

    # --- Статистика ---
    if text == "/stats":
        user_stats = stats.get(chat_id)
        if not user_stats:
            await send_message(chat_id, "Ты ещё не играл ни в одну игру.")
            return
        msg = "📊 Твоя статистика:\n\n"
        for game, s in user_stats.items():
            msg += f"• {game}: сыграно {s['played']}, побед {s['wins']}\n"
        await send_message(chat_id, msg)
        return

    # --- Тестовые вопросы ---
    if text in ["История", "Математика", "Английский"]:
        topic = text
        prompt = f'Задай один тестовый вопрос с 4 вариантами ответа по теме "{topic}". Формат: Вопрос: ... A) ... B) ... C) ... D) ... Правильный ответ: ... (A-D)'
        reply = await ask_gpt(prompt)
        match = re.search(r"Правильный ответ:\s*([A-D])", reply, re.I)
        correct_answer = match.group(1).upper() if match else None
        if not correct_answer:
            await send_message(chat_id, "⚠️ Не удалось сгенерировать вопрос. Попробуй снова.")
            return
        question_text = re.sub(r"Правильный ответ:\s*[A-D]", "", reply).strip()
        sessions[chat_id] = {"correctAnswer": correct_answer}
        await send_message(chat_id, f"📚 Вопрос по теме *{topic}*:\n\n{question_text}", parse_mode="Markdown")
        return

    # --- Проверка ответа на тест ---
    if session.get("correctAnswer"):
        user_answer = text.strip().upper()
        correct = session.pop("correctAnswer")
        if user_answer == correct:
            await send_message(chat_id, "✅ Правильно! Хочешь ещё вопрос?", {
                "keyboard": [
                    [{"text": "История"}, {"text": "Математика"}],
                    [{"text": "Английский"}, {"text": "Игры 🎲"}],
                ],
                "resize_keyboard": True
            })
        else:
            await send_message(chat_id, f"❌ Неправильно. Правильный ответ: {correct}\nПопробуешь ещё?", {
                "keyboard": [
                    [{"text": "История"}, {"text": "Математика"}],
                    [{"text": "Английский"}, {"text": "Игры 🎲"}],
                ],
                "resize_keyboard": True
            })
        return

    # --- Игры ---
    # Угадай слово
    if text == "Угадай слово":
        prompt = 'Загадай одно существительное и опиши его так, чтобы пользователь угадал. Формат: Описание: ... Загаданное слово: ...'
        reply = await ask_gpt(prompt)
        match = re.search(r"Загаданное слово:\s*(.+)", reply, re.I)
        hidden_word = match.group(1).upper() if match else None
        description = re.sub(r"Загаданное слово:\s*.+", "", reply, flags=re.I).replace("Описание:", "").strip()
        if not hidden_word:
            await send_message(chat_id, "⚠️ Не удалось сгенерировать описание. Попробуй ещё.")
            return
        sessions[chat_id] = {"game": "Угадай слово", "answer": hidden_word}
        await send_message(chat_id, f"🧠 Угадай слово:\n\n{description}")
        return

    if session.get("game") == "Угадай слово":
        guess = text.strip().upper()
        correct = session.pop("answer")
        win = guess == correct
        update_stats(chat_id, "Угадай слово", win)
        reply_text = f"🎉 Правильно! Хочешь сыграть ещё?" if win else f"❌ Неправильно. Было загадано: {correct}\nПопробуешь ещё?"
        await send_message(chat_id, reply_text, {
            "keyboard": [[{"text": "Игры 🎲"}], [{"text": "/start"}]],
            "resize_keyboard": True
        })
        return

    # --- Фоллбек ---
    await send_message(chat_id, "⚠️ Напиши /start, чтобы начать сначала или выбери команду из меню.")
