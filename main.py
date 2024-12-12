# main.py
import discord
from discord.ext import commands
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import sqlite3
import logging
import json
from datetime import datetime
import os
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('PermissionBot')

# Load config
def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("Config file not found. Please create config.json")
        raise

class PermissionBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix='!', intents=intents)
        
        self.scheduler = AsyncIOScheduler()
        self.setup_database()
        
    async def setup_hook(self):
        """Called when the bot is first setting up"""
        # Load extensions/cogs here
        await self.load_extension('cogs.permission_manager')
        logger.info("Permission manager cog loaded")
        
        # Sync commands with Discord
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
        
    def setup_database(self):
        """Initialize SQLite database with required tables"""
        try:
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS scheduled_permissions (
                        id INTEGER PRIMARY KEY,
                        channel_id INTEGER NOT NULL,
                        role_id INTEGER NOT NULL,
                        permission_type TEXT NOT NULL,
                        permission_value BOOLEAN NOT NULL,
                        schedule_time TEXT NOT NULL
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"Database setup failed: {e}")
            raise

    async def on_ready(self):
        logger.info(f'Bot is ready! Logged in as {self.user.name} ({self.user.id})')
        self.scheduler.start()
        
        # Additional sync attempt on ready, just in case
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s) after ready")
        except Exception as e:
            logger.error(f"Failed to sync commands after ready: {e}")

async def main():
    # Load config
    config = load_config()
    
    # Initialize bot
    bot = PermissionBot()
    
    try:
        await bot.start(config['token'])
    except KeyboardInterrupt:
        await bot.close()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())