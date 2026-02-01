import asyncio
import logging
import os
from typing import List

from aiogram.exceptions import TelegramEntityTooLarge
from aiogram.types import FSInputFile, InputMediaPhoto

from bot import bot
from downloaders import download_video
from utils import add_to_log, processing_tasks, safe_delete_message, safe_send_message

from utils import add_to_log, processing_tasks, safe_delete_message, safe_send_message
import stats

logger = logging.getLogger(__name__)

# Type alias for clarity
MediaGroup = List[InputMediaPhoto]


async def process_video_task(
    message_id: int,
    chat_id: int,
    processing_msg_id: int,
    url: str,
    username: str,
    platform: str,
    user_caption: str = "",
) -> None:
    """Фоновая задача: скачать видео и отправить его пользователю."""
    task_id = f"{chat_id}_{hash(url)}"
    if task_id in processing_tasks:
        await safe_delete_message(chat_id, processing_msg_id)
        return
    processing_tasks.add(task_id)

    try:
        logger.info("Начинаем загрузку: %s для @%s", url[:50], username)
        file_path, file_platform, media_type = await download_video(url, platform, username)
        logger.info("Загрузка завершена: %s, тип: %s", file_path, media_type)
        
        # Проверяем, что файл существует
        if isinstance(file_path, str):
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Файл не найден после загрузки: {file_path}")
        
        file_size = 0
        if isinstance(file_path, str):
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            if file_size_mb > 48:
                logger.warning(f"Большой файл {file_size_mb:.1f}MB: {file_path}")
            
            if file_size == 0:
                raise ValueError(f"Файл пустой: {file_path}")
        # Slideshow size check skipped for now or sum up

        
        emoji_map = {'TikTok': '🎪', 'Instagram': '📸', 'Youtube': '📺'}
        emoji = emoji_map.get(file_platform, '🎥')
        
        # Construct final caption
        base_caption = f"{emoji} <b><i>{username}</i></b> <a href='{url}'>link</a>"
        if user_caption:
            base_caption += f"\n\n{user_caption}"

        try:
            sent_msg = None
            if media_type == 'image':
                logger.info("Отправляем фото: %s", file_path)
                sent_msg = await bot.send_photo(chat_id, FSInputFile(file_path), caption=base_caption, parse_mode="HTML")
                await add_to_log(

                    url, "PHOTO", "SENT",
                    username=username, platform=platform
                )
            elif media_type == 'slideshow':
                # file_path is dict {'images': [], 'audio': ''}
                logger.info("Отправляем слайдшоу: %s", file_path)
                data = file_path
                images = data['images']
                audio = data['audio']
                
                # Создаем медиагруппу
                media_group = []
                for idx, img_path in enumerate(images):
                    if idx == 0:
                        media = InputMediaPhoto(media=FSInputFile(img_path), caption=base_caption, parse_mode="HTML")
                    else:
                        media = InputMediaPhoto(media=FSInputFile(img_path))
                    media_group.append(media)
                
                # Отправляем альбом
                if media_group:
                   msgs = await bot.send_media_group(chat_id, media_group)
                   if msgs:
                       sent_msg = msgs[0] # Register first message of album
                
                # Отправляем аудио
                if audio and os.path.exists(audio):
                    await bot.send_audio(chat_id, FSInputFile(audio), caption=f"🎵 {emoji}")

                await add_to_log(
                    url, "SLIDESHOW", "SENT",
                    username=username, platform=platform
                )

            else:
                logger.info("Отправляем видео: %s", file_path)
                sent_msg = await bot.send_video(chat_id, FSInputFile(file_path), caption=base_caption, parse_mode="HTML")
                await add_to_log(
                    url, "VIDEO", "SENT",
                    username=username, platform=platform
                )
            
            # 📊 REGISTER STATS
            if sent_msg:
                await stats.register_message(chat_id, sent_msg.message_id, url, username, platform)
                
            logger.info("Медиа успешно отправлено")
        except TelegramEntityTooLarge as e:
            # Специальная обработка для слишком больших файлов
            file_size_mb = file_size / (1024 * 1024)
            error_msg = f"Telegram отклонил файл: {file_size_mb:.2f}MB"
            logger.error(error_msg)
            await safe_send_message(
                chat_id,
                f"❌ @{username}\n"
                f"Файл слишком большой для Telegram: {file_size_mb:.2f}MB\n"
                f"Лимит: 50MB\n"
                f"Ссылка: {url}"
            )
            await add_to_log(
                url, "TELEGRAM_TOO_LARGE", error_msg,
                error=str(e), username=username, platform=platform
            )
            # Удаляем временные сообщения
            await safe_delete_message(chat_id, processing_msg_id)
            await asyncio.sleep(0.5)
            await safe_delete_message(chat_id, message_id)
            # Удаляем файл с задержкой (файл может быть ещё открыт)
            if os.path.exists(file_path):
                await asyncio.sleep(1)  # Даём время закрыть файл
                try:
                    os.remove(file_path)
                    logger.info("Файл удален после ошибки Telegram: %s", file_path)
                except Exception as rm_error:
                    logger.error("Ошибка при удалении файла: %s", rm_error)
                    # Пробуем ещё раз через секунду
                    await asyncio.sleep(1)
                    try:
                        os.remove(file_path)
                        logger.info("Файл удален со второй попытки: %s", file_path)
                    except Exception:
                        pass
            return  # Не пробрасываем исключение дальше, чтобы не дублировать сообщения
        except Exception as send_error:
            logger.error("Ошибка при отправке медиа: %s", send_error, exc_info=True)
            raise

        logger.info("Удаляем временные сообщения")
        await safe_delete_message(chat_id, processing_msg_id)
        await asyncio.sleep(0.5)
        await safe_delete_message(chat_id, message_id)
        
        if isinstance(file_path, str) and os.path.exists(file_path):
            os.remove(file_path)
            logger.info("Временный файл удален: %s", file_path)
        elif isinstance(file_path, dict):
            # Cleanup slideshow
            for img in file_path.get('images', []):
                if os.path.exists(img):
                    os.remove(img)
            if file_path.get('audio') and os.path.exists(file_path['audio']):
                os.remove(file_path['audio'])
            logger.info("Временные файлы слайдшоу удалены")

    except Exception as e:
        logger.error("Ошибка в process_video_task: %s", e, exc_info=True)
        await safe_delete_message(chat_id, processing_msg_id)
        error_text = str(e)
        
        # Логируем ошибку
        await add_to_log(
            url, "ERROR", error_text[:50],
            error=error_text, username=username, platform=platform
        )
        
        # Проверяем, не было ли уже отправлено сообщение (например, для TelegramEntityTooLarge)
        if "Entity Too Large" in error_text or "TELEGRAM_TOO_LARGE" in error_text:
            # Сообщение уже отправлено в блоке TelegramEntityTooLarge
            pass
        elif "PHOTO" in error_text:
            await safe_send_message(chat_id, f"📸 @{username}\nTikTok фото (только ссылка):\n{url}")
        elif "FILE_TOO_LARGE" in error_text or "TOO_LARGE" in error_text.upper():
            await safe_send_message(chat_id, f"❌ @{username}\nФайл слишком большой (>50MB)\nСсылка: {url}")
        elif "INSTAGRAM_FAIL" in error_text or "INSTAGRAM" in error_text.upper():
            await safe_send_message(chat_id, f"❌ @{username}\nInstagram недоступен\nСсылка: {url}")
        elif "TIKTOK_FAIL" in error_text or "TIKTOK" in error_text.upper():
            await safe_send_message(chat_id, f"❌ @{username}\nTikTok недоступен\nСсылка: {url}")
        elif "YOUTUBE_FAIL" in error_text or "YOUTUBE" in error_text.upper():
            await safe_send_message(chat_id, f"❌ @{username}\nYouTube недоступен\nСсылка: {url}")
        else:
            await safe_send_message(chat_id, f"❌ @{username}\n{platform} ошибка\n{error_text[:150]}\nСсылка: {url}")
        
        # Удаляем временные сообщения
        await safe_delete_message(chat_id, processing_msg_id)
        await asyncio.sleep(0.5)
        await safe_delete_message(chat_id, message_id)
        
        # Удаляем файл с задержкой
        if 'file_path' in locals() and os.path.exists(file_path):
            await asyncio.sleep(1)  # Даём время закрыть файл
            try:
                os.remove(file_path)
                logger.info("Файл удален после ошибки: %s", file_path)
            except Exception as rm_error:
                logger.error("Ошибка при удалении файла: %s", rm_error)
                # Пробуем ещё раз через секунду
                await asyncio.sleep(1)
                try:
                    os.remove(file_path)
                    logger.info("Файл удален со второй попытки: %s", file_path)
                except Exception:
                    pass
    finally:
        if task_id in processing_tasks:
            processing_tasks.remove(task_id)

