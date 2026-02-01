import asyncio
import json
import os
import re
import time
from typing import Optional, Tuple, Union, List, Dict, Any
import subprocess
import aiohttp
import yt_dlp
from config import TIKTOK_APIS, INSTAGRAM_APIS
from utils import add_to_log, username_context
import logging

logger = logging.getLogger(__name__)




async def compress_video_ffmpeg(input_path: str, output_path: str, target_size_mb: float = 40) -> bool:
    """Компрессия видео FFmpeg H.265 → <40MB (Telegram safe)."""
    try:
        # Проверяем FFmpeg в PATH
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        
        cmd = [
            'ffmpeg', '-y', '-i', input_path,
            '-vf', 'scale=-2:720', # 720p
            '-c:v', 'libx265', '-crf', '26', '-preset', 'fast',
            '-c:a', 'aac', '-b:a', '128k',
            '-maxrate', '1500k', '-bufsize', '3000k',
            '-t', '180', # Макс 3 мин
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

async def download_file(url: str, filename: str, session: aiohttp.ClientSession, headers: dict) -> str:
    """Универсальная загрузка файла по прямой ссылке"""
    os.makedirs('downloads', exist_ok=True)
    async with session.get(url, headers=headers) as resp:
        if resp.status == 200:
            with open(filename, 'wb') as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)
            return filename
    raise Exception("FILE_DOWNLOAD_FAIL")

async def download_tiktok(url: str, username: Optional[str] = None) -> Tuple[Union[str, Dict], str]:
    """TikTok: API → AutoCompress → yt-dlp fallback"""
    os.makedirs('downloads', exist_ok=True)
    start_time = time.time()
    
    # Photo skip
    # Photo skip removed
    # if '/photo/' in url.lower():
    #     await add_to_log(url, "TikTok фото", "ОСТАВЛЯЕМ ССЫЛКУ", username=username, platform="tiktok")
    #     raise Exception("PHOTO")
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25), headers=headers) as session:
        video_candidate = None
        
        # 1️⃣ API попытки (с приоритетом слайдшоу)
        for i, api_base in enumerate(TIKTOK_APIS, 1):
            api_name = api_base.split('/')[2] if '/' in api_base else api_base[:30]
            api_start = time.time()
            
            try:
                # Log only if it's the first attempt or if we don't have a candidate yet
                if not video_candidate:
                    await add_to_log(url, f"TikTok API {i}", f"Checking...",
                                   username=username, api=api_name, platform="tiktok")
                
                async with session.get(api_base + url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('code') == 0:
                            
                            # 📸 SLIDESHOW (IMAGES) - IMMEDIATE SUCCESS
                            if data['data'].get('images'):
                                try:
                                    images = data['data']['images']
                                    music_url = data['data']['music']
                                    short_id = re.search(r'tiktok.com/([^\s/]+)', url).group(1)[:8] if 'tiktok.com' in url else os.urandom(6).hex()
                                    
                                    await add_to_log(url, f"TikTok API {i}", f"SLIDESHOW: {len(images)} imgs",
                                                   username=username, api=api_name, platform="tiktok")
                                    
                                    # Скачиваем картинки
                                    image_paths = []
                                    for idx, img_url in enumerate(images):
                                        img_filename = f"downloads/tiktok_slide_{short_id}_{idx}.jpg"
                                        await download_file(img_url, img_filename, session, headers)
                                        image_paths.append(img_filename)
                                    
                                    # Скачиваем музыку
                                    audio_path = f"downloads/tiktok_audio_{short_id}.mp3"
                                    await download_file(music_url, audio_path, session, headers)
                                    
                                    total_time = time.time() - start_time
                                    await add_to_log(url, f"TikTok API {i}", f"SLIDESHOW OK {len(image_paths)} pics",
                                                   username=username, api=api_name, platform="tiktok", duration=total_time)
                                    
                                    return {'images': image_paths, 'audio': audio_path}, 'slideshow'
                                    
                                except Exception as e:
                                    logger.error(f"Slideshow download error: {e}")
                                    # Continue searching...
                                    
                            # 📹 VIDEO FOUND - STORE CANDIDATE
                            if not video_candidate:
                                video_url = data['data']['play']
                                short_id = re.search(r'tiktok.com/([^\s/]+)', url).group(1)[:8] if 'tiktok.com' in url else os.urandom(6).hex()
                                video_candidate = {
                                    'url': video_url,
                                    'id': short_id,
                                    'api': api_name,
                                    'i': i
                                }
                                # Don't return yet! Look for slideshow in other APIs
                                await add_to_log(url, f"TikTok API {i}", f"Video found (looking for slides...)",
                                               username=username, api=api_name, platform="tiktok")
                            
            except Exception as e:
                pass # Silent fail during search
                
        # 🏁 LOOP FINISHED - CHECK CANDIDATE
        if video_candidate:
            try:
                vc = video_candidate
                raw_filename = f"downloads/tiktok_raw_{vc['id']}.mp4"
                
                # Скачиваем
                file_path = await download_file(vc['url'], raw_filename, session, headers)
                
                # ✅ АВТОКОМПРЕССИЯ >40MB
                file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                final_filename = file_path
                
                if file_size_mb > 40:
                    await add_to_log(url, "TikTok RAW", f"{file_size_mb:.1f}MB → COMPRESS",
                                   username=username, api=vc['api'], platform="tiktok")
                    compressed_filename = file_path.replace('raw_', 'opt_')
                    
                    if await compress_video_ffmpeg(file_path, compressed_filename):
                        os.remove(file_path)
                        final_filename = compressed_filename
                    else:
                        # Fallback trim
                        trimmed_filename = file_path.replace('raw_', 'trim_')
                        subprocess.run([
                            'ffmpeg', '-y', '-i', file_path, '-t', '180', '-c', 'copy', trimmed_filename
                        ], capture_output=True)
                        os.remove(file_path)
                        final_filename = trimmed_filename
                
                total_time = time.time() - start_time
                final_size_mb = os.path.getsize(final_filename) / (1024 * 1024)
                await add_to_log(url, f"TikTok API {vc['i']}", f"VIDEO OK {final_size_mb:.1f}MB ✓",
                               username=username, api=vc['api'], platform="tiktok", duration=total_time)
                return final_filename, 'video'
            except Exception as e:
                 logger.error(f"Video candidate download failed: {e}")
                 # Fallback to YT-DLP if candidate failed logic
        
        # 2️⃣ YT-DLP FALLBACK (100% работает)
        await add_to_log(url, "YT-DLP", "TikTok FAILBACK START", username=username, platform="tiktok")
        try:
            # Сначала получаем инфо без скачивания
            info_opts = {'quiet': True, 'extract_flat': False}
            
            def get_info():
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            info = await asyncio.to_thread(get_info)
            
            # 📸 SLIDESHOW CHECK (YT-DLP)
            if info.get('_type') == 'playlist' or (info.get('entries') and len(info['entries']) > 0):
                 await add_to_log(url, "YT-DLP", "SLIDESHOW DETECTED", username=username, platform="tiktok")
                 
                 image_urls = []
                 # Пытаемся найти картинки
                 if info.get('entries'):
                     for entry in info['entries']:
                         # yt-dlp для tiktok slideshow часто возвращает список, где каждое entry - это url картинки или видео
                         if entry.get('url'):
                             image_urls.append(entry['url'])
                         elif entry.get('thumbnails'): # Иногда тут
                             image_urls.append(entry['thumbnails'][-1]['url'])

                 # Если не нашли в entries, иногда они в formats (редко для yt-dlp slideshow)
                 
                 if image_urls:
                     image_paths = []
                     for idx, img_url in enumerate(image_urls):
                         filename = f"downloads/tiktok_yt_{os.urandom(6).hex()}_{idx}.jpg"
                         await download_file(img_url, filename, session, headers)
                         image_paths.append(filename)
                     
                     # Audio
                     audio_path = None
                     # Пытаемся найти аудио ссылку
                     # Часто в info есть 'requested_downloads' или 'url' pointing to mp3 if extracted
                     # Для простоты, попробуем скачать аудио отдельно через yt-dlp 'bestaudio'
                     
                     audio_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': f'downloads/tiktok_audio_yt_{os.urandom(6).hex()}.%(ext)s',
                        'quiet': True,
                     }
                     
                     def download_audio():
                        with yt_dlp.YoutubeDL(audio_opts) as ydl:
                            return ydl.prepare_filename(ydl.extract_info(url, download=True))

                     try:
                         audio_path = await asyncio.to_thread(download_audio)
                     except Exception as e:
                         logger.warning(f"Audio download failed: {e}")

                     return {'images': image_paths, 'audio': audio_path}, 'slideshow'

            # Если не слайдшоу, качаем как видео
            ydl_opts = {
                'format': 'best[height<=720][ext=mp4]/best',
                'outtmpl': f'downloads/tiktok_fallback_{os.urandom(6).hex()}.%(ext)s',
                'quiet': True,
            }
            
            def run_yt_dlp():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info)
            
            fallback_filename = await asyncio.to_thread(run_yt_dlp)
            
            # Компрессия fallback
            file_size_mb = os.path.getsize(fallback_filename) / (1024 * 1024)
            final_filename = fallback_filename
            
            if file_size_mb > 40:
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
    """🚀 Instagram Reels 2026: 6 API + HTML + GraphQL + yt-dlp ULTIMATE FALLBACK"""
    os.makedirs('downloads', exist_ok=True)
    start_time = time.time()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.instagram.com/', 'Origin': 'https://www.instagram.com'
    }
    
    # Shortcode extraction
    shortcode_match = re.search(r'/([A-Za-z0-9_-]{11})/?', url)
    shortcode = shortcode_match.group(1) if shortcode_match else ''
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35), headers=headers) as session:
        # 🔥 1. НОВЫЕ РАБОЧИЕ API 2026 (замена мёртвых)
        for i, api_base in enumerate(INSTAGRAM_APIS, 1):
            api_name = api_base.split('/')[2]
            api_start = time.time()
            
            try:
                await add_to_log(url, f"Insta API {i}", f"{api_name} | API: {api_name}",
                               username=username, api=api_name, platform="instagram")
                
                api_url = api_base + url
                async with session.get(api_url) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        
                        # Современные Reels patterns
                        patterns = [
                            r'"(https://[^"\s]+scontent[^"\s]+(?:jpg|jpeg|mp4))"',
                            r'"download_url":"(https://[^"]+scontent[^"]+(?:jpg|mp4))"',
                            r'"video_url":"(https://[^"]+scontent[^"]+\.mp4)"',
                            r'src="(https://[^"\s]+scontent[^"\s]+(?:jpg|mp4))"'
                        ]
                        
                        for pattern in patterns:
                            match = re.search(pattern, content, re.IGNORECASE)
                            if match:
                                media_url = match.group(1).replace('\\\\', '')
                                if 'scontent' in media_url:
                                    ext = 'jpg' if any(x in media_url.lower() for x in ['.jpg', '.jpeg']) else 'mp4'
                                    filename = f"downloads/insta_api_{os.urandom(6).hex()}.{ext}"
                                    
                                    file_path = await download_file(media_url, filename, session, headers)
                                    
                                    # Автокомпрессия видео
                                    if ext == 'mp4' and os.path.getsize(file_path) > 40 * 1024 * 1024:
                                        compressed = file_path.replace('.mp4', '_opt.mp4')
                                        if await compress_video_ffmpeg(file_path, compressed):
                                            os.remove(file_path)
                                            file_path = compressed
                                    
                                    total_time = time.time() - start_time
                                    await add_to_log(url, f"Insta API {i}", f"{ext.upper()} OK ✓",
                                                   username=username, api=api_name, platform="instagram", duration=total_time)
                                    return file_path, ext
            except Exception as e:
                api_time = time.time() - api_start
                await add_to_log(url, f"Insta API {i}", f"ERR: {str(e)[:30]}",
                               error=str(e)[:50], username=username, api=api_name,
                               platform="instagram", duration=api_time)
                await asyncio.sleep(0.3)
        
        # 2️⃣ HTML + JSON parsing (ваш оригинал)
        await add_to_log(url, "Instagram HTML", "scraping...", username=username, api="HTML Parse", platform="instagram")
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    
                    # window._sharedData
                    json_match = re.search(r'window\._sharedData = ({.*?});', html, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            entry_data = data.get('entry_data', {}).get('PostPage', [{}])[0]
                            post_data = entry_data.get('graphql', {}).get('shortcode_media', {})
                            
                            # Image
                            if post_data.get('__typename') == 'GraphImage':
                                img_url = post_data.get('display_url')
                                if img_url and 'scontent' in img_url:
                                    filename = f"downloads/insta_{os.urandom(6).hex()}.jpg"
                                    file_path = await download_file(img_url, filename, session, headers)
                                    await add_to_log(url, "JSON Image", "OK", username=username, api="HTML JSON", platform="instagram")
                                    return file_path, 'image'
                            
                            # Video/Reel
                            elif post_data.get('video_url'):
                                video_url = post_data.get('video_url')
                                filename = f"downloads/insta_{os.urandom(6).hex()}.mp4"
                                file_path = await download_file(video_url, filename, session, headers)
                                
                                # Компрессия
                                if os.path.getsize(file_path) > 40 * 1024 * 1024:
                                    compressed = file_path.replace('.mp4', '_opt.mp4')
                                    if await compress_video_ffmpeg(file_path, compressed):
                                        os.remove(file_path)
                                        file_path = compressed
                                
                                await add_to_log(url, "JSON Video", "OK", username=username, api="HTML Video", platform="instagram")
                                return file_path, 'video'
                        except:
                            pass
                    
                    # CDN fallback patterns (ваш код)
                    cdn_patterns = [
                        r'"display_url":"(https://[^"]+scontent[^"]+(?:jpg|jpeg))"',
                        r'"video_url":"(https://[^"]+scontent[^"]+\.mp4)"'
                    ]
                    for pattern in cdn_patterns:
                        match = re.search(pattern, html, re.IGNORECASE)
                        if match and 'scontent' in match.group(1):
                            media_url = match.group(1)
                            ext = 'jpg' if '.jpg' in media_url or '.jpeg' in media_url else 'mp4'
                            filename = f"downloads/insta_{os.urandom(6).hex()}.{ext}"
                            file_path = await download_file(media_url, filename, session, headers)
                            await add_to_log(url, "HTML CDN", f"{ext.upper()} OK", username=username, api="HTML CDN", platform="instagram")
                            return file_path, ext
                    
            await add_to_log(url, "HTML parse", "no media", username=username, api="HTML Parse", platform="instagram")
        except Exception as e:
            await add_to_log(url, "HTML fetch", f"ERR: {str(e)[:30]}", username=username, api="HTML Fetch", platform="instagram")
        
        # 3️⃣ GraphQL (ваш оригинал)
        await add_to_log(url, "GraphQL", "trying...", username=username, api="GraphQL", platform="instagram")
        if shortcode:
            try:
                query_hash = "d5d763b1e2acf209d62d22cf2957d710"
                variables = {"shortcode": shortcode, "child_index": 0, "fetch_comment_count": 3,
                           "fetch_comment_cursor": "", "fetch_mutual": True}
                graphql_url = f"https://www.instagram.com/graphql/query/?query_hash={query_hash}&variables={json.dumps(variables)}"
                
                async with session.get(graphql_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        post_data = data.get('data', {}).get('shortcode_media', {})
                        
                        if post_data.get('__typename') == 'GraphImage' and post_data.get('display_url'):
                            filename = f"downloads/insta_gql_{os.urandom(6).hex()}.jpg"
                            return await download_file(post_data['display_url'], filename, session, headers), 'image'
                        elif post_data.get('video_url'):
                            filename = f"downloads/insta_gql_{os.urandom(6).hex()}.mp4"
                            file_path = await download_file(post_data['video_url'], filename, session, headers)
                            # Компрессия
                            if os.path.getsize(file_path) > 40 * 1024 * 1024:
                                compressed = file_path.replace('.mp4', '_opt.mp4')
                                if await compress_video_ffmpeg(file_path, compressed):
                                    os.remove(file_path)
                                    file_path = compressed
                            return file_path, 'video'
            except:
                pass
        
        # 4️⃣ oEmbed
        await add_to_log(url, "oEmbed", "FINAL", username=username, api="oEmbed", platform="instagram")
        try:
            oembed_url = f"https://www.instagram.com/oembed/?url={url}"
            async with session.get(oembed_url, headers={'User-Agent': headers['User-Agent']}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('thumbnail_url'):
                        filename = f"downloads/insta_oembed_{os.urandom(6).hex()}.jpg"
                        return await download_file(data['thumbnail_url'], filename, session, headers), 'image'
        except:
            pass
        
        # 🔥🔥 ULTIMATE YT-DLP FALLBACK (СПАСЁТ ВСЁ!)
        await add_to_log(url, "yt-dlp ULTIMATE", "Instagram FAIL → yt-dlp rescue!", username=username, platform="instagram")
        try:
            ydl_opts = {
                'format': 'best[filesize<50M][height<=720]/best',
                'outtmpl': f'downloads/instagram_yt_{os.urandom(6).hex()}.%(ext)s',
                'quiet': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios']
                    }
                }
            }
            
            def run_yt_dlp():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    # Fix webm
                    if filename.endswith('.webm'):
                        subprocess.run(['ffmpeg', '-y', '-i', filename, filename.replace('.webm', '.mp4')], 
                                     capture_output=True, quiet=True)
                        filename = filename.replace('.webm', '.mp4')
                    return filename
            
            final_filename = await asyncio.to_thread(run_yt_dlp)
            
            # Финальная компрессия
            if os.path.getsize(final_filename) > 40 * 1024 * 1024:
                compressed = final_filename.replace('.mp4', '_final.mp4')
                await compress_video_ffmpeg(final_filename, compressed)
                os.remove(final_filename)
                final_filename = compressed
            
            await add_to_log(url, "YT-DLP Instagram", "RESCUE SUCCESS ✓", username=username, platform="instagram")
            return final_filename, 'video'
        
        except Exception as e:
            await add_to_log(url, "YT-DLP FAIL", str(e)[:50], username=username, platform="instagram")
        
        await add_to_log(url, "ERROR", "INSTAGRAMFAIL", username=username)
        raise Exception("INSTAGRAM_FAIL")

async def download_youtube(url: str, username: Optional[str] = None) -> Tuple[str, str]:
    """YouTube Shorts через yt-dlp (ваш оригинал + улучшения)"""
    os.makedirs('downloads', exist_ok=True)
    start_time = time.time()
    
    await add_to_log(url, "YouTube", "yt-dlp START", username=username, api="yt-dlp", platform="youtube")
    
    ydl_opts = {
        'format': 'best[filesize<50M][height<=720]/best',
        'outtmpl': f'downloads/youtube_{os.urandom(6).hex()}.%(ext)s',
        'quiet': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios']
            }
        }
    }
    
    try:
        def run_ydl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                # Webm → mp4
                if filename.endswith('.webm'):
                    subprocess.run(['ffmpeg', '-y', '-i', filename, filename.replace('.webm', '.mp4')], 
                                 capture_output=True)
                    return filename.replace('.webm', '.mp4')
                return filename
        
        filename = await asyncio.to_thread(run_ydl)
        
        # Компрессия если нужно
        if os.path.getsize(filename) > 40 * 1024 * 1024:
            compressed = filename.replace('.mp4', '_opt.mp4')
            if await compress_video_ffmpeg(filename, compressed):
                os.remove(filename)
                filename = compressed
        
        total_time = time.time() - start_time
        await add_to_log(url, "YouTube", f"OK {os.path.getsize(filename)/(1024*1024):.1f}MB", 
                        username=username, api="yt-dlp", platform="youtube", duration=total_time)
        return filename, 'video'
    
    except Exception as e:
        total_time = time.time() - start_time
        await add_to_log(url, "YouTube FAIL", str(e)[:30], username=username, api="yt-dlp", platform="youtube")
        raise Exception("YOUTUBE_FAIL")

async def download_video(url: str, platform: str, username: Optional[str] = None) -> Tuple[Union[str, Dict], str, str]:
    """Главная точка входа (роутинг + полный fallback)"""
    await add_to_log(url, platform.upper(), "START", username=username, platform=platform)
    
    try:
        if platform == 'tiktok':
            filename, media_type = await download_tiktok(url, username)
            return filename, 'TikTok', media_type
        elif platform == 'instagram':
            try:
                filename, media_type = await download_instagram(url, username)
                return filename, 'Instagram', media_type
            except Exception as e:
                if "INSTAGRAM_FAIL" in str(e):
                    logger.warning(f"Instagram ALL FAIL → ULTIMATE yt-dlp для {username}")
                    filename, media_type = await download_youtube(url, username)  # Используем youtube func как universal
                    return filename, 'Instagram(yt-dlp)', media_type
                raise
        elif platform == 'youtube':
            filename, media_type = await download_youtube(url, username)
            return filename, 'Youtube', media_type
        else:
            raise ValueError(f"Unknown platform: {platform}")
    except Exception as e:
        await add_to_log(url, "ERROR", str(e), username=username, platform=platform)
        raise
