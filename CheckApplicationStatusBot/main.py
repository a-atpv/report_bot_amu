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
    """Return all rows from DB_TICKETS in chunks to respect Telegram limits."""
    try:
        global ticket_service
        if ticket_service is None:
            ticket_service = get_ticket_service()
        limit = 500
        offset = 0
        total_rows = 0
        max_message_len = 4000

        # while True:
            # rows = ticket_service.fetch_tickets_by_status(limit=limit, offset=offset)
            # if not rows:
            #     break

            # total_rows += len(rows)

            # # Build message chunks under Telegram's message size limit
            # current_chunk = ""
            # for row in rows:
            #     line = str(row)
            #     if len(current_chunk) + len(line) + 1 > max_message_len:
            #         await update.message.reply_text(current_chunk)
            #         current_chunk = ""
            #     current_chunk += ("\n" if current_chunk else "") + line

            # if current_chunk:
            #     await update.message.reply_text(current_chunk)

            # offset += limit
        rows = ticket_service.fetch_tickets_by_status(limit=limit, offset=offset)
        if rows == None:
            await update.message.reply_text("No tickets found.")
        else:
            await update.message.reply_text(f"Total tickets: {rows}")
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
