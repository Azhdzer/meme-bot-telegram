import asyncio
import logging
from typing import List, Tuple

from aiogram import F, types
from aiogram.filters import Command

from bot import bot, dp
from config import url_patterns
from tasks import process_video_task
from utils import add_to_log, download_log, format_log_entry, safe_send_message


logger = logging.getLogger(__name__)


@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        "MemeBot v6.5 - GitHub HTML Scraping!\n"
        "✅ TikTok видео\n"
        "✅ Instagram HTML parse\n"
        "✅ YouTube Shorts\n\n"
        "log ссылка | logs | start",
        parse_mode=None,
    )


@dp.message(Command("logs"))
async def cmd_logs(message: types.Message) -> None:
    """Показать последние 3 загрузки с детальной информацией."""
    if not download_log:
        await message.answer("Логов нет")
        return

    log_text = "🔍 ПОСЛЕДНИЕ 3 ЗАГРУЗКИ:\n" + "=" * 50 + "\n\n"
    
    for url in list(download_log.keys())[-3:]:
        entries = download_log[url]
        if not entries:
            continue
            
        # Получаем метаданные из первой записи
        first_entry = entries[0]
        username = first_entry.get('username', 'unknown')
        platform = first_entry.get('platform', '').upper()
        total_duration = entries[-1].get('duration')
        
        log_text += f"🔗 URL: {url[:60]}\n"
        log_text += f"👤 Пользователь: @{username}\n"
        if platform:
            log_text += f"📱 Платформа: {platform}\n"
        if total_duration:
            log_text += f"⏱ Общее время: {total_duration}s\n"
        log_text += f"📊 Записей в логе: {len(entries)}\n"
        log_text += "\n📋 Детали:\n"
        
        # Показываем последние 5 записей
        for entry in entries[-5:]:
            log_text += format_log_entry(entry) + "\n"
        
        log_text += "\n" + "-" * 50 + "\n\n"

    # Разбиваем на части если слишком длинно
    for i in range(0, len(log_text), 3800):
        await safe_send_message(message.chat.id, log_text[i:i + 3800])


@dp.message(Command("log"))
async def cmd_log(message: types.Message) -> None:
    """Показать детальный лог для конкретной ссылки."""
    text = message.text.strip()
    urls: List[str] = []
    for pattern in url_patterns.values():
        found = pattern.findall(text)
        urls.extend(found)

    if len(text.split()) > 1:
        arg = ' '.join(text.split()[1:])
        for pattern in url_patterns.values():
            if pattern.search(arg):
                urls = [arg]
                break

    if not urls:
        await safe_send_message(message.chat.id, "/log https://ссылка")
        return

    url = urls[0]
    if url not in download_log:
        await safe_send_message(message.chat.id, f"❌ Лог не найден: {url[:50]}\nИспользуйте /logs для просмотра всех логов")
        return

    entries = download_log[url]
    if not entries:
        await safe_send_message(message.chat.id, f"❌ Лог пуст для: {url[:50]}")
        return
    
    # Собираем статистику
    first_entry = entries[0]
    last_entry = entries[-1]
    username = first_entry.get('username', 'unknown')
    platform = first_entry.get('platform', '').upper()
    total_duration = last_entry.get('duration')
    
    # Подсчитываем использованные API
    used_apis = {entry['api'][:40] for entry in entries if entry.get('api')}
    
    # Формируем детальный лог
    log_text = "=" * 50 + "\n"
    log_text += f"📋 ДЕТАЛЬНЫЙ ЛОГ\n"
    log_text += "=" * 50 + "\n\n"
    log_text += f"🔗 URL: {url}\n"
    log_text += f"👤 Пользователь: @{username}\n"
    if platform:
        log_text += f"📱 Платформа: {platform}\n"
    if total_duration:
        log_text += f"⏱ Общее время: {total_duration}s\n"
    if used_apis:
        log_text += f"🔌 Использованные API: {', '.join(list(used_apis)[:3])}\n"
    log_text += f"📊 Всего записей: {len(entries)}\n"
    log_text += "\n" + "-" * 50 + "\n"
    log_text += "📝 ХРОНОЛОГИЯ СОБЫТИЙ:\n"
    log_text += "-" * 50 + "\n\n"
    
    # Показываем все записи (или последние 15 если их слишком много)
    entries_to_show = entries[-15:] if len(entries) > 15 else entries
    for i, entry in enumerate(entries_to_show, 1):
        log_text += f"{i}. {format_log_entry(entry)}\n"
    
    if len(entries) > 15:
        log_text += f"\n... (показано последние 15 из {len(entries)} записей)\n"
    
    await safe_send_message(message.chat.id, log_text)


@dp.message(F.text)
async def handle_message(message: types.Message) -> None:
    text = message.text
    if not text or text.startswith('/'):
        return

    username = message.from_user.username or message.from_user.full_name or "Unknown"
    urls: List[Tuple[str, str]] = []
    for platform, pattern in url_patterns.items():
        found_urls = pattern.findall(text)
        urls.extend([(url, platform) for url in found_urls])

    if not urls:
        return

    logger.info("User @%s: %d ссылок", username, len(urls))
    # Не логируем пустой URL, это просто информационное сообщение

    for url, platform in urls:
        processing_msg = await bot.send_message(
            message.chat.id,
            f"⏳ @{username}, {platform}...",
        )
        asyncio.create_task(
            process_video_task(
                message.message_id,
                message.chat.id,
                processing_msg.message_id,
                url,
                username,
                platform,
            )
        )

