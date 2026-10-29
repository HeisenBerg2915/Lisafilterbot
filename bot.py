import os
import re
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
from pymongo import MongoClient
from bson.objectid import ObjectId

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
MONGO_URI = os.environ["MONGO_URI"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
BOT_USERNAME = os.environ["BOT_USERNAME"].lstrip("@")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db = client["autofilter_bot"]
files_collection = db["files"]

FILES_PER_PAGE = 10
MAX_SEARCH_RESULTS = 100


def format_file_size(size):
    """Convert a file size in bytes into a readable label."""
    if not size:
        return "Size N/A"

    size = float(size)

    if size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.2f} GB"
    if size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.2f} MB"
    if size >= 1024:
        return f"{size / 1024:.2f} KB"
    return f"{size:.0f} B"


# ---------------------------------
# SAVE FILES FROM CHANNEL
# ---------------------------------

async def save_channel_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.channel_post

    if not message or message.chat_id != CHANNEL_ID:
        return

    media = None
    file_name = None
    file_type = None

    if message.document:
        media = message.document
        file_name = media.file_name or "document"
        file_type = "document"
    elif message.video:
        media = message.video
        file_name = media.file_name or "video"
        file_type = "video"
    elif message.audio:
        media = message.audio
        file_name = media.file_name or "audio"
        file_type = "audio"
    elif message.animation:
        media = message.animation
        file_name = media.file_name or "animation"
        file_type = "animation"

    if not media:
        return

    files_collection.update_one(
        {
            "channel_id": message.chat_id,
            "message_id": message.message_id,
        },
        {
            "$set": {
                "file_name": file_name,
                "file_id": media.file_id,
                "file_type": file_type,
                "file_size": media.file_size,
                "channel_id": message.chat_id,
                "message_id": message.message_id,
            }
        },
        upsert=True,
    )

    logger.info("Saved file: %s (%s)", file_name, format_file_size(media.file_size))


# ---------------------------------
# GROUP SEARCH WITH FILE SIZE
# ---------------------------------

async def search_files(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if not message or not message.text:
        return

    query = message.text.strip()

    if not query or query.startswith("/") or len(query) < 2:
        return

    pattern = re.escape(query)

    results = list(
        files_collection.find(
            {"file_name": {"$regex": pattern, "$options": "i"}}
        )
        .sort("file_name", 1)
        .limit(MAX_SEARCH_RESULTS)
    )

    if not results:
        await message.reply_text(f"❌ No files found for: {query}")
        return

    context.user_data["search_results"] = [
        str(item["_id"]) for item in results
    ]
    context.user_data["search_query"] = query

    await send_search_page(
        message=message,
        context=context,
        page=0,
    )


async def send_search_page(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
    edit_message=None,
):
    file_ids = context.user_data.get("search_results", [])
    query = context.user_data.get("search_query", "")
    total_files = len(file_ids)

    if not total_files:
        if edit_message:
            await edit_message.edit_text("❌ No files found.")
        else:
            await message.reply_text("❌ No files found.")
        return

    total_pages = (total_files + FILES_PER_PAGE - 1) // FILES_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start_index = page * FILES_PER_PAGE
    current_ids = file_ids[start_index:start_index + FILES_PER_PAGE]

    keyboard = []

    for file_id in current_ids:
        try:
            item = files_collection.find_one({"_id": ObjectId(file_id)})
        except Exception:
            item = None

        if not item:
            continue

        file_name = item.get("file_name", "Unknown File")
        file_size = format_file_size(item.get("file_size"))

        # Keep the whole button label within Telegram's button text limit.
        prefix = f"📁 {file_size} ➤ "
        available = max(1, 64 - len(prefix))
        button_text = prefix + file_name[:available]

        keyboard.append([
            InlineKeyboardButton(
                button_text,
                url=f"https://t.me/{BOT_USERNAME}?start={file_id}",
            )
        ])

    navigation = [
        InlineKeyboardButton(
            f"{page + 1}/{total_pages}",
            callback_data="autofilter_page_info",
        )
    ]

    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                "⬅️ BACK",
                callback_data=f"autofilter_page_{page - 1}",
            )
        )

    if page < total_pages - 1:
        navigation.append(
            InlineKeyboardButton(
                "NEXT ➜",
                callback_data=f"autofilter_page_{page + 1}",
            )
        )

    keyboard.append(navigation)

    text = (
        f"🔎 Search Results: {query}\n\n"
        f"📂 Files Found: {total_files}"
    )
    markup = InlineKeyboardMarkup(keyboard)

    if edit_message:
        await edit_message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup)


async def pagination_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data == "autofilter_page_info":
        return

    match = re.fullmatch(r"autofilter_page_(\d+)", data)
    if not match:
        return

    await send_search_page(
        message=query.message,
        context=context,
        page=int(match.group(1)),
        edit_message=query.message,
    )


# ---------------------------------
# SEND FILE IN PRIVATE CHAT
# ---------------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if not message:
        return

    if not context.args:
        await message.reply_text(
            "👋 Welcome to Auto Filter Bot!\n\n"
            "🔎 Search a movie in the group to find its files."
        )
        return

    file_id = context.args[0]

    if not re.fullmatch(r"[0-9a-fA-F]{24}", file_id):
        await message.reply_text("❌ Invalid file link.")
        return

    item = files_collection.find_one({"_id": ObjectId(file_id)})

    if not item:
        await message.reply_text("❌ File not found in the database.")
        return

    try:
        file_type = item["file_type"]
        telegram_file_id = item["file_id"]
        caption = f"📁 {item['file_name']}"

        if file_type == "video":
            await message.reply_video(video=telegram_file_id, caption=caption)
        elif file_type == "audio":
            await message.reply_audio(audio=telegram_file_id, caption=caption)
        elif file_type == "animation":
            await message.reply_animation(
                animation=telegram_file_id,
                caption=caption,
            )
        else:
            await message.reply_document(
                document=telegram_file_id,
                caption=caption,
            )

    except Exception:
        logger.exception("Unable to send file")
        await message.reply_text(
            "❌ Unable to send this file. Please try again later."
        )


# ---------------------------------
# RENDER WEBHOOK
# ---------------------------------

def main():
    render_url = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
    port = int(os.environ.get("PORT", "10000"))

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        CallbackQueryHandler(
            pagination_callback,
            pattern=r"^autofilter_page_",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST
            & (
                filters.Document.ALL
                | filters.VIDEO
                | filters.AUDIO
                | filters.ANIMATION
            ),
            save_channel_file,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & filters.TEXT
            & ~filters.COMMAND,
            search_files,
        )
    )

    logger.info("Starting Auto Filter Bot")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{render_url}/{BOT_TOKEN}",
        allowed_updates=["message", "channel_post", "callback_query"],
    )


if __name__ == "__main__":
    main()
