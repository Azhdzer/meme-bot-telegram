from aiogram import Bot, Dispatcher

from config import API_TOKEN


# Инициализация бота и диспетчера в отдельном модуле
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

