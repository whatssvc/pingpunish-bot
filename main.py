import discord
from discord.ext import commands
from discord import app_commands
import os
import time
import asyncio
import datetime
from dotenv import load_dotenv
from collections import defaultdict
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading

# Dummy server so Render doesn't complain about ports
def run_web_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))  # This is your server ID
MOD_ROLE_ID = 1391654796989169707      # Only members with this role can use punish/unpunish

# Intents setup (enable in dev portal too)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# Prefixes stored in-memory (default is "!")
DEFAULT_PREFIX = "!"
prefixes = defaultdict(lambda: DEFAULT_PREFIX)

# Tracking pings: guild_id -> target_id -> list[timestamps]
mention_tracker = defaultdict(lambda: defaultdict(list))

# Bot setup
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

# Set prefix via slash command
@bot.tree.command(name="setprefix", description="Set a custom prefix for this server")
@app_commands.describe(new_prefix="The new prefix")
async def setprefix(interaction: discord.Interaction, new_prefix: str):
    if MOD_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    prefixes[interaction.guild.id] = new_prefix
    await interaction.response.send_message(f"✅ Prefix set to `{new_prefix}`", ephemeral=True)

# Slash: Enable ping protection
@bot.tree.command(name="pingpunish", description="Protect a user or role from being pinged twice")
@app_commands.describe(target="The user or role to protect")
async def slash_pingpunish(interaction: discord.Interaction, target: discord.Member | discord.Role):
    if MOD_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    mention_tracker[interaction.guild.id][target.id] = []
    await interaction.response.send_message(f"🔒 {target.mention} is now protected.", ephemeral=True)

# Slash: Disable ping protection
@bot.tree.command(name="unpingpunish", description="Remove ping protection from a user or role")
@app_commands.describe(target="The user or role to unprotect")
async def slash_unpingpunish(interaction: discord.Interaction, target: discord.Member | discord.Role):
    if MOD_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    if target.id in mention_tracker[interaction.guild.id]:
        del mention_tracker[interaction.guild.id][target.id]
        await interaction.response.send_message(f"🔓 {target.mention} is no longer protected.", ephemeral=True)
    else:
        await interaction.response.send_message(f"ℹ️ {target.mention} was not protected.", ephemeral=True)

# Prefix version: enable ping protection
@bot.command(name="pingpunish")
async def prefix_pingpunish(ctx, target: discord.Member | discord.Role):
    if MOD_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission.")
        return

    mention_tracker[ctx.guild.id][target.id] = []
    await ctx.send(f"🔒 {target.mention} is now protected.")

# Prefix version: disable ping protection
@bot.command(name="unpingpunish")
async def prefix_unpingpunish(ctx, target: discord.Member | discord.Role):
    if MOD_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission.")
        return

    if target.id in mention_tracker[ctx.guild.id]:
        del mention_tracker[ctx.guild.id][target.id]
        await ctx.send(f"🔓 {target.mention} is no longer protected.")
    else:
        await ctx.send(f"ℹ️ {target.mention} was not protected.")

# Monitor messages for double-pings
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
                until = discord.utils.utcnow() + datetime.timedelta(seconds=60)
                try:
                    await message.author.timeout(until, reason="Double pinged protected member/role")
                    await message.channel.send(f"🔇 {message.author.mention} was timed out for pinging <@{target_id}> twice.")
                except discord.Forbidden:
                    await message.channel.send("❌ I don't have permission to timeout this user.")
                mention_tracker[guild_id][target_id] = []
                return

    await bot.process_commands(message)

# Start the bot
bot.run(TOKEN)
