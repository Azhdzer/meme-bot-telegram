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


INSTAGRAM_REELS_APIS = [
    "https://igram.world/api/ajaxSearch?url=",  
    "https://saveinsta.app/api/ajaxSearch?url=",
    "https://fastdl.app/api/ajaxSearch?url=",
    "https://instadownloader.co/api?url=",
    "https://snapinsta.app/api?url="
]
