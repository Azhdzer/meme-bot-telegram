import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from bot import bot

from contextlib import contextmanager
import asyncio

@contextmanager
def username_context(username: str):
    """Context manager для логирования с username (пустышка если нет в utils)"""
    old_username = getattr(username_context, 'current_username', None)
    username_context.current_username = username
    
    try:
        yield username
    finally:
        username_context.current_username = old_username


logger = logging.getLogger(__name__)

# Структура: {url: [{"timestamp": str, "action": str, "status": str, "username": str, 
#                    "api": str, "platform": str, "duration": float, "error": str}, ...]}
download_log: Dict[str, List[Dict[str, Any]]] = {}
processing_tasks: Set[str] = set()
# Храним время начала для каждого URL (сбрасывается при новом запросе)
download_start_times: Dict[str, float] = {}


async def add_to_log(
    url: str,
    action: str,
    status: str = "",
    error: str = "",
    username: Optional[str] = None,
    api: Optional[str] = None,
    platform: Optional[str] = None,
    duration: Optional[float] = None,
) -> None:
    """
    Добавление записи в лог загрузки по конкретному URL.
    
    Args:
        url: URL загружаемого контента
        action: Действие (например, "TikTok API 1", "Instagram HTML")
        status: Статус выполнения
        error: Текст ошибки (если есть)
        username: Имя пользователя, который запросил загрузку
        api: Использованное API (например, "tikwm.com", "GraphQL")
        platform: Платформа (tiktok, instagram, youtube)
        duration: Время выполнения в секундах
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    safe_action = str(action).replace('*', '').replace('_', '').replace('`', '')
    safe_status = str(status or error or '⏳').replace('*', '').replace('_', '').replace('`', '')
    
    # Если это начало загрузки, сбрасываем и запоминаем время
    if "START" in action.upper():
        download_start_times[url] = time.time()
    
    # Вычисляем длительность если не передана и есть время начала
    if duration is None and url in download_start_times:
        duration = time.time() - download_start_times[url]
    
    log_entry = {
        "timestamp": timestamp,
        "action": safe_action,
        "status": safe_status,
        "username": username or "system",
        "api": api or "",
        "platform": platform or "",
        "duration": round(duration, 2) if duration else None,
        "error": error or "",
    }

    if url not in download_log:
        download_log[url] = []
    download_log[url].append(log_entry)
    
    # Формируем строку для logger
    log_str = f"📝 [{safe_action}] {url[:50]}: {safe_status}"
    if username:
        log_str += f" | @{username}"
    if api:
        log_str += f" | API: {api[:30]}"
    if duration:
        log_str += f" | {duration:.2f}s"
    logger.info(log_str)


async def safe_delete_message(chat_id: int, message_id: int):
    """Безопасное удаление сообщения (игнорирует любые ошибки Telegram)."""
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def safe_send_message(chat_id: int, text: str, parse_mode=None) -> None:
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


def format_log_entry(entry: Dict[str, Any]) -> str:
    """
    Форматирование одной записи лога для отображения.
    
    Args:
        entry: Словарь с данными записи лога
        
    Returns:
        Отформатированная строка
    """
    parts = [f"[{entry['timestamp']}] {entry['action']}: {entry['status']}"]
    
    if entry.get('username') and entry['username'] != 'system':
        parts.append(f"👤 @{entry['username']}")
    
    if entry.get('api'):
        parts.append(f"🔌 API: {entry['api'][:40]}")
    
    if entry.get('platform'):
        parts.append(f"📱 {entry['platform'].upper()}")
    
    if entry.get('duration'):
        parts.append(f"⏱ {entry['duration']}s")
    
    if entry.get('error'):
        parts.append(f"❌ {entry['error'][:50]}")
    
    return " | ".join(parts)

