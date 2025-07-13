import discord
from discord.ext import commands
from discord import app_commands
import os
import time
import asyncio
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
MOD_ROLE_ID = 1391654796989169707  # Only members with this role can use admin commands

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

DEFAULT_PREFIX = "!"
prefixes = defaultdict(lambda: DEFAULT_PREFIX)
mention_tracker = defaultdict(lambda: defaultdict(list))  # {guild_id: {target_id: [timestamps]}}

class PingBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=self.get_prefix, intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def get_prefix(self, message):
        return prefixes.get(message.guild.id, DEFAULT_PREFIX)

bot = PingBot()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# Slash command: setprefix
@bot.tree.command(name="setprefix", description="Set a custom prefix for text commands")
@app_commands.describe(new_prefix="The new prefix to use")
async def setprefix(interaction: discord.Interaction, new_prefix: str):
    if MOD_ROLE_ID not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message("You don't have permission to set the prefix.", ephemeral=True)
        return
    prefixes[interaction.guild.id] = new_prefix
    await interaction.response.send_message(f"Prefix set to `{new_prefix}`", ephemeral=True)

# Slash command: pingpunish
@bot.tree.command(name="pingpunish", description="Protect a user or role from repeated pings")
@app_commands.describe(target="The user or role to protect")
async def pingpunish(interaction: discord.Interaction, target: discord.Member | discord.Role):
    if MOD_ROLE_ID not in [r.id for r in interaction.user.roles]:
        await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
        return
    mention_tracker[interaction.guild.id][target.id] = []
    await interaction.response.send_message(f"{target.mention} is now protected from double-pings.", ephemeral=True)

# Prefix command version
@bot.command()
async def pingpunish(ctx, target: discord.Member | discord.Role):
    if MOD_ROLE_ID not in [r.id for r in ctx.author.roles]:
        await ctx.send("You don't have permission to use this command.")
        return
    mention_tracker[ctx.guild.id][target.id] = []
    await ctx.send(f"{target.mention} is now protected from double-pings.")

# Watch for pings and punish
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = message.guild.id
    now = time.time()
    mentioned_ids = [m.id for m in message.mentions] + [r.id for r in message.role_mentions]

    for target_id in mention_tracker[guild_id].keys():
        if target_id in mentioned_ids:
            timestamps = mention_tracker[guild_id][target_id]
            timestamps = [t for t in timestamps if now - t < 60]
            timestamps.append(now)
            mention_tracker[guild_id][target_id] = timestamps

            if len(timestamps) >= 2:
                mute_role = await get_or_create_mute_role(message.guild)
                await message.author.add_roles(mute_role, reason="Pinged protected target twice")
                await message.channel.send(f"{message.author.mention} muted for pinging {target_id} twice!")
                await asyncio.sleep(60)
                await message.author.remove_roles(mute_role)
                mention_tracker[guild_id][target_id] = []
                return

    await bot.process_commands(message)

async def get_or_create_mute_role(guild):
    role = discord.utils.get(guild.roles, name="Muted")
    if not role:
        role = await guild.create_role(name="Muted", reason="For ping punish")
        for channel in guild.channels:
            try:
                await channel.set_permissions(role, send_messages=False, add_reactions=False)
            except:
                continue
    return role

bot.run(TOKEN)
