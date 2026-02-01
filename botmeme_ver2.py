import asyncio
import logging

from bot import bot, dp
import handlers  # noqa: F401  регистрирует хендлеры через декораторы


from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Python 3.8 backport
    from backports.zoneinfo import ZoneInfo

import stats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def scheduled_stats_task():
    """Еженедельная рассылка статистики"""
    logger.info("📅 Scheduler started")
    while True:
        try:
            try:
                tz = ZoneInfo("Europe/Warsaw")
            except Exception:
                # Fallback implementation if tzdata is missing
                from datetime import timezone, timedelta
                # WARSAW is roughly UTC+1 (CET) or UTC+2 (CEST). 
                # For simplicity in fallback, we use UTC+1 (Winter) or user can install tzdata
                tz = timezone(timedelta(hours=1))
                # Log usage of fallback once
                if "fallback_logged" not in locals():
                    logger.warning("⚠️ timezone 'Europe/Warsaw' not found. Using fixed UTC+1. Install 'tzdata' for correct DST support.")
                    locals()["fallback_logged"] = True

            now = datetime.now(tz)
            # Sunday == 6, 20:00
            if now.weekday() == 6 and now.hour == 20 and now.minute == 0:
                chat_id = stats.get_report_chat_id()
                if chat_id:
                    report = stats.get_stats_report()
                    await bot.send_message(chat_id, "📅 <b>Еженедельный отчет:</b>\n\n" + report, parse_mode="HTML")
                    logger.info(f"Weekly report sent to {chat_id}")
                    # Wait 61 seconds to avoid double sending
                    await asyncio.sleep(61)
            
            await asyncio.sleep(60) # Check every minute
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(60)


async def main() -> None:
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        # Запускаем планировщик
        asyncio.create_task(scheduled_stats_task())
        
        logger.info("🤖 MemeBot v6.5 - Instagram HTML Scraping 2026!")
        await dp.start_polling(bot, allowed_updates=["message", "message_reaction", "message_reaction_count"])
    except KeyboardInterrupt:
        logger.info("👋 Graceful shutdown")
    except Exception as e:
        logger.error("💥 Fatal: %s", e)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
