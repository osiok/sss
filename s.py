import os
import time
import json
import threading
import sqlite3
import urllib.request
import re
import sys
import requests
import asyncio
import aiohttp
from rubpy import Client
from rubpy import Rubino
from rubpy.types import Update
from config import *
from rubika_client import rubika
from urllib.parse import unquote
from file_utils import is_video_file, is_audio_file, is_image_file, convert_video_to_3gp, create_zip_file, random_filename

bot = Client(
    name=SESSION_NAME,
    timeout=120,            
)

TELEGRAM_ID = "@OSIOK"
WIDTH = 10
print(f"TELEGRAM{TELEGRAM_ID:>{WIDTH}}")

bot.rubino = Rubino(bot)

AUTH_KEY = None
PRIVATE_KEY = None

try:
    with open("account", "r") as f:
        acc = json.load(f)
        AUTH_KEY = acc.get('auth')
        PRIVATE_KEY = acc.get('private_key')
except:
    try:
        conn = sqlite3.connect(ONE_PLUS_RP_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session'")
        if cursor.fetchone():
            cursor.execute("SELECT auth, private_key FROM session LIMIT 1")
            row = cursor.fetchone()
            if row:
                AUTH_KEY = row[0]
                PRIVATE_KEY = row[1]
        conn.close()
    except Exception as e:
        print(f"❌ خطا در خواندن OnePlus7.rp: {e}")

rb = None
if AUTH_KEY:
    try:
        rb = rubika(auth=AUTH_KEY)
    except Exception as e:
        print(f"⚠️ خطا در ساخت rubika: {e}")

current_target = None
user_temp_data = {}
stored_files = {}

def download_file_with_bot_session(url, save_path, timeout=120):
    try:
        loop = bot.connection.session._loop
        async def _download():
            async with bot.connection.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                resp.raise_for_status()
                with open(save_path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
                        f.write(chunk)
            return True
        future = asyncio.run_coroutine_threadsafe(_download(), loop)
        future.result()
        return True
    except Exception as e:
        print(f"❌ خطا در دانلود با session: {e}")
        return False
    
def load_stored_files():
    global stored_files
    try:
        with open(STORED_FILES_JSON, "r", encoding='utf-8') as f:
            data = json.load(f)
            stored_files = {int(k): v for k, v in data.items()}
    except:
        print("⚠️ فایل stored_files.json وجود ندارد.")
def get_rubino_post_info(post_url):
    try:
        share_string = post_url.rstrip('/').split('/')[-1]
        payload = {
            "api_version": "0",
            "auth": bot.auth,
            "client": bot.rubino.DEFAULT_PLATFORM,
            "data": {
                "share_string": share_string,
            },
            "method": "getPostByShareLink"
        }
        url = bot.rubino.url  
        headers = {
            "User-Agent": bot.user_agent,
            "Content-Type": "application/json"
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get('status') != 'OK':
            print(f"⚠️ پاسخ روبینو ناموفق: {result}")
            return (None, None, None, None)
        post = result.get('data', {}).get('post', {})
        if not post:
            return (None, None, None, None)

        file_url = post.get('full_file_url')
        if not file_url:
            return (None, None, None, None)

        file_name = os.path.basename(file_url.split('?')[0])
        if not file_name or '.' not in file_name:
            file_name = f"rubino_{share_string}.mp4"  

        file_type = post.get('file_type', '').lower()
        if file_type == 'video':
            our_type = 'video'
        elif file_type == 'picture':
            our_type = 'image'
        else:
            our_type = 'other'

        caption = post.get('caption', '')  # <-- کپشن پست

        return (file_url, file_name, our_type, caption)
    except Exception as e:
        print(f"❌ خطا در دریافت پست روبینو: {e}")
        return (None, None, None, None)
    
def save_stored_files():
    serializable = {str(k): v for k, v in stored_files.items()}
    with open(STORED_FILES_JSON, "w", encoding='utf-8') as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)

def load_target():
    global current_target
    try:
        with open(TARGET_SAVE_FILE, "r") as f:
            data = json.load(f)
            current_target = data.get("target", DEFAULT_TARGET_GUID)
    except:
        current_target = DEFAULT_TARGET_GUID

def save_target():
    with open(TARGET_SAVE_FILE, "w") as f:
        json.dump({"target": current_target}, f)

load_stored_files()
load_target()

user_settings = {
    "always_convert_to_3gp": False,
    "default_caption": None,
    "keep_temp_files": False,
    "source_folder": None
}

SETTINGS_FILE = "user_settings.json"

def load_settings():
    global user_settings
    try:
        with open(SETTINGS_FILE, "r", encoding='utf-8') as f:
            saved = json.load(f)
            user_settings.update(saved)
    except:
        pass

def save_settings():
    with open(SETTINGS_FILE, "w", encoding='utf-8') as f:
        json.dump(user_settings, f, ensure_ascii=False, indent=2)

load_settings()

CAPTION_FILTERS = {
    # مثال:
    # "@Skinclarity": None,      # حذف کامل کلمه
    # "کلمه_ناخواسته": "جایگزین",
}

def clean_caption(text):
    if not text:
        return ''
    for word, replacement in CAPTION_FILTERS.items():
        if replacement is None:
            text = re.sub(r'\s*' + re.escape(word) + r'\s*', ' ', text)
        else:
            text = text.replace(word, replacement)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def delete_messages_after_delay(chat_id, msg_ids, delay):
    time.sleep(delay)
    for mid in msg_ids:
        try:
            bot.delete_message(object_guid=chat_id, message_id=mid)
        except:
            pass

def delete_message_after_delay(chat_id, msg_id, delay):
    delete_messages_after_delay(chat_id, [msg_id], delay)

def save_file_info(message_id, file_info):
    stored_files[message_id] = file_info
    save_stored_files()

def download_file_from_info(message_id, custom_name=None, progress_chat_id=None, progress_msg_id=None):
    """دانلود ساده و قابل اطمینان بدون چندبخشی"""
    print(f"[DEBUG] download_file_from_info called - message_id: {message_id}")
    
    file_info = stored_files.get(message_id)
    if not file_info:
        try:
            with open(STORED_FILES_JSON, "r", encoding='utf-8') as f:
                all_data = json.load(f)
                file_info = all_data.get(str(message_id))
                if file_info:
                    stored_files[message_id] = file_info
                    print(f"🔄 اطلاعات فایل {message_id} از فایل JSON بازیابی شد.")
        except:
            pass
        if not file_info:
            print(f"[ERROR] File info not found for message_id: {message_id}")
            return None
    
    file_inline = file_info['file_inline']
    original_name = file_info['original_filename']
    
    if custom_name:
        custom_name = unquote(custom_name)
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            custom_name = custom_name.replace(char, '_')
        final_name = custom_name
        if not os.path.splitext(custom_name)[1]:
            ext = os.path.splitext(original_name)[1]
            final_name = custom_name + ext
    else:
        final_name = original_name

    file_data = {
        'file_id': file_inline.get('file_id'),
        'access_hash_rec': file_inline.get('access_hash_rec'),
        'dc_id': file_inline.get('dc_id'),
        'size': file_inline.get('size', 0)
    }

    if not file_data['file_id'] or not file_data['access_hash_rec'] or not rb:
        print(f"[ERROR] Invalid file_data: {file_data}")
        return None

    os.makedirs(TEMP_DIR, exist_ok=True)
    
    base_path = os.path.join(TEMP_DIR, final_name)
    name_without_ext, ext = os.path.splitext(base_path)
    timestamp = int(time.time() * 1000)
    save_path = f"{name_without_ext}_{timestamp}{ext}"
    print(f"📁 ذخیره در: {os.path.basename(save_path)}")

    real_total_size = file_data.get('size', 0)
    print(f"📊 حجم واقعی فایل: {real_total_size/(1024**2):.1f} MB")

    last_percent = -1

    def progress(downloaded, total, args):
        nonlocal last_percent
        effective_total = real_total_size if real_total_size > 0 else total
        p = (downloaded / effective_total) * 100 if effective_total > 0 else 0
        print(f"\r⏳ دانلود: {p:.1f}% ({downloaded}/{effective_total} bytes)", end='')
        sys.stdout.flush()
        
        if progress_chat_id and progress_msg_id and int(p) != last_percent and (int(p) % 10 == 0 or p >= 100):
            last_percent = int(p)
            try:
                if progress_msg_id and str(progress_msg_id).isdigit():
                    bot.edit_message(
                        object_guid=progress_chat_id,
                        message_id=int(progress_msg_id),
                        text=f"**⏳ دانلود فایل... {p:.1f}%**"
                    )
            except Exception as e:
                print(f"\n⚠️ خطا در ادیت پیام: {e}")

    max_retries = 7
    retry_delay = 3
    
    for attempt in range(max_retries):
        try:
            rb.download(file_data, save_path, progress, None)
            print(f"\n✅ دانلود کامل شد: {save_path}")
            
            downloaded_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
            
            if downloaded_size > 0:
                if real_total_size > 0 and downloaded_size < real_total_size * 0.95:
                    print(f"⚠️ دانلود ناقص، تلاش مجدد...")
                    os.remove(save_path)
                    time.sleep(retry_delay)
                    continue
                return save_path
            else:
                raise Exception("فایل دانلود شده خالی است")
                
        except Exception as e:
            print(f"\n❌ خطا در دانلود (تلاش {attempt+1}): {e}")
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except:
                    pass
            
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                print(f"🔄 تلاش مجدد در {wait_time} ثانیه...")
                time.sleep(wait_time)
            else:
                print(f"❌ دانلود پس از {max_retries} تلاش ناموفق بود")
                return None
    
    return None

def handle_forwarded_file(update):
    try:
        
        if not getattr(update, 'is_forward', False):
            return False
        
        file_inline = getattr(update, 'file_inline', None)
        if not file_inline and isinstance(update.message, dict):
            file_inline = update.message.get('file_inline')
        if not file_inline:
            return False

        if not isinstance(file_inline, dict):
            file_inline = {
                'file_id': getattr(file_inline, 'file_id', None),
                'access_hash_rec': getattr(file_inline, 'access_hash_rec', None),
                'dc_id': getattr(file_inline, 'dc_id', None),
                'file_name': getattr(file_inline, 'file_name', 'downloaded_file.bin'),
                'mime': getattr(file_inline, 'mime', ''),
                'type': getattr(file_inline, 'type', ''),
                'music_performer': getattr(file_inline, 'music_performer', None),
                'size': getattr(file_inline, 'size', 0),
                'time': getattr(file_inline, 'time', 0),
            }

        original_filename = unquote(file_inline.get('file_name', 'downloaded_file.bin'))
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            original_filename = original_filename.replace(char, '_')
        
        mime = file_inline.get('mime', '').lower()
        type_val = file_inline.get('type', '').lower()
        ext = os.path.splitext(original_filename)[1].lower().strip('.')
        
        file_type = 'other'
        if mime.startswith('video/'):
            file_type = 'video'
        elif mime.startswith('audio/') or type_val == 'music':
            file_type = 'audio'
        elif mime.startswith('image/'):
            file_type = 'image'
        else:
            if ext in ['mp4', 'mkv', 'avi', 'mov', '3gp', 'webm']:
                file_type = 'video'
            elif ext in ['mp3', 'ogg', 'wav', 'flac', 'm4a']:
                file_type = 'audio'
            elif ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                file_type = 'image'

        message_id = update.message_id
        if not message_id:
            return False

        save_file_info(message_id, {
            'original_filename': original_filename,
            'file_type': file_type,
            'file_inline': file_inline,
            'performer': file_inline.get('music_performer', 'ناشناس'),
            'title': os.path.splitext(original_filename)[0],
            'size': file_inline.get('size', 0),
            'duration': file_inline.get('time', 0)
        })
        
        update.reply(f"📥 فایل `{original_filename}` ثبت شد.\nبرای دانلود ریپلی کن و بنویس `دان`")
        return True
    except Exception as e:
        print(f"خطا در handle_forwarded_file: {e}")
        return False

def ask_for_file_choice(update, original_filename, file_type, bot_msg_ids, target_msg_id=None, new_filename=None, caption=None, user_id=None):
    
    if file_type == 'video' and user_settings.get('always_convert_to_3gp'):
        user_temp_data[user_id] = {
            'step': 'waiting_choice_file',
            'original_filename': original_filename,
            'file_type': file_type,
            'target_message_id': target_msg_id,
            'chat_id': update.chat_id,
            'bot_msg_ids': bot_msg_ids,
            'new_filename': new_filename,
            'caption': caption
        }
        process_choice_file(update, '2', user_id)
        return

    if file_type == 'video':
        q = "**🎬 داداش یه ویدیو دادی!**\n\n**چیکار باهاش کنم؟**\n1️⃣ خود ویدیو بفرستم\n2️⃣ تبدیل به 3gp\n3️⃣ فایل معمولی\n0️⃣ انصراف"
    elif file_type == 'audio':
        q = "**🎵 آهه یه فایل صوتی!**\n\n**چطور بفرستمش؟**\n**1️⃣ به‌عنوان آهنگ (قابل پخش)**\n**2️⃣ به‌عنوان فایل معمولی**\n**0️⃣ بیخیال**\n\n**عددشو بگو رفیق:**"
    elif file_type == 'image':
        q = "**🖼️ یه عکس قشنگ!**\n\n**چکار کنم؟**\n**1️⃣ به‌عنوان عکس بفرستم**\n**2️⃣ به‌عنوان فایل معمولی بفرستم**\n**0️⃣ نه الان نه**\n\n**عددشو بگو:**"
    else:
        q = "**📁 یه فایل معمولی گرفتم.**\n\n**باهاش چیکار کنم؟**\n**1️⃣ همونطوری بفرستم**\n**2️⃣ بزنمش تو زیپ بفرستم**\n**0️⃣ ولش کن**\n\n**عددشو بگو داداش:**"

    sent = update.reply(q)
    bot_msg_ids.append(sent.message_id)
    user_temp_data[user_id] = {
        'step': 'waiting_choice_file',
        'original_filename': original_filename,
        'file_type': file_type,
        'question_msg_id': sent.message_id,
        'chat_id': update.chat_id,
        'bot_msg_ids': bot_msg_ids,
        'target_message_id': target_msg_id,
        'new_filename': new_filename,
        'caption': caption
    }
    threading.Thread(target=delete_message_after_delay, args=(update.chat_id, sent.message_id, 60)).start()

def process_choice_file(update, choice_text, user_id=None):
    
    data = user_temp_data.get(user_id)
    if not data or data.get('step') != 'waiting_choice_file':
        return False
    
    try:
        bot.delete_message(object_guid=data['chat_id'], message_id=data['question_msg_id'])
    except:
        pass
    
    bot_msg_ids = data['bot_msg_ids']
    
    if choice_text == '0':
        cancel_msg = update.reply("❌ انصراف.")
        bot_msg_ids.append(cancel_msg.message_id)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 3)).start()
        user_temp_data.pop(user_id, None)
        return True

    file_type = data['file_type']
    original_filename = data['original_filename']
    new_filename = data.get('new_filename')
    caption = data.get('caption')
    target_msg_id = data.get('target_message_id')

    if not target_msg_id:
        target_msg_id = update.reply_to_message_id if hasattr(update, 'reply_to_message_id') else None
        if not target_msg_id:
            error_msg = update.reply("❌ شناسه پیام یافت نشد.")
            bot_msg_ids.append(error_msg.message_id)
            threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 5)).start()
            user_temp_data.pop(user_id, None)
            return True

    file_info = stored_files.get(target_msg_id)
    if not file_info:
        try:
            with open(STORED_FILES_JSON, "r", encoding='utf-8') as f:
                all_data = json.load(f)
                file_info = all_data.get(str(target_msg_id))
                if file_info:
                    stored_files[target_msg_id] = file_info
        except:
            pass
        if not file_info:
            error_msg = update.reply("❌ اطلاعات فایل یافت نشد.")
            bot_msg_ids.append(error_msg.message_id)
            threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 5)).start()
            user_temp_data.pop(user_id, None)
            return True

    valid = {'video': ['1','2','3'], 'audio': ['1','2'], 'image': ['1','2'], 'other': ['1','2']}
    if choice_text not in valid.get(file_type, []):
        error_msg = update.reply("**❌ انتخاب نامعتبر.**")
        bot_msg_ids.append(error_msg.message_id)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 3)).start()
        user_temp_data.pop(user_id, None)
        return True

    status_msg = update.reply("**⏳ یه لحظه...**")
    bot_msg_ids.append(status_msg.message_id)

    final_name = original_filename
    if new_filename:
        ext = os.path.splitext(original_filename)[1]
        final_name = new_filename + ext

    file_path = download_file_from_info(target_msg_id, final_name, data['chat_id'], status_msg.message_id)
    if not file_path:
        error_msg = update.reply("❌ دانلود ناموفق.")
        bot_msg_ids.append(error_msg.message_id)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 5)).start()
        user_temp_data.pop(user_id, None)
        return True

    try:
        bot.delete_message(object_guid=data['chat_id'], message_id=status_msg.message_id)
    except:
        pass

    final_path = file_path
    final_display_name = final_name

    try:
        if file_type == 'video' and choice_text == '2':
            out = os.path.splitext(file_path)[0] + ".3gp"
            out_path = os.path.join(TEMP_DIR, out)
            try:
                import subprocess
                cmd = [
                    'ffmpeg', '-i', file_path,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
                    '-c:a', 'aac', '-b:a', '64k',
                    '-s', '320x240',
                    '-y', out_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    final_path = out_path
                    final_display_name = os.path.basename(out)
                    os.remove(file_path)
                    print(f"✅ تبدیل به 3gp موفق: {out_path}")
                else:
                    print(f"⚠️ تبدیل ویدیو ناموفق. ffmpeg stderr:\n{result.stderr}")
            except FileNotFoundError:
                print("❌ ffmpeg پیدا نشد.")
            except Exception as convert_error:
                print(f"⚠️ خطا در تبدیل: {convert_error}")
        elif file_type == 'other' and choice_text == '2':
            out = file_path + ".zip"
            if create_zip_file(file_path, out):
                final_path = out
                final_display_name = os.path.basename(out)
                os.remove(file_path)

        if RANDOM_FILENAME:
            ext = os.path.splitext(final_display_name)[1]
            final_display_name = random_filename(ext)

        send_success = False
        last_error = None
        
        send_methods = []
        
        if file_type == 'video' and choice_text == '1':
            send_methods = [
                ("ارسال ویدیو", lambda: bot.send_video(object_guid=current_target, video=final_path, file_name=final_display_name, caption=caption)),
                ("ارسال به عنوان فایل معمولی", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=final_display_name, caption=caption)),
            ]
        elif file_type == 'video' and choice_text == '3':
            send_methods = [
                ("ارسال فایل معمولی", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=final_display_name, caption=caption)),
            ]
        elif file_type == 'audio' and choice_text == '1':
            performer = file_info.get('performer', 'ناشناس')
            title = file_info.get('title', original_filename)
            duration = file_info.get('duration', 0)
            send_methods = [
                ("ارسال آهنگ", lambda: bot.send_audio(object_guid=current_target, audio=final_path, file_name=final_display_name, performer=performer, title=title, duration=duration, caption=caption) if hasattr(bot, 'send_audio') else bot.send_music(object_guid=current_target, music=final_path, file_name=final_display_name, performer=performer, title=title, duration=duration, caption=caption)),
            ]
        elif file_type == 'image' and choice_text == '1':
            send_methods = [
                ("ارسال عکس", lambda: bot.send_photo(object_guid=current_target, photo=final_path, file_name=final_display_name, caption=caption)),
            ]
        else:
            send_methods = [
                ("ارسال معمولی", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=final_display_name, caption=caption)),
            ]
        
        for method_name, method_func in send_methods:
            if send_success:
                break

            for attempt in range(1, 6):  
                try:
                    print(f"🔄 {method_name} - تلاش {attempt}/5...")
                    result = method_func()

                    if isinstance(result, dict) and result.get('status') != 'OK':
                        raise Exception(f"Server returned error: {result}")

                    if result is not None:
                        send_success = True
                        print(f"✅ {method_name} موفق شد")
                        break
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    print(f"❌ {method_name} - تلاش {attempt} ناموفق: {error_str}")

                    if 'memory' in str(e).lower():
                        break
                    if attempt < 5:
                        wait_time = 5
                        print(f"⏳ صبر {wait_time} ثانیه و تلاش مجدد...")
                        time.sleep(wait_time)
                    else:
                        break

            if send_success:
                break
        
        if send_success:
            if not user_settings.get('keep_temp_files'):
                try:
                    os.remove(final_path)
                    print(f"🗑️ فایل {final_display_name} پاک شد")
                except:
                    pass
            else:
                print(f"📁 فایل {final_display_name} نگهداری شد")
            
            success_msg = update.reply("**✅ فرستادم.**")
            bot_msg_ids.append(success_msg.message_id)
            threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 3)).start()
        else:
            print(f"📁 فایل در مسیر زیر ذخیره شد: {final_path}")
            update.reply(f"⚠️ خطا در ارسال. فایل در مسیر زیر ذخیره شد:\n`{final_path}`")
            
    except Exception as e:
        error_msg = update.reply(f"❌ خطا: {e}")
        bot_msg_ids.append(error_msg.message_id)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 5)).start()
        
    finally:
        user_temp_data.pop(user_id, None)
    
    return True

def set_target(update, target_value, user_id=None, send_reply=True):
    global current_target
    target_value = target_value.strip()
    
    if not target_value:
        if send_reply:
            ask_for_forward(update, "مقصد", user_id=user_id)
        return
    
    if target_value.startswith(('g0', 'u0', 'c0', 'me')):
        current_target = target_value
        save_target()
        if send_reply:
            if target_value == 'me':
                msg = update.reply("🎯 هدف روی **پیوی خودت** تنظیم شد.")
            else:
                msg = update.reply(f"**✅ هدف با شناسه `{target_value}` تنظیم شد.**")
            threading.Thread(target=delete_message_after_delay, args=(update.chat_id, msg.message_id, 5)).start()
        return
    
    if send_reply:
        reply_msg = update.reply(f"**❌ ورودی نامعتبر. لطفاً یک شناسه (`g0...` یا `u0...` یا `c0...`) یا `me` وارد کن.**\n**یا از روش فوروارد استفاده کن.**")
        threading.Thread(target=delete_message_after_delay, args=(update.chat_id, reply_msg.message_id, 5)).start()
        ask_for_forward(update, target_value, user_id=user_id)

def ask_for_forward(update, username, user_id=None):
    user_temp_data[user_id] = {
        'step': 'waiting_forward',
        'username': username,
        'chat_id': update.chat_id,
        'bot_msg_ids': []
    }
    sent_msg = update.reply("**🔁 یه پیام ازش بفرست ببینم چیه کیه تا برات ثبتش کنم**")
    user_temp_data[user_id]['bot_msg_ids'].append(sent_msg.message_id)
    threading.Thread(target=delete_message_after_delay, args=(update.chat_id, sent_msg.message_id, 60)).start()

def process_forward(update: Update, user_id=None):
    data = user_temp_data.get(user_id)
    if not data or data.get('step') != 'waiting_forward':
        return False
    
    target_guid = None
    if hasattr(update, 'forward_from') and update.forward_from:
        target_guid = getattr(update.forward_from, 'object_guid', None)
    elif hasattr(update, 'fwd_from') and update.fwd_from:
        target_guid = getattr(update.fwd_from, 'object_guid', None)
        if not target_guid and isinstance(update.fwd_from, str):
            target_guid = update.fwd_from
    elif hasattr(update, 'forwarded_from') and update.forwarded_from:
        target_guid = getattr(update.forwarded_from, 'object_guid', None)
    elif hasattr(update, 'forward_date') and update.forward_date:
        if hasattr(update, 'sender_object_guid'):
            target_guid = update.sender_object_guid
    
    if target_guid:
        reply_msg = update.reply(f"**✅ هدف `{target_guid}` ثبت شد.**")
        data['bot_msg_ids'].append(reply_msg.message_id)
        set_target(update, target_guid, user_id=user_id, send_reply=False)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], data['bot_msg_ids'], 3)).start()
        user_temp_data.pop(user_id, None)
        return True
    else:
        error_msg = update.reply("**❌ نتونستم شناسه چت رو تشخیص بدم. دوباره تلاش کن یا شناسه رو دستی بزن.**")
        data['bot_msg_ids'].append(error_msg.message_id)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], data['bot_msg_ids'], 5)).start()
        user_temp_data.pop(user_id, None)
        return False

def show_target(update):
    if current_target:
        if current_target == 'me':
            msg = update.reply("📍 هدف فعلی: **پیوی خودت**")
        else:
            msg = update.reply(f"**📍 هدفمون: `{current_target}`**")
        threading.Thread(target=delete_message_after_delay, args=(update.chat_id, msg.message_id, 5)).start()
    else:
        msg = update.reply("**⚠️ هنوز هدفی تنظیم نشده. با دستور `هدف` یه مقصد انتخاب کن.**")
        threading.Thread(target=delete_message_after_delay, args=(update.chat_id, msg.message_id, 5)).start()

def process_upload(update, url, original_filename, file_type, bot_msg_ids, user_id=None, caption=None):
    print(f"[DEBUG] process_upload - url: {url[:50]}...")
    if user_id in user_temp_data:
        user_temp_data.pop(user_id, None)
        
    if file_type == 'video' and user_settings.get('always_convert_to_3gp'):
        user_temp_data[user_id] = {
            'step': 'waiting_choice',
            'url': url,
            'original_filename': original_filename,
            'file_type': file_type,
            'question_msg_id': None,
            'chat_id': update.chat_id,
            'bot_msg_ids': bot_msg_ids,
            'created_at': time.time(),
            'caption': caption 
        }
        process_choice(update, '2', user_id)
        return

    if file_type == 'video':
        question = "**🎬 داداش یه ویدیو دادی!**\n\n**چیکار باهاش کنم؟**\n**1️⃣ خود ویدیو بفرستم (همون فرمت خودش)**\n**2️⃣ تغییر بدم 3gp بکنم بفرستم**\n**3️⃣ به‌عنوان فایل معمولی بفرستم**\n**0️⃣ نه بابا ولش کن**\n\n**فقط عددشو بگو:**"
    # ... بقیه کد
    elif file_type == 'audio':
        question = "**🎵 آهه یه فایل صوتی!**\n\n**چطور بفرستمش؟**\n**1️⃣ به‌عنوان آهنگ (قابل پخش)**\n**2️⃣ به‌عنوان فایل معمولی**\n**0️⃣ بیخیال**\n\n**عددشو بگو رفیق:**"
    elif file_type == 'image':
        question = "**🖼️ یه عکس قشنگ!**\n\n**چکار کنم؟**\n**1️⃣ به‌عنوان عکس بفرستم**\n**2️⃣ به‌عنوان فایل معمولی بفرستم**\n**0️⃣ نه الان نه**\n\n**عددشو بگو:**"
    else:
        question = "**📁 یه فایل معمولی گرفتم.**\n\n**باهاش چیکار کنم؟**\n**1️⃣ همونطوری بفرستم**\n**2️⃣ بزنمش تو زیپ بفرستم**\n**0️⃣ ولش کن**\n\n**عددشو بگو داداش:**"

    sent_msg = update.reply(question)
    bot_msg_ids.append(sent_msg.message_id)
    user_temp_data[user_id] = {
        'step': 'waiting_choice',
        'url': url,
        'original_filename': original_filename,
        'file_type': file_type,
        'question_msg_id': sent_msg.message_id,
        'chat_id': update.chat_id,
        'bot_msg_ids': bot_msg_ids,
        'created_at': time.time(),
        'caption': caption
    }
    threading.Thread(target=delete_message_after_delay, args=(update.chat_id, sent_msg.message_id, 60)).start()



def process_choice(update, choice_text, user_id=None):
    print(f"[DEBUG] process_choice - choice_text: {choice_text}")
    if user_id not in user_temp_data:
        update.reply("⚠️ شما در حال هیچ عملیاتی نیستید. لطفاً ابتدا یک لینک ارسال کنید.")
        return False
    if choice_text is None or choice_text.strip() == '':
        update.reply("❌ لطفاً یک عدد وارد کنید.\nمثال: `1` یا `2` یا `0`")
        return False
    
    if not choice_text.isdigit() or choice_text not in ['0', '1', '2', '3']:
        update.reply("❌ انتخاب نامعتبر.\nلطفاً یکی از اعداد `0`، `1`، `2` یا `3` را وارد کنید.")
        return False
    
    data = user_temp_data.get(user_id)
    if not data or data.get('step') != 'waiting_choice':
        update.reply("❌ زمان انتخاب به پایان رسیده. لطفاً دوباره لینک را ارسال کنید.")
        return False
    
    user_temp_data.pop(user_id, None)
    
    try:
        bot.delete_message(object_guid=data['chat_id'], message_id=data['question_msg_id'])
    except:
        pass
    
    url = data['url']
    original_filename = data['original_filename']
    file_type = data['file_type']
    bot_msg_ids = data['bot_msg_ids']
        
    if choice_text == '0':
        cancel_msg = update.reply("**❌ انصراف.**")
        bot_msg_ids.append(cancel_msg.message_id)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 3)).start()
        user_temp_data.pop(user_id, None)
        return True
    caption = data.get('caption')
    if caption:
        caption = clean_caption(caption)
    if not caption:
        caption = user_settings.get('default_caption')       

    valid_choices = {'video': ['1','2','3'], 'audio': ['1','2'], 'image': ['1','2'], 'other': ['1','2']}
    if choice_text not in valid_choices.get(file_type, []):
        error_msg = update.reply("**❌ عدد اشتباه.**")
        bot_msg_ids.append(error_msg.message_id)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 3)).start()
        user_temp_data.pop(user_id, None)
        return True

    status_msg = update.reply("**⏳ یه لحظه...**")
    bot_msg_ids.append(status_msg.message_id)
    threading.Thread(target=delete_message_after_delay, args=(data['chat_id'], status_msg.message_id, 5)).start()

    os.makedirs(TEMP_DIR, exist_ok=True)
    temp_input_path = os.path.join(TEMP_DIR, original_filename)
    
    try:
        if 'iranlms.ir' in url or 'rubika.ir' in url:
            success = download_file_with_bot_session(url, temp_input_path)
            if not success or os.path.getsize(temp_input_path) == 0:
                raise Exception("دانلود با session ربات ناموفق بود")
            total_size = os.path.getsize(temp_input_path)
            print(f"\n✅ دانلود کامل شد: {temp_input_path}")
        else:
            with requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=120) as response:
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                chunk_size = 1048576

                with open(temp_input_path, 'wb') as f:
                    last_percent = -1
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

                            if total_size > 0:
                                percent = (downloaded / total_size) * 100
                                current_percent = int(percent)
                                if current_percent != last_percent and current_percent % 5 == 0:
                                    last_percent = current_percent
                                    try:
                                        bot.edit_message(
                                            object_guid=data['chat_id'],
                                            message_id=status_msg.message_id,
                                            text=f"**⏳ دانلود فایل... {percent:.1f}%**"
                                        )
                                    except:
                                        pass
                                print(f"\r⏳ دانلود: {percent:.1f}% ({downloaded}/{total_size} bytes)", end='')
                                sys.stdout.flush()
            
            print(f"\n✅ دانلود کامل شد: {temp_input_path}")

            if os.path.getsize(temp_input_path) == 0:
                raise Exception("فایل دانلود شده خالی است")
        
        final_path = temp_input_path
        final_name = original_filename
        
        if file_type == 'video' and choice_text == '2':
            out = os.path.splitext(original_filename)[0] + ".3gp"
            out_path = os.path.join(TEMP_DIR, out)
            try:
                import subprocess
                cmd = [
                    'ffmpeg', '-i', temp_input_path,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '28',
                    '-c:a', 'aac', '-b:a', '64k',
                    '-s', '320x240',
                    '-y', out_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    final_path = out_path
                    final_name = out
                    os.remove(temp_input_path)
                    print(f"✅ تبدیل به 3gp موفق: {out_path}")
                else:
                    print(f"⚠️ تبدیل ویدیو ناموفق. ffmpeg stderr:\n{result.stderr}")
                    choice_text = '3'
            except FileNotFoundError:
                print("❌ ffmpeg پیدا نشد. لطفاً ffmpeg را نصب کنید و در PATH قرار دهید.")
                choice_text = '3'
            except Exception as convert_error:
                print(f"⚠️ خطا در تبدیل: {convert_error}")
                choice_text = '3'
        
        if file_type == 'video' and choice_text == '1':
            file_size_mb = os.path.getsize(final_path) / (1024 * 1024)
            if file_size_mb > 50:
                print(f"⚠️ حجم فایل {file_size_mb:.1f}MB است، ممکن است خطا دهد")
        
        if RANDOM_FILENAME:
            ext = os.path.splitext(final_name)[1]
            final_name = random_filename(ext)



        send_success = False
        last_error = None
        
        send_methods = []
        
        if file_type == 'video' and choice_text == '1':
            send_methods = [
                ("ارسال ویدیو", lambda: bot.send_video(object_guid=current_target, video=final_path, file_name=final_name, caption=caption)),
                ("ارسال به عنوان فایل معمولی", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=final_name, caption=caption)),
                ("ارسال با نام متفاوت", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=f"file_{int(time.time())}{os.path.splitext(final_name)[1]}", caption=caption))
            ]
        elif file_type == 'video' and choice_text == '3':
            send_methods = [
                ("ارسال فایل معمولی", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=final_name, caption=caption)),
                ("ارسال با نام متفاوت", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=f"file_{int(time.time())}{os.path.splitext(final_name)[1]}", caption=caption))
            ]
        else:
            send_methods = [
                ("ارسال معمولی", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=final_name, caption=caption)),
                ("ارسال با نام متفاوت", lambda: bot.send_document(object_guid=current_target, document=final_path, file_name=f"file_{int(time.time())}{os.path.splitext(final_name)[1]}", caption=caption))
            ]
        
        
        for method_name, method_func in send_methods:
            if send_success:
                break

            for attempt in range(1, 6):  
                try:
                    print(f"🔄 {method_name} - تلاش {attempt}/5...")
                    result = method_func()

                    # اگر خروجی یک دیکشنری بود و وضعیت آن موفقیت‌آمیز نبود
                    if isinstance(result, dict) and result.get('status') != 'OK':
                        raise Exception(f"Server returned error: {result}")

                    if result is not None:
                        send_success = True
                        print(f"✅ {method_name} موفق شد (تلاش {attempt})")
                        break
                except Exception as e:
                    last_error = e
                    error_type = type(e).__name__
                    error_str = str(e)
                    error_repr = repr(e)

                    print(f"❌ {method_name} - تلاش {attempt} ناموفق")
                    print(f"   نوع خطا: {error_type}")
                    print(f"   متن خطا: {error_str}")
                    print(f"   repr خطا: {error_repr}")

                    full_error = f"{error_type} {error_str} {error_repr}".lower()

                    retryable_keywords = [
                        '503', '502', '500', '504',
                        'timeout', 'connection', 'bad gateway',
                        'error_try_again', 'server_error',
                        'invalid_auth', 'error_generic',
                        'none type', 'subscriptable', "'nonetype'",
                        'try again', 'retry', 'rate limit'
                    ]

                    is_retryable = any(keyword in full_error for keyword in retryable_keywords)

                    if is_retryable:
                        if attempt < 5:          # 5 تلاش کلی
                            wait_time = attempt * 5
                            print(f"   🔄 خطا قابل تلاش مجدد است")
                            print(f"   ⏳ صبر {wait_time} ثانیه و تلاش مجدد...")
                            time.sleep(wait_time)
                            continue
                        else:
                            print(f"   ❌ اتمام تلاش‌ها برای این روش")
                            break
                    else:
                        print(f"   ❌ خطای غیر قابل تلاش مجدد، رفتن به روش بعدی")
                        break

            if send_success:
                break
        
        if send_success:
            if not user_settings.get('keep_temp_files'):
                try:
                    os.remove(final_path)
                    print(f"🗑️ فایل {final_name} پاک شد (نگهداری غیرفعال)")
                except Exception as e:
                    print(f"⚠️ خطا در پاک کردن: {e}")
            else:
                print(f"📁 فایل {final_name} در temp نگهداری شد (نگهداری فعال)")

            success_msg = update.reply("**✅ فرستادم**")
            bot_msg_ids.append(success_msg.message_id)
            threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 3)).start()
        else:
            raise Exception(f"ارسال ناموفق: {last_error}")
        
    except Exception as e:
        error_msg = update.reply(f"**❌ خطا: {e}**")
        bot_msg_ids.append(error_msg.message_id)
        threading.Thread(target=delete_messages_after_delay, args=(data['chat_id'], bot_msg_ids, 5)).start()
    finally:
        if not user_settings.get('keep_temp_files'):
            if os.path.exists(temp_input_path):
                try:
                    os.remove(temp_input_path)
                    print(f"🗑️ فایل اصلی {original_filename} پاک شد (نگهداری غیرفعال)")
                except:
                    pass
        else:
            print(f"📁 فایل اصلی {original_filename} در temp نگهداری شد (نگهداری فعال)")
        user_temp_data.pop(user_id, None)  
    
    return True

def list_folder_contents(folder_path):
    
    if not os.path.exists(folder_path):
        return None, f"❌ پوشه `{folder_path}` وجود ندارد."
    if not os.path.isdir(folder_path):
        return None, f"❌ مسیر `{folder_path}` یک پوشه نیست."
    
    files = []
    for f in os.listdir(folder_path):
        full_path = os.path.join(folder_path, f)
        if os.path.isfile(full_path):
            files.append(f)
    
    if not files:
        return None, f"📁 پوشه `{folder_path}` خالی است."
    
    files.sort()
    
    MAX_DISPLAY = 10
    total_files = len(files)
    display_files = files[:MAX_DISPLAY]
    
    result = f"📁 **پوشه:** `{folder_path}`\n"
    result += f"📊 **تعداد کل فایل‌ها:** {total_files}\n\n"
    
    for idx, f in enumerate(display_files, 1):
        file_path = os.path.join(folder_path, f)
        try:
            size = os.path.getsize(file_path)
            if size > 1024 * 1024:
                size_str = f"{size // (1024*1024)} MB"
            elif size > 1024:
                size_str = f"{size // 1024} KB"
            else:
                size_str = f"{size} B"
        except:
            size_str = "?"
        result += f"**{idx}.** {f} ({size_str})\n"
    
    if total_files > MAX_DISPLAY:
        result += f"\n... و {total_files - MAX_DISPLAY} فایل دیگر\n"
    
    result += f"\n🔢 **برای ارسال، شماره فایل(ها) را وارد کنید.**"
    result += f"\nمثال: `1 3 5` یا `2-6`"
    result += f"\nبرای ارسال همه: `همه`"
    result += f"\n🗑️ **برای حذف فایل(ها):** `حذف 1 3 5` یا `حذف همه`"
    
    
    return files, result

def handle_folder_command(update, msg_text, user_id):
    
    parts = msg_text.split(maxsplit=1)
    if len(parts) < 2:
        update.reply("❌ لطفاً مسیر پوشه را مشخص کنید.\nمثال: `پوشه E:/myfiles`")
        return
    
    folder_path = parts[1].strip()
    
    if not os.path.exists(folder_path):
        update.reply(f"❌ پوشه `{folder_path}` وجود ندارد.\nلطفاً مسیر صحیح را وارد کنید.")
        return
    
    user_settings['source_folder'] = folder_path
    save_settings()
    
    files, result = list_folder_contents(folder_path)
    
    print(f"[DEBUG] files: {files is not None}, result length: {len(result) if result else 0}")
    
    if files is None:
        update.reply(f"❌ خطا در خواندن پوشه:\n{result}")
        return
    
    if user_id in user_temp_data:
        user_temp_data.pop(user_id, None)
    
    user_temp_data[user_id] = {
        'step': 'waiting_folder_selection',
        'folder_files': files,
        'folder_path': folder_path,
        'chat_id': update.chat_id,
        'created_at': time.time()
    }
    
    update.reply(result)

def send_file_from_disk(file_path, chat_id, caption=None, convert_3gp=None):
  
    print(f"[DEBUG] send_file_from_disk - file_path: {file_path}")
    
    if not os.path.exists(file_path):
        return False, "فایل وجود ندارد"
    
    file_name = os.path.basename(file_path)
    ext = os.path.splitext(file_name)[1].lower().strip('.')
    
    should_convert = convert_3gp
    if should_convert is None:
        should_convert = user_settings.get('always_convert_to_3gp', False)
    
    final_send_path = file_path
    final_send_name = file_name
    
    try:
        if ext in ['mp4', 'mkv', 'avi', 'mov', 'webm'] and should_convert:
            temp_dir = os.path.dirname(file_path)
            out_filename = os.path.splitext(file_name)[0] + ".3gp"
            out_path = os.path.join(temp_dir, out_filename)
            
            convert_result = convert_video_to_3gp(file_path, out_path)
            if convert_result is True:
                if not os.path.exists(out_path):
                    return False, f"❌ فایل {file_name} تبدیل شد ولی فایل خروجی وجود ندارد"
                result = bot.send_video(object_guid=chat_id, video=out_path, file_name=out_filename, caption=caption)
                if not user_settings.get('keep_temp_files'):
                    try:
                        os.remove(out_path)
                    except:
                        pass
                if result is None:
                    return False, f"⚠️ فایل {file_name} ارسال نشد (خطای سرور)"
                return True, f"✅ فایل {file_name} تبدیل به 3gp و ارسال شد"
            else:
                result = bot.send_video(object_guid=chat_id, video=final_send_path, file_name=final_send_name, caption=caption)
                if result is None:
                    return False, f"⚠️ فایل {file_name} ارسال نشد (خطای سرور)"
                return True, f"✅ فایل {file_name} (بدون تبدیل) ارسال شد"
        

        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            result = bot.send_photo(object_guid=chat_id, photo=final_send_path, file_name=final_send_name, caption=caption)
            if result is None:
                return False, f"⚠️ خطا در ارسال عکس {file_name}"
                
        elif ext in ['mp3', 'ogg', 'wav', 'flac', 'm4a']:
            name_parts = os.path.splitext(file_name)[0].split(' - ')
            performer = name_parts[0] if len(name_parts) > 1 else "ناشناس"
            title = name_parts[1] if len(name_parts) > 1 else name_parts[0]
            try:
                if hasattr(bot, 'send_audio'):
                    result = bot.send_audio(object_guid=chat_id, audio=final_send_path, file_name=final_send_name, performer=performer, title=title, caption=caption)
                else:
                    result = bot.send_document(object_guid=chat_id, document=final_send_path, file_name=final_send_name, caption=caption)
                if result is None:
                    # تلاش مجدد با send_document
                    result = bot.send_document(object_guid=chat_id, document=final_send_path, file_name=final_send_name, caption=caption)
            except Exception:
                result = bot.send_document(object_guid=chat_id, document=final_send_path, file_name=final_send_name, caption=caption)
                
        elif ext in ['mp4', 'mkv', 'avi', 'mov', '3gp', 'webm']:
            result = bot.send_video(object_guid=chat_id, video=final_send_path, file_name=final_send_name, caption=caption)
            if result is None:
                return False, f"⚠️ خطا در ارسال ویدیو {file_name}"
        else:
            result = bot.send_document(object_guid=chat_id, document=final_send_path, file_name=final_send_name, caption=caption)
            if result is None:
                return False, f"⚠️ خطا در ارسال فایل {file_name}"
        
        return True, f"✅ فایل {file_name} ارسال شد"
        
    except Exception as e:
        return False, f"❌ خطا در ارسال {file_name}: {e}"

def delete_files_from_folder(folder_path, indices, files):
    deleted = []
    not_found = []
    
    for idx in indices:
        if 1 <= idx <= len(files):
            file_path = os.path.join(folder_path, files[idx-1])
            try:
                os.remove(file_path)
                deleted.append(files[idx-1])
            except Exception as e:
                not_found.append(f"{files[idx-1]} ({e})")
        else:
            not_found.append(f"شماره {idx}")
    
    return deleted, not_found


def safe_edit_message(chat_id, message_id, text):
    if not chat_id or not message_id:
        return False
    try:
        if isinstance(message_id, str):
            message_id = int(message_id)
        bot.edit_message(object_guid=chat_id, message_id=message_id, text=text)
        return True
    except Exception as e:
        print(f"⚠️ خطا در ادیت پیام {message_id}: {e}")
        return False

def process_folder_selection(update, user_input, user_id):
    
    data = user_temp_data.get(user_id)
    if not data or data.get('step') != 'waiting_folder_selection':
        return False
    
    if user_input.lower() in ['انصراف', 'cancel', 'لغو', '0']:
        user_temp_data.pop(user_id, None)
        update.reply("❌ عملیات انتخاب فایل از پوشه کنسل شد.")
        return True
    if user_input.lower().startswith('حذف'):
        parts = user_input.split()
        if len(parts) < 2:
            update.reply("❌ لطفاً شماره فایل(ها) را برای حذف مشخص کنید.\nمثال: `حذف 1 3 5` یا `حذف همه`")
            return True
        
        files = data['folder_files']
        folder_path = data['folder_path']
        
        if parts[1].lower() == 'همه':
            indices = list(range(1, len(files) + 1))
        else:
            indices = []
            for part in parts[1:]:
                try:
                    idx = int(part)
                    if 1 <= idx <= len(files):
                        indices.append(idx)
                    else:
                        update.reply(f"❌ شماره {idx} خارج از محدوده (1 تا {len(files)})")
                        return True
                except ValueError:
                    update.reply(f"❌ شماره نامعتبر: {part}")
                    return True
        
        deleted, not_found = delete_files_from_folder(folder_path, indices, files)
        
        result = f"🗑️ **نتیجه حذف فایل‌ها:**\n"
        if deleted:
            result += f"✅ حذف شد: {', '.join(deleted)}\n"
        if not_found:
            result += f"❌ حذف نشد: {', '.join(not_found)}\n"
        
        update.reply(result)
        
        new_files, new_result = list_folder_contents(folder_path)
        if new_files is None:
            user_temp_data.pop(user_id, None)
            update.reply("📁 پوشه خالی شد!")
        else:
            user_temp_data[user_id]['folder_files'] = new_files
            update.reply(new_result)
        
        return True
    
    if user_input is None or user_input.strip() == '':
        update.reply("❌ ورودی خالی است. لطفاً شماره فایل(ها) را وارد کنید.")
        return True
    
    if user_input.lower().startswith('پوشه'):
        update.reply("⚠️ لطفاً شماره فایل(ها) را وارد کنید، نه دستور پوشه.\nمثال: `1 3 5` یا `2-6` یا `همه`")
        return True
    
    user_input_clean = user_input.strip()
    if user_input_clean != 'همه' and not re.match(r'^[\d\s\-]+$', user_input_clean):
        update.reply("❌ لطفاً فقط شماره فایل(ها) را وارد کنید.\nمثال: `1 3 5` یا `2-6` یا `همه`")
        return True
    
    files = data['folder_files']
    folder_path = data['folder_path']
    
    selected_indices = []
    
    if user_input.lower() == 'همه':
        selected_indices = list(range(1, len(files) + 1))
    else:
        parts = user_input.split()
        for part in parts:
            if '-' in part:
                try:
                    start, end = map(int, part.split('-'))
                    for i in range(start, end + 1):
                        if 1 <= i <= len(files):
                            selected_indices.append(i)
                except ValueError:
                    update.reply(f"❌ محدوده نامعتبر: {part}\nمثال صحیح: `2-6`")
                    return True
            else:
                try:
                    idx = int(part)
                    if 1 <= idx <= len(files):
                        selected_indices.append(idx)
                    else:
                        update.reply(f"❌ شماره {idx} خارج از محدوده (1 تا {len(files)})")
                        return True
                except ValueError:
                    update.reply(f"❌ ورودی نامعتبر: {part}\nلطفاً فقط عدد وارد کنید.")
                    return True
    
    if not selected_indices:
        update.reply("**❌ شماره معتبری وارد نشد.**")
        user_temp_data.pop(user_id, None)
        return True
    
    selected_indices = sorted(set(selected_indices))
    selected_files = [files[i-1] for i in selected_indices]
    
    if not current_target:
        update.reply("**⚠️ ابتدا با دستور `هدف` یک مقصد انتخاب کنید.**")
        user_temp_data.pop(user_id, None)
        return True
    
    user_temp_data[user_id]['selected_files'] = selected_files
    user_temp_data[user_id]['step'] = 'waiting_folder_send'
    
    has_video = False
    for file_name in selected_files:
        ext = os.path.splitext(file_name)[1].lower().strip('.')
        if ext in ['mp4', 'mkv', 'avi', 'mov', 'webm']:
            has_video = True
            break
    
    if has_video and not user_settings.get('always_convert_to_3gp'):
        q = "**🎬 در بین فایل‌های انتخاب شده ویدیو وجود دارد!**\n\n"
        q += "**چیکار باهاش کنم؟**\n"
        q += "1️⃣ ویدیوها را بدون تغییر بفرستم\n"
        q += "2️⃣ همه ویدیوها را به 3gp تبدیل کنم\n"
        q += "3️⃣ فایل معمولی بفرستم\n"
        q += "0️⃣ انصراف\n\n"
        q += "**عددشو بگو:**"
        sent = update.reply(q)
        user_temp_data[user_id]['question_msg_id'] = sent.message_id
        user_temp_data[user_id]['step'] = 'waiting_folder_convert_choice'
        return True
    
    # ارسال مستقیم
    process_folder_send(update, user_id, convert_videos=False)
    return True

def process_folder_choice(update, choice_text, user_id):
    
    data = user_temp_data.get(user_id)
    if not data or data.get('step') != 'waiting_folder_convert_choice':
        update.reply("❌ زمان انتخاب به پایان رسیده. لطفاً دوباره دستور `پوشه` را وارد کنید.")
        return False
    
    try:
        question_msg_id = data.get('question_msg_id')
        if question_msg_id:
            bot.delete_message(object_guid=data['chat_id'], message_id=question_msg_id)
    except:
        pass
    
    if choice_text == '0':
        update.reply("❌ انصراف.")
        user_temp_data.pop(user_id, None)
        return True
    
    if choice_text not in ['1', '2', '3']:
        update.reply("❌ انتخاب نامعتبر.\nلطفاً یکی از اعداد `1`، `2`، `3` یا `0` را وارد کنید.")
        user_temp_data.pop(user_id, None)
        return True
    
    convert_videos = (choice_text == '2')
    process_folder_send(update, user_id, convert_videos)
    return True

def process_folder_send(update, user_id, convert_videos=False):
    print(f"[DEBUG] process_folder_send - convert_videos: {convert_videos}")
    
    data = user_temp_data.get(user_id)
    if not data:
        update.reply("❌ خطا: اطلاعات انتخاب فایل یافت نشد.")
        return
    
    selected_files = data.get('selected_files', [])
    folder_path = data['folder_path']
    
    if not selected_files:
        update.reply("❌ هیچ فایلی انتخاب نشده است.")
        user_temp_data.pop(user_id, None)
        return
    
    if not current_target:
        update.reply("**⚠️ ابتدا با دستور `هدف` یک مقصد انتخاب کنید.**")
        user_temp_data.pop(user_id, None)
        return
    
    status_msg = update.reply(f"**⏳ در حال ارسال {len(selected_files)} فایل...**")
    if status_msg is None:
        update.reply("❌ خطا در ارسال پیام وضعیت")
        user_temp_data.pop(user_id, None)
        return
    
    success_count = 0
    fail_count = 0
    results = []
    total_size = 0
    uploaded_size = 0
    
    for idx, file_name in enumerate(selected_files, 1):
        file_path = os.path.join(folder_path, file_name)
        ext = os.path.splitext(file_name)[1].lower().strip('.')
        
        try:
            file_size = os.path.getsize(file_path)
            total_size += file_size
        except:
            pass
        
        should_convert = convert_videos and ext in ['mp4', 'mkv', 'avi', 'mov', 'webm']
        
        print(f"\n📤 ارسال فایل {idx}/{len(selected_files)}: {file_name}")
        
        success, msg = send_file_from_disk(file_path, current_target, None, should_convert)
        
        if success:
            success_count += 1
            results.append(f"✅ {file_name}")
            try:
                uploaded_size += os.path.getsize(file_path)
            except:
                pass
        else:
            fail_count += 1
            results.append(f"❌ {file_name}: {msg}")
        
        if total_size > 0:
            percent = (uploaded_size / total_size) * 100
            print(f"📊 پیشرفت کل: {percent:.1f}%")
        
        time.sleep(0.1)
    
    summary = f"**📊 نتیجه ارسال:**\nموفق: {success_count} | ناموفق: {fail_count}\n\n"
    summary += "\n".join(results[:15])
    if len(results) > 15:
        summary += f"\n... و {len(results)-15} فایل دیگر"
    
    try:
        safe_edit_message(status_msg.chat_id, status_msg.message_id, summary)
    except:
        try:
            update.reply(summary)
        except:
            pass
    
    user_temp_data.pop(user_id, None)
    print(f"[DEBUG] process_folder_send completed - success: {success_count}, fail: {fail_count}")

def process_command(update: Update, msg_text: str, user_id: str):
    global current_target
    
    print(f"[DEBUG] process_command - user_id: {user_id}, msg_text: {msg_text[:50] if msg_text else 'None'}")
    if msg_text and msg_text.strip().lower() in ['انصراف', 'cancel', 'لغو', '0']:
        if user_id in user_temp_data:
            user_temp_data.pop(user_id, None)
            update.reply("❌ عملیات جاری کنسل شد.")
            return
        else:
            update.reply("⚠️ هیچ عملیات در حال روندی برای کنسل کردن وجود ندارد.")
            return    
    if msg_text and msg_text.strip().isdigit() and user_id not in user_temp_data:
        update.reply("⚠️ شما در حال حاضر هیچ عملیاتی در جریان ندارید.\nبرای آپلود لینک، ابتدا لینک را ارسال کنید.")
        return
    
    new_filename = None
    caption = None
    

    if msg_text is not None:
        if msg_text.strip() == 'دان':
            new_filename = None
            caption = None
        elif msg_text.startswith('دان\n'):
            lines = msg_text.split('\n')
            if len(lines) >= 2:
                new_filename = lines[1].strip()
                if new_filename == '':
                    new_filename = None
            if len(lines) >= 3:
                caption = '\n'.join(lines[2:]).strip()
                if caption == '':
                    caption = None
        elif msg_text.startswith('دان '):
            parts = msg_text.split(maxsplit=1)
            if len(parts) >= 2:
                new_filename = parts[1].strip()
        
        if not caption and user_settings.get('default_caption'):
            caption = user_settings['default_caption']

    if msg_text is not None and (msg_text.strip() == 'دان' or msg_text.startswith('دان\n') or msg_text.startswith('دان ')):
        if not hasattr(update, 'reply_to_message_id') or not update.reply_to_message_id:
            update.reply("⚠️ لطفاً روی پیامی که فایل دارد ریپلی بزنید و «دان» را بنویسید.")
            return
        
        replied_msg_id = update.reply_to_message_id
        file_info = stored_files.get(replied_msg_id)
        if not file_info:
            try:
                with open(STORED_FILES_JSON, "r", encoding='utf-8') as f:
                    stored = json.load(f)
                    file_info = stored.get(str(replied_msg_id))
            except:
                pass
        
        if not file_info:
            update.reply("❌ اطلاعات این فایل یافت نشد. لطفاً فایل را مجدداً فوروارد کنید.")
            return
        
        bot_msg_ids = []
        user_temp_data[user_id] = {
            'step': 'waiting_choice_file',
            'original_filename': file_info['original_filename'],
            'file_type': file_info['file_type'],
            'target_message_id': replied_msg_id,
            'chat_id': update.chat_id,
            'bot_msg_ids': bot_msg_ids,
            'new_filename': new_filename,
            'caption': caption,
            'created_at': time.time()
        }
        ask_for_file_choice(update, file_info['original_filename'], file_info['file_type'], bot_msg_ids, target_msg_id=replied_msg_id, new_filename=new_filename, caption=caption, user_id=user_id)
        return

    if handle_forwarded_file(update):
        return

    if user_id in user_temp_data:
        data = user_temp_data[user_id]
        step = data.get('step')
        
        if 'created_at' in data:
            if time.time() - data['created_at'] > 300:
                user_temp_data.pop(user_id, None)
                update.reply("⏰ زمان انتخاب به پایان رسید. لطفاً دوباره تلاش کنید.")
                return
        
        if step == 'waiting_forward':
            process_forward(update, user_id=user_id)
            return
            
        if step == 'waiting_choice':
            if msg_text is None:
                return
            process_choice(update, msg_text.strip(), user_id=user_id)
            return
            
        if step == 'waiting_choice_file':
            if msg_text is None:
                return
            process_choice_file(update, msg_text.strip(), user_id=user_id)
            return
            
        if step == 'waiting_folder_selection':
            if msg_text is None:
                return
            process_folder_selection(update, msg_text.strip(), user_id)
            return
            
        if step == 'waiting_folder_convert_choice':
            if msg_text is None:
                return
            process_folder_choice(update, msg_text.strip(), user_id)
            return
        
        if step == 'waiting_folder_send':
            if msg_text is None:
                return
            if msg_text.strip().isdigit():
                update.reply("⚠️ در حال ارسال فایل‌ها هستم. لطفاً صبر کنید...")
                return

    if msg_text is None:
        return
        
    text = msg_text.strip()
    low = text.lower()

    if low.startswith('هدف'):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            ask_for_forward(update, "مقصد", user_id=user_id)
        else:
            set_target(update, parts[1], user_id=user_id, send_reply=True)
        return

    if low == 'نمایش هدف':
        show_target(update)
        return


    if low.startswith('پوشه'):
        if user_id in user_temp_data and user_temp_data[user_id].get('step') == 'waiting_folder_selection':
            update.reply("⚠️ شما در حال انتخاب فایل از پوشه هستید.\nلطفاً شماره فایل(ها) را وارد کنید یا `انصراف` بگویید.")
            return
        handle_folder_command(update, text, user_id)
        return

    if low == 'نگهداری فعال':
        user_settings['keep_temp_files'] = True
        save_settings()
        update.reply("✅ **حالت نگهداری فایل‌ها در temp فعال شد.**\nفایل‌های دانلود شده دیگر پاک نمی‌شوند.")
        return

    if low == 'نگهداری غیرفعال':
        user_settings['keep_temp_files'] = False
        save_settings()
        update.reply("✅ **حالت نگهداری فایل‌ها در temp غیرفعال شد.**\nفایل‌ها پس از ارسال از temp پاک می‌شوند.")
        return

    if low == 'وضعیت نگهداری':
        status = "فعال" if user_settings.get('keep_temp_files') else "غیرفعال"
        update.reply(f"📁 وضعیت نگهداری فایل‌ها در temp: **{status}**")
        return

    if low.startswith('همیشه 3gp'):
        rest = text[len('همیشه 3gp'):].strip()
        if not rest:
            status = "فعال" if user_settings['always_convert_to_3gp'] else "غیرفعال"
            update.reply(f"📍 وضعیت تبدیل خودکار ویدیو به 3gp: **{status}**\nبرای تغییر: `همیشه 3gp روشن` یا `همیشه 3gp خاموش`")
            return
        if rest == 'روشن':
            user_settings['always_convert_to_3gp'] = True
            save_settings()
            update.reply("✅ **حالت تبدیل خودکار ویدیو به 3gp فعال شد.** (دیگر سوالی پرسیده نمی‌شود)")
        elif rest == 'خاموش':
            user_settings['always_convert_to_3gp'] = False
            save_settings()
            update.reply("✅ **حالت تبدیل خودکار ویدیو به 3gp غیرفعال شد.**")
        else:
            update.reply("❌ دستور نامعتبر. استفاده: `همیشه 3gp روشن` یا `همیشه 3gp خاموش`")
        return

    if low.startswith('کپشن همیشه'):
        new_caption = text[len('کپشن همیشه '):].strip()
        if new_caption:
            user_settings['default_caption'] = new_caption
            save_settings()
            update.reply(f"✅ **کپشن پیش‌فرض تنظیم شد:**\n{new_caption}")
        else:
            update.reply("❌ لطفاً متن کپشن را وارد کنید.\nمثال: `کپشن همیشه سلام این یک تست است`")
        return

    if low == 'حذف کپشن پیشفرض':
        user_settings['default_caption'] = None
        save_settings()
        update.reply("✅ **کپشن پیش‌فرض پاک شد.**")
        return

    if low.startswith('/upload ') or low.startswith('up '):
        url = text[8:] if low.startswith('/upload ') else text[3:]
        url = url.strip()

        if not url.startswith(('http://', 'https://')):
            msg = update.reply("**❌ لینک نامعتبر.**\nلطفاً یک لینک معتبر وارد کنید.")
            threading.Thread(target=delete_message_after_delay, args=(update.chat_id, msg.message_id, 5)).start()
            return

        if not current_target:
            msg = update.reply("**⚠️ اول با دستور `هدف` یه مقصد انتخاب کن.**")
            threading.Thread(target=delete_message_after_delay, args=(update.chat_id, msg.message_id, 5)).start()
            return

        if 'rubika.ir/post/' in url:
            direct_url, file_name, ftype, post_caption = get_rubino_post_info(url)
            try:
                bot.delete_message(object_guid=update.chat_id, message_id=status_msg.message_id)
            except:
                pass

            if direct_url:
                url = direct_url
                original_filename = file_name
                file_type = ftype
                caption = post_caption 
            else:
                update.reply("❌ نتوانستم فایل را از روبینو دریافت کنم.")
                return
        else:
            original_filename = None
            file_type = None
            caption = None   

        status_msg = update.reply("**🔍 دارم لینک رو می‌بینم...**")
        bot_msg_ids = [status_msg.message_id]
        threading.Thread(target=delete_message_after_delay, args=(update.chat_id, status_msg.message_id, 5)).start()

        if original_filename is None:
            orig_name = url.split('/')[-1].split('?')[0] or "downloaded_file.bin"
            orig_name = unquote(orig_name)
            invalid_chars = '<>:"/\\|?*'
            for char in invalid_chars:
                orig_name = orig_name.replace(char, '_')
            original_filename = orig_name

        if file_type is None:
            if is_video_file(original_filename):
                file_type = 'video'
            elif is_audio_file(original_filename):
                file_type = 'audio'
            elif is_image_file(original_filename):
                file_type = 'image'
            else:
                file_type = 'other'

        process_upload(update, url, original_filename, file_type, bot_msg_ids, user_id=user_id, caption=caption)
        return

def show_help(update):
    help_text = """
🤖 راهنمای ربات

📌 دستورات اصلی:
• هدف g0... - تنظیم مقصد ارسال
• هدف me - تنظیم مقصد به پیوی خود
• نمایش هدف - نمایش مقصد فعلی
• پوشه مسیر - نمایش فایل های پوشه
• up لینک - آپلود فایل از لینک
• دان - دانلود فایل فوروارد شده (ریپلی کنید)
• انصراف - لغو عملیات جاری

⚙️ تنظیمات:
• همیشه 3gp روشن/خاموش - تبدیل خودکار ویدیو
• کپشن همیشه متن - کپشن پیش فرض
• نگهداری فعال/غیرفعال - نگهداری فایل در temp

📁 دستورات پوشه:
بعد از پوشه مسیر:
• 1 3 5 - ارسال فایل های 1،3،5
• 2-6 - ارسال فایل های 2 تا 6
• همه - ارسال همه فایل ها
• حذف 1 3 5 - حذف فایل های 1،3،5
• حذف همه - حذف همه فایل ها

🎬 تبدیل ویدیو:
• 1 - ارسال بدون تغییر
• 2 - تبدیل به 3gp
• 3 - ارسال به عنوان فایل معمولی
• 0 - انصراف

⚠️ نکته: قبل از ارسال، هدف را تنظیم کنید: هدف me
"""
    update.reply(help_text)

@bot.on_message_updates()
def handler(update: Update):
    user_id = getattr(update, 'author_object_guid', None)
    
    if not user_id or user_id not in SOURCE_USER_GUIDS:
        return
    
    if hasattr(update, 'text') and update.text and update.text.strip().lower() in ['help', 'راهنما', 'کامند', 'commands']:
        show_help(update)
        return
    
    try:
        process_command(update, update.text if hasattr(update, 'text') else None, user_id)
    except Exception as e:
        print(f"[ERROR] خطای داخلی: {e}")
        import traceback
        traceback.print_exc()
        err_msg = update.reply(f"**❌ خطای داخلی: {e}**")
        threading.Thread(target=delete_message_after_delay, args=(update.chat_id, err_msg.message_id, 10)).start()

def run_bot():
    print("✅ ربات روشن شد ")
    print("=" * 50)
    bot.run()

if __name__ == "__main__":
    run_bot()
