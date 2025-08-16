import os
import json
import re
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()

# --- Память ---
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

# ---- GPT через OpenRouter ----
async def ask_gpt(prompt):
    if not OPENROUTER_API_KEY:
        return "Ошибка: нет OPENROUTER_API_KEY"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
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
            print("GPT response data:", data)  # дебаг
            choices = data.get("choices")
            if choices and len(choices) > 0:
                message = choices[0].get("message")
                if message:
                    return message.get("content", "Ошибка генерации.")
            return "Ошибка генерации."
    except Exception as e:
        print("ask_gpt error:", e)
        return "Ошибка генерации."

# ---- Webhook ----
@app.post("/api/telegram")
async def telegram_webhook(req: Request):
    raw = await read_raw_body(req)
    try:
        update = json.loads(raw)
    except Exception as e:
        print("Bad JSON:", e)
        return PlainTextResponse("Bad JSON", status_code=400)

    chat_id = (
        update.get("message", {}).get("chat", {}).get("id") or
        update.get("edited_message", {}).get("chat", {}).get("id") or
        update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
    )
    if not chat_id:
        return PlainTextResponse("ok")

    chat_id_str = str(chat_id)
    first_name = (
        update.get("message", {}).get("from", {}).get("first_name") or
        update.get("edited_message", {}).get("from", {}).get("first_name") or
        update.get("callback_query", {}).get("from", {}).get("first_name") or
        ""
    )

    text = (
        update.get("message", {}).get("text") or
        update.get("edited_message", {}).get("text") or
        update.get("callback_query", {}).get("data") or
        ""
    )

    if update.get("callback_query"):
        try:
            await answer_callback_query(update["callback_query"]["id"])
        except:
            pass

    # Обработка контактов
    if update.get("message", {}).get("contact"):
        contact = update["message"]["contact"]
        await send_message(chat_id_str, f"✅ Получен номер: +{contact['phone_number']}")
        await send_message(
            OWNER_ID,
            f"📞 Контакт:\nИмя: {contact['first_name']}\nТелефон: +{contact['phone_number']}\nID: {contact['user_id']}"
        )
        return PlainTextResponse("ok")

    # Обработка игровой логики
    try:
        await process_game_logic(chat_id_str, str(text or ""), first_name)
    except Exception as e:
        print("process_game_logic error:", e)

    return PlainTextResponse("ok")


# ---- Игровая логика ----
async def process_game_logic(chat_id, text, first_name):
    session = sessions.get(chat_id, {})

    def update_local_stats(game, win):
        if chat_id not in stats:
            stats[chat_id] = {}
        if game not in stats[chat_id]:
            stats[chat_id][game] = {"played": 0, "wins": 0}
        stats[chat_id][game]["played"] += 1
        if win:
            stats[chat_id][game]["wins"] += 1

    # --- /start ---
    if text == "/start":
        sessions[chat_id] = {"firstName": first_name}
        await send_message(chat_id, f"👋 Привет, {first_name or 'друг'}! Выбери игру или тест:", {
            "keyboard": [
                [{"text": "История"}, {"text": "Математика"}],
                [{"text": "Английский"}, {"text": "Игры 🎲"}],
                [{"text": "/feedback"}, {"text": "📤 Поделиться контактом", "request_contact": True}],
            ],
            "resize_keyboard": True
        })
        return

    # --- Игры меню ---
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

    # ===== Найди ложь =====
    if text == "Найди ложь":
        prompt = """Придумай три коротких утверждения. Два правдивых, одно ложное. В конце укажи, какое из них ложь. Формат:
1. ...
2. ...
3. ...
Ложь: №..."""
        reply = await ask_gpt(prompt)
        print("GPT reply (Найди ложь):", reply)
        match = re.search(r"(?:Ложь|Lie)[:\s\-]*#?(\d)", reply, re.IGNORECASE)
        false_index = match.group(1) if match else None
        if not false_index:
            await send_message(chat_id, "⚠️ Не удалось сгенерировать утверждения.")
            return
        statement_text = re.sub(r"(?:Ложь|Lie)[:\s\-]*#?\d", "", reply, flags=re.IGNORECASE).strip()
        sessions[chat_id] = {"game": "Найди ложь", "answer": false_index, "question_text": statement_text}
        await send_message(chat_id, f"🕵️ Найди ложь:\n\n{statement_text}\n\nОтвет введи цифрой (1, 2 или 3).")
        return

    if session.get("game") == "Найди ложь":
        guess = text.strip()
        correct = session["answer"]
        win = guess == correct
        update_local_stats("Найди ложь", win)
        reply_text = "🎉 Верно! Ты нашёл ложь!" if win else f"❌ Нет, ложь была под номером {correct}."
        sessions.pop(chat_id)
        await send_message(chat_id, reply_text)
        return

    # ===== Продолжи историю =====
    if text == "Продолжи историю":
        prompt = """Придумай короткое начало истории и три возможных продолжения. Варианты пронумеруй. Формат:
Начало: ...
1. ...
2. ...
3. ..."""
        reply = await ask_gpt(prompt)
        print("GPT reply (Продолжи историю):", reply)
        sessions[chat_id] = {"game": "Продолжи историю", "story": reply}
        await send_message(chat_id, f"📖 Продолжи историю:\n\n{reply}\n\nВыбери номер продолжения (1, 2 или 3).")
        return

    if session.get("game") == "Продолжи историю":
        choice = text.strip()
        win = choice in ["1", "2", "3"]
        update_local_stats("Продолжи историю", win)
        sessions.pop(chat_id)
        await send_message(chat_id, "🎉 Классное продолжение!" if win else "❌ Не похоже на вариант из списка.")
        return

    # ===== Шарада =====
    if text == "Шарада":
        prompt = """Придумай шараду из трёх частей. В конце напиши ответ. Формат:
1) ...
2) ...
3) ...
Ответ: ..."""
        reply = await ask_gpt(prompt)
        print("GPT reply (Шарада):", reply)
        match = re.search(r"Ответ[:\s\-]*(.+)", reply, re.IGNORECASE)
        answer = match.group(1).strip().upper() if match else None
        if not answer:
            await send_message(chat_id, "⚠️ Не удалось сгенерировать шараду.")
            return
        riddle_text = re.sub(r"Ответ[:\s\-]*.+", "", reply, flags=re.IGNORECASE).strip()
        sessions[chat_id] = {"game": "Шарада", "answer": answer, "riddle_text": riddle_text}
        await send_message(chat_id, f"🧩 Шарада:\n\n{riddle_text}\n\nНапиши свой ответ.")
        return

    if session.get("game") == "Шарада":
        guess = text.strip().upper()
        correct = session["answer"]
        win = guess == correct
        update_local_stats("Шарада", win)
        sessions.pop(chat_id)
        await send_message(chat_id, "🎉 Верно!" if win else f"❌ Неправильно. Ответ: {correct}")
        return

    # --- Фоллбек ---
    await send_message(chat_id, "⚠️ Напиши /start, чтобы начать или выбери команду из меню.")
