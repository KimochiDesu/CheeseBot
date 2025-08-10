import discord
from discord import app_commands
from discord.ext import tasks
import json
import os
import asyncio
import logging
from datetime import datetime, time, timedelta
from dotenv import load_dotenv
from scraper import get_cheese_of_the_day, get_cheese_details, get_random_cheese

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    logger.error("DISCORD_TOKEN not found in environment variables!")
    exit(1)

CONFIG_FILE = "config.json"

def load_config():
    """Load bot configuration from JSON file."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Error loading config: {e}")
        return {}

def save_config(data):
    """Save bot configuration to JSON file."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

config = load_config()

class CheeseBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # Required for some bot features
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        """Called when the bot is starting up."""
        try:
            await self.tree.sync()
            logger.info("Command tree synced successfully")
            self.daily_cheese_task.start()
            logger.info("Daily cheese task started")
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}")

    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        
        # Set bot status
        activity = discord.Activity(
            type=discord.ActivityType.watching, 
            name="cheese.com for daily updates 🧀"
        )
        await self.change_presence(activity=activity)

    def make_cheese_embed(self, data):
        """Create a rich Discord embed for cheese information."""
        # Choose embed color based on cheese characteristics
        color = discord.Color.yellow()  # Default
        if data.get('colour'):
            colour_text = data['colour'].lower()
            if 'white' in colour_text:
                color = discord.Color.from_rgb(255, 255, 240)  # Ivory
            elif 'blue' in colour_text:
                color = discord.Color.blue()
            elif 'orange' in colour_text or 'yellow' in colour_text:
                color = discord.Color.orange()
            elif 'red' in colour_text:
                color = discord.Color.red()

        embed = discord.Embed(
            title=f"🧀 {data['name']}", 
            description=data.get("about") or "No description available.",
            color=color,
            url=data.get("source_url")
        )

        # Main image
        if data.get("image_url"):
            embed.set_thumbnail(url=data["image_url"])

        # Add structured fields in organized sections
        basic_info = []
        if data.get("made_from"):
            basic_info.append(f"**Made from:** {data['made_from']}")
        if data.get("country_of_origin"):
            basic_info.append(f"**Country:** {data['country_of_origin']}")
        if data.get("region"):
            basic_info.append(f"**Region:** {data['region']}")
        
        if basic_info:
            embed.add_field(name="🌍 Origin", value="\n".join(basic_info), inline=True)

        characteristics = []
        if data.get("family"):
            characteristics.append(f"**Family:** {data['family']}")
        if data.get("type"):
            characteristics.append(f"**Type:** {data['type']}")
        if data.get("texture"):
            characteristics.append(f"**Texture:** {data['texture']}")
        
        if characteristics:
            embed.add_field(name="📋 Classification", value="\n".join(characteristics), inline=True)

        sensory = []
        if data.get("colour"):
            sensory.append(f"**Color:** {data['colour']}")
        if data.get("flavour"):
            sensory.append(f"**Flavor:** {data['flavour']}")
        if data.get("aroma"):
            sensory.append(f"**Aroma:** {data['aroma']}")
        
        if sensory:
            embed.add_field(name="👃 Sensory", value="\n".join(sensory), inline=True)

        # Add vegetarian info if available
        if data.get("vegetarian"):
            embed.add_field(name="🌱 Dietary", value=f"Vegetarian: {data['vegetarian']}", inline=True)

        # Add source link
        if data.get("source_url"):
            embed.add_field(
                name="🔗 More Information", 
                value=f"[View on Cheese.com]({data['source_url']})", 
                inline=False
            )

        # Footer with additional context
        footer_text = "Data from cheese.com"
        if data.get("about_images") and len(data["about_images"]) > 1:
            footer_text += f" • {len(data['about_images'])} images available"
        
        embed.set_footer(text=footer_text)

        # Truncate description if too long
        if len(embed.description) > 2048:
            embed.description = embed.description[:2045] + "..."

        return embed

    def seconds_until_next_run(self):
        """Calculate seconds until next scheduled run in PH time."""
        if "cheese_time" not in config:
            return None
        try:
            hour, minute = map(int, config["cheese_time"].split(":"))
        except ValueError:
            return None

        # Current time in UTC
        now_utc = datetime.utcnow()

        # Target time in PH (UTC+8), then convert to UTC
        target_ph = datetime.combine(now_utc.date(), time(hour, minute))
        target_utc = target_ph - timedelta(hours=8)

        if now_utc >= target_utc:
            target_utc += timedelta(days=1)

        return (target_utc - now_utc).total_seconds()

    @tasks.loop(minutes=1)
    async def daily_cheese_task(self):
        """Background task for posting daily cheese."""
        if "cheese_channel" not in config or "cheese_time" not in config:
            logger.debug("Daily cheese task skipped - missing channel or time config")
            return

        try:
            # Check if it's the right minute to post
            now_ph = datetime.utcnow() + timedelta(hours=8)
            set_hour, set_minute = map(int, config["cheese_time"].split(":"))
            
            # Add debug logging
            logger.debug(f"Current PH time: {now_ph.strftime('%H:%M')}, Target: {config['cheese_time']}")
            
            if now_ph.hour == set_hour and now_ph.minute == set_minute:
                logger.info("Time match! Starting daily cheese post...")
                
                url, cheese_name = get_cheese_of_the_day()
                details = get_cheese_details(url)
                embed = self.make_cheese_embed(details)
                
                channel = self.get_channel(config["cheese_channel"])
                if channel:
                    logger.info(f"Found channel: {channel.name} in {channel.guild.name}")
                    
                    # Check if there's a cheese role to ping
                    content = "🧀 **Daily Cheese Alert!** 🧀"
                    if "cheese_role_id" in config:
                        role = channel.guild.get_role(config["cheese_role_id"])
                        if role:
                            content = f"🧀 **Daily Cheese Alert!** 🧀 {role.mention}"
                            logger.info(f"Will ping role: {role.name}")
                        else:
                            logger.warning(f"Cheese role ID {config['cheese_role_id']} not found")
                    
                    await channel.send(content=content, embed=embed)
                    logger.info(f"✅ Posted daily cheese: {cheese_name}")
                else:
                    logger.error(f"Could not find channel with ID {config['cheese_channel']}")
                
                # Sleep to avoid posting multiple times in the same minute
                await asyncio.sleep(65)
            else:
                # Only log every 10 minutes to avoid spam
                if now_ph.minute % 10 == 0:
                    logger.debug(f"Waiting for cheese time. Current: {now_ph.strftime('%H:%M')}, Target: {config['cheese_time']}")
                    
        except Exception as e:
            logger.error(f"Error posting daily cheese: {e}", exc_info=True)

    @daily_cheese_task.before_loop
    async def before_daily_cheese_task(self):
        """Wait for bot to be ready before starting daily task."""
        await self.wait_until_ready()

bot = CheeseBot()

# Command: Set cheese channel
@bot.tree.command(name="setcheesechannel", description="Set the channel for daily Cheese of the Day posts.")
@app_commands.describe(channel="The channel to post daily cheese updates (optional, defaults to current channel)")
async def setcheesechannel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    # Check if user has permission (admin or manage channels)
    if not interaction.user.guild_permissions.manage_channels:
        embed = discord.Embed(
            title="❌ Permission Denied",
            description="You need the 'Manage Channels' permission to set the cheese channel.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
        
    target_channel = channel or interaction.channel
    config["cheese_channel"] = target_channel.id
    save_config(config)
    
    embed = discord.Embed(
        title="✅ Channel Set",
        description=f"Daily cheese updates will be posted in {target_channel.mention}",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Command: Set cheese time
@bot.tree.command(name="setcheesetime", description="Set the time for daily Cheese of the Day posts (Philippine Time).")
@app_commands.describe(time="Time in HH:MM format (24-hour, Philippine Time)")
async def setcheesetime(interaction: discord.Interaction, time: str):
    # Check if user has permission (admin or manage channels)
    if not interaction.user.guild_permissions.manage_channels:
        embed = discord.Embed(
            title="❌ Permission Denied",
            description="You need the 'Manage Channels' permission to set the cheese time.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Validate time format
    try:
        # Try to parse the time to validate format
        datetime.strptime(time, "%H:%M")
        hour, minute = map(int, time.split(":"))
        
        # Validate hour and minute ranges
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            raise ValueError("Invalid time range")
            
    except ValueError:
        embed = discord.Embed(
            title="❌ Invalid Time Format",
            description="Please use HH:MM format (24-hour). Examples: `09:00`, `14:30`, `23:59`",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    config["cheese_time"] = time
    save_config(config)
    
    # Convert to 12-hour format for display
    try:
        dt = datetime.strptime(time, "%H:%M")
        friendly_time = dt.strftime("%I:%M %p")
    except ValueError:
        friendly_time = time
    
    embed = discord.Embed(
        title="✅ Time Set",
        description=f"Daily cheese updates will be posted at **{friendly_time}** (Philippine Time)",
        color=discord.Color.green()
    )
    
    # Calculate next post time
    seconds_left = bot.seconds_until_next_run()
    if seconds_left:
        hours = int(seconds_left // 3600)
        minutes = int((seconds_left % 3600) // 60)
        embed.add_field(
            name="⏰ Next Post", 
            value=f"In {hours}h {minutes}m", 
            inline=True
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Command: Set cheese role
@bot.tree.command(name="setcheeserole", description="Set a role to ping for daily cheese updates.")
@app_commands.describe(role="The role to ping for daily cheese updates")
async def setcheeserole(interaction: discord.Interaction, role: discord.Role):
    # Check if user has permission (admin or manage roles)
    if not interaction.user.guild_permissions.manage_roles:
        embed = discord.Embed(
            title="❌ Permission Denied",
            description="You need the 'Manage Roles' permission to set the cheese role.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    config["cheese_role_id"] = role.id
    save_config(config)
    
    embed = discord.Embed(
        title="✅ Cheese Role Set",
        description=f"The {role.mention} role will be pinged for daily cheese updates!",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Command: Remove cheese role
@bot.tree.command(name="removecheeserole", description="Remove the cheese notification role.")
async def removecheeserole(interaction: discord.Interaction):
    # Check if user has permission
    if not interaction.user.guild_permissions.manage_roles:
        embed = discord.Embed(
            title="❌ Permission Denied",
            description="You need the 'Manage Roles' permission to remove the cheese role.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if "cheese_role_id" in config:
        role_id = config["cheese_role_id"]
        role = interaction.guild.get_role(role_id)
        role_name = role.name if role else "Unknown Role"
        
        del config["cheese_role_id"]
        save_config(config)
        
        embed = discord.Embed(
            title="✅ Cheese Role Removed",
            description=f"The '{role_name}' role will no longer be pinged for daily cheese updates.",
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="ℹ️ No Role Set",
            description="There was no cheese notification role configured.",
            color=discord.Color.blue()
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Command: Join/Leave cheese role (for users)
@bot.tree.command(name="cheeserole", description="Join or leave the cheese notification role.")
async def cheeserole(interaction: discord.Interaction):
    if "cheese_role_id" not in config:
        embed = discord.Embed(
            title="❌ No Cheese Role",
            description="No cheese notification role has been set up yet. Ask an admin to set one using `/setcheeserole`.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    role = interaction.guild.get_role(config["cheese_role_id"])
    if not role:
        embed = discord.Embed(
            title="❌ Role Not Found",
            description="The configured cheese role no longer exists. Ask an admin to set a new one.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    user = interaction.user
    
    if role in user.roles:
        # User has the role, remove it
        try:
            await user.remove_roles(role, reason="User left cheese notifications")
            embed = discord.Embed(
                title="📤 Left Cheese Role",
                description=f"You've been removed from the {role.mention} role. You won't receive daily cheese pings anymore.",
                color=discord.Color.orange()
            )
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ Permission Error",
                description="I don't have permission to remove that role from you. Ask an admin for help.",
                color=discord.Color.red()
            )
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to remove role: {str(e)}",
                color=discord.Color.red()
            )
    else:
        # User doesn't have the role, add it
        try:
            await user.add_roles(role, reason="User joined cheese notifications")
            embed = discord.Embed(
                title="📥 Joined Cheese Role",
                description=f"You've been added to the {role.mention} role! You'll now receive daily cheese pings. 🧀",
                color=discord.Color.green()
            )
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ Permission Error",
                description="I don't have permission to give you that role. Ask an admin for help.",
                color=discord.Color.red()
            )
        except Exception as e:
            embed = discord.Embed(
                title="❌ Error",
                description=f"Failed to add role: {str(e)}",
                color=discord.Color.red()
            )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Command: Get daily cheese
@bot.tree.command(name="dailycheese", description="Get today's featured Cheese of the Day.")
async def dailycheese(interaction: discord.Interaction):
    try:
        await interaction.response.defer(thinking=True)
        logger.info(f"Daily cheese command called by {interaction.user}")
        
        url, cheese_name = get_cheese_of_the_day()
        logger.info(f"Got cheese URL: {url}, name: {cheese_name}")
        
        details = get_cheese_details(url)
        logger.info(f"Got cheese details for: {details.get('name', 'Unknown')}")
        
        embed = bot.make_cheese_embed(details)
        await interaction.followup.send(
            content="🌟 **Today's Featured Cheese** 🌟", 
            embed=embed
        )
        logger.info(f"✅ Served daily cheese: {cheese_name}")
    except Exception as e:
        logger.error(f"Error fetching daily cheese: {e}", exc_info=True)
        try:
            error_embed = discord.Embed(
                title="❌ Error",
                description="Sorry, I couldn't fetch today's cheese. The website might be temporarily unavailable.",
                color=discord.Color.red()
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
        except Exception as followup_error:
            logger.error(f"Failed to send error message: {followup_error}")

# Command: Get random cheese
@bot.tree.command(name="cheese", description="Discover a random cheese from around the world!")
async def cheese(interaction: discord.Interaction):
    try:
        await interaction.response.defer(thinking=True)
        logger.info(f"Random cheese command called by {interaction.user}")
        
        details = get_random_cheese()
        logger.info(f"Got random cheese: {details.get('name', 'Unknown')}")
        
        embed = bot.make_cheese_embed(details)
        await interaction.followup.send(
            content="🎲 **Random Cheese Discovery** 🎲", 
            embed=embed
        )
        logger.info(f"✅ Served random cheese: {details.get('name', 'Unknown')}")
    except Exception as e:
        logger.error(f"Error fetching random cheese: {e}", exc_info=True)
        try:
            error_embed = discord.Embed(
                title="❌ Error",
                description="Oops! I couldn't find a random cheese right now. Please try again in a moment.",
                color=discord.Color.red()
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
        except Exception as followup_error:
            logger.error(f"Failed to send error message: {followup_error}")

# Command: Show bot status and configuration
@bot.tree.command(name="cheesestatus", description="Show current bot configuration and status.")
async def cheesestatus(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Cheese Bot Status",
        color=discord.Color.blue()
    )
    
    # Channel info
    if "cheese_channel" in config:
        channel = bot.get_channel(config["cheese_channel"])
        channel_info = f"<#{config['cheese_channel']}>" if channel else "Channel not found"
    else:
        channel_info = "Not configured"
    
    # Role info
    if "cheese_role_id" in config:
        role = bot.get_guild(interaction.guild.id).get_role(config["cheese_role_id"]) if interaction.guild else None
        role_info = f"<@&{config['cheese_role_id']}>" if role else "Role not found"
    else:
        role_info = "Not configured"
    
    embed.add_field(name="🔔 Notification Role", value=role_info, inline=False)
    
    # Time info
    if "cheese_time" in config:
        try:
            dt = datetime.strptime(config["cheese_time"], "%H:%M")
            friendly_time = dt.strftime("%I:%M %p")
            time_info = f"{friendly_time} (Philippine Time)"
            
            # Calculate next post time
            seconds_left = bot.seconds_until_next_run()
            if seconds_left:
                hours = int(seconds_left // 3600)
                minutes = int((seconds_left % 3600) // 60)
                time_info += f"\nNext post in: {hours}h {minutes}m"
        except ValueError:
            time_info = "Invalid time format"
    else:
        time_info = "Not configured"
    
    embed.add_field(name="⏰ Daily Post Time", value=time_info, inline=False)
    
    # Commands info
    commands_info = (
        "`/cheese` - Random cheese\n"
        "`/dailycheese` - Today's featured cheese\n"
        "`/cheeserole` - Join/leave cheese notifications\n"
        "`/setcheesechannel` - Configure channel (Admin)\n"
        "`/setcheesetime` - Configure time (Admin)\n"
        "`/setcheeserole` - Set notification role (Admin)\n"
        "`/removecheeserole` - Remove notification role (Admin)"
    )
    embed.add_field(name="📋 Available Commands", value=commands_info, inline=False)
    
    embed.set_footer(text="Powered by cheese.com")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Command: Show help
@bot.tree.command(name="cheesehelp", description="Show detailed help and usage instructions.")
async def cheesehelp(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🧀 Cheese Bot Help",
        description="Your friendly neighborhood cheese expert!",
        color=discord.Color.gold()
    )
    
    # Commands section
    commands = [
        ("🎲 `/cheese`", "Get a random cheese from around the world"),
        ("🌟 `/dailycheese`", "Get today's featured Cheese of the Day"),
        ("🔔 `/cheeserole`", "Join or leave daily cheese notifications"),
        ("📺 `/setcheesechannel`", "Set channel for daily cheese posts (Admin only)"),
        ("⏰ `/setcheesetime`", "Set time for daily posts in PH time (Admin only)"),
        ("🔔 `/setcheeserole`", "Set role to ping for daily cheese (Admin only)"),
        ("🚫 `/removecheeserole`", "Remove cheese notification role (Admin only)"),
        ("📊 `/cheesestatus`", "View current bot configuration"),
        ("❓ `/cheesehelp`", "Show this help message")
    ]
    
    for name, desc in commands:
        embed.add_field(name=name, value=desc, inline=False)
    
    embed.add_field(
        name="ℹ️ About",
        value="This bot scrapes cheese information from cheese.com to bring you daily cheese discoveries!",
        inline=False
    )
    
    embed.set_footer(text="Made with ❤️ for cheese lovers")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Error handling
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"Command error: {error}")
    
    if not interaction.response.is_done():
        embed = discord.Embed(
            title="❌ Command Error",
            description="An unexpected error occurred. Please try again later.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(
            title="❌ Error",
            description="Something went wrong while processing your request.",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        logger.error("Invalid Discord token! Please check your DISCORD_TOKEN in the .env file.")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")