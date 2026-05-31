import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TARGET_CHAT_ID = int(os.getenv("TARGET_CHAT_ID"))
SEND_TIME = os.getenv("SEND_TIME", "09:00")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
BUTTON_USERNAME = os.getenv("BUTTON_USERNAME")
PREFILLED_MESSAGE = os.getenv("PREFILLED_MESSAGE", "")

MESSAGES_FILE = Path("messages.txt")
MUSIC_DIR = Path("music")
STATE_FILE = Path("state.json")
LOG_FILE = Path("logs.txt")
USERS_FILE = Path("users.json")

AUDIO_EXTENSIONS = {".mp3", ".ogg", ".m4a", ".flac", ".wav", ".opus"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def write_log(event: str, details: dict) -> None:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines = [f"\n{'─' * 48}", f"  {now}  |  {event}"]
    for key, value in details.items():
        lines.append(f"  {key}: {value}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def load_messages() -> list[str]:
    lines = MESSAGES_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def get_music_files() -> list[Path]:
    if not MUSIC_DIR.exists():
        return []
    return sorted(f for f in MUSIC_DIR.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"message_index": 0, "song_index": 0}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_users() -> set[int]:
    if USERS_FILE.exists():
        return set(json.loads(USERS_FILE.read_text(encoding="utf-8")))
    return set()


def save_users(users: set[int]) -> None:
    USERS_FILE.write_text(json.dumps(list(users), ensure_ascii=False), encoding="utf-8")


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    username = f"@{user.username}" if user.username else "нет ника"

    users = load_users()
    is_new = user.id not in users
    users.add(user.id)
    save_users(users)

    write_log("КОМАНДА /start", {
        "Кто запустил": f"{user.full_name} ({username}, ID: {user.id})",
        "Статус": "новый пользователь" if is_new else "уже зарегистрирован",
    })

    await update.message.reply_text("Ты подписан на ежедневные сообщения 💌")


async def send_daily_message(bot: Bot) -> None:
    messages = load_messages()
    music_files = get_music_files()
    state = load_state()
    users = load_users()

    if not messages:
        logger.error("messages.txt пуст — нечего отправлять")
        write_log("ОШИБКА", {"Причина": "messages.txt пуст — нечего отправлять"})
        return

    if not users:
        logger.warning("Нет зарегистрированных пользователей — некому отправлять")
        write_log("ПРЕДУПРЕЖДЕНИЕ", {"Причина": "Нет зарегистрированных пользователей"})
        return

    msg_idx = state["message_index"] % len(messages)
    text = messages[msg_idx]

    button_url = f"https://t.me/{BUTTON_USERNAME}?text={quote(PREFILLED_MESSAGE)}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Написать 💌", url=button_url)]])

    short_text = text if len(text) <= 80 else text[:80] + "..."
    sent_count = 0
    error_count = 0

    if music_files:
        song_idx = state["song_index"] % len(music_files)
        song_path = music_files[song_idx]
        file_id = None

        for user_id in users:
            try:
                if file_id:
                    await bot.send_audio(
                        chat_id=user_id,
                        audio=file_id,
                        caption=text,
                        reply_markup=keyboard,
                    )
                else:
                    with open(song_path, "rb") as audio_file:
                        msg = await bot.send_audio(
                            chat_id=user_id,
                            audio=audio_file,
                            caption=text,
                            reply_markup=keyboard,
                        )
                    file_id = msg.audio.file_id
                sent_count += 1
                logger.info("Отправлено пользователю %d: сообщение #%d, песня «%s»", user_id, msg_idx, song_path.name)
            except Exception as e:
                error_count += 1
                logger.error("Ошибка отправки пользователю %d: %s", user_id, e)

        write_log("РАССЫЛКА ЗАВЕРШЕНА", {
            "Текст": f"«{short_text}»",
            "Музыка": song_path.name,
            "Отправлено": f"{sent_count} из {len(users)}",
            "Ошибок": error_count,
        })
        state["song_index"] = (song_idx + 1) % len(music_files)
    else:
        for user_id in users:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=keyboard,
                )
                sent_count += 1
                logger.info("Отправлено пользователю %d: сообщение #%d", user_id, msg_idx)
            except Exception as e:
                error_count += 1
                logger.error("Ошибка отправки пользователю %d: %s", user_id, e)

        write_log("РАССЫЛКА ЗАВЕРШЕНА", {
            "Текст": f"«{short_text}»",
            "Музыка": "нет",
            "Отправлено": f"{sent_count} из {len(users)}",
            "Ошибок": error_count,
        })

    state["message_index"] = (msg_idx + 1) % len(messages)
    save_state(state)


async def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")
    if not BUTTON_USERNAME:
        raise ValueError("BUTTON_USERNAME не задан в .env")

    # Авто-регистрация основного получателя
    users = load_users()
    users.add(TARGET_CHAT_ID)
    save_users(users)

    app = Application.builder().token(BOT_TOKEN).build()
    bot = app.bot

    app.add_handler(CommandHandler("start", on_start))

    hour, minute = map(int, SEND_TIME.split(":"))

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        send_daily_message,
        trigger="cron",
        hour=hour,
        minute=minute,
        args=[bot],
    )
    scheduler.start()

    logger.info("Бот запущен. Ежедневная отправка в %s (%s)", SEND_TIME, TIMEZONE)

    try:
        me = await bot.get_me()
        bot_info = f"@{me.username} ({me.full_name})"
    except Exception:
        bot_info = "неизвестно"

    write_log("БОТ ЗАПУЩЕН", {
        "Бот": bot_info,
        "Зарегистрированных пользователей": len(load_users()),
        "Время отправки": f"{SEND_TIME} ({TIMEZONE})",
    })

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
