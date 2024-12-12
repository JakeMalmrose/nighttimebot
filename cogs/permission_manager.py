# cogs/permission_manager.py
from discord.ext import commands
import discord
import sqlite3
from datetime import datetime
import logging

logger = logging.getLogger('PermissionBot')

class PermissionManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help_permissions")
    async def help_permissions(self, ctx):
        """Show available permission commands and how to use them"""
        help_text = """
**Permission Bot Commands:**
`!schedule_permission <#channel> <@role> <permission> <True/False> <HH:MM>`
- Schedule a permission change for a channel
- Example: `!schedule_permission #general @everyone send_messages False 22:00`

`!list_schedules`
- Show all scheduled permission changes

`!remove_schedule <id>`
- Remove a scheduled permission change
- Example: `!remove_schedule 1`

**Available Permissions:**
- send_messages
- read_messages
- embed_links
- attach_files
- read_message_history
- mention_everyone
"""
        await ctx.send(help_text)

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def schedule_permission(self, ctx, channel: discord.TextChannel, role: discord.Role, 
                                permission: str, value: bool, time: str):
        """Schedule a permission change for a specific time"""
        valid_permissions = [
            'send_messages', 'read_messages', 'embed_links', 
            'attach_files', 'read_message_history', 'mention_everyone'
        ]
        
        if permission not in valid_permissions:
            await ctx.send(f"Invalid permission. Valid options are: {', '.join(valid_permissions)}")
            return
            
        try:
            # Validate time format
            datetime.strptime(time, '%H:%M')
            
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO scheduled_permissions 
                    (channel_id, role_id, permission_type, permission_value, schedule_time)
                    VALUES (?, ?, ?, ?, ?)
                ''', (channel.id, role.id, permission, value, time))
                conn.commit()

            # Schedule the permission change
            self.bot.scheduler.add_job(
                self.update_permission,
                'cron',
                args=[channel.id, role.id, permission, value],
                hour=int(time.split(':')[0]),
                minute=int(time.split(':')[1])
            )
            
            await ctx.send(f"✅ Scheduled permission change for {channel.mention} at {time}\n"
                         f"Permission: {permission} will be set to {value} for role {role.name}")
            
        except ValueError:
            await ctx.send("Invalid time format. Please use HH:MM (24-hour format)")
        except Exception as e:
            logger.error(f"Failed to schedule permission: {e}")
            await ctx.send("Failed to schedule permission change. Check logs for details.")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def list_schedules(self, ctx):
        """List all scheduled permission changes"""
        try:
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM scheduled_permissions')
                schedules = cursor.fetchall()
                
            if not schedules:
                await ctx.send("No scheduled permission changes found.")
                return
                
            message = "**Scheduled Permission Changes:**\n\n"
            for schedule in schedules:
                id, channel_id, role_id, perm_type, perm_value, time = schedule
                channel = ctx.guild.get_channel(channel_id)
                role = ctx.guild.get_role(role_id)
                
                if channel and role:
                    message += f"ID: {id}\n"
                    message += f"Channel: {channel.mention}\n"
                    message += f"Role: {role.name}\n"
                    message += f"Permission: {perm_type} = {perm_value}\n"
                    message += f"Time: {time}\n"
                    message += "-------------------\n"
            
            await ctx.send(message)
            
        except Exception as e:
            logger.error(f"Failed to list schedules: {e}")
            await ctx.send("Failed to retrieve scheduled permissions. Check logs for details.")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def remove_schedule(self, ctx, schedule_id: int):
        """Remove a scheduled permission change"""
        try:
            with sqlite3.connect('permissions.db') as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM scheduled_permissions WHERE id = ?', (schedule_id,))
                if cursor.rowcount > 0:
                    conn.commit()
                    await ctx.send(f"✅ Successfully removed schedule #{schedule_id}")
                else:
                    await ctx.send(f"❌ No schedule found with ID {schedule_id}")
                    
        except Exception as e:
            logger.error(f"Failed to remove schedule: {e}")
            await ctx.send("Failed to remove schedule. Check logs for details.")

    async def update_permission(self, channel_id, role_id, permission, value):
        """Update channel permissions at scheduled time"""
        try:
            channel = self.bot.get_channel(channel_id)
            role = channel.guild.get_role(role_id)
            
            overwrite = channel.overwrites_for(role)
            setattr(overwrite, permission, value)
            await channel.set_permissions(role, overwrite=overwrite)
            
            logger.info(f"Updated permissions for {channel.name}: {permission}={value}")
            
        except Exception as e:
            logger.error(f"Failed to update permission: {e}")

async def setup(bot):
    await bot.add_cog(PermissionManager(bot))