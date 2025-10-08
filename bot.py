import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import threading
import time
from flask import Flask, request

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID") # আপনার প্রাইভেট চ্যানেলের আইডি দিন

# --- Bot and Flask Setup ---
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
server = Flask(__name__)

# --- In-memory Stores (For simplicity) ---
user_states = {} # ব্যবহারকারীর বর্তমান অবস্থা ট্র্যাক করার জন্য
known_users = set() # নতুন ব্যবহারকারী শনাক্ত করার জন্য (প্রোডাকশনে ডাটাবেস ব্যবহার করুন)

# --- Helper Functions ---
def log_new_user(message):
    """Checks if a user is new and logs their info to the channel."""
    chat_id = message.chat.id
    if chat_id not in known_users:
        try:
            log_message = (
                f"<b>👋 New User Alert!</b>\n\n"
                f"<b>User ID:</b> <code>{message.from_user.id}</code>\n"
                f"<b>First Name:</b> {message.from_user.first_name}\n"
                f"<b>Username:</b> @{message.from_user.username if message.from_user.username else 'N/A'}"
            )
            bot.send_message(LOG_CHANNEL_ID, log_message)
            known_users.add(chat_id)
        except Exception as e:
            print(f"Failed to log new user: {e}")

def create_progress_bar(percentage):
    """Creates a modern progress bar string."""
    bar_length = 10
    filled_length = int(bar_length * percentage // 100)
    bar = '▓' * filled_length + '░' * (bar_length - filled_length)
    return f"{bar} {percentage:.1f}%"

def upload_progress_callback(current, total, status_message):
    """Updates the message with upload progress."""
    if total > 0:
        percentage = (current / total) * 100
        progress_text = create_progress_bar(percentage)
        new_text = f"Uploading... \n{progress_text}"
        
        # To avoid flooding Telegram API, update message not too frequently
        if not hasattr(upload_progress_callback, "last_update"):
            upload_progress_callback.last_update = 0
        
        current_time = time.time()
        if current_time - upload_progress_callback.last_update > 1.5:
            try:
                bot.edit_message_text(new_text, status_message.chat.id, status_message.message_id)
                upload_progress_callback.last_update = current_time
            except Exception:
                pass # Ignore if message not modified

# --- Bot Handlers ---

@bot.message_handler(commands=['start'])
def start(message):
    log_new_user(message)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Instagram Downloader", callback_data="ig_download"),
        InlineKeyboardButton("Facebook Downloader", callback_data="fb_download")
    )
    bot.send_message(
        message.chat.id,
        "Hi! What do you want to download?",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith(('ig_', 'fb_')))
def platform_selector(call):
    chat_id = call.message.chat.id
    if call.data == "ig_download":
        user_states[chat_id] = {"action": "awaiting_ig_link"}
        bot.send_message(chat_id, "Please send me an Instagram Post/Reel/Video link.")
    elif call.data == "fb_download":
        user_states[chat_id] = {"action": "awaiting_fb_link"}
        bot.send_message(chat_id, "Please send me a Facebook video link.")
    bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda message: user_states.get(message.chat.id))
def handle_link(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    action = state.get("action")
    
    if action in ["awaiting_ig_link", "awaiting_fb_link"]:
        user_states[chat_id]['url'] = message.text
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🎬 Video", callback_data="select_video"),
            InlineKeyboardButton("🎵 Audio", callback_data="select_audio")
        )
        bot.send_message(chat_id, "What do you want to download?", reply_markup=markup)
        bot.delete_message(chat_id, message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def format_selector(call):
    chat_id = call.message.chat.id
    state = user_states.get(chat_id, {})
    url = state.get("url")
    action = state.get("action")
    
    if not url:
        bot.answer_callback_query(call.id, "Something went wrong. Please try again from /start.", show_alert=True)
        return

    media_type = 'video' if 'video' in call.data else 'audio'
    
    if "awaiting_ig_link" in action:
        # For Instagram, download directly
        thread = threading.Thread(target=process_download, args=(chat_id, call.message.message_id, url, media_type))
        thread.start()
    elif "awaiting_fb_link" in action:
        if media_type == 'audio':
            thread = threading.Thread(target=process_download, args=(chat_id, call.message.message_id, url, 'audio'))
            thread.start()
        else: # It's a video, so fetch qualities
            bot.edit_message_text("Fetching video qualities...", chat_id, call.message.message_id)
            thread = threading.Thread(target=fetch_fb_qualities, args=(chat_id, call.message.message_id, url))
            thread.start()

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('quality_'))
def quality_downloader(call):
    chat_id = call.message.chat.id
    state = user_states.get(chat_id, {})
    url = state.get("url")
    quality = call.data.split('_')[1]

    if not url:
        bot.answer_callback_query(call.id, "Something went wrong. Please try again from /start.", show_alert=True)
        return
        
    thread = threading.Thread(target=process_download, args=(chat_id, call.message.message_id, url, 'video', quality))
    thread.start()
    bot.answer_callback_query(call.id)


def fetch_fb_qualities(chat_id, message_id, url):
    """Fetches available video qualities for a Facebook video."""
    try:
        ydl_opts = {
            'quiet': True,
            'listformats': True,
            'source_address': '0.0.0.0'
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            markup = InlineKeyboardMarkup()
            found_qualities = set()
            
            for f in formats:
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('height'):
                    height = f['height']
                    if height >= 360 and height not in found_qualities:
                        markup.add(InlineKeyboardButton(f"{height}p", callback_data=f"quality_{height}"))
                        found_qualities.add(height)

            if not found_qualities:
                bot.edit_message_text("No video qualities found. Please try another link.", chat_id, message_id)
                user_states.pop(chat_id, None)
                return

            bot.edit_message_text("Select video quality:", chat_id, message_id, reply_markup=markup)

    except Exception as e:
        bot.edit_message_text(f"Could not fetch qualities. Error: {str(e)}", chat_id, message_id)
        user_states.pop(chat_id, None)


def process_download(chat_id, message_id, url, media_type, quality=None):
    """Handles the download and upload process in a thread."""
    bot.edit_message_text("Preparing to download...", chat_id, message_id)
    
    try:
        format_selection = 'bestaudio/best' if media_type == 'audio' else f'bestvideo[height<={quality}]+bestaudio/best' if quality else 'bestvideo+bestaudio/best'
        
        output_template = f'downloads/%(title)s_{chat_id}.%(ext)s'
        if not os.path.exists('downloads'):
            os.makedirs('downloads')

        ydl_opts = {
            'format': format_selection,
            'outtmpl': output_template,
            'noplaylist': True,
            'socket_timeout': 30, # Timeout for downloading
            'source_address': '0.0.0.0'
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            bot.edit_message_text("Downloading...", chat_id, message_id)
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
        
        status_message = bot.edit_message_text("Download complete. Now uploading...", chat_id, message_id)
        
        with open(filename, 'rb') as f:
            if media_type == 'audio':
                bot.send_audio(chat_id, f, timeout=120, progress_callback=lambda current, total: upload_progress_callback(current, total, status_message))
            else:
                bot.send_video(chat_id, f, timeout=120, supports_streaming=True, progress_callback=lambda current, total: upload_progress_callback(current, total, status_message))

        bot.delete_message(chat_id, status_message.message_id)
        os.remove(filename) # Clean up the downloaded file

    except Exception as e:
        bot.edit_message_text(f"Sorry, something went wrong. Could not download.\nError: <i>{str(e)}</i>", chat_id, message_id)
    finally:
        user_states.pop(chat_id, None) # Clear user state

# --- Webhook Handling ---
@server.route('/' + BOT_TOKEN, methods=['POST'])
def get_message():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@server.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f'https://{os.environ.get("RENDER_EXTERNAL_HOSTNAME")}/{BOT_TOKEN}')
    return "Webhook set!", 200

if __name__ == "__main__":
    print("Bot is running locally...")

