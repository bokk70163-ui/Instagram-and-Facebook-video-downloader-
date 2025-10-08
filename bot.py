-
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
        
        if not hasattr(upload_progress_callback, "last_update"):
