import os
import re
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from pymongo import MongoClient
from bson.objectid import ObjectId

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
MONGO_URI = os.environ["MONGO_URI"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
BOT_USERNAME = os.environ["BOT_USERNAME"].lstrip("@")

client = MongoClient(MONGO_URI)
db = client["autofilter_bot"]
files_collection = db["files"]

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

    # Avoid saving the same channel post twice.
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
                "channel_id": message.chat_id,
                "message_id": message.message_id,
            }
        },
        upsert=True,
    )

    logger.info("Saved file: %s", file_name)


# ---------------------------------
# GROUP SEARCH
# ---------------------------------

async def search_files(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message

    if not message or not message.text:
        return

    query = message.text.strip()

    if not query or query.startswith("/"):
        return

    if len(query) < 2:
        return

    # Search file names without treating user input as regex.
    pattern = re.escape(query)

    results = list(
        files_collection.find(
            {"file_name": {"$regex": pattern, "$options": "i"}}
        ).limit(10)
    )

    if not results:
        await message.reply_text(
            f"❌ No files found for: {query}"
        )
        return

    keyboard = []

    for item in results:
        file_name = item["file_name"]
        file_id = str(item["_id"])

        # Telegram deep links support start parameters
        # up to 64 characters.
        button_text = f"📁 {file_name[:55]}"

        keyboard.append([
            InlineKeyboardButton(
                button_text,
                url=(
                    f"https://t.me/{BOT_USERNAME}"
                    f"?start={file_id}"
                ),
            )
        ])

    await message.reply_text(
        f"🎬 Search Results: {query}\n\n"
        f"📂 Files Found: {len(results)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
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
            "🔎 Search a movie in the group "
            "to find its files."
        )
        return

    file_id = context.args[0]

    if not re.fullmatch(r"[0-9a-fA-F]{24}", file_id):
        await message.reply_text("❌ Invalid file link.")
        return

    item = files_collection.find_one(
        {"_id": ObjectId(file_id)}
    )

    if not item:
        await message.reply_text(
            "❌ File not found in the database."
        )
        return

    try:
        file_type = item["file_type"]
        telegram_file_id = item["file_id"]
        caption = f"📁 {item['file_name']}"

        if file_type == "video":
            await message.reply_video(
                video=telegram_file_id,
                caption=caption,
            )

        elif file_type == "audio":
            await message.reply_audio(
                audio=telegram_file_id,
                caption=caption,
            )

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
            "❌ Unable to send this file. "
            "Please try again later."
        )


# ---------------------------------
# RENDER WEBHOOK
# ---------------------------------

def main():
    render_url = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
    port = int(os.environ.get("PORT", "10000"))

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))

    # Receive channel posts separately.
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

    # Search messages in groups.
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
        allowed_updates=[
            "message",
            "channel_post",
        ],
    )


if __name__ == "__main__":
    main()
