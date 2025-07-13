import discord
from discord.ext import commands
from discord import app_commands
import os
import time
import datetime
import asyncio
from dotenv import load_dotenv
from collections import defaultdict
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading
import json

# Dummy web server for Render
def run_web_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# Prefix management
DEFAULT_PREFIX = "!"
prefixes = defaultdict(lambda: DEFAULT_PREFIX)

# Ping protection tracking
mention_tracker = defaultdict(lambda: defaultdict(list))  # guild_id -> {target_id: timestamps}

# Counting game tracking
count_channels = {}        # guild_id -> channel_id
current_count = {}         # guild_id -> number
cooldowns = defaultdict(lambda: defaultdict(float))  # guild_id -> {user_id: cooldown_end_time}

# -------------------
# Permissions system
# -------------------

perm_file_path = "permissions.json"

# Default fallback role IDs
DEFAULT_COMMAND_ROLES = {
    "pingpunish": 1391654796989169707,
    "setprefix": 1392243928673161296,
    "setcountchannel": 1392243928673161296,
}

# Load permissions
if os.path.exists(perm_file_path):
    with open(perm_file_path, "r") as f:
        command_permissions = json.load(f)
    command_permissions = {int(g): {k: int(v) for k, v in perms.items()} for g, perms in command_permissions.items()}
else:
    command_permissions = {}

def save_permissions():
    with open(perm_file_path, "w") as f:
        json.dump(command_permissions, f, indent=2)

def get_allowed_role(guild_id, command_name):
    guild_perms = command_permissions.get(guild_id, {})
    return guild_perms.get(command_name, DEFAULT_COMMAND_ROLES.get(command_name))

def set_command_role(guild_id, command_name, role_id):
    if guild_id not in command_permissions:
        command_permissions[guild_id] = {}
    command_permissions[guild_id][command_name] = role_id
    save_permissions()

# -------------------

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=self.get_prefix, intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def get_prefix(self, message):
        return prefixes.get(message.guild.id, DEFAULT_PREFIX)

bot = MyBot()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

# -------------
# Role permission set command for server owner only
# -------------

@bot.tree.command(name="role", description="Set which role can use a command (server owner only)")
@app_commands.describe(command_name="Command to configure", role="Role to assign permission to")
async def set_role_permission(interaction: discord.Interaction, command_name: str, role: discord.Role):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("❌ Only the server owner can change command permissions.", ephemeral=True)
        return

    command_name = command_name.lower()
    valid_commands = DEFAULT_COMMAND_ROLES.keys()

    if command_name not in valid_commands:
        await interaction.response.send_message(f"❌ Invalid command. Valid commands: {', '.join(valid_commands)}", ephemeral=True)
        return

    set_command_role(interaction.guild.id, command_name, role.id)
    await interaction.response.send_message(f"✅ `{command_name}` can now be used by `{role.name}`.", ephemeral=True)

# -------------
# Prefix Set Command
# -------------

@bot.tree.command(name="setprefix", description="Set a custom prefix")
@app_commands.describe(new_prefix="The new prefix to use")
async def setprefix(interaction: discord.Interaction, new_prefix: str):
    allowed_role = get_allowed_role(interaction.guild.id, "setprefix")
    if allowed_role not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission to set the prefix.", ephemeral=True)
        return
    prefixes[interaction.guild.id] = new_prefix
    await interaction.response.send_message(f"✅ Prefix set to `{new_prefix}`", ephemeral=True)

# -------------
# Ping Punishment
# -------------

@bot.tree.command(name="pingpunish", description="Protect a user or role from being pinged twice")
@app_commands.describe(target="User or role to protect")
async def slash_pingpunish(interaction: discord.Interaction, target: discord.Member | discord.Role):
    allowed_role = get_allowed_role(interaction.guild.id, "pingpunish")
    if allowed_role not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    if target.id in mention_tracker[interaction.guild.id]:
        await interaction.response.send_message(f"⚠️ {target.mention} is already protected.", ephemeral=True)
        return
    mention_tracker[interaction.guild.id][target.id] = []
    await interaction.response.send_message(f"🔒 {target.mention} is now protected.", ephemeral=True)

@bot.tree.command(name="unpingpunish", description="Remove ping protection")
@app_commands.describe(target="User or role to unprotect")
async def slash_unpingpunish(interaction: discord.Interaction, target: discord.Member | discord.Role):
    allowed_role = get_allowed_role(interaction.guild.id, "pingpunish")
    if allowed_role not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    if target.id in mention_tracker[interaction.guild.id]:
        del mention_tracker[interaction.guild.id][target.id]
        await interaction.response.send_message(f"🔓 {target.mention} is no longer protected.", ephemeral=True)
    else:
        await interaction.response.send_message(f"ℹ️ {target.mention} was not protected.", ephemeral=True)

@bot.command(name="pingpunish")
async def prefix_pingpunish(ctx, target: discord.Member | discord.Role):
    allowed_role = get_allowed_role(ctx.guild.id, "pingpunish")
    if allowed_role not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission.")
        return
    if target.id in mention_tracker[ctx.guild.id]:
        await ctx.send(f"⚠️ {target.mention} is already protected.")
        return
    mention_tracker[ctx.guild.id][target.id] = []
    await ctx.send(f"🔒 {target.mention} is now protected.")

@bot.command(name="unpingpunish")
async def prefix_unpingpunish(ctx, target: discord.Member | discord.Role):
    allowed_role = get_allowed_role(ctx.guild.id, "pingpunish")
    if allowed_role not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission.")
        return
    if target.id in mention_tracker[ctx.guild.id]:
        del mention_tracker[ctx.guild.id][target.id]
        await ctx.send(f"🔓 {target.mention} is no longer protected.")
    else:
        await ctx.send(f"ℹ️ {target.mention} was not protected.")

# -------------
# Set Counting Channel
# -------------

@bot.tree.command(name="setcountchannel", description="Set the channel for the counting game")
@app_commands.describe(channel="The counting channel")
async def setcountchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    allowed_role = get_allowed_role(interaction.guild.id, "setcountchannel")
    if allowed_role not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission to set the counting channel.", ephemeral=True)
        return
    count_channels[interaction.guild.id] = channel.id
    current_count[interaction.guild.id] = 0
    cooldowns[interaction.guild.id] = defaultdict(float)
    await interaction.response.send_message(f"✅ Counting game set in {channel.mention}", ephemeral=True)

@bot.command(name="setcountchannel")
async def prefix_setcountchannel(ctx, channel: discord.TextChannel):
    allowed_role = get_allowed_role(ctx.guild.id, "setcountchannel")
    if allowed_role not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission to set the counting channel.")
        return
    count_channels[ctx.guild.id] = channel.id
    current_count[ctx.guild.id] = 0
    cooldowns[ctx.guild.id] = defaultdict(float)
    await ctx.send(f"✅ Counting game set in {channel.mention}")

# -------------
# Event Handlers
# -------------

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = message.guild.id
    now = time.time()

    # Ping protection logic
    mentioned_ids = [m.id for m in message.mentions] + [r.id for r in message.role_mentions]
    for target_id, timestamps in mention_tracker[guild_id].items():
        if target_id in mentioned_ids:
            timestamps = [t for t in timestamps if now - t < 60]
            timestamps.append(now)
            mention_tracker[guild_id][target_id] = timestamps

            if len(timestamps) >= 2:
                until = discord.utils.utcnow() + datetime.timedelta(seconds=60)
                try:
                    await message.author.timeout(until, reason="Double pinged protected member/role")
                    await message.channel.send(f"🔇 {message.author.mention} was timed out for pinging <@{target_id}> twice.")
                except
