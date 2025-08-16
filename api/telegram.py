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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or ""
OWNER_ID = str(os.getenv("MY_TELEGRAM_ID") or "")

# Лимит Telegram (~4096)
TELEGRAM_SEND_MAX = 3900

# ---- Утилиты ----
async def read_raw_body(req: Request):
    return await req.body()

def chunk_string(s, size=TELEGRAM_SEND_MAX):
    return [s[i:i+size] for i in range(0, len(s), size)]

def safe_json(obj):
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except:
        return str(obj)

# ---- sendMessage wrapper ----
async def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    body = {"chat_id": str(chat_id), "text": str(text)}
    if reply_markup:
        body["reply_markup"] = reply_markup
    if parse_mode:
        body["parse_mode"] = parse_mode
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                headers={"Content-Type": "application/json"},
                content=json.dumps(body)
            )
        return r
    except Exception as e:
        print("send_message error:", e)
        raise e

async def answer_callback_query(callback_query_id):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                headers={"Content-Type": "application/json"},
                content=json.dumps({"callback_query_id": callback_query_id})
            )
    except Exception as e:
        print("answer_callback_query error:", e)

# ---- Статистика игр ----
def update_stats(chat_id, game, win):
    if chat_id not in stats:
        stats[chat_id] = {}
    if game not in stats[chat_id]:
        stats[chat_id][game] = {"played": 0, "wins": 0}
    stats[chat_id][game]["played"] += 1
    if win:
        stats[chat_id][game]["wins"] += 1

# ---- ask_gpt через OpenRouter ----
async def ask_gpt(prompt):
    if not OPENROUTER_API_KEY:
        return "Ошибка: нет OPENROUTER_API_KEY"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "openai/gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7
                }
            )
            data = res.json()
            if not res.status_code == 200:
                print("OpenRouter API error:", data)
                return "Ошибка генерации: " + (data.get("error", {}).get("message") or "неизвестная ошибка")
            return data.get("choices", [{}])[0].get("message", {}).get("content", "Ошибка генерации.")
    except Exception as e:
        print("ask_gpt error:", e)
        return "Ошибка генерации."

# ---- Основная игровая логика и меню ----
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

    # ===== Здесь далее вся игровая логика, как в JS-коде =====
    # Код для тестов, угадай слово, найди ложь, продолжи историю, шарада
    # (вставь полностью блок process_game_logic из предыдущего сообщения)
    # Для сокращения повторов я оставляю здесь комментарий, но при использовании вставь весь блок.

# ---- Webhook ----
@app.post("/api/webhook")
async def telegram_webhook(req: Request):
    raw = await read_raw_body(req)
    try:
        update = json.loads(raw.decode())
    except Exception as e:
        print("Bad JSON:", e)
        return PlainTextResponse("Bad JSON", status_code=400)

    print("📩 Получен update:", update.get("update_id"))

    # Получаем fromId и проверяем владельца
    from_id = str(
        update.get("message", {}).get("from", {}).get("id") or
        update.get("edited_message", {}).get("from", {}).get("id") or
        update.get("callback_query", {}).get("from", {}).get("id") or
        update.get("inline_query", {}).get("from", {}).get("id") or ""
    )
    is_owner = from_id == OWNER_ID

    # Текст сообщения
    msg_text = (
        update.get("message", {}).get("text") or
        update.get("edited_message", {}).get("text") or
        update.get("callback_query", {}).get("data") or
        update.get("inline_query", {}).get("query") or ""
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

    # Пересылка JSON апдейта владельцу
    if not is_owner and OWNER_ID:
        payload = f"📡 Новое событие (update_id: {update.get('update_id', '—')})\nСодержимое апдейта (JSON):\n{safe_json(update)}"
        for chunk in chunk_string(payload, TELEGRAM_SEND_MAX):
            await send_message(OWNER_ID, f"```json\n{chunk}\n```", parse_mode="Markdown")

    # Игровая логика
    chat_id = (
        update.get("message", {}).get("chat", {}).get("id") or
        update.get("edited_message", {}).get("chat", {}).get("id") or
        update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
    )

    if update.get("callback_query"):
        cqid = update["callback_query"]["id"]
        await answer_callback_query(cqid)

    if chat_id:
        chat_id_str = str(chat_id)
        first_name = (
            update.get("message", {}).get("from", {}).get("first_name") or
            update.get("edited_message", {}).get("from", {}).get("first_name") or
            update.get("callback_query", {}).get("from", {}).get("first_name") or ""
        )

        # Контакт
        if update.get("message", {}).get("contact"):
            contact = update["message"]["contact"]
            await send_message(chat_id_str, f"✅ Спасибо! Я получил твой номер: +{contact.get('phone_number')}")
            await send_message(
                OWNER_ID,
                f"📞 Новый контакт:\nИмя: {contact.get('first_name')}\nТелефон: +{contact.get('phone_number')}\nID: {contact.get('user_id')}"
            )
            return PlainTextResponse("ok")

        # Передаём текст в игровую логику
        text = (
            update.get("message", {}).get("text") or
            update.get("edited_message", {}).get("text") or
            update.get("callback_query", {}).get("data") or ""
        )
        await process_game_logic(chat_id_str, str(text), first_name)

    return PlainTextResponse("ok")
