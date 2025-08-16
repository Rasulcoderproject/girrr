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
            if res.status_code != 200:
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
            feedback_sessions.pop(chat_id)
            fn = session.get("firstName")
            username = session.get("username")
            await send_message(OWNER_ID, f"💬 Отзыв от {fn or 'Без имени'} (@{username or 'нет'})\nID: {chat_id}\nТекст: {text}")
            await send_message(OWNER_ID, f"/reply {chat_id}")
            await send_message(chat_id, "✅ Ваш комментарий отправлен, скоро с вами свяжутся!")
            return

        # ==== /start / Назад ====
        if text in ["/start"]:
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
        
        
        
        if text in ["Назад"]:
            sessions[chat_id] = {"firstName": first_name}
            await send_message(chat_id, f"{first_name or 'друг'}!, Выбери тему для теста или игру:", {
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

        # ==== Игры ====
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
            correct = session.pop("correctAnswer").upper()
            win = user_answer == correct
            update_stats(chat_id, "Тест", win)
            reply_text = "✅ Правильно! Хочешь ещё вопрос?" if win else f"❌ Неправильно. Правильный ответ: {correct}\nПопробуешь ещё?"
            await send_message(chat_id, reply_text, {
                "keyboard": [
                    [{"text": "История"}, {"text": "Математика"}],
                    [{"text": "Английский"}, {"text": "Игры 🎲"}]
                ],
                "resize_keyboard": True
            })
            return

        # ==== Общий обработчик игр ====
        games_prompts = {
            "Угадай слово": """
Загадай одно существительное. Опиши его так, чтобы пользователь попытался угадать. В конце добавь: "Загаданное слово: ...".
Формат:
Описание: ...
Загаданное слово: ...
            """,
            "Найди ложь": """
Придумай три коротких утверждения на любые темы. Два из них правдивые, одно ложное. В конце укажи, какое из них ложь (например: "Ложь: №2").
Формат:
1. ...
2. ...
3. ...
Ложь: №...
            """,
            "Продолжи историю": """
Придумай короткое начало истории и три возможных продолжения. Варианты продолжения пронумеруй.
Формат:
Начало: ...
1. ...
2. ...
3. ...
            """,
            "Шарада": """
Придумай одну шараду (загадку), которая состоит из трех частей, каждая часть даёт подсказку, чтобы угадать слово. В конце напиши ответ.
Формат:
1) ...
2) ...
3) ...
Ответ: ...
            """
        }

        if text in games_prompts:
            reply = await ask_gpt(games_prompts[text])
            answer, description = None, reply
            if text == "Угадай слово":
                match = re.search(r"Загаданное слово:\s*(.+)", reply, re.I)
                answer = match.group(1).strip().upper() if match else None
                description = re.sub(r"Загаданное слово:\s*.+", "", reply, flags=re.I).replace("Описание:", "").strip()
                if not answer:
                    await send_message(chat_id, "⚠️ Не удалось сгенерировать слово. Попробуй ещё.")
                    return
                sessions[chat_id] = {"game": text, "answer": answer}
                await send_message(chat_id, f"🧠 {text}:\n\n{description}")
                return
            elif text == "Найди ложь":
                match = re.search(r"Ложь:\s*№?([1-3])", reply, re.I)
                answer = match.group(1) if match else None
                description = re.sub(r"Ложь:\s*№?[1-3]", "", reply, flags=re.I).strip()
                if not answer:
                    await send_message(chat_id, "⚠️ Не удалось сгенерировать утверждения. Попробуй ещё.")
                    return
                sessions[chat_id] = {"game": text, "answer": answer}
                await send_message(chat_id, f"🕵️ {text}:\n\n{description}\n\nОтвет введи цифрой (1, 2 или 3).")
                return
            elif text == "Продолжи историю":
                sessions[chat_id] = {"game": text, "answer": None}
                await send_message(chat_id, f"📖 {text}:\n\n{reply}\n\nВыбери номер продолжения (1, 2 или 3).")
                return
            elif text == "Шарада":
                match = re.search(r"Ответ:\s*(.+)", reply, re.I)
                answer = match.group(1).strip().upper() if match else None
                description = re.sub(r"Ответ:\s*.+", "", reply, flags=re.I).strip()
                if not answer:
                    await send_message(chat_id, "⚠️ Не удалось сгенерировать шараду. Попробуй ещё.")
                    return
                sessions[chat_id] = {"game": text, "answer": answer}
                await send_message(chat_id, f"🧩 {text}:\n\n{description}\n\nНапиши свой ответ.")
                return

        # ==== Ответ на активную игру ====
        if session.get("game"):
            game = session.get("game")
            correct = session.get("answer")
            user_input = text.strip().upper()
            win = False
            if game in ["Продолжи историю"]:
                # Любой выбор 1-3 считается успешным
                win = user_input in ["1", "2", "3"]
            else:
                win = correct and user_input == correct.upper()
            update_stats(chat_id, game, win)
            sessions.pop(chat_id, None)
            reply_text = f"🎉 Верно!" if win else f"❌ Неправильно. Было: {correct}" if correct else "❌ Попробуй снова."
            await send_message(chat_id, reply_text, {
                "keyboard": [[{"text": "Игры 🎲"}], [{"text": "/stats"}], [{"text": "Назад"}]],
                "resize_keyboard": True
            })
            return

        # ==== Фоллбек ====
        await send_message(chat_id, "⚠️ Напиши /start, чтобы начать сначала или выбери команду из меню.")

    except Exception as e:
        print("process_game_logic error:", e)
        await send_message(chat_id, "⚠️ Произошла ошибка. Попробуй снова.")

# ---- Webhook обработчик ----
@app.post("/api/telegram")
async def telegram_webhook(request: Request):
    raw = await read_raw_body(request)
    try:
        update = json.loads(raw)
    except Exception as e:
        print("Bad JSON:", e)
        return PlainTextResponse("Bad JSON", status_code=400)

    from_id = str(
        update.get("message", {}).get("from", {}).get("id") or
        update.get("edited_message", {}).get("from", {}).get("id") or
        update.get("callback_query", {}).get("from", {}).get("id") or
        update.get("inline_query", {}).get("from", {}).get("id") or ""
    )
    is_owner = from_id and OWNER_ID and from_id == OWNER_ID

    msg_text = (
        update.get("message", {}).get("text") or
        update.get("edited_message", {}).get("text") or
        update.get("callback_query", {}).get("data") or
        update.get("inline_query", {}).get("query") or ""
    )

    # ---- /reply для владельца ----
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

    # ---- Пересылка JSON владельцу ----
    if not is_owner and OWNER_ID:
        header = f"📡 Новое событие (update_id: {update.get('update_id', '—')})\nСодержимое апдейта (JSON):\n"
        payload = header + safe_json(update)
        for chunk in chunk_string(payload):
            await send_message(OWNER_ID, f"```json\n{chunk}\n```", parse_mode="Markdown")

    chat_id = (
        update.get("message", {}).get("chat", {}).get("id") or
        update.get("edited_message", {}).get("chat", {}).get("id") or
        update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")
    )

    # ---- CallbackQuery ----
    if update.get("callback_query"):
        cqid = update["callback_query"].get("id")
        if cqid:
            await answer_callback_query(cqid)

    if chat_id:
        chat_id_str = str(chat_id)
        first_name = (
            update.get("message", {}).get("from", {}).get("first_name") or
            update.get("edited_message", {}).get("from", {}).get("first_name") or
            update.get("callback_query", {}).get("from", {}).get("first_name") or
            ""
        )

        # Контакт
        contact = update.get("message", {}).get("contact")
        if contact:
            await send_message(chat_id_str, f"✅ Спасибо! Я получил твой номер: +{contact.get('phone_number')}")
            await send_message(
                OWNER_ID,
                f"📞 Новый контакт:\nИмя: {contact.get('first_name')}\nТелефон: +{contact.get('phone_number')}\nID: {contact.get('user_id')}"
            )
            return PlainTextResponse("ok")

        text = msg_text
        await process_game_logic(chat_id_str, str(text or ""), first_name)

    return PlainTextResponse("ok")
