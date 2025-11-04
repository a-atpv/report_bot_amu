import os
import logging
import sys
import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import TimedOut, NetworkError
from services.db_service import get_ticket_service

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN not found in environment variables. Please check your .env file."
    )

ticket_service = get_ticket_service()
ANNOUNCE_CHAT_ID_RAW = os.getenv("ANNOUNCE_CHAT_ID")
ANNOUNCE_CHAT_ID = int(ANNOUNCE_CHAT_ID_RAW) if ANNOUNCE_CHAT_ID_RAW else None
try:
    ASTANA_TZ = ZoneInfo("Asia/Almaty")  # Astana time zone
except Exception:
    ASTANA_TZ = datetime.timezone.utc
    logger = logging.getLogger(__name__)
    logger.warning("Falling back to UTC timezone; could not load Asia/Almaty")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
        f"Hello {user.first_name}! 👋\n\n"
        "Welcome to the bot! Use /help to see available commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = """
Available commands:
/start - Start the bot
/help - Show this help message
/status - Check status
/tickets - Выжимка по новым заявкам (как в расписании)
    """
    await update.message.reply_text(help_text)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send status information."""
    await update.message.reply_text("Bot is running! ✅")


def compose_new_tickets_summary() -> str:
    global ticket_service
    if ticket_service is None:
        ticket_service = get_ticket_service()
    rows = ticket_service.fetch_tickets_by_status(
        status="new", department_id=33, limit=1000, offset=0
    )
    if not rows:
        return "на данный момент есть 0 новых запросов."
    total_count = len(rows)
    per_building: dict[str, int] = {}
    for row in rows:
        building_key = row.get("building_id") if isinstance(row, dict) else None
        if building_key is None:
            building_key = "не указан"
        building_key = str(building_key)
        per_building[building_key] = per_building.get(building_key, 0) + 1
    id_to_description = ticket_service.fetch_building_descriptions()
    lines = [
        f"📊 На данный момент: {total_count} новых запросов",
        "🏢 Распределение по корпусам:",
    ]
    for b in sorted(per_building.keys()):
        readable = id_to_description.get(b, b)
        lines.append(f"• корпус {readable}: {per_building[b]} 📨")
    return "\n\n".join(lines)


async def tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return summary of NEW tickets and counts per building."""
    try:
        text = compose_new_tickets_summary()
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"/tickets failed: {e}")
        await update.message.reply_text(
            "Failed to fetch tickets. Please try again later."
        )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    await update.message.reply_text(update.message.text)


def main() -> None:
    """Start the bot."""
    # Create the Application with increased timeout settings
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(60.0)  # Increase connection timeout to 60s
        .read_timeout(60.0)  # Increase read timeout to 60s
        .write_timeout(60.0)  # Increase write timeout to 60s
        .pool_timeout(60.0)  # Increase pool timeout to 60s
        .build()
    )

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("tickets", tickets))

    # Echo handler - responds to all text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Schedule daily announcements of new tickets (Astana time)
    async def send_new_tickets_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if ANNOUNCE_CHAT_ID is None:
                logger.warning("ANNOUNCE_CHAT_ID is not set; skipping scheduled send.")
                return
            text = compose_new_tickets_summary()
            await context.bot.send_message(chat_id=ANNOUNCE_CHAT_ID, text=text)
        except Exception as e:
            logger.error(f"Scheduled send failed: {e}")

    times = [
        datetime.time(8, 30, tzinfo=ASTANA_TZ),
        datetime.time(12, 0, tzinfo=ASTANA_TZ),
        datetime.time(15, 0, tzinfo=ASTANA_TZ),
        datetime.time(17, 7, tzinfo=ASTANA_TZ),
        datetime.time(17, 25, tzinfo=ASTANA_TZ),
    ]
    if application.job_queue is None:
        logger.warning(
            "JobQueue is not available. Install PTB with job-queue extra or APScheduler to enable scheduled jobs."
        )
    else:
        for idx, t in enumerate(times):
            application.job_queue.run_daily(
                send_new_tickets_job,
                time=t,
                name=f"send_new_tickets_{idx}",
            )

    # Start the bot with error handling
    logger.info("Bot is starting...")
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
        )
    except (TimedOut, NetworkError) as e:
        logger.error(f"Connection timeout/error: {e}")

        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
        # /new


if __name__ == "__main__":
    main()
