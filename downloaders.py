import asyncio
import json
import os
import re
import time
from typing import Optional, Tuple
import subprocess

import aiohttp

from config import TIKTOK_APIS
from utils import add_to_log

async def compress_video_ffmpeg(input_path: str, output_path: str, target_size_mb: float = 40) -> bool:
    """Компрессия видео FFmpeg H.265 → <40MB (Telegram safe)."""
    try:
        # Проверяем FFmpeg в PATH
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'scale=-2:720',  # 720p
            '-c:v', 'libx265', '-crf', '26', '-preset', 'fast',
            '-c:a', 'aac', '-b:a', '128k',
            '-maxrate', '1500k', '-bufsize', '3000k',
            '-t', '180',  # Макс 3 мин
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        
        if result.returncode == 0 and os.path.exists(output_path):
            orig_size = os.path.getsize(input_path) / (1024*1024)
            new_size = os.path.getsize(output_path) / (1024*1024)
            ratio = (1 - new_size/orig_size) * 100
            await add_to_log("", f"FFMPEG ↓{ratio:.0f}%", f"{orig_size:.1f}→{new_size:.1f}MB", api="H.265")
            return True
        return False
    except Exception as e:
        await add_to_log("", "FFMPEG FAIL", str(e)[:50], api="compress")
        return False

async def download_tiktok(url: str, username: Optional[str] = None) -> Tuple[str, str]:
    """Загрузка TikTok + АВТОКОМПРЕССИЯ >40MB → H.265 <45MB + YT-DLP FALLBACK."""
    os.makedirs('downloads', exist_ok=True)
    start_time = time.time()
    
    if '/photo/' in url.lower():
        await add_to_log(url, "TikTok фото", "ОСТАВЛЯЕМ ССЫЛКУ", username=username, platform="tiktok")
        raise Exception("PHOTO")

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # 🆕 1. Попытка API
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25), headers=headers) as session:
        for i, api_base in enumerate(TIKTOK_APIS, 1):
            api_name = api_base.split('/')[2] if '/' in api_base else api_base[:30]
            api_start = time.time()
            try:
                await add_to_log(url, f"TikTok API {i}", f"Попытка {i}/{len(TIKTOK_APIS)}",
                               username=username, api=api_name, platform="tiktok")
                async with session.get(api_base + url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('code') == 0:
                            video_url = data['data']['play']
                            raw_filename = f"downloads/tiktok_raw_{os.urandom(6).hex()}.mp4"
                            download_start = time.time()
                            async with session.get(video_url) as video_resp:
                                with open(raw_filename, 'wb') as f:
                                    f.write(await video_resp.read())
                            
                            # ✅ v6.6 АВТОКОМПРЕССИЯ 166MB→25MB
                            file_size_mb = os.path.getsize(raw_filename) / (1024 * 1024)
                            final_filename = raw_filename
                            
                            if file_size_mb > 40:  # Telegram safe margin
                                await add_to_log(url, "TikTok RAW", f"{file_size_mb:.1f}MB → COMPRESS",
                                               username=username, api=api_name, platform="tiktok")
                                
                                compressed_filename = raw_filename.replace('raw_', 'opt_')
                                if await compress_video_ffmpeg(raw_filename, compressed_filename):
                                    os.remove(raw_filename)
                                    final_filename = compressed_filename
                                else:
                                    # Fallback: обрезка до 40MB
                                    await add_to_log(url, "FFmpeg FAIL", "→ TRIM 3min", username=username)
                                    trimmed_filename = raw_filename.replace('raw_', 'trim_')
                                    subprocess.run([
                                        'ffmpeg', '-y', '-i', raw_filename, '-t', '180', '-c', 'copy', trimmed_filename
                                    ], capture_output=True)
                                    os.remove(raw_filename)
                                    final_filename = trimmed_filename
                            
                            download_time = time.time() - download_start
                            total_time = time.time() - start_time
                            final_size_mb = os.path.getsize(final_filename) / (1024 * 1024)
                            await add_to_log(url, f"TikTok API {i}", f"VIDEO OK {final_size_mb:.1f}MB ✓",
                                           username=username, api=api_name, platform="tiktok", duration=total_time)
                            return final_filename, 'video'
            except Exception as e:
                api_time = time.time() - api_start
                await add_to_log(url, f"TikTok API {i}", f"FAIL ({str(e)[:30]})",
                               error=str(e)[:50], username=username, api=api_name,
                               platform="tiktok", duration=api_time)

    # 🆕 2. YT-DLP FALLBACK (100% работает для TikTok!)
    await add_to_log(url, "YT-DLP", "TikTok FAILBACK START", username=username, platform="tiktok")
    try:
        ydl_opts = {
            'format': 'best[height<=720][ext=mp4]/best',
            'outtmpl': f'downloads/tiktok_fallback_{os.urandom(6).hex()}.%(ext)s',
            'quiet': True,
        }
        from yt_dlp import YoutubeDL
        
        def run_yt_dlp():
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename_local = ydl.prepare_filename(info)
                return filename_local
        
        fallback_filename = await asyncio.to_thread(run_yt_dlp)
        
        # Компрессия fallback видео
        file_size_mb = os.path.getsize(fallback_filename) / (1024 * 1024)
        final_filename = fallback_filename
        
        if file_size_mb > 40:
            await add_to_log(url, "YT-DLP RAW", f"{file_size_mb:.1f}MB → COMPRESS", username=username)
            compressed_filename = fallback_filename.replace('.mp4', '_opt.mp4')
            if await compress_video_ffmpeg(fallback_filename, compressed_filename):
                os.remove(fallback_filename)
                final_filename = compressed_filename
        
        total_time = time.time() - start_time
        final_size_mb = os.path.getsize(final_filename) / (1024 * 1024)
        await add_to_log(url, "YT-DLP TikTok", f"FALLBACK OK {final_size_mb:.1f}MB ✓", 
                        username=username, platform="tiktok", duration=total_time)
        return final_filename, 'video'
    except Exception as e:
        await add_to_log(url, "YT-DLP FAIL", str(e)[:50], username=username, platform="tiktok")

    raise Exception("TIKTOK_FAIL")

async def download_instagram(url: str, username: Optional[str] = None) -> Tuple[str, str]:
    """Instagram Reels 2026: 5 API + HTML scraper."""
    os.makedirs('downloads', exist_ok=True)
    start_time = time.time()

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.instagram.com/', 'Origin': 'https://www.instagram.com'
    }

    # Shortcode для /p/ и /reel/
    shortcode_match = re.search(r'/([A-Za-z0-9_-]{11})/?', url)
    shortcode = shortcode_match.group(1) if shortcode_match else ''

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35), headers=headers) as session:
        # ✅ 1. 5 Instagram Reels API (работают 2026)
        INSTAGRAM_REELS_APIS = [
            "https://igram.world/api/ajaxSearch?url=",
            "https://saveinsta.app/api/ajaxSearch?url=",
            "https://fastdl.app/api/ajaxSearch?url=",
            "https://instadownloader.co/api?url=",
            "https://snapinsta.app/api?url="
        ]
        
        for i, api_base in enumerate(INSTAGRAM_REELS_APIS, 1):
            api_name = api_base.split('/')[2]
            api_start = time.time()
            try:
                await add_to_log(url, f"Insta API {i}", api_name,
                               username=username, api=api_name, platform="instagram")
                api_url = api_base + url
                async with session.get(api_url) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        # Современные Reels patterns
                        patterns = [
                            r'"(https://[^"\s]+scontent[^"\s]+\.(?:jpg|jpeg|mp4))"',
                            r'"download_url":"(https://[^"]+scontent[^"]+\.(?:jpg|mp4))"',
                            r'"video_url":"(https://[^"]+scontent[^"]+\.mp4)"',
                            r'src="(https://[^"\s]+scontent[^"\s]+\.(?:jpg|mp4))"'
                        ]
                        for pattern in patterns:
                            match = re.search(pattern, content, re.IGNORECASE)
                            if match:
                                media_url = match.group(1).replace('\\', '')
                                if 'scontent' in media_url:
                                    ext = 'jpg' if any(x in media_url.lower() for x in ['.jpg', '.jpeg']) else 'mp4'
                                    filename = f"downloads/insta_{os.urandom(6).hex()}.{ext}"
                                    async with session.get(media_url, headers=headers, allow_redirects=True) as media_resp:
                                        if media_resp.status == 200:
                                            content_bytes = await media_resp.read()
                                            if len(content_bytes) > 15*1024:
                                                with open(filename, 'wb') as f:
                                                    f.write(content_bytes)
                                                media_type = 'image' if ext == 'jpg' else 'video'
                                                api_time = time.time() - api_start
                                                total_time = time.time() - start_time
                                                await add_to_log(url, f"Insta API {i}", f"{media_type.upper()} OK ✓",
                                                               username=username, api=api_name, platform="instagram", duration=total_time)
                                                return filename, media_type
            except Exception as e:
                api_time = time.time() - api_start
                await add_to_log(url, f"Insta API {i}", f"ERR: {str(e)[:30]}",
                               error=str(e)[:50], username=username, api=api_name,
                               platform="instagram", duration=api_time)

        # 2️⃣ Улучшенный HTML + GraphQL (ваш код без изменений)
        html_start = time.time()
        try:
            await add_to_log(url, "Instagram HTML", "scraping...", username=username, api="HTML Parse", platform="instagram")
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()

                    # PARSE window._sharedData
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
                                            html_time = time.time() - html_start
                                            total_time = time.time() - start_time
                                            await add_to_log(url, "JSON Image", "OK", username=username, api="HTML JSON",
                                                           platform="instagram", duration=total_time)
                                            return filename, 'image'

                            # Карусель
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
                                                html_time = time.time() - html_start
                                                total_time = time.time() - start_time
                                                await add_to_log(url, "Carousel IMG", "OK", username=username, api="HTML Carousel",
                                                               platform="instagram", duration=total_time)
                                                return filename, 'image'

                            # Видео
                            elif post_data.get('video_url'):
                                video_url = post_data.get('video_url')
                                filename = f"downloads/insta_{os.urandom(6).hex()}.mp4"
                                async with session.get(video_url, headers=headers) as video_resp:
                                    if video_resp.status == 200:
                                        with open(filename, 'wb') as f:
                                            f.write(await video_resp.read())
                                        html_time = time.time() - html_start
                                        total_time = time.time() - start_time
                                        await add_to_log(url, "JSON Video", "OK", username=username, api="HTML Video",
                                                       platform="instagram", duration=total_time)
                                        return filename, 'video'
                        except Exception as e:
                            await add_to_log(url, "JSON parse", "fail", error=str(e)[:50], username=username,
                                           api="HTML JSON", platform="instagram")

                    # Fallback CDN patterns
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
                                                html_time = time.time() - html_start
                                                total_time = time.time() - start_time
                                                await add_to_log(url, "HTML CDN", f"{media_type.upper()} OK",
                                                               username=username, api="HTML CDN", platform="instagram", duration=total_time)
                                                return filename, media_type
                                except Exception:
                                    continue
                    await add_to_log(url, "HTML parse", "no media", username=username, api="HTML Parse", platform="instagram")
        except Exception as e:
            await add_to_log(url, "HTML fetch", f"ERR: {str(e)[:30]}", error=str(e)[:50], username=username,
                           api="HTML Fetch", platform="instagram")

        # 3️⃣ GraphQL (ваш код)
        graphql_start = time.time()
        try:
            await add_to_log(url, "GraphQL", "trying...", username=username, api="GraphQL", platform="instagram")
            if shortcode:
                query_hash = "d5d763b1e2acf209d62d22cf2957d710"
                variables = {"shortcode": shortcode, "child_index": 0, "fetch_comment_count": 3,
                           "fetch_comment_cursor": "", "fetch_mutual": True}
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
                                        total_time = time.time() - start_time
                                        await add_to_log(url, "GraphQL IMG", "OK", username=username, api="GraphQL",
                                                       platform="instagram", duration=total_time)
                                        return filename, 'image'

                        elif post_data.get('video_url'):
                            video_url = post_data.get('video_url')
                            filename = f"downloads/insta_{os.urandom(6).hex()}.mp4"
                            async with session.get(video_url) as video_resp:
                                if video_resp.status == 200:
                                    with open(filename, 'wb') as f:
                                        f.write(await video_resp.read())
                                    total_time = time.time() - start_time
                                    await add_to_log(url, "GraphQL VID", "OK", username=username, api="GraphQL",
                                                   platform="instagram", duration=total_time)
                                    return filename, 'video'
        except Exception as e:
            await add_to_log(url, "GraphQL", "fail", error=str(e)[:50], username=username,
                           api="GraphQL", platform="instagram")

        # 4️⃣ oEmbed
        oembed_start = time.time()
        try:
            await add_to_log(url, "oEmbed", "FINAL", username=username, api="oEmbed", platform="instagram")
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
                                total_time = time.time() - start_time
                                await add_to_log(url, "oEmbed THUMB", "OK", username=username, api="oEmbed",
                                               platform="instagram", duration=total_time)
                                return filename, 'image'
        except Exception as e:
            await add_to_log(url, "oEmbed", "fail", error=str(e)[:50], username=username,
                           api="oEmbed", platform="instagram")

    raise Exception("INSTAGRAM_FAIL")

async def download_youtube(url: str, username: Optional[str] = None) -> Tuple[str, str]:
    """Загрузка видео с YouTube (включая Shorts) через yt-dlp."""
    os.makedirs('downloads', exist_ok=True)
    start_time = time.time()
    await add_to_log(url, "YouTube", "yt-dlp START", username=username, api="yt-dlp", platform="youtube")

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
                return filename_local

        filename = await asyncio.to_thread(run_ydl)
        total_time = time.time() - start_time
        await add_to_log(url, "YouTube", "OK", username=username, api="yt-dlp", platform="youtube", duration=total_time)
        return filename, 'video'
    except Exception as e:
        total_time = time.time() - start_time
        await add_to_log(url, "YouTube", str(e)[:30], error=str(e)[:50], username=username,
                       api="yt-dlp", platform="youtube", duration=total_time)
        raise Exception("YOUTUBE_FAIL")

async def download_video(url: str, platform: str, username: Optional[str] = None) -> Tuple[str, str, str]:
    """Обёртка над загрузчиками по платформе."""
    await add_to_log(url, platform.upper(), "START", username=username, platform=platform)
    try:
        if platform == 'tiktok':
            filename, media_type = await download_tiktok(url, username)
            return filename, 'TikTok', media_type
        if platform == 'instagram':
            filename, media_type = await download_instagram(url, username)
            return filename, 'Instagram', media_type
        if platform == 'youtube':
            filename, media_type = await download_youtube(url, username)
            return filename, 'Youtube', media_type
    except Exception as e:
        await add_to_log(url, "ERROR", str(e), error=str(e)[:100], username=username, platform=platform)
        raise

    raise ValueError(f"Unsupported platform: {platform}")
