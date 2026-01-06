import asyncio
import os
from typing import Tuple

from aiogram.types import FSInputFile

from bot import bot
from downloaders import download_video
from utils import add_to_log, processing_tasks, safe_delete_message, safe_send_message


async def process_video_task(
    message_id: int,
    chat_id: int,
    processing_msg_id: int,
    url: str,
    username: str,
    platform: str,
) -> None:
    """Фоновая задача: скачать видео и отправить его пользователю."""
    task_id = f"{chat_id}_{hash(url)}"
    if task_id in processing_tasks:
        await safe_delete_message(chat_id, processing_msg_id)
        return
    processing_tasks.add(task_id)

    try:
        file_path, file_platform, media_type = await download_video(url, platform)
        emoji_map = {'TikTok': '🎪', 'Instagram': '📸', 'Youtube': '📺'}
        emoji = emoji_map.get(file_platform, '🎥')

        if media_type == 'image':
            await bot.send_photo(chat_id, FSInputFile(file_path), caption=f"{emoji} @{username}")
            await add_to_log(url, "PHOTO", "SENT")
        else:
            await bot.send_video(chat_id, FSInputFile(file_path), caption=f"{emoji} @{username}")
            await add_to_log(url, "VIDEO", "SENT")

        await safe_delete_message(chat_id, processing_msg_id)
        await asyncio.sleep(0.5)
        await safe_delete_message(chat_id, message_id)
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await safe_delete_message(chat_id, processing_msg_id)
        error_text = str(e)
        if "PHOTO" in error_text:
            await safe_send_message(chat_id, f"{username} TikTok фото: {url}")
        elif "FILE_TOO_LARGE" in error_text:
            await safe_send_message(chat_id, f"{username} Файл >50MB: {url}")
        elif "INSTAGRAM_FAIL" in error_text:
            await safe_send_message(chat_id, f"{username} Instagram недоступен")
        else:
            await safe_send_message(chat_id, f"{username} {platform} ошибка")
    finally:
        if task_id in processing_tasks:
            processing_tasks.remove(task_id)

