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


# ===================== ТЕСТ — ЗАКОММЕНТИРОВАТЬ ПОСЛЕ ПРОВЕРКИ =====================
async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    username = f"@{user.username}" if user.username else "нет ника"
    write_log("КОМАНДА /start", {
        "Кто запустил": f"{user.full_name} ({username}, ID: {user.id})",
    })
    await send_daily_message(context.bot)
# ==================================================================================


async def send_daily_message(bot: Bot) -> None:
    messages = load_messages()
    music_files = get_music_files()
    state = load_state()

    if not messages:
        logger.error("messages.txt пуст — нечего отправлять")
        write_log("ОШИБКА", {"Причина": "messages.txt пуст — нечего отправлять"})
        return

    msg_idx = state["message_index"] % len(messages)
    text = messages[msg_idx]

    try:
        chat = await bot.get_chat(TARGET_CHAT_ID)
        name = chat.full_name or chat.title or "—"
        username = f"@{chat.username}" if chat.username else "нет ника"
        recipient = f"{name} ({username}, ID: {TARGET_CHAT_ID})"
    except Exception:
        recipient = f"ID: {TARGET_CHAT_ID}"

    button_url = f"https://t.me/{BUTTON_USERNAME}?text={quote(PREFILLED_MESSAGE)}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Написать 💌", url=button_url)]])

    short_text = text if len(text) <= 80 else text[:80] + "..."

    if music_files:
        song_idx = state["song_index"] % len(music_files)
        song_path = music_files[song_idx]
        try:
            with open(song_path, "rb") as audio_file:
                await bot.send_audio(
                    chat_id=TARGET_CHAT_ID,
                    audio=audio_file,
                    caption=text,
                    reply_markup=keyboard,
                )
            logger.info("Отправлено: сообщение #%d, песня «%s»", msg_idx, song_path.name)
            write_log("ОТПРАВЛЕНО", {
                "Кому": recipient,
                "Текст": f"«{short_text}»",
                "Музыка": song_path.name,
                "Статус": "доставлено ✓",
            })
        except Exception as e:
            logger.error("Ошибка отправки: %s", e)
            write_log("ОШИБКА ОТПРАВКИ", {
                "Кому": recipient,
                "Текст": f"«{short_text}»",
                "Музыка": song_path.name,
                "Причина": str(e),
            })
            return
        state["song_index"] = (song_idx + 1) % len(music_files)
    else:
        try:
            await bot.send_message(
                chat_id=TARGET_CHAT_ID,
                text=text,
                reply_markup=keyboard,
            )
            logger.info("Отправлено: сообщение #%d (без музыки)", msg_idx)
            write_log("ОТПРАВЛЕНО", {
                "Кому": recipient,
                "Текст": f"«{short_text}»",
                "Музыка": "нет",
                "Статус": "доставлено ✓",
            })
        except Exception as e:
            logger.error("Ошибка отправки: %s", e)
            write_log("ОШИБКА ОТПРАВКИ", {
                "Кому": recipient,
                "Текст": f"«{short_text}»",
                "Причина": str(e),
            })
            return

    state["message_index"] = (msg_idx + 1) % len(messages)
    save_state(state)


async def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env")
    if not BUTTON_USERNAME:
        raise ValueError("BUTTON_USERNAME не задан в .env")

    app = Application.builder().token(BOT_TOKEN).build()
    bot = app.bot

    # ===================== ТЕСТ — ЗАКОММЕНТИРОВАТЬ ПОСЛЕ ПРОВЕРКИ =====================
    app.add_handler(CommandHandler("start", on_start))
    # ==================================================================================

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

    try:
        chat = await bot.get_chat(TARGET_CHAT_ID)
        name = chat.full_name or chat.title or "—"
        username = f"@{chat.username}" if chat.username else "нет ника"
        target_info = f"{name} ({username}, ID: {TARGET_CHAT_ID})"
    except Exception:
        target_info = f"ID: {TARGET_CHAT_ID}"

    write_log("БОТ ЗАПУЩЕН", {
        "Бот": bot_info,
        "Кому будет писать": target_info,
        "Время отправки": f"{SEND_TIME} ({TIMEZONE})",
    })

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
