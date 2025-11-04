# Telegram Bot

A basic Telegram bot built with python-telegram-bot.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables (optional):
   - Copy `.env.example` to `.env`
   - Add your bot token to `.env`

3. Run the bot:
```bash
python main.py
```

## Features

- `/start` - Start the bot and get a welcome message
- `/help` - Show available commands
- `/status` - Check bot status
- Echo functionality - The bot echoes back any text messages you send

## Database Service

The project includes a separate MySQL database service for reading from the `DB_TICKETS` table.

Environment variables expected in `.env`:

- `DB_HOST`
- `DB_PORT`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`

Example usage:
```python
from services.db_service import get_ticket_service

service = get_ticket_service()
all_tickets = service.fetch_all_tickets(limit=50)
one_ticket = service.fetch_ticket_by_id(123)
open_tickets = service.fetch_tickets_by_status("OPEN", limit=20)
```

## Notes

- The bot token is currently hardcoded in `main.py`. For better security, use environment variables.
- Make sure to add `.env` to `.gitignore` to avoid committing sensitive information.

