import os
import logging
import sys
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
/tickets - List all tickets from DB_TICKETS
    """
    await update.message.reply_text(help_text)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send status information."""
    await update.message.reply_text("Bot is running! ✅")


async def tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return summary of NEW tickets and counts per building."""
    try:
        global ticket_service
        if ticket_service is None:
            ticket_service = get_ticket_service()
        # Fetch only NEW tickets for department 33
        rows = ticket_service.fetch_tickets_by_status(
            status="new", department_id=33, limit=1000, offset=0
        )

        if not rows:
            await update.message.reply_text("на данный момент есть 0 новых запросов.")
            return

        total_count = len(rows)

        # Group by building id/name
        per_building: dict[str, int] = {}
        for row in rows:
            building_key = row.get("building_id") if isinstance(row, dict) else None
            if building_key is None:
                building_key = "не указан"
            building_key = str(building_key)
            per_building[building_key] = per_building.get(building_key, 0) + 1

        # Map building ids to human-readable descriptions from cat_building
        id_to_description = ticket_service.fetch_building_descriptions()

        # Build message
        lines = [f"на данный момент есть {total_count} новых запросов."]
        for b in sorted(per_building.keys()):
            readable = id_to_description.get(b, b)
            lines.append(f"в корпусе {readable}  {per_building[b]} новых запросов")

        await update.message.reply_text("\n\n".join(lines))
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
