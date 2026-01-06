import asyncio
import logging
from typing import List, Tuple

from aiogram import F, types
from aiogram.filters import Command

from bot import bot, dp
from config import url_patterns
from tasks import process_video_task
from utils import add_to_log, download_log, safe_send_message


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
    if not download_log:
        await message.answer("Логов нет")
        return

    log_text = "🔍 ПОСЛЕДНИЕ 3:\n\n"
    for url in list(download_log.keys())[-3:]:
        log_text += f"🔗 {url[:60]}:\n" + "".join(download_log[url][-4:]) + "\n\n"

    for i in range(0, len(log_text), 3800):
        await safe_send_message(message.chat.id, log_text[i:i + 3800])


@dp.message(Command("log"))
async def cmd_log(message: types.Message) -> None:
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
        await safe_send_message(message.chat.id, f"❌ Лог не найден: {url[:50]}\n/logs")
        return

    log_text = f"📋 ЛОГ {url[:50]}:\n\n" + "".join(download_log[url][-10:])
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
    await add_to_log("", f"@{username}", f"{len(urls)} ссылок")

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

