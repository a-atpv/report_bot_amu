import os
import json
import logging
import sys
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    CallbackQueryHandler,
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
    first_name = user.first_name if user and user.first_name else "гость"
    status_text = compose_bot_status_text()
    await update.message.reply_text(
        f"Добрый день, {first_name}! 👋\n\n{status_text}",
        reply_markup=get_main_reply_keyboard(),
    )
    # Also show inline keyboard for callback-based actions
    await update.message.reply_text(
        "Быстрые действия:", reply_markup=get_main_inline_keyboard()
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
/new - Список всех новых заявок департамента 33
    """
    await update.message.reply_text(help_text, reply_markup=get_main_reply_keyboard())


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Bottom reply keyboard with three quick-action buttons."""
    keyboard = [
        [
            KeyboardButton(text="Новые"),
            KeyboardButton(text="В работе"),
            KeyboardButton(text="Статус"),
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
    )


def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard with callback-based actions."""
    keyboard = [
        [
            InlineKeyboardButton(text="Новые", callback_data="menu:new"),
            InlineKeyboardButton(text="В работе", callback_data="menu:taken"),
            InlineKeyboardButton(text="Статус", callback_data="menu:status"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send status information."""
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)
    await update.message.reply_text(compose_bot_status_text())


def compose_bot_status_text() -> str:
    """Return short health status that we can reuse in /start and /status."""
    global ticket_service

    issues: list[str] = []

    # Lazy-init the ticket service to detect obvious failures early.
    if ticket_service is None:
        try:
            ticket_service = get_ticket_service()
        except Exception:
            issues.append("⚠️ Не удалось подключиться к сервису заявок")

    if issues:
        return "\n".join(["Статус бота:", *issues])

    return "Статус бота:\n✅ Все работает штатно"


def compose_new_tickets_summary() -> str:
    """
    Compose a summary of tickets (counts only, no individual ticket details).
    Returns summary grouped by building and specialist.
    """
    global ticket_service
    if ticket_service is None:
        ticket_service = get_ticket_service()

    # Fetch available tickets (unassigned/new tickets ready to be worked on)
    # Try "available" status first, fallback to "new" if "available" returns empty
    new_rows = ticket_service.fetch_tickets_by_status(
        status="available", department_id=33, limit=1000, offset=0
    )
    # If "available" returns no results, try "new" status
    if not new_rows:
        new_rows = ticket_service.fetch_tickets_by_status(
            status="new", department_id=33, limit=1000, offset=0
        )

    # Fetch taken tickets (status="taken" means in progress)
    taken_rows = ticket_service.fetch_tickets_by_status(
        status="taken", department_id=33, limit=1000, offset=0
    )

    lines = []

    # Header
    lines.append("📬 *Статистика заявок*")

    total_count = len(new_rows) if new_rows else 0
    lines.append(f"📊 *Всего новых:* {total_count}")

    if new_rows:
        per_building: dict[str, int] = {}
        for ticket in new_rows:
            # Only count, don't include individual ticket details
            building_key = ticket.building_id
            if building_key is None:
                building_key = "не указан"
            building_key = str(building_key)
            per_building[building_key] = per_building.get(building_key, 0) + 1

        id_to_description = ticket_service.fetch_building_descriptions()
        lines.append("🏠 *По адресам:*")
        lines.append("")

        # Separate "Другое" (unassigned/unknown) from regular buildings
        other_count = per_building.get("не указан", 0)
        regular_buildings = {k: v for k, v in per_building.items() if k != "не указан"}

        # Sort regular buildings by description
        sorted_buildings = sorted(
            regular_buildings.items(), key=lambda x: id_to_description.get(x[0], x[0])
        )

        for building_id, count in sorted_buildings:
            readable = id_to_description.get(building_id, building_id)
            lines.append(f"🏢 {readable} — *{count}*")

        if other_count > 0:
            lines.append(f"🏗 Другое — *{other_count}*")

    # Taken tickets section
    if taken_rows:
        lines.append("")
        lines.append("")
        lines.append("⚙️ *В работе:*")
        lines.append("")

        # Group taken tickets by specialist_id and building_id
        per_specialist_building: dict[tuple, int] = {}
        specialist_ids = set()

        for ticket in taken_rows:
            specialist_id = ticket.specialist_id
            building_id = ticket.building_id

            if specialist_id is None:
                continue

            specialist_ids.add(specialist_id)
            building_key = building_id if building_id is not None else "не указан"
            key = (specialist_id, building_key)
            per_specialist_building[key] = per_specialist_building.get(key, 0) + 1

        # Fetch user information for all specialists
        if specialist_ids:
            users_dict = ticket_service.fetch_users_by_ids(list(specialist_ids))
            id_to_description = ticket_service.fetch_building_descriptions()

            # Sort by specialist_id and building_id for consistent output
            for (spec_id, building_id), count in sorted(
                per_specialist_building.items()
            ):
                user = users_dict.get(spec_id)
                full_name = user.full_name if user else f"ID {spec_id}"

                building_desc = id_to_description.get(
                    str(building_id), str(building_id)
                )
                lines.append(f"👷‍♂️ {full_name} — ({building_desc}) — *{count}*")

    return "\n".join(lines)


async def tickets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return summary of tickets (counts grouped by building/specialist), not individual tickets."""
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)
    try:
        text = compose_new_tickets_summary()
        if not text or not text.strip():
            await update.message.reply_text("No tickets found.")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"/tickets failed: {e}", exc_info=True)
        await update.message.reply_text(
            "Failed to fetch tickets summary. Please try again later."
        )


def compose_new_tickets_list() -> str:

    global ticket_service
    if ticket_service is None:
        ticket_service = get_ticket_service()

    new_rows = ticket_service.fetch_tickets_by_status(
        status="new", department_id=33, limit=1000, offset=0
    )

    if not new_rows:
        return "всего новых заявок: 0"

    user_ids = set()

    for ticket in new_rows:
        user_id = ticket.user_id

        if user_id is not None:
            user_ids.add(user_id)

    users_dict = ticket_service.fetch_users_by_ids(list(user_ids))
    buildings_dict = ticket_service.fetch_building_descriptions()

    # Fetch categories and subcategories for department 33
    categories = ticket_service.fetch_categories_by_department_id(department_id=33)
    categories_dict = {cat.id: cat.name_ru or f"ID {cat.id}" for cat in categories}

    # Fetch all subcategories for all categories
    subcategories_dict = {}
    for category in categories:
        subcategories = ticket_service.fetch_subcategories_by_category_id(category.id)
        for subcat in subcategories:
            subcategories_dict[subcat.id] = subcat.name_ru or f"ID {subcat.id}"

    def esc(value: str) -> str:
        s = str(value)
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return s

    lines = []
    lines.append(f"всего новых заявок: {len(new_rows)}")
    lines.append("")

    # Format each ticket as a quoted block
    for ticket in new_rows:
        ticket_id = ticket.id
        user_id = ticket.user_id
        building_id = ticket.building_id
        phone = ticket.title or ""
        description = ticket.description or "не указано"
        cabinet = ticket.cabinet or "не указан"

        # Get applicant name
        if user_id:
            user = users_dict.get(user_id)
            if user:
                applicant_name = user.full_name
            else:
                applicant_name = f"ID {user_id}"
        else:
            applicant_name = "не указан"

        # Get category name
        if ticket.category_id:
            category_name = categories_dict.get(
                ticket.category_id, f"ID {ticket.category_id}"
            )
        else:
            category_name = "не указана"

        # Get subcategory name
        if ticket.subcategory_id:
            subcategory_name = subcategories_dict.get(
                ticket.subcategory_id, f"ID {ticket.subcategory_id}"
            )
        else:
            subcategory_name = "не указана"

        # Get building name
        if building_id:
            building_name = buildings_dict.get(str(building_id), str(building_id))
        else:
            building_name = "не указан"

        ticket_lines = [
            f"Заявка №{esc(ticket_id)}",
            f"Заявитель: {esc(applicant_name)}",
            f"Категория: {esc(category_name)}",
            f"Подкатегория: {esc(subcategory_name)}",
            f"Контакты: {esc(phone)}",
            f"Описание: {esc(description)}",
            f"корпус: {esc(building_name)}",
            f"Кабинет: {esc(cabinet)}",
        ]

        # Wrap each ticket into HTML blockquote for Telegram
        lines.append("<blockquote>" + "\n".join(ticket_lines) + "</blockquote>")
        lines.append("")

    return "\n".join(lines)


def compose_taken_tickets_list() -> str:

    global ticket_service
    if ticket_service is None:
        ticket_service = get_ticket_service()

    taken_rows = ticket_service.fetch_tickets_by_status(
        status="taken", department_id=33, limit=1000, offset=0
    )

    if not taken_rows:
        return "всего заявок в работе: 0"

    user_ids = set()
    specialist_ids = set()

    for ticket in taken_rows:
        user_id = ticket.user_id
        specialist_id = ticket.specialist_id

        if user_id is not None:
            user_ids.add(user_id)
        if specialist_id is not None:
            specialist_ids.add(specialist_id)

    users_dict = ticket_service.fetch_users_by_ids(list(user_ids | specialist_ids))

    buildings_dict = ticket_service.fetch_building_descriptions()

    # Fetch categories and subcategories for department 33
    categories = ticket_service.fetch_categories_by_department_id(department_id=33)
    categories_dict = {cat.id: cat.name_ru or f"ID {cat.id}" for cat in categories}

    # Fetch all subcategories for all categories
    subcategories_dict = {}
    for category in categories:
        subcategories = ticket_service.fetch_subcategories_by_category_id(category.id)
        for subcat in subcategories:
            subcategories_dict[subcat.id] = subcat.name_ru or f"ID {subcat.id}"

    def esc(value: str) -> str:
        s = str(value)
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return s

    lines = []
    lines.append(f"всего заявок в работе: {len(taken_rows)}")
    lines.append("")

    # Format each ticket as a quoted block
    for ticket in taken_rows:
        ticket_id = ticket.id
        user_id = ticket.user_id
        specialist_id = ticket.specialist_id
        building_id = ticket.building_id
        phone = ticket.title or ""
        description = ticket.description or "не указано"
        cabinet = ticket.cabinet or "не указан"

        # Get applicant name
        if user_id:
            user = users_dict.get(user_id)
            if user:
                applicant_name = user.full_name
            else:
                applicant_name = f"ID {user_id}"
        else:
            applicant_name = "не указан"

        specialist_name = (
            users_dict.get(specialist_id).full_name if specialist_id else "не указан"
        )

        # Get category name
        if ticket.category_id:
            category_name = categories_dict.get(
                ticket.category_id, f"ID {ticket.category_id}"
            )
        else:
            category_name = "не указана"

        # Get subcategory name
        if ticket.subcategory_id:
            subcategory_name = subcategories_dict.get(
                ticket.subcategory_id, f"ID {ticket.subcategory_id}"
            )
        else:
            subcategory_name = "не указана"

        # Get building name
        if building_id:
            building_name = buildings_dict.get(str(building_id), str(building_id))
        else:
            building_name = "не указан"

        ticket_lines = [
            f"Заявка №{esc(ticket_id)}",
            f"Заявитель: {esc(applicant_name)}",
            f"Категория: {esc(category_name)}",
            f"Подкатегория: {esc(subcategory_name)}",
            f"Контакты: {esc(phone)}",
            f"Описание: {esc(description)}",
            f"корпус: {esc(building_name)}",
            f"Кабинет: {esc(cabinet)}",
            f"Исполнитель: {esc(specialist_name)}",
        ]

        # Wrap each ticket into HTML blockquote for Telegram
        lines.append("<blockquote>" + "\n".join(ticket_lines) + "</blockquote>")
        lines.append("")

    return "\n".join(lines)


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return detailed list of all new tickets in department 33."""
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)
    try:
        text = compose_new_tickets_list()
        if not text or not text.strip():
            await update.message.reply_text("всего новых заявок: 0")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"/new failed: {e}", exc_info=True)
        await update.message.reply_text(
            "Не удалось получить список новых заявок. Попробуйте позже."
        )


async def taken_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return detailed list of all taken tickets in department 33."""
    chat = update.effective_chat
    if chat:
        track_chat_id(chat.id)
    try:
        text = compose_taken_tickets_list()
        if not text or not text.strip():
            await update.message.reply_text("всего заявок в работе: 0")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"/taken failed: {e}", exc_info=True)
        await update.message.reply_text(
            "Не удалось получить список заявок в работе. Попробуйте позже."
        )


async def menu_buttons_router(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:

    await track_chat_from_update(update)
    text = update.message.text or ""
    if text == "Новые":
        await new_command(update, context)
    elif text == "В работе":
        await taken_command(update, context)
    elif text == "Статус":
        # Map to tickets summary (alias requested as /ticket)
        await tickets(update, context)
    else:
        # Fallback to echo to preserve previous behavior
        await echo(update, context)


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


async def on_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard callback queries for the main menu."""
    query = update.callback_query
    if not query:
        return
    await track_chat_from_update(update)
    await query.answer()
    data = (query.data or "").strip()

    if data == "menu:new":
        try:
            text = compose_new_tickets_list()
            msg_text = text if text and text.strip() else "всего новых заявок: 0"
            await query.edit_message_text(
                text=msg_text,
                parse_mode="HTML",
                reply_markup=get_main_inline_keyboard(),
            )
        except Exception:
            await query.edit_message_text(
                text="Не удалось получить список новых заявок. Попробуйте позже.",
                reply_markup=get_main_inline_keyboard(),
            )
    elif data == "menu:taken":
        try:
            text = compose_taken_tickets_list()
            msg_text = text if text and text.strip() else "всего заявок в работе: 0"
            await query.edit_message_text(
                text=msg_text,
                parse_mode="HTML",
                reply_markup=get_main_inline_keyboard(),
            )
        except Exception:
            await query.edit_message_text(
                text="Не удалось получить список заявок в работе. Попробуйте позже.",
                reply_markup=get_main_inline_keyboard(),
            )
    elif data == "menu:status":
        try:
            text = compose_new_tickets_summary()
            msg_text = text if text and text.strip() else "No tickets found."
            await query.edit_message_text(
                text=msg_text,
                parse_mode="Markdown",
                reply_markup=get_main_inline_keyboard(),
            )
        except Exception:
            await query.edit_message_text(
                text="Failed to fetch tickets summary. Please try again later.",
                reply_markup=get_main_inline_keyboard(),
            )
    else:
        await query.edit_message_reply_markup(reply_markup=get_main_inline_keyboard())


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
    application.add_handler(CommandHandler("ticket", tickets))  # alias
    application.add_handler(CommandHandler("new", new_command))
    application.add_handler(CommandHandler("taken", taken_command))

    # Track chats when bot member status changes (e.g., added to groups)
    application.add_handler(
        ChatMemberHandler(chat_member_handler, ChatMemberHandler.CHAT_MEMBER)
    )

    # Route our bottom buttons first, then generic echo
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & (filters.Regex("(?i)^(Новые|В работе|Статус)$")),
            menu_buttons_router,
        )
    )
    # Handle inline keyboard callbacks for main menu
    application.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^menu:"))
    # Echo handler - responds to all other text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Schedule daily announcements of new tickets (Astana time)
    async def send_new_tickets_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            now_astana_dt = datetime.datetime.now(ASTANA_TZ)
            now_astana = now_astana_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
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
                    await context.bot.send_message(
                        chat_id=chat_id, text=text, parse_mode="Markdown"
                    )
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
                    days=(0, 1, 2, 3, 4),  # run only on weekdays (Mon-Fri)
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
