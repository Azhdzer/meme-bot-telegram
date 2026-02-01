import json
import os
import logging
from collections import defaultdict
from typing import Dict, Any, List

from aiogram.types import MessageReactionUpdated

logger = logging.getLogger(__name__)

STATS_FILE = "stats.json"

# FORMAT:
# {
#   "messages": {
#       "chat_id:message_id": {
#           "url": "http...",
#           "username": "user",
#           "platform": "tiktok",
#           "reactions": {"🔥": 1, ...}
#       }
#   },
#   "global": {
#       "🔥": 10,
#       "❤️": 5
#   }
# }

def load_stats() -> Dict[str, Any]:
    if not os.path.exists(STATS_FILE):
        return {"messages": {}, "global": {}}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load stats: {e}")
        return {"messages": {}, "global": {}}

def save_stats(data: Dict[str, Any]):
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save stats: {e}")

async def register_message(chat_id: int, message_id: int, url: str, username: str, platform: str):
    """Регистрируем отправленное сообщение чтобы отслеживать реакции"""
    data = load_stats()
    key = f"{chat_id}:{message_id}"
    
    data["messages"][key] = {
        "url": url,
        "username": username,
        "platform": platform,
        "reactions": {}
    }
    
    # Ограничиваем размер (чистим старые если > 1000)
    if len(data["messages"]) > 1000:
        # Удаляем 100 старых
        keys = list(data["messages"].keys())[:100]
        for k in keys:
            del data["messages"][k]
            
    save_stats(data)

async def handle_reaction(event: MessageReactionUpdated):
    """Обработка добавления/удаления реакций"""
    data = load_stats()
    key = f"{event.chat.id}:{event.message_id}"
    
    if key not in data["messages"]:
        return

    msg_data = data["messages"][key]
    
    # Считаем новые реакции
    added_emojis = {r.emoji for r in event.new_reaction if hasattr(r, 'emoji')}
    removed_emojis = {r.emoji for r in event.old_reaction if hasattr(r, 'emoji')}
    
    # Update message specific stats
    for emoji in added_emojis:
        if emoji not in removed_emojis:
            msg_data["reactions"][emoji] = msg_data["reactions"].get(emoji, 0) + 1
            data["global"][emoji] = data["global"].get(emoji, 0) + 1
            
    for emoji in removed_emojis:
        if emoji not in added_emojis:
            current = msg_data["reactions"].get(emoji, 0)
            if current > 0:
                msg_data["reactions"][emoji] = current - 1
                
            global_cur = data["global"].get(emoji, 0)
            if global_cur > 0:
                data["global"][emoji] = global_cur - 1

    save_stats(data)

def get_stats_report() -> str:
    data = load_stats()
    global_stats = data.get("global", {})
    
    if not global_stats:
        return "📊 Статистика пуста"
    
    # Sort by count desc
    sorted_stats = sorted(global_stats.items(), key=lambda x: x[1], reverse=True)
    
    text = "📊 <b>Статистика реакций:</b>\n\n"
    for emoji, count in sorted_stats:
        text += f"{emoji}: {count}\n"
        
    # Top 3 most reacted messages
    text += "\n🏆 <b>Топ-3 видео:</b>\n"
    
    # Calculate sum of reactions per message
    msg_stats = []
    for key, val in data["messages"].items():
        total = sum(val.get("reactions", {}).values())
        if total > 0:
            msg_stats.append((total, val))
            
    msg_stats.sort(key=lambda x: x[0], reverse=True)
    
    for i, (count, val) in enumerate(msg_stats[:3], 1):
        top_emojis = sorted(val.get("reactions", {}).items(), key=lambda x: x[1], reverse=True)[:3]
        emoji_str = " ".join([e[0] for e in top_emojis])
        text += f"{i}. <a href='{val['url']}'>Видео</a> ({count} {emoji_str})\n"
        
    return text

def set_report_chat_id(chat_id: int):
    data = load_stats()
    if "config" not in data:
        data["config"] = {}
    data["config"]["report_chat_id"] = chat_id
    save_stats(data)

def get_report_chat_id() -> int:
    data = load_stats()
    return data.get("config", {}).get("report_chat_id")

