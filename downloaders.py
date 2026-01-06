import asyncio
import json
import os
import re
from typing import Tuple

import aiohttp

from config import TIKTOK_APIS
from utils import add_to_log


async def download_tiktok(url: str) -> Tuple[str, str]:
    """Загрузка видео с TikTok через несколько публичных API."""
    os.makedirs('downloads', exist_ok=True)
    if '/photo/' in url.lower():
        await add_to_log(url, "TikTok фото", "ОСТАВЛЯЕМ ССЫЛКУ")
        raise Exception("PHOTO")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), headers=headers) as session:
        for i, api_base in enumerate(TIKTOK_APIS, 1):
            try:
                await add_to_log(url, f"TikTok API {i}", api_base[:40])
                async with session.get(api_base + url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('code') == 0:
                            video_url = data['data']['play']
                            filename = f"downloads/tiktok_{os.urandom(6).hex()}.mp4"
                            async with session.get(video_url) as video_resp:
                                with open(filename, 'wb') as f:
                                    f.write(await video_resp.read())
                            await add_to_log(url, f"TikTok API {i}", "ВИДЕО OK")
                            return filename, 'video'
            except Exception:
                await add_to_log(url, f"TikTok API {i}", "FAIL")
    raise Exception("TIKTOK_FAIL")


async def download_instagram(url: str) -> Tuple[str, str]:
    """Загрузка медиа с Instagram: HTML + GraphQL + oEmbed."""
    os.makedirs('downloads', exist_ok=True)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    }

    # Извлекаем shortcode
    shortcode_match = re.search(r'/p/([A-Za-z0-9_-]+)', url)
    shortcode = shortcode_match.group(1) if shortcode_match else ''

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25), headers=headers) as session:
        # 1️⃣ DIRECT Instagram HTML парсинг
        try:
            await add_to_log(url, "Instagram HTML", "scraping...")
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()

                    # PARSE window._sharedData (Instagram JSON)
                    json_match = re.search(r'window\._sharedData = ({.*?});</script>', html, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            entry_data = data.get('entry_data', {}).get('PostPage', [{}])[0]
                            post_data = entry_data.get('graphql', {}).get('shortcode_media', {})

                            # Картинка
                            if post_data.get('__typename') == 'GraphImage':
                                img_url = post_data.get('display_url')
                                if img_url and 'scontent' in img_url:
                                    filename = f"downloads/insta_{os.urandom(6).hex()}.jpg"
                                    async with session.get(img_url, headers=headers) as img_resp:
                                        if img_resp.status == 200:
                                            with open(filename, 'wb') as f:
                                                f.write(await img_resp.read())
                                            await add_to_log(url, "JSON Image", "OK")
                                            return filename, 'image'

                            # Карусель (первая картинка)
                            elif post_data.get('__typename') == 'GraphSidecar':
                                edges = post_data.get('edge_sidecar_to_children', {}).get('edges', [])
                                if edges:
                                    first_node = edges[0]['node']
                                    img_url = first_node.get('display_url')
                                    if img_url:
                                        filename = f"downloads/insta_{os.urandom(6).hex()}.jpg"
                                        async with session.get(img_url, headers=headers) as img_resp:
                                            if img_resp.status == 200:
                                                with open(filename, 'wb') as f:
                                                    f.write(await img_resp.read())
                                                await add_to_log(url, "Carousel IMG", "OK")
                                                return filename, 'image'

                            # Видео
                            elif post_data.get('video_url'):
                                video_url = post_data.get('video_url')
                                filename = f"downloads/insta_{os.urandom(6).hex()}.mp4"
                                async with session.get(video_url, headers=headers) as video_resp:
                                    if video_resp.status == 200:
                                        with open(filename, 'wb') as f:
                                            f.write(await video_resp.read())
                                        await add_to_log(url, "JSON Video", "OK")
                                        return filename, 'video'
                        except Exception:
                            await add_to_log(url, "JSON parse", "fail")

                    # Fallback: CDN patterns из HTML
                    cdn_patterns = [
                        r'"display_url":"(https://[^"]+scontent[^"]+\.(?:jpg|jpeg))"',
                        r'"display_resources":\[[^]]*"src":"(https://[^"]+scontent[^"]+\.jpg)"',
                        r'"video_url":"(https://[^"]+scontent[^"]+\.mp4)"',
                        r'"edge_sidecar_to_children":\{"edges":\[{"node":\{"display_url":"(https://[^"]+)"'
                    ]

                    for pattern in cdn_patterns:
                        matches = re.finditer(pattern, html, re.IGNORECASE)
                        for match in matches:
                            media_url = match.group(1)
                            if 'scontent' in media_url:
                                ext = 'jpg' if '.jpg' in media_url or '.jpeg' in media_url else 'mp4'
                                filename = f"downloads/insta_{os.urandom(6).hex()}.{ext}"
                                try:
                                    async with session.get(media_url, headers=headers, allow_redirects=True) as media_resp:
                                        if media_resp.status == 200:
                                            content = await media_resp.read()
                                            if len(content) > 10 * 1024:
                                                with open(filename, 'wb') as f:
                                                    f.write(content)
                                                media_type = 'image' if ext == 'jpg' else 'video'
                                                await add_to_log(url, "HTML CDN", f"{media_type.upper()} OK")
                                                return filename, media_type
                                except Exception:
                                    continue
                    await add_to_log(url, "HTML parse", "no media")
        except Exception as e:
            await add_to_log(url, "HTML fetch", f"ERR: {str(e)[:30]}")

        # 2️⃣ Instagram GraphQL endpoint
        try:
            await add_to_log(url, "GraphQL", "trying...")
            if shortcode:
                query_hash = "d5d763b1e2acf209d62d22cf2957d710"
                variables = {
                    "shortcode": shortcode,
                    "child_index": 0,
                    "fetch_comment_count": 3,
                    "fetch_comment_cursor": "",
                    "fetch_mutual": True
                }
                graphql_url = f"https://www.instagram.com/graphql/query/?query_hash={query_hash}&variables={json.dumps(variables)}"

                async with session.get(graphql_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        post_data = data.get('data', {}).get('shortcode_media', {})

                        if post_data.get('__typename') == 'GraphImage':
                            img_url = post_data.get('display_url')
                            if img_url:
                                filename = f"downloads/insta_{os.urandom(6).hex()}.jpg"
                                async with session.get(img_url) as img_resp:
                                    if img_resp.status == 200:
                                        with open(filename, 'wb') as f:
                                            f.write(await img_resp.read())
                                        await add_to_log(url, "GraphQL IMG", "OK")
                                        return filename, 'image'

                        elif post_data.get('video_url'):
                            video_url = post_data.get('video_url')
                            filename = f"downloads/insta_{os.urandom(6).hex()}.mp4"
                            async with session.get(video_url) as video_resp:
                                if video_resp.status == 200:
                                    with open(filename, 'wb') as f:
                                        f.write(await video_resp.read())
                                    await add_to_log(url, "GraphQL VID", "OK")
                                    return filename, 'video'
        except Exception:
            await add_to_log(url, "GraphQL", "fail")

        # 3️⃣ oEmbed (последний резерв)
        try:
            await add_to_log(url, "oEmbed", "FINAL")
            oembed_url = f"https://www.instagram.com/oembed/?url={url}"
            async with session.get(oembed_url, headers={'User-Agent': headers['User-Agent']}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    thumb_url = data.get('thumbnail_url')
                    if thumb_url:
                        filename = f"downloads/insta_{os.urandom(6).hex()}.jpg"
                        async with session.get(thumb_url) as thumb_resp:
                            if thumb_resp.status == 200:
                                with open(filename, 'wb') as f:
                                    f.write(await thumb_resp.read())
                                await add_to_log(url, "oEmbed THUMB", "OK")
                                return filename, 'image'
        except Exception:
            await add_to_log(url, "oEmbed", "fail")

    raise Exception("INSTAGRAM_FAIL")


async def download_youtube(url: str) -> Tuple[str, str]:
    """Загрузка видео с YouTube (включая Shorts) через yt-dlp."""
    os.makedirs('downloads', exist_ok=True)
    await add_to_log(url, "YouTube", "yt-dlp START")

    ydl_opts = {
        'format': 'best[height<=720][ext=mp4]/best',
        'outtmpl': 'downloads/youtube_%(id)s.%(ext)s',
        'quiet': True,
    }

    try:
        from yt_dlp import YoutubeDL

        def run_ydl() -> str:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename_local = ydl.prepare_filename(info)
                if os.path.getsize(filename_local) > 50 * 1024 * 1024:
                    os.remove(filename_local)
                    raise Exception("FILE_TOO_LARGE")
                return filename_local

        filename = await asyncio.to_thread(run_ydl)
        await add_to_log(url, "YouTube", "OK")
        return filename, 'video'
    except Exception as e:
        await add_to_log(url, "YouTube", str(e)[:30])
        raise Exception("YOUTUBE_FAIL")


async def download_video(url: str, platform: str) -> Tuple[str, str, str]:
    """Обёртка над загрузчиками по платформе."""
    await add_to_log(url, platform.upper(), "START")
    try:
        if platform == 'tiktok':
            filename, media_type = await download_tiktok(url)
            return filename, 'TikTok', media_type
        if platform == 'instagram':
            filename, media_type = await download_instagram(url)
            return filename, 'Instagram', media_type
        if platform == 'youtube':
            filename, media_type = await download_youtube(url)
            return filename, 'Youtube', media_type
    except Exception as e:
        await add_to_log(url, "ERROR", str(e))
        raise

    raise ValueError(f"Unsupported platform: {platform}")

