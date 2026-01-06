import os
import re


# Токен можно переопределить через переменную окружения BOT_TOKEN
API_TOKEN = os.getenv(
    "BOT_TOKEN",
    "8334248088:AAGH5M6-mSKjk9tknycGgBEFRUi-QB6B5s4",
)

# Паттерны ссылок по платформам
url_patterns = {
    'tiktok': re.compile(r"https?://(?:www\.)?(?:vm\.tiktok\.com|(?:www\.)?tiktok\.com)/[\w/]+", re.IGNORECASE),
    'youtube': re.compile(r"https?://(?:www\.)?(?:youtube\.com/(?:shorts|watch?v=|embed)|youtu\.be)/[\w?=&]+", re.IGNORECASE),
    'instagram': re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel)/[^/\s?]{8,}/?", re.IGNORECASE)
}

# Список используемых API для TikTok
TIKTOK_APIS = [
    "https://tikwm.com/api/?url=",
    "https://www.snaptik.app/abc.php?url=",
    "https://tikwm.com/api/?url=",
    "https://ssstik.io/abc.php?url="
]
