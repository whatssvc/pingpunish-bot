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
from difflib import get_close_matches

# Dummy web server for Render
def run_web_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

# Role IDs
PINGPROTECT_ROLE_ID = 1391654796989169707
CONTROL_ROLE_ID = 1392243928673161296  # for /setprefix and /setcountchannel

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

# Track banned users and their names
banned_users_by_guild = defaultdict(dict)  # guild_id -> {name: user_id}


class MyBot(commands.Bot):
    def __init__(self):
        # Use sync prefix getter here, commands.Bot requires this
        super().__init__(command_prefix=self.get_prefix, intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    def get_prefix(self, message):
        # Synchronous function for prefix (required)
        if not message.guild:
            return DEFAULT_PREFIX
        return prefixes.get(message.guild.id, DEFAULT_PREFIX)


bot = MyBot()


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")


# =======================
#  Prefix Set Command
# =======================

@bot.tree.command(name="setprefix", description="Set a custom prefix")
@app_commands.describe(new_prefix="The new prefix to use")
async def setprefix(interaction: discord.Interaction, new_prefix: str):
    if CONTROL_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission to set the prefix.", ephemeral=True)
        return
    prefixes[interaction.guild.id] = new_prefix
    await interaction.response.send_message(f"✅ Prefix set to `{new_prefix}`", ephemeral=True)


# =======================
#  Ping Punishment
# =======================

@bot.tree.command(name="pingpunish", description="Protect a user or role from being pinged twice")
@app_commands.describe(target="User or role to protect")
async def slash_pingpunish(interaction: discord.Interaction, target: discord.Member | discord.Role):
    if PINGPROTECT_ROLE_ID not in [role.id for role in interaction.user.roles]:
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
    if PINGPROTECT_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    if target.id in mention_tracker[interaction.guild.id]:
        del mention_tracker[interaction.guild.id][target.id]
        await interaction.response.send_message(f"🔓 {target.mention} is no longer protected.", ephemeral=True)
    else:
        await interaction.response.send_message(f"ℹ️ {target.mention} was not protected.", ephemeral=True)


@bot.command(name="pingpunish")
async def prefix_pingpunish(ctx, target: discord.Member | discord.Role):
    if PINGPROTECT_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission.")
        return
    if target.id in mention_tracker[ctx.guild.id]:
        await ctx.send(f"⚠️ {target.mention} is already protected.")
        return
    mention_tracker[ctx.guild.id][target.id] = []
    await ctx.send(f"🔒 {target.mention} is now protected.")


@bot.command(name="unpingpunish")
async def prefix_unpingpunish(ctx, target: discord.Member | discord.Role):
    if PINGPROTECT_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission.")
        return
    if target.id in mention_tracker[ctx.guild.id]:
        del mention_tracker[ctx.guild.id][target.id]
        await ctx.send(f"🔓 {target.mention} is no longer protected.")
    else:
        await ctx.send(f"ℹ️ {target.mention} was not protected.")


# =======================
#  Set Counting Channel
# =======================

@bot.tree.command(name="setcountchannel", description="Set the channel for the counting game")
@app_commands.describe(channel="The counting channel")
async def setcountchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    if CONTROL_ROLE_ID not in [role.id for role in interaction.user.roles]:
        await interaction.response.send_message("❌ You don't have permission to set the counting channel.", ephemeral=True)
        return
    count_channels[interaction.guild.id] = channel.id
    current_count[interaction.guild.id] = 0
    cooldowns[interaction.guild.id] = defaultdict(float)
    await interaction.response.send_message(f"✅ Counting game set in {channel.mention}", ephemeral=True)


@bot.command(name="setcountchannel")
async def prefix_setcountchannel(ctx, channel: discord.TextChannel):
    if CONTROL_ROLE_ID not in [role.id for role in ctx.author.roles]:
        await ctx.send("❌ You don't have permission to set the counting channel.")
        return
    count_channels[ctx.guild.id] = channel.id
    current_count[ctx.guild.id] = 0
    cooldowns[ctx.guild.id] = defaultdict(float)
    await ctx.send(f"✅ Counting game set in {channel.mention}")


# =======================
#  Modban / Unmodban Commands
# =======================

@bot.tree.command(name="modban", description="Permanently ban a user by name or mention")
@app_commands.describe(target="User to ban", reason="Reason for the ban")
async def modban(interaction: discord.Interaction, target: discord.User, reason: str):
    if target.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't ban yourself.", ephemeral=True)
        return
    try:
        await interaction.guild.ban(target, reason=reason)
        banned_users_by_guild[interaction.guild.id][target.name.lower()] = target.id
        try:
            await target.send(f"You have been permanently banned from **{interaction.guild.name}**.\nReason: {reason}")
        except:
            pass
        await interaction.response.send_message(f"✅ Permanently banned {target.mention}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to ban that user.", ephemeral=True)


@bot.tree.command(name="unmodban", description="Unban a previously banned user by name")
@app_commands.describe(name="Name of the banned user")
async def unmodban(interaction: discord.Interaction, name: str):
    name = name.lower()
    banned_dict = banned_users_by_guild.get(interaction.guild.id, {})
    close_matches = get_close_matches(name, banned_dict.keys(), n=1, cutoff=0.6)

    if not close_matches:
        await interaction.response.send_message("⚠️ Couldn't find a banned user matching that name.", ephemeral=True)
        return

    matched_name = close_matches[0]
    user_id = banned_dict[matched_name]
    try:
        await interaction.guild.unban(discord.Object(id=user_id), reason="Unmodban command")
        del banned_users_by_guild[interaction.guild.id][matched_name]
        try:
            user = await bot.fetch_user(user_id)
            await user.send(f"You have been unbanned from **{interaction.guild.name}**.")
        except:
            pass
        await interaction.response.send_message(f"✅ Unbanned `{matched_name}`")
    except discord.NotFound:
        await interaction.response.send_message("⚠️ That user was not found in the ban list.", ephemeral=True)


# =======================
#  Event Handlers
# =======================

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
            # Remove timestamps older than 60 seconds
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

    # Counting game logic
    if guild_id in count_channels and message.channel.id == count_channels[guild_id]:
        expected = current_count.get(guild_id, 0) + 1
        user_cooldowns = cooldowns[guild_id]
        cooldown_end = user_cooldowns.get(message.author.id, 0)

        if time.time() < cooldown_end:
            return  # Still on cooldown

        try:
            number = int(message.content.strip())
        except ValueError:
            return

        if number != expected:
            user_cooldowns[message.author.id] = time.time() + 10
            current_count[guild_id] = 0

            embed = discord.Embed(
                title="❌ Wrong number!",
                description=f"{message.author.mention} messed up the count!\nRestarting...",
                color=discord.Color.red()
            )
            embed.add_field(name="⏳ Cooldown", value="10 seconds", inline=False)
            msg = await message.channel.send(embed=embed)

            for i in range(9, 0, -1):
                await asyncio.sleep(1)
                embed.set_field_at(0, name="⏳ Cooldown", value=f"{i} seconds", inline=False)
                await msg.edit(embed=embed)

            await asyncio.sleep(1)
            await msg.delete()
            return

        current_count[guild_id] = number
        bot_response = number + 1
        current_count[guild_id] = bot_response
        await message.channel.send(str(bot_response))

    await bot.process_commands(message)


# =======================
#  Run the Bot
# =======================

bot.run(TOKEN)
