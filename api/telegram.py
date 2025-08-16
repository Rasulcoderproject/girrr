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
def chunk_string(s: str, size=TELEGRAM_SEND_MAX):
    return [s[i:i+size] for i in range(0, len(s), size)]

def safe_json(obj):
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

async def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = {"chat_id": str(chat_id), "text": str(text)}
    if reply_markup:
        body["reply_markup"] = reply_markup
    if parse_mode:
        body["parse_mode"] = parse_mode
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=body)
        return r

async def answer_callback_query(callback_query_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"callback_query_id": callback_query_id})

async def ask_gpt(prompt: str):
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
            if res.status_code != 200:
                return "Ошибка генерации: " + data.get("error", {}).get("message", "неизвестная")
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print("askGPT error:", e)
        return "Ошибка генерации."

# ---- Основной обработчик ----
@app.post("/api/telegram")
async def telegram_webhook(req: Request):
    try:
        update = await req.json()
    except Exception as e:
        print("Bad JSON:", e)
        return PlainTextResponse("Bad JSON", status_code=400)

    print("📩 Получен update:", update.get("update_id"))

    # 1) Определяем владельца
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

    # /reply для владельца
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

    # 2) Пересылка JSON апдейта владельцу
    if not is_owner and OWNER_ID:
        header = f"📡 Новое событие (update_id: {update.get('update_id','—')})\nСодержимое апдейта (JSON):\n"
        body = safe_json(update)
        payload = header + body
        for chunk in chunk_string(payload, TELEGRAM_SEND_MAX):
            await send_message(OWNER_ID, f"```json\n{chunk}\n```", parse_mode="Markdown")

    # 3) Обработка игр
    chat_id = (
        update.get("message", {}).get("chat", {}).get("id")
        or update.get("edited_message", {}).get("chat", {}).get("id")
        or update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
    )

    if update.get("callback_query"):
        cqid = update["callback_query"]["id"]
        try:
            await answer_callback_query(cqid)
        except:
            pass

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
            await process_game_logic(chat_id_str, str(text or ""), first_name)
        except Exception as e:
            print("processGameLogic error:", e)

    return PlainTextResponse("ok")

# ---- Игровая логика ----
async def process_game_logic(chat_id, text, first_name):
    session = sessions.get(chat_id, {})

    def update_stats(local_id, game, win):
        if local_id not in stats:
            stats[local_id] = {}
        if game not in stats[local_id]:
            stats[local_id][game] = {"played": 0, "wins": 0}
        stats[local_id][game]["played"] += 1
        if win:
            stats[local_id][game]["wins"] += 1

    # /start
    if text == "/start" or text == "Назад":
        sessions[chat_id] = {"firstName": first_name}
        await send_message(
            chat_id,
            f"👋 Привет, {first_name or 'друг'}! Выбери тему для теста или игру:",
            reply_markup={
                "keyboard": [
                    [{"text": "История"}, {"text": "Математика"}],
                    [{"text": "Английский"}, {"text": "Игры 🎲"}],
                    [{"text": "/feedback"}, {"text": "📤 Поделиться контактом", "request_contact": True}],
                ],
                "resize_keyboard": True,
            },
        )
        return

    # /feedback
    if text == "/feedback":
        feedback_sessions[chat_id] = True
        await send_message(chat_id, "📝 Пожалуйста, введите ваш комментарий одним сообщением:")
        return

    if feedback_sessions.get(chat_id):
        del feedback_sessions[chat_id]
        fn = sessions.get(chat_id, {}).get("firstName")
        await send_message(
            OWNER_ID,
            f"💬 Отзыв от {fn or 'Без имени'} (ID: {chat_id})\nТекст: {text}"
        )
        await send_message(OWNER_ID, f"/reply {chat_id}")
        await send_message(chat_id, "✅ Ваш комментарий отправлен!")
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
        await send_message(chat_id, "Выбери игру:", reply_markup={
            "keyboard": [
                [{"text": "Угадай слово"}, {"text": "Найди ложь"}],
                [{"text": "Продолжи историю"}, {"text": "Шарада"}],
                [{"text": "Назад"}, {"text": "/stats"}],
            ],
            "resize_keyboard": True,
        })
        return

    # Тесты: История, Математика, Английский
    if text in ["История", "Математика", "Английский"]:
        prompt = f"""
Задай один тестовый вопрос с 4 вариантами ответа по теме \"{text}\".
Формат:
Вопрос: ...
A) ...
B) ...
C) ...
D) ...
Правильный ответ: ... (A-D)
""".strip()
        reply = await ask_gpt(prompt)
        match = re.search(r"Правильный ответ:\s*([A-D])", reply, re.I)
        correct = match.group(1).upper() if match else None
        if not correct:
            await send_message(chat_id, "⚠️ Не удалось сгенерировать вопрос. Попробуй снова.")
            return
        question = re.sub(r"Правильный ответ:\s*[A-D]", "", reply).strip()
        sessions[chat_id] = {"correctAnswer": correct}
        await send_message(chat_id, f"📚 Вопрос по теме *{text}*:\n\n{question}")
        return

    # Ответ на тест
    if "correctAnswer" in session:
        user_answer = text.strip().upper()
        correct = session["correctAnswer"]
        del sessions[chat_id]["correctAnswer"]
        if user_answer == correct:
            await send_message(chat_id, "✅ Правильно!")
        else:
            await send_message(chat_id, f"❌ Неправильно. Правильный ответ: {correct}")
        return

    # --- Мини-игры (Угадай слово / Найди ложь / Продолжи историю / Шарада) ---
    # Аналогично можно переписать из JS: ask_gpt(prompt), парсить ответ, класть в sessions и сверять

    await send_message(chat_id, "⚠️ Напиши /start, чтобы начать заново.")
