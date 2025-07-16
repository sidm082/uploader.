import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import sqlite3
import os
import logging
import re
from functools import wraps
import uuid

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Admin credentials from environment variables
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

# Database setup
def get_db_connection():
    """Create and return a database connection."""
    conn = sqlite3.connect('/data/archive.db')
    return conn

def init_db():
    """Initialize the SQLite database and create necessary tables."""
    os.makedirs('/data', exist_ok=True)
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS menus 
                    (id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS files 
                    (id INTEGER PRIMARY KEY, menu_id INTEGER, file_type TEXT, 
                    file_id TEXT, caption TEXT, link TEXT, file_link_id TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins 
                    (user_id INTEGER PRIMARY KEY, username TEXT, password TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                    (user_id INTEGER PRIMARY KEY, username TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS channels 
                    (id INTEGER PRIMARY KEY, channel_id TEXT, channel_link TEXT)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_menu_id ON files (menu_id)')
        conn.commit()

init_db()

# States for conversation
ADD_MENU, EDIT_MENU, DELETE_MENU, ADD_FILE, ADD_LINK, ADD_CHANNEL, EDIT_CHANNEL, DELETE_CHANNEL = range(8)

# Admin check decorator
def admin_required(func):
    """Decorator to restrict access to admin-only functions."""
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
            if c.fetchone() or context.user_data.get('admin_authenticated'):
                return await func(update, context, *args, **kwargs)
        await update.message.reply_text("لطفاً ابتدا با /admin_login وارد شوید")
        return
    return wrapper

# Check channel membership
async def check_channel_membership(user_id, context):
    """Check if user is a member of all required channels."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT channel_id FROM channels")
        channels = c.fetchall()
    
    if not channels:
        return True  # No channels required
    
    for channel_id in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel_id[0], user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except telegram.error.TelegramError as e:
            logger.error(f"Error checking channel membership: {e}")
            return False
    return True

# Cancel conversation
async def cancel(update, context):
    """Cancel the current conversation."""
    await update.message.reply_text("عملیات لغو شد.")
    return ConversationHandler.END

# Start command
async def start(update, context):
    """Handle the /start command and initialize user in the database."""
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    logger.info(f"User {user_id} started the bot")
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (user_id, username))
        conn.commit()
    
    keyboard = [[InlineKeyboardButton("مشاهده منوها", callback_data='show_menus')],
               [InlineKeyboardButton("ورود ادمین", callback_data='admin_login')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('به ربات آرشیو خوش آمدید!', reply_markup=reply_markup)

# Admin login
async def admin_login(update, context):
    """Initiate admin login process."""
    query = update.callback_query
    await query.message.reply_text("نام کاربری ادمین را وارد کنید:")
    return ADD_MENU

async def check_admin_credentials(update, context):
    """Check admin username."""
    username = update.message.text
    if username == ADMIN_USERNAME:
        await update.message.reply_text("رمز عبور را وارد کنید:")
        context.user_data['temp_username'] = username
        return EDIT_MENU
    await update.message.reply_text("نام کاربری اشتباه است!")
    return ConversationHandler.END

async def verify_password(update, context):
    """Verify admin password and show admin panel."""
    password = update.message.text
    if password == ADMIN_PASSWORD:
        context.user_data['admin_authenticated'] = True
        await update.message.reply_text("ورود موفقیت‌آمیز! به پنل مدیریت خوش آمدید.")
        keyboard = [
            [InlineKeyboardButton("اضافه کردن منو", callback_data='add_menu')],
            [InlineKeyboardButton("ویرایش منو", callback_data='edit_menu')],
            [InlineKeyboardButton("حذف منو", callback_data='delete_menu')],
            [InlineKeyboardButton("آپلود فایل", callback_data='upload_file')],
            [InlineKeyboardButton("اضافه کردن لینک", callback_data='add_link')],
            [InlineKeyboardButton("نمایش کاربران", callback_data='show_users')],
            [InlineKeyboardButton("مدیریت کانال‌ها", callback_data='manage_channels')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("انتخاب کنید:", reply_markup=reply_markup)
        return ConversationHandler.END
    await update.message.reply_text("رمز عبور اشتباه است!")
    return ConversationHandler.END

# Menu management
@admin_required
async def add_menu(update, context):
    """Prompt for adding a new menu."""
    await update.message.reply_text("نام منوی جدید را وارد کنید:")
    return ADD_MENU

async def save_menu(update, context):
    """Save a new menu to the database."""
    menu_name = update.message.text.strip()
    if not menu_name:
        await update.message.reply_text("نام منو نمی‌تواند خالی باشد!")
        return ADD_MENU
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO menus (name, parent_id) VALUES (?, ?)", 
                 (menu_name, context.user_data.get('parent_id', 0)))
        conn.commit()
    await update.message.reply_text(f"منوی '{menu_name}' اضافه شد!")
    return ConversationHandler.END

@admin_required
async def edit_menu(update, context):
    """Show menus for editing."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM menus")
        menus = c.fetchall()
    
    if not menus:
        await update.message.reply_text("هیچ منویی وجود ندارد!")
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(name, callback_data=f'edit_menu_{id}')] for id, name in menus]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("منوی مورد نظر برای ویرایش را انتخاب کنید:", reply_markup=reply_markup)
    return EDIT_MENU

async def select_menu_to_edit(update, context):
    """Prompt for new menu name."""
    query = update.callback_query
    menu_id = int(query.data.split('_')[-1])
    context.user_data['edit_menu_id'] = menu_id
    await query.message.reply_text("نام جدید منو را وارد کنید:")
    return DELETE_MENU

async def save_edited_menu(update, context):
    """Save edited menu name."""
    new_name = update.message.text.strip()
    if not new_name:
        await update.message.reply_text("نام منو نمی‌تواند خالی باشد!")
        return DELETE_MENU
    menu_id = context.user_data['edit_menu_id']
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE menus SET name = ? WHERE id = ?", (new_name, menu_id))
        conn.commit()
    await update.message.reply_text(f"منو به '{new_name}' تغییر یافت!")
    return ConversationHandler.END

@admin_required
async def delete_menu(update, context):
    """Show menus for deletion."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM menus")
        menus = c.fetchall()
    
    if not menus:
        await update.message.reply_text("هیچ منویی وجود ندارد!")
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(name, callback_data=f'delete_menu_{id}')] for id, name in menus]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("منوی مورد نظر برای حذف را انتخاب کنید:", reply_markup=reply_markup)
    return DELETE_MENU

async def confirm_delete_menu(update, context):
    """Delete a menu and its associated files."""
    query = update.callback_query
    menu_id = int(query.data.split('_')[-1])
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM menus WHERE id = ?", (menu_id,))
        c.execute("DELETE FROM files WHERE menu_id = ?", (menu_id,))
        conn.commit()
    await query.message.reply_text("منو با موفقیت حذف شد!")
    return ConversationHandler.END

# File upload
@admin_required
async def upload_file(update, context):
    """Show menus for file upload."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM menus")
        menus = c.fetchall()
    
    if not menus:
        await update.message.reply_text("هیچ منویی وجود ندارد! ابتدا یک منو ایجاد کنید.")
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(name, callback_data=f'upload_to_{id}')] for id, name in menus]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("منوی مقصد برای آپلود فایل را انتخاب کنید:", reply_markup=reply_markup)
    return ADD_FILE

async def select_menu_for_file(update, context):
    """Prompt for file upload."""
    query = update.callback_query
    menu_id = int(query.data.split('_')[-1])
    context.user_data['upload_menu_id'] = menu_id
    await query.message.reply_text("لطفاً فایل (سند، ویدئو، تصویر، صدا یا گیف) را آپلود کنید:")
    return ADD_FILE

async def save_file(update, context):
    """Save uploaded file to the database."""
    menu_id = context.user_data['upload_menu_id']
    file = None
    file_type = None
    
    if update.message.document:
        file = update.message.document
        file_type = 'document'
    elif update.message.video:
        file = update.message.video
        file_type = 'video'
    elif update.message.photo:
        file = update.message.photo[-1]
        file_type = 'photo'
    elif update.message.audio:
        file = update.message.audio
        file_type = 'audio'
    elif update.message.animation:
        file = update.message.animation
        file_type = 'animation'
    
    if file:
        file_id = file.file_id
        caption = update.message.caption or ""
        file_link_id = str(uuid.uuid4())
        
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO files (menu_id, file_type, file_id, caption, file_link_id) VALUES (?, ?, ?, ?, ?)",
                     (menu_id, file_type, file_id, caption, file_link_id))
            conn.commit()
        
        keyboard = [[InlineKeyboardButton("دریافت فایل", callback_data=f'get_file_{file_link_id}')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"فایل با موفقیت آپلود شد! لینک دسترسی:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("لطفاً یک فایل معتبر (سند، ویدئو، تصویر، صدا یا گیف) آپلود کنید!")
    return ConversationHandler.END

# Link management
@admin_required
async def add_link(update, context):
    """Show menus for adding a link."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM menus")
        menus = c.fetchall()
    
    if not menus:
        await update.message.reply_text("هیچ منویی وجود ندارد! ابتدا یک منو ایجاد کنید.")
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(name, callback_data=f'link_to_{id}')] for id, name in menus]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("منوی مقصد برای لینک را انتخاب کنید:", reply_markup=reply_markup)
    return ADD_LINK

async def select_menu_for_link(update, context):
    """Prompt for link input."""
    query = update.callback_query
    menu_id = int(query.data.split('_')[-1])
    context.user_data['link_menu_id'] = menu_id
    await query.message.reply_text("لینک را وارد کنید (مثال: https://example.com):")
    return ADD_LINK

async def save_link(update, context):
    """Save a link to the database."""
    link = update.message.text.strip()
    if not re.match(r'^(https?://|t.me/|@)[^\s]+$', link):
        await update.message.reply_text("لطفاً یک لینک معتبر وارد کنید!")
        return ADD_LINK
    
    menu_id = context.user_data['link_menu_id']
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO files (menu_id, file_type, link) VALUES (?, ?, ?)",
                 (menu_id, 'link', link))
        conn.commit()
    
    await update.message.reply_text("لینک با موفقیت اضافه شد!")
    return ConversationHandler.END

# Channel management
@admin_required
async def manage_channels(update, context):
    """Show channel management options."""
    keyboard = [
        [InlineKeyboardButton("اضافه کردن کانال", callback_data='add_channel')],
        [InlineKeyboardButton("ویرایش کانال", callback_data='edit_channel')],
        [InlineKeyboardButton("حذف کانال", callback_data='delete_channel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("مدیریت کانال‌ها:", reply_markup=reply_markup)
    return ADD_CHANNEL

@admin_required
async def add_channel(update, context):
    """Prompt for adding a new channel."""
    await update.message.reply_text("لطفاً ID یا لینک کانال را وارد کنید (مثال: @ChannelName یا -1001234567890):")
    return ADD_CHANNEL

async def save_channel(update, context):
    """Save a new channel to the database."""
    channel = update.message.text.strip()
    if not re.match(r'^(@[A-Za-z0-9_]+|-100[0-9]+)$', channel):
        await update.message.reply_text("لطفاً یک ID یا لینک معتبر کانال وارد کنید.")
        return ADD_CHANNEL
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO channels (channel_id, channel_link) VALUES (?, ?)", (channel, channel))
        conn.commit()
    await update.message.reply_text(f"کانال '{channel}' اضافه شد!")
    return ConversationHandler.END

@admin_required
async def edit_channel(update, context):
    """Show channels for editing."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, channel_link FROM channels")
        channels = c.fetchall()
    
    if not channels:
        await update.message.reply_text("هیچ کانالی وجود ندارد!")
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(link, callback_data=f'edit_channel_{id}')] for id, link in channels]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("کانال مورد نظر برای ویرایش را انتخاب کنید:", reply_markup=reply_markup)
    return EDIT_CHANNEL

async def select_channel_to_edit(update, context):
    """Prompt for new channel ID or link."""
    query = update.callback_query
    channel_id = int(query.data.split('_')[-1])
    context.user_data['edit_channel_id'] = channel_id
    await query.message.reply_text("لینک یا ID جدید کانال را وارد کنید:")
    return EDIT_CHANNEL

async def save_edited_channel(update, context):
    """Save edited channel."""
    new_channel = update.message.text.strip()
    if not re.match(r'^(@[A-Za-z0-9_]+|-100[0-9]+)$', new_channel):
        await update.message.reply_text("لطفاً یک ID یا لینک معتبر کانال وارد کنید.")
        return EDIT_CHANNEL
    
    channel_id = context.user_data['edit_channel_id']
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE channels SET channel_id = ?, channel_link = ? WHERE id = ?", 
                 (new_channel, new_channel, channel_id))
        conn.commit()
    await update.message.reply_text(f"کانال به '{new_channel}' تغییر یافت!")
    return ConversationHandler.END

@admin_required
async def delete_channel(update, context):
    """Show channels for deletion."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, channel_link FROM channels")
        channels = c.fetchall()
    
    if not channels:
        await update.message.reply_text("هیچ کانالی وجود ندارد!")
        return ConversationHandler.END
    
    keyboard = [[InlineKeyboardButton(link, callback_data=f'delete_channel_{id}')] for id, link in channels]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("کانال مورد نظر برای حذف را انتخاب کنید:", reply_markup=reply_markup)
    return DELETE_CHANNEL

async def confirm_delete_channel(update, context):
    """Delete a channel from the database."""
    query = update.callback_query
    channel_id = int(query.data.split('_')[-1])
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        conn.commit()
    await query.message.reply_text("کانال با موفقیت حذف شد!")
    return ConversationHandler.END

# Show users
@admin_required
async def show_users(update, context):
    """Show list of registered users."""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, username FROM users")
        users = c.fetchall()
    
    if not users:
        await update.message.reply_text("هیچ کاربری ثبت نشده است!")
        return
    
    user_list = "\n".join([f"ID: {user_id}, Username: @{username or 'Unknown'}" for user_id, username in users])
    await update.message.reply_text(f"لیست کاربران:\n{user_list}")

# Show menus
async def show_menus(update, context):
    """Show top-level menus."""
    query = update.callback_query
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM menus WHERE parent_id = 0")
        menus = c.fetchall()
    
    if not menus:
        await query.message.reply_text("هیچ منویی وجود ندارد!")
        return
    
    keyboard = [[InlineKeyboardButton(name, callback_data=f'menu_{id}')] for id, name in menus]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("منوها:", reply_markup=reply_markup)

async def show_submenu(update, context):
    """Show submenus and files for a selected menu."""
    query = update.callback_query
    menu_id = int(query.data.split('_')[-1])
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM menus WHERE parent_id = ?", (menu_id,))
        submenus = c.fetchall()
        c.execute("SELECT file_type, file_id, caption, link, file_link_id FROM files WHERE menu_id = ?", (menu_id,))
        files = c.fetchall()
    
    keyboard = [[InlineKeyboardButton(name, callback_data=f'menu_{id}')] for id, name in submenus]
    for file_type, file_id, caption, link, file_link_id in files:
        if file_type != 'link':
            keyboard.append([InlineKeyboardButton(caption or "فایل", callback_data=f'get_file_{file_link_id}')])
        else:
            keyboard.append([InlineKeyboardButton(caption or "لینک", url=link)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text("زیرمنوها و فایل‌ها:", reply_markup=reply_markup)

# Handle file request
async def get_file(update, context):
    """Send requested file to user if they are a channel member."""
    query = update.callback_query
    file_link_id = query.data.split('_')[-1]
    user_id = query.from_user.id
    
    if not await check_channel_membership(user_id, context):
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT channel_link FROM channels")
            channels = c.fetchall()
        
        keyboard = [[InlineKeyboardButton(f"عضویت در {link}", url=f"https://t.me/{link.lstrip('@')}")] for link in channels]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("برای دسترسی به فایل، باید در کانال‌های زیر عضو شوید:", reply_markup=reply_markup)
        return
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT file_type, file_id, caption FROM files WHERE file_link_id = ?", (file_link_id,))
        file_data = c.fetchone()
    
    if file_data:
        file_type, file_id, caption = file_data
        try:
            if file_type == 'document':
                await query.message.reply_document(document=file_id, caption=caption)
            elif file_type == 'video':
                await query.message.reply_video(video=file_id, caption=caption)
            elif file_type == 'photo':
                await query.message.reply_photo(photo=file_id, caption=caption)
            elif file_type == 'audio':
                await query.message.reply_audio(audio=file_id, caption=caption)
            elif file_type == 'animation':
                await query.message.reply_animation(animation=file_id, caption=caption)
        except telegram.error.TelegramError as e:
            logger.error(f"Error sending file {file_id}: {e}")
            await query.message.reply_text(f"خطا در ارسال فایل: {str(e)}")
    else:
        await query.message.reply_text("فایل یافت نشد!")

# Main function
def main():
    """Main function to run the bot."""
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is not set")
        raise ValueError("BOT_TOKEN environment variable is not set")
    
    application = Application.builder().token(bot_token).build()
    
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_login, pattern='admin_login')],
        states={
            ADD_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_admin_credentials)],
            EDIT_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_password)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    menu_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_menu, pattern='add_menu'),
            CallbackQueryHandler(edit_menu, pattern='edit_menu'),
            CallbackQueryHandler(delete_menu, pattern='delete_menu'),
            CallbackQueryHandler(upload_file, pattern='upload_file'),
            CallbackQueryHandler(add_link, pattern='add_link'),
            CallbackQueryHandler(manage_channels, pattern='manage_channels'),
            CallbackQueryHandler(add_channel, pattern='add_channel'),
            CallbackQueryHandler(edit_channel, pattern='edit_channel'),
            CallbackQueryHandler(delete_channel, pattern='delete_channel')
        ],
        states={
            ADD_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_menu)],
            EDIT_MENU: [CallbackQueryHandler(select_menu_to_edit, pattern='edit_menu_')],
            DELETE_MENU: [
                CallbackQueryHandler(confirm_delete_menu, pattern='delete_menu_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_menu)
            ],
            ADD_FILE: [
                CallbackQueryHandler(select_menu_for_file, pattern='upload_to_'),
                MessageHandler(
                    filters.Document.ALL | filters.Video.ALL | filters.Photo.ALL | 
                    filters.Audio.ALL | filters.Animation.ALL,
                    save_file
                )
            ],
            ADD_LINK: [
                CallbackQueryHandler(select_menu_for_link, pattern='link_to_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_link)
            ],
            ADD_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_channel)],
            EDIT_CHANNEL: [
                CallbackQueryHandler(select_channel_to_edit, pattern='edit_channel_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_edited_channel)
            ],
            DELETE_CHANNEL: [CallbackQueryHandler(confirm_delete_channel, pattern='delete_channel_')]
        ],
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(admin_conv)
    application.add_handler(menu_conv)
    application.add_handler(CallbackQueryHandler(show_menus, pattern='show_menus'))
    application.add_handler(CallbackQueryHandler(show_users, pattern='show_users'))
    application.add_handler(CallbackQueryHandler(show_submenu, pattern='menu_'))
    application.add_handler(CallbackQueryHandler(get_file, pattern='get_file_'))
    
    application.run_polling()

if __name__ == '__main__':
    main()
