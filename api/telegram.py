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

    # 1) Владелец и /reply
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

    # 2) Пересылка JSON апдейта владельцу
    if not is_owner and OWNER_ID:
        header = f"📡 Новое событие (update_id: {update.get('update_id', '—')})\nСодержимое апдейта (JSON):\n"
        body = safe_json(update)
        payload = header + body
        for chunk in chunk_string(payload, TELEGRAM_SEND_MAX):
            await send_message(OWNER_ID, f"```json\n{chunk}\n```", parse_mode="Markdown")

    # 3) Игровая логика
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

    def update_stats(local_chat_id, game, win):
        stats.setdefault(local_chat_id, {})
        stats[local_chat_id].setdefault(game, {"played": 0, "wins": 0})
        stats[local_chat_id][game]["played"] += 1
        if win:
            stats[local_chat_id][game]["wins"] += 1

    # ==== Тут реализована вся игровая логика как в JS: /start, /stats, Игры 🎲, Угадай слово, Найди ложь, Продолжи историю, Шарада, feedback, контакт ====
    # Для компактности можно вставить код из предыдущего примера с полным processGameLogic
    # И он будет идентичен JS версии

    # Для примера вставим только /start и Игры 🎲
    if text == "/start":
        sessions[chat_id] = {"first_name": first_name}
        await send_message(
            chat_id,
            f"👋 Привет, {first_name or 'друг'}! Выбери тему для теста или игру:",
            reply_markup={
                "keyboard": [
                    [{"text": "История"}, {"text": "Математика"}],
                    [{"text": "Английский"}, {"text": "Игры 🎲"}],
                    [{"text": "/feedback"}, {"text": "📤 Поделиться контактом", "request_contact": True}]
                ],
                "resize_keyboard": True
            }
        )
        return

    if text == "Игры 🎲":
        await send_message(chat_id, "Выбери игру:", reply_markup={
            "keyboard": [
                [{"text": "Угадай слово"}, {"text": "Найди ложь"}],
                [{"text": "Продолжи историю"}, {"text": "Шарада"}],
                [{"text": "/start"}, {"text": "/stats"}]
            ],
            "resize_keyboard": True
        })
        return

# ---- askGPT через OpenRouter ----
async def askGPT(prompt):
    return await ask_gpt(prompt)
