import os
import json
import re
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import httpx

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

TELEGRAM_SEND_MAX = 3900

# ---- Утилиты ----
async def read_raw_body(request: Request):
    return await request.body()

def chunk_string(text: str, size=TELEGRAM_SEND_MAX):
    return [text[i:i+size] for i in range(0, len(text), size)]

def safe_json(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)

async def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    body = {"chat_id": str(chat_id), "text": str(text)}
    if reply_markup:
        body["reply_markup"] = reply_markup
    if parse_mode:
        body["parse_mode"] = parse_mode
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=body
            )
        except Exception as e:
            print("send_message error:", e)

async def answer_callback_query(callback_query_id):
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id}
            )
        except Exception as e:
            print("answer_callback_query error:", e)

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
                return "Ошибка генерации: " + str(data.get("error", {}).get("message", "неизвестная ошибка"))
            return data.get("choices", [{}])[0].get("message", {}).get("content", "Ошибка генерации.")
    except Exception as e:
        print("ask_gpt error:", e)
        return "Ошибка генерации."

# ---- Игровая логика ----
async def process_game_logic(chat_id, text, first_name):
    session = sessions.get(chat_id, {})

    def update_stats(local_chat_id, game, win):
        if local_chat_id not in stats:
            stats[local_chat_id] = {}
        if game not in stats[local_chat_id]:
            stats[local_chat_id][game] = {"played": 0, "wins": 0}
        stats[local_chat_id][game]["played"] += 1
        if win:
            stats[local_chat_id][game]["wins"] += 1

    try:
        # ==== Контакт ====
        if text == "/contact":
            feed[chat_id] = True
            await send_message(chat_id, "📱 Пожалуйста, поделитесь своим номером телефона:", {
                "keyboard": [[{"text": "📤 Поделиться контактом", "request_contact": True}], [{"text": "Назад"}]],
                "resize_keyboard": True,
                "one_time_keyboard": True
            })
            return

        # ==== Feedback ====
        if text == "/feedback":
            feedback_sessions[chat_id] = True
            await send_message(chat_id, "📝 Пожалуйста, введите ваш комментарий одним сообщением:")
            return
        if feedback_sessions.get(chat_id):
            feedback_sessions.pop(chat_id, None)
            fn = sessions.get(chat_id, {}).get("firstName")
            username = sessions.get(chat_id, {}).get("username")
            await send_message(OWNER_ID, f"💬 Отзыв от {fn or 'Без имени'} (@{username or 'нет'})\nID: {chat_id}\nТекст: {text}")
            await send_message(OWNER_ID, f"/reply {chat_id}")
            await send_message(chat_id, "✅ Ваш комментарий отправлен, скоро с вами свяжутся!")
            return

        # ==== /start и Назад ====
        if text in ["/start", "Назад"]:
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

        # ==== /stats ====
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

        # ==== Игры меню ====
        if text == "Игры 🎲":
            await send_message(chat_id, "Выбери игру:", {
                "keyboard": [
                    [{"text": "Угадай слово"}, {"text": "Найди ложь"}],
                    [{"text": "Продолжи историю"}, {"text": "Шарада"}],
                    [{"text": "Назад"}, {"text": "/stats"}]
                ],
                "resize_keyboard": True
            })
            return

        # ==== Тесты по темам ====
        if text in ["История", "Математика", "Английский"]:
            topic = text
            prompt = f"""
Задай один тестовый вопрос с 4 вариантами ответа по теме "{topic}".
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
            correct_answer = match.group(1).upper() if match else None
            if not correct_answer:
                await send_message(chat_id, "⚠️ Не удалось сгенерировать вопрос. Попробуй снова.")
                return
            question_without_answer = re.sub(r"Правильный ответ:\s*[A-D]", "", reply, flags=re.I).strip()
            sessions[chat_id] = {"correctAnswer": correct_answer}
            await send_message(chat_id, f"📚 Вопрос по теме *{topic}*:\n\n{question_without_answer}", {"parse_mode": "Markdown"})
            return

        # ==== Проверка ответа на тест ====
        if session.get("correctAnswer"):
            user_answer = text.strip().upper()
            correct = session.pop("correctAnswer", None)
            if not correct:
                await send_message(chat_id, "⚠️ Ошибка: отсутствует правильный ответ. Напиши /start для новой попытки.")
                return
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

        # ==== Игры ====
        games = {
            "Угадай слово": "answer",
            "Найди ложь": "answer",
            "Продолжи историю": "game",
            "Шарада": "answer"
        }

        if text in games:
            await handle_game_start(chat_id, text)
            return

        # ==== Продолжение игры ====
        if "game" in session or "answer" in session:
            await handle_game_answer(chat_id, text)
            return

        # ==== Фоллбек ====
        await send_message(chat_id, "⚠️ Напиши /start, чтобы начать сначала или выбери команду из меню.")

    except Exception as e:
        print(f"process_game_logic error: {e}")
        await send_message(chat_id, "⚠️ Произошла ошибка в обработке твоего сообщения. Напиши /start и попробуй снова.")



# ---- Webhook обработчик ----
# ---- Webhook обработчик ----
@app.post("/api/telegram")
async def telegram_webhook(request: Request):
    raw = await request.body()
    try:
        update = json.loads(raw)
    except Exception as e:
        print("Bad JSON:", e)
        return PlainTextResponse("Bad JSON", status_code=400)

    try:
        # Определяем from_id
        from_id = str(
            update.get("message", {}).get("from", {}).get("id") or
            update.get("edited_message", {}).get("from", {}).get("id") or
            update.get("callback_query", {}).get("from", {}).get("id") or
            update.get("inline_query", {}).get("from", {}).get("id") or ""
        )
        is_owner = from_id and OWNER_ID and from_id == OWNER_ID

        # Определяем текст сообщения или данные callback
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
            reply_text = " ".join(parts[2:]) if len(parts) > 2 else ""
            if not target_id or not reply_text:
                await send_message(OWNER_ID, "⚠ Формат: /reply <chat_id> <текст>")
            else:
                await send_message(target_id, reply_text)
                await send_message(OWNER_ID, f"✅ Сообщение отправлено пользователю {target_id}")
            return PlainTextResponse("ok")

        # Пересылка JSON владельцу (если не он сам)
        if not is_owner and OWNER_ID:
            payload = f"📡 Новое событие (update_id: {update.get('update_id', '—')})\nJSON:\n{safe_json(update)}"
            for chunk in chunk_string(payload):
                await send_message(OWNER_ID, f"```json\n{chunk}\n```", parse_mode="Markdown")

        # Определяем chat_id безопасно
        chat_id = (
            update.get("message", {}).get("chat", {}).get("id") or
            update.get("edited_message", {}).get("chat", {}).get("id") or
            update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
        )
        if chat_id is None:
            print("No chat_id in update:", safe_json(update))
            return PlainTextResponse("ok")  # безопасно пропускаем апдейт без chat_id

        chat_id_str = str(chat_id)

        # Имя пользователя
        first_name = (
            update.get("message", {}).get("from", {}).get("first_name") or
            update.get("edited_message", {}).get("from", {}).get("first_name") or
            update.get("callback_query", {}).get("from", {}).get("first_name") or
            ""
        )

        # Обработка контакта
        contact = update.get("message", {}).get("contact")
        if contact:
            phone = contact.get("phone_number", "")
            first = contact.get("first_name", "")
            user_id = contact.get("user_id", "")
            await send_message(chat_id_str, f"✅ Спасибо! Я получил твой номер: +{phone}")
            if OWNER_ID:
                await send_message(OWNER_ID, f"📞 Новый контакт:\nИмя: {first}\nТелефон: +{phone}\nID: {user_id}")
            return PlainTextResponse("ok")

        # Обработка callback_query
        if "callback_query" in update:
            cqid = update["callback_query"].get("id")
            if cqid:
                await answer_callback_query(cqid)

        # Обработка текстовых сообщений и игр с защитой try/except
        text = msg_text or ""
        try:
            await process_game_logic(chat_id_str, str(text), first_name)
        except Exception as e:
            print("process_game_logic error:", e)
            await send_message(OWNER_ID, f"❌ Ошибка обработки сообщения:\n{text}\nОшибка: {e}")

        return PlainTextResponse("ok")

    except Exception as e_outer:
        print("Unexpected webhook error:", e_outer)
        if OWNER_ID:
            await send_message(OWNER_ID, f"❌ Необработанная ошибка webhook:\n{e_outer}")
        return PlainTextResponse("ok")
