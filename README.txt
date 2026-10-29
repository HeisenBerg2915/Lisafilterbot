Auto Filter Bot (Render + MongoDB)

Files:
- bot.py: Telegram bot
- requirements.txt: Python dependencies
- render.yaml: Render service configuration

Required Render Environment Variables:
- BOT_TOKEN: token from BotFather
- BOT_USERNAME: bot username without @
- CHANNEL_ID: numeric ID of the file channel (usually starts with -100)
- MONGO_URI: MongoDB Atlas connection string

Deploy:
1. Upload these files to your GitHub repository.
2. Create or update a Render Web Service from that repository.
3. Build command: pip install -r requirements.txt
4. Start command: python bot.py
5. Set all four environment variables.
6. Make the bot an administrator in the file channel so it receives channel posts.
7. Add the bot to your group. If it must read ordinary group messages, disable Group Privacy for the bot via BotFather.

Notes:
- New channel uploads save file_size in MongoDB.
- Existing database entries without file_size display "Size N/A".
- Search results show up to 100 matches, 10 per page.
- The pagination buttons edit the same result message.
