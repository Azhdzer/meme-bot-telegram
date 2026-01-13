import os
import re

API_TOKEN = os.getenv("BOT_TOKEN", "8334248088:AAGH5M6-mSKjk9tknycGgBEFRUi-QB6B5s4")

url_patterns = {
    'tiktok': re.compile(r"https?://(?:www\.)?(?:vm\.tiktok\.com|(?:www\.)?tiktok\.com)/[\w/]+", re.IGNORECASE),
    'youtube': re.compile(r"https?://(?:www\.)?(?:youtube\.com/(?:shorts|watch?v=|embed)|youtu\.be)/[\w?=&]+", re.IGNORECASE),
    'instagram': re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel)/[^/\s?]{8,}/?", re.IGNORECASE)
}

TIKTOK_APIS = [
    "https://tikwm.com/api/?url=",           
    "https://www.snaptik.app/abc.php?url=",  
    "https://ssstik.io/abc.php?url=",         
    "https://tiktokio.com/api?url=",         
    "https://snaptik.app/action.php?url=",    
    "https://musicallydown.com/api?url="     
]


INSTAGRAM_APIS = [
    "https://igram.world/api",
    "https://indown.io/api",  # ✅ Работает без логина [web:62]
    "https://sssinstagram.com/api",  # Альтернатива snapinsta [web:64]
    "https://reelsvideo.io/download",  # Reels HD [web:66]
    "https://storysaver.net/api"  # Универсальный [web:64]
]

