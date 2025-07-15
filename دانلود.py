import os
from telethon import TelegramClient, events
from datetime import datetime
from aiohttp import web

# 🧩 اطلاعات ورود
api_id = 123456            # جایگزین کن با api_id خودت
api_hash = 'your_api_hash' # جایگزین کن با api_hash خودت
bot_token = 'your_bot_token'  # توکن بات

# :file_folder: مسیر ذخیره فایل‌ها
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# :electric_plug: ساخت کلاینت تلگرام
client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)

# :incoming_envelope: رویداد دریافت فایل
@client.on(events.NewMessage)
async def handler(event):
    if event.message.media:
        sender = await event.get_sender()
        file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{event.message.id}"

        # :arrow_down: دانلود فایل
        path = os.path.join(DOWNLOAD_DIR, file_name)
        await event.message.download_media(file=path)

        # :link: ساخت لینک محلی
        link = f"http://your_domain_or_ip:8080/{file_name}"

        await event.reply(f":white_check_mark: فایل دریافت شد!\n:inbox_tray: لینک دانلود مستقیم:\n{link}")
    else:
        await event.reply("لطفاً یک فایل ارسال کنید.")

# :globe_with_meridians: سرور برای ارائه لینک دانلود (aiohttp)
async def file_server(request):
    filename = request.match_info['filename']
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.isfile(filepath):
        return web.FileResponse(filepath)
    else:
        return web.Response(text="فایل پیدا نشد.", status=404)

# ⚙ اجرا هم‌زمان کلاینت و وب‌سرور
async def main():
    # راه‌اندازی سرور aiohttp
    app = web.Application()
    app.router.add_get("/{filename}", file_server)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    # اجرای تلگرام کلاینت
    print(":white_check_mark: ربات فعال شد! منتظر فایل باشید...")
    await client.run_until_disconnected()

# اجرای برنامه
import asyncio
asyncio.run(main()