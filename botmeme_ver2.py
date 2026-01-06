import asyncio
import logging

from bot import bot, dp
import handlers  # noqa: F401  регистрирует хендлеры через декораторы


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("🤖 MemeBot v6.5 - Instagram HTML Scraping 2026!")
        await dp.start_polling(bot)
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
