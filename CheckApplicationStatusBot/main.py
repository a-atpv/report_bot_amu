import os
import json
import logging
import sys
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)
from telegram.error import TimedOut, NetworkError, TelegramError
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

# File to store tracked chat IDs
CHAT_IDS_FILE = Path("chat_ids.json")


def load_chat_ids() -> set[int]:
    """Load tracked chat IDs from file."""
    if CHAT_IDS_FILE.exists():
        try:
            with open(CHAT_IDS_FILE, "r") as f:
                data = json.load(f)
                return set(data.get("chat_ids", []))
        except Exception as e:
            logger.error(f"Failed to load chat IDs: {e}")
            return set()
    return set()


def save_chat_ids(chat_ids: set[int]) -> None:
    """Save tracked chat IDs to file."""
    try:
        with open(CHAT_IDS_FILE, "w") as f:
            json.dump({"chat_ids": list(chat_ids)}, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save chat IDs: {e}")


# Global set to track active chat IDs
tracked_chat_ids = load_chat_ids()
if tracked_chat_ids:
    logger.info(f"Loaded {len(tracked_chat_ids)} tracked chat IDs from file")
if ANNOUNCE_CHAT_ID and ANNOUNCE_CHAT_ID not in tracked_chat_ids:
    tracked_chat_ids.add(ANNOUNCE_CHAT_ID)
    save_chat_ids(tracked_chat_ids)
    logger.info(f"Added ANNOUNCE_CHAT_ID {ANNOUNCE_CHAT_ID} to tracked chats")


def track_chat_id(chat_id: int) -> None:
    """Track a chat ID if not already tracked."""
    global tracked_chat_ids
    if chat_id not in tracked_chat_ids:
        tracked_chat_ids.add(chat_id)
        save_chat_ids(tracked_chat_ids)
        logger.info(f"Added new chat ID {chat_id} to tracked chats")


try:
    ASTANA_TZ = ZoneInfo("Asia/Almaty")  # Astana time zone
except Exception:
    # Fallback to fixed UTC+6 (Almaty/Astana) instead of UTC to keep local schedule
    ASTANA_TZ = datetime.timezone(datetime.timedelta(hours=5), name="UTC+05")
    logger = logging.getLogger(__name__)
    logger.warning("Falling back to fixed UTC+06 timezone; could not load Asia/Almaty")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)
    await update.message.reply_text(
        f"Hello {user.first_name}! 👋\n\n"
        "Welcome to the bot! Use /help to see available commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)
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
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)
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
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)
    try:
        text = compose_new_tickets_summary()
        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"/tickets failed: {e}")
        await update.message.reply_text(
            "Failed to fetch tickets. Please try again later."
        )


async def track_chat_from_update(update: Update) -> None:
    """Helper function to track chat ID from any update."""
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    await track_chat_from_update(update)
    if update.message and update.message.text:
        await update.message.reply_text(update.message.text)


async def chat_member_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle chat member updates (e.g., when bot is added to a group)."""
    await track_chat_from_update(update)
    if update.chat_member:
        new_status = update.chat_member.new_chat_member.status
        if new_status in ["member", "administrator"]:
            logger.info(
                f"Bot was added to chat {update.effective_chat.id} with status: {new_status}"
            )


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

    # Track chats when bot member status changes (e.g., added to groups)
    application.add_handler(
        ChatMemberHandler(chat_member_handler, ChatMemberHandler.CHAT_MEMBER)
    )

    # Echo handler - responds to all text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Schedule daily announcements of new tickets (Astana time)
    async def send_new_tickets_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            now_astana = datetime.datetime.now(ASTANA_TZ).strftime(
                "%Y-%m-%d %H:%M:%S %Z"
            )
            logger.info(f"Executing scheduled send at {now_astana}")

            # Reload chat IDs from file in case they were updated
            global tracked_chat_ids
            tracked_chat_ids = load_chat_ids()

            if not tracked_chat_ids:
                logger.warning("No tracked chat IDs found. Skipping scheduled send.")
                return

            text = compose_new_tickets_summary()
            successful_sends = 0
            failed_sends = 0

            for (
                chat_id
            ) in (
                tracked_chat_ids.copy()
            ):  # Use copy to avoid modification during iteration
                try:
                    await context.bot.send_message(chat_id=chat_id, text=text)
                    successful_sends += 1
                    logger.info(
                        f"Successfully sent scheduled message to chat {chat_id}"
                    )
                except TelegramError as e:
                    failed_sends += 1
                    error_msg = str(e).lower()
                    # Remove chat ID if bot was removed or chat doesn't exist
                    if (
                        "chat not found" in error_msg
                        or "bot was blocked" in error_msg
                        or "unauthorized" in error_msg
                    ):
                        tracked_chat_ids.discard(chat_id)
                        save_chat_ids(tracked_chat_ids)
                        logger.warning(
                            f"Removed chat {chat_id} from tracked chats: {e}"
                        )
                    else:
                        logger.error(f"Failed to send to chat {chat_id}: {e}")
                except Exception as e:
                    failed_sends += 1
                    logger.error(f"Unexpected error sending to chat {chat_id}: {e}")

            logger.info(
                f"Scheduled send completed: {successful_sends} successful, {failed_sends} failed out of {len(tracked_chat_ids)} total chats"
            )
        except Exception as e:
            logger.error(f"Scheduled send job failed: {e}", exc_info=True)

    times = [
        datetime.time(8, 30, tzinfo=ASTANA_TZ),
        datetime.time(12, 0, tzinfo=ASTANA_TZ),
        datetime.time(15, 0, tzinfo=ASTANA_TZ),
        datetime.time(9, 10, tzinfo=ASTANA_TZ),
        datetime.time(17, 25, tzinfo=ASTANA_TZ),
    ]

    # Check if job_queue is available
    if application.job_queue is None:
        logger.error(
            "JobQueue is not available. Install PTB with job-queue extra: "
            "pip install 'python-telegram-bot[job-queue]'"
        )
    else:
        logger.info(f"JobQueue is available. Scheduling {len(times)} daily jobs...")
        for idx, t in enumerate(times):
            try:
                logger.info(
                    f"Scheduling job 'send_new_tickets_{idx}' for {t.strftime('%H:%M')} {t.tzname()}"
                )
                application.job_queue.run_daily(
                    send_new_tickets_job,
                    time=t,
                    name=f"send_new_tickets_{idx}",
                )
                logger.info(f"Successfully scheduled job 'send_new_tickets_{idx}'")
            except Exception as e:
                logger.error(
                    f"Failed to schedule job 'send_new_tickets_{idx}': {e}",
                    exc_info=True,
                )

    # Start the bot with error handling
    logger.info("Bot is starting...")
    logger.info(f"ANNOUNCE_CHAT_ID: {ANNOUNCE_CHAT_ID}")
    logger.info(f"Tracked chat IDs: {len(tracked_chat_ids)} chats")
    logger.info(f"Timezone: {ASTANA_TZ}")

    # Verify job queue before starting
    if application.job_queue is not None:
        logger.info("Job queue is ready. Jobs should run at scheduled times.")
    else:
        logger.error("Job queue is NOT available. Scheduled messages will not work!")

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
