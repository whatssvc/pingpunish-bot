import discord
from discord.ext import commands
from discord import app_commands
import os
import time
import asyncio
from dotenv import load_dotenv
from collections import defaultdict
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading

# Run dummy server so Render doesn't complain about ports
def run_web_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# Load token & guild from Render's env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
MOD_ROLE_ID = 1391654796989169707

# Intents required (make sure you enable them in the Dev Portal)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# Prefix system
DEFAULT_PREFIX = "!"
prefixes = defaultdict(lambda: DEFAULT_PREFIX)

# Track pings: guild -> target_id -> list[timestamps]
mention_tracker = defaultdict(lambda: defaultdict(list))

# Create bot
class PingBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=self.get_prefix, intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def get_prefix(self, message):
        return prefixes.get(message.guild.id, DEFAULT_PREFIX)

bot = PingBot()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

# Slash command: Set prefix
@bot.tree.command(name="setprefix", description="Set a custom prefix for this server")
@app_commands.describe(new_prefix="New command prefix")
async def setprefix(interaction: discord.Interaction, new_prefix: str):
    if MOD_ROLE_ID not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    prefixes[interaction.guild.id] = new_prefix
    await interaction.response.send_message(f"✅ Prefix set to `{new_prefix}`", ephemeral=True)

# Slash command: Protect someone from pings
@bot.tree.command(name="pingpunish", description="Protect a user or role from double-pings")
@app_commands.describe(target="The user or role to protect")
async def slash_pingpunish(interaction: discord.Interaction, target: discord.Member | discord.Role):
    if MOD_ROLE_ID not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    mention_tracker[interaction.guild.id][target.id] = []
    await interaction.response.send_message(f"🔒 {target.mention} is now protected from double-pings.", ephemeral=True)

# Prefix version of pingpunish
@bot.command(name="pingpunish")
async def prefix_pingpunish(ctx, target: discord.Member | discord.Role):
    if MOD_ROLE_ID not in [r.id for r in ctx.author.roles]:
        await ctx.send("❌ You don't have permission.")
        return
    mention_tracker[ctx.guild.id][target.id] = []
    await ctx.send(f"🔒 {target.mention} is now protected from double-pings.")

# Event: Check pings and mute
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = message.guild.id
    now = time.time()
    mentioned_ids = [m.id for m in message.mentions] + [r.id for r in message.role_mentions]

    for target_id, timestamps in mention_tracker[guild_id].items():
        if target_id in mentioned_ids:
            timestamps = [t for t in timestamps if now - t < 60]
            timestamps.append(now)
            mention_tracker[guild_id][target_id] = timestamps

            if len(timestamps) >= 2:
                mute_role = await get_or_create_mute_role(message.guild)
                await message.author.add_roles(mute_role, reason="Double pinged protected member")
                await message.channel.send(f"🔇 {message.author.mention} muted for pinging <@{target_id}> twice.")
                await asyncio.sleep(60)
                await message.author.remove_roles(mute_role)
                mention_tracker[guild_id][target_id] = []
                return

    await bot.process_commands(message)

# Create or get Muted role
async def get_or_create_mute_role(guild):
    role = discord.utils.get(guild.roles, name="Muted")
    if not role:
        role = await guild.create_role(name="Muted", reason="Ping protection mute")
        for channel in guild.channels:
            try:
                await channel.set_permissions(role, send_messages=False, add_reactions=False)
            except Exception:
                continue
    return role

# Run bot
bot.run(TOKEN)
