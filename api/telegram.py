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
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id},
            )
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
            data = await res.json()
            if res.status_code != 200:
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

    # Владелец и /reply
    from_id = str(
        update.get("message", {}).get("from", {}).get("id") or
        update.get("edited_message", {}).get("from", {}).get("id") or
        update.get("callback_query", {}).get("from", {}).get("id") or
        update.get("inline_query", {}).get("from", {}).get("id") or
        ""
    )
    is_owner = OWNER_ID and from_id == OWNER_ID

    msg_text = (
        update.get("message", {}).get("text") or
        update.get("edited_message", {}).get("text") or
        update.get("callback_query", {}).get("data") or
        update.get("inline_query", {}).get("query") or
        ""
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

    # Пересылка JSON апдейта владельцу
    if not is_owner and OWNER_ID:
        header = f"📡 Новое событие (update_id: {update.get('update_id', '—')})\nСодержимое апдейта (JSON):\n"
        body = safe_json(update)
        payload = header + body
        for chunk in chunk_string(payload, TELEGRAM_SEND_MAX):
            await send_message(OWNER_ID, f"```json\n{chunk}\n```", parse_mode="Markdown")

    # Игровая логика
    chat_id = (
        update.get("message", {}).get("chat", {}).get("id") or
        update.get("edited_message", {}).get("chat", {}).get("id") or
        update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
    )
    if update.get("callback_query"):
        try:
            await answer_callback_query(update["callback_query"]["id"])
        except: pass

    if chat_id:
        chat_id_str = str(chat_id)
        first_name = (
            update.get("message", {}).get("from", {}).get("first_name") or
            update.get("edited_message", {}).get("from", {}).get("first_name") or
            update.get("callback_query", {}).get("from", {}).get("first_name") or
            ""
        )

        if update.get("message", {}).get("contact"):
            contact = update["message"]["contact"]
            await send_message(chat_id_str, f"✅ Спасибо! Я получил твой номер: +{contact['phone_number']}")
            await send_message(
                OWNER_ID,
                f"📞 Новый контакт:\nИмя: {contact['first_name']}\nТелефон: +{contact['phone_number']}\nID: {contact['user_id']}"
            )
            return PlainTextResponse("ok")

        text = (
            update.get("message", {}).get("text") or
            update.get("edited_message", {}).get("text") or
            update.get("callback_query", {}).get("data") or
            ""
        )

        try:
            await process_game_logic(chat_id_str, str(text or ""), first_name)
        except Exception as e:
            print("process_game_logic error:", e)

    return PlainTextResponse("ok")

# ---- Игровая логика ----
async def process_game_logic(chat_id, text, first_name):
    session = sessions.get(chat_id, {})

    def update_local_stats(game, win):
        update_stats(chat_id, game, win)

    # === Запрос контакта ===
    if text == "/contact":
        feed[chat_id] = True
        await send_message(chat_id, "📱 Пожалуйста, поделитесь своим номером телефона:", {
            "keyboard": [
                [{"text": "📤 Поделиться контактом", "request_contact": True}],
                [{"text": "/start"}]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True
        })
        return

    # === Feedback кнопка ===
    if text == "/feedback":
        feedback_sessions[chat_id] = True
        await send_message(chat_id, "📝 Пожалуйста, введите ваш комментарий одним сообщением:")
        return

    # Приём отзыва
    if feedback_sessions.get(chat_id):
        feedback_sessions.pop(chat_id)
        user_data = sessions.get(chat_id, {})
        await send_message(
            OWNER_ID,
            f"💬 Отзыв от {user_data.get('firstName', 'Без имени')} (@{user_data.get('username', 'нет')})\nID: {chat_id}\nТекст: {text}"
        )
        await send_message(OWNER_ID, f"/reply {chat_id}")
        await send_message(chat_id, "✅ Ваш комментарий отправлен, скоро с вами свяжутся!")
        return

    # /start
    if text == "/start":
        sessions[chat_id] = {"firstName": first_name}
        await send_message(chat_id, f"👋 Привет, {first_name or 'друг'}! Выбери тему для теста или игру:", {
            "keyboard": [
                [{"text": "История"}, {"text": "Математика"}],
                [{"text": "Английский"}, {"text": "Игры 🎲"}],
                [{"text": "/feedback"}, {"text": "📤 Поделиться контактом", "request_contact": True}],
            ],
            "resize_keyboard": True
        })
        return

    if text == "📤 Поделиться контактом":
        await send_message(chat_id, "Получен")
        return

    # /stats
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

    # Игры меню
    if text == "Игры 🎲":
        await send_message(chat_id, "Выбери игру:", {
            "keyboard": [
                [{"text": "Угадай слово"}, {"text": "Найди ложь"}],
                [{"text": "Продолжи историю"}, {"text": "Шарада"}],
                [{"text": "/start"}, {"text": "/stats"}]
            ],
            "resize_keyboard": True
        })
        return

    # Проверка ответа для тестов
    if session.get("correctAnswer"):
        user_answer = text.strip().upper()
        correct = session["correctAnswer"].upper()
        sessions[chat_id].pop("correctAnswer")
        if user_answer == correct:
            await send_message(chat_id, "✅ Правильно! Хочешь ещё вопрос?", {
                "keyboard": [
                    [{"text": "История"}, {"text": "Математика"}],
                    [{"text": "Английский"}, {"text": "Игры 🎲"}]
                ],
                "resize_keyboard": True
            })
        else:
            await send_message(chat_id, f"❌ Неправильно. Правильный ответ: {correct}\nПопробуешь ещё?", {
                "keyboard": [
                    [{"text": "История"}, {"text": "Математика"}],
                    [{"text": "Английский"}, {"text": "Игры 🎲"}]
                ],
                "resize_keyboard": True
            })
        return

    # Выбор темы для теста
    
    
    
    
    # ===== Найди ложь =====
    if text == "Найди ложь":
        prompt = """
Придумай три коротких утверждения. Два правдивых, одно ложное. В конце укажи, какое из них ложь.
Формат:
1. ...
2. ...
3. ...
Ложь: №...
        """.strip()
        reply = await ask_gpt(prompt)
        match = re.search(r"Ложь:\s*№?([1-3])", reply, re.IGNORECASE)
        false_index = match.group(1) if match else None
        if not false_index:
            await send_message(chat_id, "⚠️ Не удалось сгенерировать утверждения. Попробуй ещё.")
            return
        statement_text = re.sub(r"Ложь:\s*№?[1-3]", "", reply, flags=re.IGNORECASE).strip()
        sessions[chat_id] = {"game": "Найди ложь", "answer": false_index}
        await send_message(chat_id, f"🕵️ Найди ложь:\n\n{statement_text}\n\nОтвет введи цифрой (1, 2 или 3).")
        return

    if session.get("game") == "Найди ложь":
        guess = text.strip()
        correct = session["answer"]
        sessions.pop(chat_id)
        win = guess == correct
        update_local_stats("Найди ложь", win)
        reply_text = "🎉 Верно! Ты нашёл ложь!" if win else f"❌ Нет, ложь была под номером {correct}. Попробуешь ещё?"
        await send_message(chat_id, reply_text, {
            "keyboard": [[{"text": "Игры 🎲"}], [{"text": "/start"}]],
            "resize_keyboard": True
        })
        return

    # ===== Продолжи историю =====
    if text == "Продолжи историю":
        prompt = """
Придумай короткое начало истории и три возможных продолжения. Варианты пронумеруй.
Формат:
Начало: ...
1. ...
2. ...
3. ...
        """.strip()
        reply = await ask_gpt(prompt)
        match = re.search(r"Начало:\s*(.+?)(?:\n|$)", reply, re.IGNORECASE)
        intro = match.group(1).strip() if match else None
        if not intro:
            await send_message(chat_id, "⚠️ Не удалось сгенерировать историю. Попробуй ещё.")
            return
        sessions[chat_id] = {"game": "Продолжи историю"}
        await send_message(chat_id, f"📖 Продолжи историю:\n\n{reply}\n\nВыбери номер продолжения (1, 2 или 3).")
        return

    if session.get("game") == "Продолжи историю":
        choice = text.strip()
        win = choice in ["1", "2", "3"]
        sessions.pop(chat_id)
        update_local_stats("Продолжи историю", win)
        reply_text = "🎉 Классное продолжение!" if win else "❌ Не похоже на вариант из списка."
        await send_message(chat_id, reply_text, {
            "keyboard": [[{"text": "Игры 🎲"}], [{"text": "/start"}]],
            "resize_keyboard": True
        })
        return

    # ===== Шарада =====
    if text == "Шарада":
        prompt = """
Придумай одну шараду из трёх частей. В конце напиши ответ.
Формат:
1) ...
2) ...
3) ...
Ответ: ...
        """.strip()
        reply = await ask_gpt(prompt)
        match = re.search(r"Ответ:\s*(.+)", reply, re.IGNORECASE)
        answer = match.group(1).strip().upper() if match else None
        if not answer:
            await send_message(chat_id, "⚠️ Не удалось сгенерировать шараду. Попробуй ещё.")
            return
        riddle_text = re.sub(r"Ответ:\s*.+", "", reply, flags=re.IGNORECASE).strip()
        sessions[chat_id] = {"game": "Шарада", "answer": answer}
        await send_message(chat_id, f"🧩 Шарада:\n\n{riddle_text}\n\nНапиши свой ответ.")
        return

    if session.get("game") == "Шарада":
        guess = text.strip().upper()
        correct = session["answer"]
        sessions.pop(chat_id)
        win = guess == correct
        update_local_stats("Шарада", win)
        reply_text = "🎉 Молодец! Правильно угадал!" if win else f"❌ Неправильно. Правильный ответ: {correct}. Попробуешь ещё?"
        await send_message(chat_id, reply_text, {
            "keyboard": [[{"text": "Игры 🎲"}], [{"text": "/start"}]],
            "resize_keyboard": True
        })
        return

    # Фоллбек
    await send_message(chat_id, "⚠️ Напиши /start, чтобы начать сначала или выбери команду из меню.")
