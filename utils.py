import logging
import re
from datetime import datetime
from typing import Dict, List, Set

from bot import bot


logger = logging.getLogger(__name__)

download_log: Dict[str, List[str]] = {}
processing_tasks: Set[str] = set()


async def add_to_log(url: str, action: str, status: str = "", error: str = ""):
    """Добавление строки в лог загрузки по конкретному URL."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    safe_action = str(action).replace('*', '').replace('_', '').replace('`', '')
    safe_status = str(status or error or '⏳').replace('*', '').replace('_', '').replace('`', '')
    log_entry = f"[{timestamp}] {safe_action}: {safe_status}\n"

    if url not in download_log:
        download_log[url] = []
    download_log[url].append(log_entry)
    logger.info(f"📝 [{safe_action}] {url[:50]}: {safe_status}")


async def safe_delete_message(chat_id: int, message_id: int):
    """Безопасное удаление сообщения (игнорирует любые ошибки Telegram)."""
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def safe_send_message(chat_id: int, text: str, parse_mode=None):
    """Безопасная отправка без Markdown-ошибок."""
    try:
        safe_text = (str(text)
                     .replace('*', '')
                     .replace('_', '')
                     .replace('`', '')
                     .replace('[', '')
                     .replace(']', ''))
        await bot.send_message(chat_id, safe_text, parse_mode=None)
    except Exception:
        clean_text = re.sub(r'[\*\_\`\[\]]', '', str(text))
        await bot.send_message(chat_id, clean_text[:4000])

