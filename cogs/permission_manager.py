# cogs/permission_manager.py
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
from datetime import datetime
import logging
from typing import List, Literal

logger = logging.getLogger('PermissionBot')

class TimeModal(discord.ui.Modal, title="Set Schedule Time"):
    hour = discord.ui.TextInput(
        label="Hour (00-23)",
        placeholder="Enter hour (00-23)",
        min_length=2,
        max_length=2,
        required=True
    )
    minute = discord.ui.TextInput(
        label="Minute (00-59)",
        placeholder="Enter minute (00-59)",
        min_length=2,
        max_length=2,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hour = int(self.hour.value)
            minute = int(self.minute.value)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                time_str = f"{hour:02d}:{minute:02d}"
                self.time_value = time_str
                await interaction.response.send_message(f"Time set to {time_str}", ephemeral=True)
            else:
                await interaction.response.send_message("Invalid time format. Hour must be 00-23, minute must be 00-59.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please enter valid numbers for hour and minute.", ephemeral=True)

class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, mode: str):
        super().__init__(
            placeholder=f"Select channels for {mode} mode",
            min_values=1,
            max_values=25,  # Discord's maximum for selections
            channel_types=[discord.ChannelType.text]
        )
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        selected_channels = self.values
        channel_list = ", ".join([channel.mention for channel in selected_channels])
        await interaction.response.send_message(
            f"Selected channels for {self.mode} mode: {channel_list}\n"
            f"These channels will ONLY be accessible during {self.mode} time.",
            ephemeral=True
        )
        self.view.selected_channels = selected_channels

class ChannelSelectView(discord.ui.View):
    def __init__(self, mode: str, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(ChannelSelect(mode))
        self.selected_channels = None

class PermissionManagerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.setup_database()

    def setup_database(self):
        """Initialize database with new tables for day/night mode"""
        try:
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                # Table for schedule times
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS schedule_times (
                        id INTEGER PRIMARY KEY,
                        night_start TEXT NOT NULL,
                        day_start TEXT NOT NULL
                    )
                ''')
                # Table for managed channels
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS managed_channels (
                        channel_id INTEGER PRIMARY KEY,
                        mode TEXT NOT NULL
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"Database setup failed: {e}")
            raise

    @app_commands.command(name="settime")
    @app_commands.describe(
        period="Select whether to set night start or day start time"
    )
    async def set_time(self, interaction: discord.Interaction, period: Literal["night", "day"]):
        """Set the start time for night or day mode"""
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("You need Manage Channels permission.", ephemeral=True)
            return

        modal = TimeModal()
        await interaction.response.send_modal(modal)
        await modal.wait()

        try:
            time_str = modal.time_value
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                # Check if times exist
                cursor.execute('SELECT * FROM schedule_times WHERE id = 1')
                exists = cursor.fetchone()
                
                if exists:
                    if period == "night":
                        cursor.execute('UPDATE schedule_times SET night_start = ? WHERE id = 1', (time_str,))
                    else:
                        cursor.execute('UPDATE schedule_times SET day_start = ? WHERE id = 1', (time_str,))
                else:
                    # Insert default times, then update the one specified
                    default_time = "00:00"
                    cursor.execute('INSERT INTO schedule_times (id, night_start, day_start) VALUES (1, ?, ?)',
                                 (time_str if period == "night" else default_time,
                                  time_str if period == "day" else default_time))
                conn.commit()

            await interaction.followup.send(
                f"✅ {period.capitalize()} time set to {time_str}\n"
                f"At this time:\n"
                f"- {period} channels will be UNLOCKED\n"
                f"- {'day' if period == 'night' else 'night'} channels will be LOCKED"
            )
            await self.update_scheduler()

        except Exception as e:
            logger.error(f"Failed to set time: {e}")
            await interaction.followup.send("Failed to set time. Check logs for details.", ephemeral=True)

    @app_commands.command(name="setchannels")
    @app_commands.describe(
        mode="Select whether to set channels for night or day mode"
    )
    async def set_channels(self, interaction: discord.Interaction, mode: Literal["night", "day"]):
        """Set which channels should be managed during night/day"""
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("You need Manage Channels permission.", ephemeral=True)
            return

        view = ChannelSelectView(mode)
        await interaction.response.send_message(
            f"Select channels that should ONLY be accessible during {mode} time:",
            view=view,
            ephemeral=True
        )

        await view.wait()
        if view.selected_channels:
            try:
                with sqlite3.connect('permissions.db') as conn:
                    cursor = conn.cursor()
                    # Remove existing channels for this mode
                    cursor.execute('DELETE FROM managed_channels WHERE mode = ?', (mode,))
                    # Add new channels
                    for channel in view.selected_channels:
                        cursor.execute('INSERT OR REPLACE INTO managed_channels (channel_id, mode) VALUES (?, ?)',
                                     (channel.id, mode))
                    conn.commit()

                channel_list = ", ".join([channel.mention for channel in view.selected_channels])
                await interaction.followup.send(
                    f"✅ Updated {mode} mode channels:\n{channel_list}\n"
                    f"These channels will ONLY be accessible during {mode} time.",
                    ephemeral=True
                )
                # Immediately apply current state
                await self.apply_current_state()

            except Exception as e:
                logger.error(f"Failed to set channels: {e}")
                await interaction.followup.send("Failed to update channels. Check logs for details.", ephemeral=True)

    @app_commands.command(name="viewsettings")
    async def view_settings(self, interaction: discord.Interaction):
        """View current day/night settings"""
        try:
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT night_start, day_start FROM schedule_times WHERE id = 1')
                times = cursor.fetchone()
                
                cursor.execute('SELECT channel_id, mode FROM managed_channels')
                channels = cursor.fetchall()

            embed = discord.Embed(
                title="⚙️ Day/Night Mode Settings", 
                color=discord.Color.blue(),
                description="Channels are only accessible during their designated time period."
            )
            
            if times:
                embed.add_field(name="🌙 Night Start", value=times[0], inline=True)
                embed.add_field(name="☀️ Day Start", value=times[1], inline=True)
                embed.add_field(name="\u200b", value="\u200b", inline=True)  # Empty field for alignment
            else:
                embed.add_field(name="⚠️ Times", value="Not set", inline=False)

            night_channels = []
            day_channels = []
            for channel_id, mode in channels:
                channel = interaction.guild.get_channel(channel_id)
                if channel:
                    if mode == "night":
                        night_channels.append(channel.mention)
                    else:
                        day_channels.append(channel.mention)

            embed.add_field(
                name="🌙 Night-Only Channels",
                value="\n".join(night_channels) if night_channels else "None set",
                inline=False
            )
            embed.add_field(
                name="☀️ Day-Only Channels",
                value="\n".join(day_channels) if day_channels else "None set",
                inline=False
            )

            current_hour = datetime.now().hour
            current_time = datetime.now().strftime("%H:%M")
            if times:
                night_start_hour = int(times[0].split(":")[0])
                day_start_hour = int(times[1].split(":")[0])
                current_period = "night" if night_start_hour <= current_hour < day_start_hour else "day"
                embed.add_field(
                    name="🕒 Current Status",
                    value=f"It's currently {current_time} ({current_period.upper()} time)\n"
                          f"- Night channels are {'UNLOCKED' if current_period == 'night' else 'LOCKED'}\n"
                          f"- Day channels are {'UNLOCKED' if current_period == 'day' else 'LOCKED'}",
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Failed to view settings: {e}")
            await interaction.response.send_message("Failed to retrieve settings. Check logs for details.", ephemeral=True)

    async def update_scheduler(self):
        """Update the scheduler with current settings"""
        try:
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT night_start, day_start FROM schedule_times WHERE id = 1')
                times = cursor.fetchone()

            if times:
                night_start, day_start = times
                
                # Clear existing jobs
                self.bot.scheduler.remove_all_jobs()

                # Schedule night mode
                self.bot.scheduler.add_job(
                    self.apply_mode_changes,
                    'cron',
                    args=["night"],
                    hour=int(night_start.split(':')[0]),
                    minute=int(night_start.split(':')[1])
                )

                # Schedule day mode
                self.bot.scheduler.add_job(
                    self.apply_mode_changes,
                    'cron',
                    args=["day"],
                    hour=int(day_start.split(':')[0]),
                    minute=int(day_start.split(':')[1])
                )

                logger.info(f"Scheduler updated - Night: {night_start}, Day: {day_start}")

        except Exception as e:
            logger.error(f"Failed to update scheduler: {e}")

    async def apply_mode_changes(self, current_mode: str):
        """Apply permission changes for the specified mode"""
        try:
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                # Get all channels
                cursor.execute('SELECT channel_id, mode FROM managed_channels')
                channels = cursor.fetchall()

            for channel_id, channel_mode in channels:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    everyone_role = channel.guild.default_role
                    overwrite = channel.overwrites_for(everyone_role)
                    
                    # If it's currently day time:
                    # - Day channels should be unlocked
                    # - Night channels should be locked
                    # And vice versa for night time
                    should_be_unlocked = (channel_mode == current_mode)
                    overwrite.send_messages = should_be_unlocked
                    
                    await channel.set_permissions(everyone_role, overwrite=overwrite)
                    logger.info(f"Set channel {channel.name} ({channel_mode} mode) to {'unlocked' if should_be_unlocked else 'locked'} during {current_mode} time")

        except Exception as e:
            logger.error(f"Failed to apply {current_mode} mode changes: {e}")

    async def apply_current_state(self):
        """Apply the correct state based on current time"""
        try:
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT night_start, day_start FROM schedule_times WHERE id = 1')
                times = cursor.fetchone()

            if times:
                night_start, day_start = times
                current_hour = datetime.now().hour
                night_hour = int(night_start.split(':')[0])
                day_hour = int(day_start.split(':')[0])

                # Determine if it's currently night or day time
                current_mode = "night" if night_hour <= current_hour < day_hour else "day"
                await self.apply_mode_changes(current_mode)

        except Exception as e:
            logger.error(f"Failed to apply current state: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(PermissionManagerCog(bot))