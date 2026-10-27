"""Secret Sandy Claws: a Discord bot that runs a Secret Santa.

How a game works:
  1. Someone types `!start @a @b @c ...` in a server channel. They become
     the organizer.
  2. The bot DMs every participant at once, asking what gift they'd like.
  3. Once everyone has replied (or run out of time), the bot shuffles the
     participants into a loop and DMs each person who they're buying for,
     along with that person's wish.

The organizer can use `!check` to see who has replied so far, and `!clear`
to cancel the game.

The bot is built on the discord.py library. Most functions are `async`:
they can pause at each `await` (for example, while waiting for a reply)
so the bot can handle other people's messages in the meantime.

Run it with the DISCORD_TOKEN environment variable set to your bot's
token. See README.md for setup.
"""

import asyncio
import os
import random

import discord
from discord.ext import commands

# Only the message content intent is needed (for "!" commands). It is
# privileged, so enable it for the bot in the Discord Developer Portal.
intents = discord.Intents.default()
intents.message_content = True

# The bot itself. Messages starting with "!" are treated as commands.
# Never ping anyone, even if a name or wish looks like a mention.
client = commands.Bot(command_prefix='!', intents=intents, allowed_mentions=discord.AllowedMentions.none())

# --- Settings ---

# How long each participant has to send their wish, in seconds.
RESPONSE_TIMEOUT = int(os.environ.get('SANTA_RESPONSE_TIMEOUT', 24 * 60 * 60))
# Used as the wish when someone doesn't reply, or replies with nothing.
NO_WISH = 'No wish given, surprise them!'
# Keeps the pairing message under Discord's 2000 character limit.
MAX_WISH_LENGTH = 1500

# Joke lines. One from chat_messages is posted in the server channel each
# time someone replies; one from received_confirmed is DMed back to them.
chat_messages = ['Hes Coming', 'He Knows', 'Its simple, we kill the batman', 'Sandy Claws is coming to town']
received_confirmed = ['K', 'Why Though?', 'Really?', 'Nah, you are getting coal', 'Wow, everyone, and I mean everyone, is dumber with this is in world', 'Good idea!', 'Wow, this will be great!', 'I never would have thought of that.']


class Game:
    """Everything the bot knows about one running Secret Santa."""

    def __init__(self, organizer, participants):
        self.organizer = organizer  # the member who typed !start
        self.participants = participants  # list of discord.Member
        self.gift_ideas = {}  # member id -> wish
        self.task = None  # the running !start command, so !clear can stop it


# --- Running games ---
# These live in memory only, so restarting the bot loses any game in progress.

# One game per server, keyed by guild id ("guild" is Discord's API name for a server).
games = {}
# Ids of members in any running game, so their DMs aren't claimed by two games.
active_member_ids = set()


# --- Helpers ---

def end_game(guild_id, game):
    """Forget a finished or cancelled game so its server can start a new one."""
    # Only remove this game, in case a newer one already replaced it.
    if games.get(guild_id) is game:
        del games[guild_id]
        for member in game.participants:
            active_member_ids.discard(member.id)


async def safe_send(target, text):
    """Send a message to a member, DM or channel. Returns False instead of raising if it fails."""
    # A single failed message (closed DMs, missing permissions) shouldn't end the game.
    try:
        await target.send(text)
        return True
    except discord.HTTPException:
        return False


def label(member):
    """Name a member in messages, e.g. "Ann (@ann123)"."""
    # Usernames are unique, display names aren't.
    return f'{member.display_name} (@{member.name})'


def wish_text(message):
    """Turn someone's DM reply into the wish text passed on to their Secret Santa."""
    # Include links to any attached images, so an image-only reply isn't lost.
    parts = [message.content.strip()] + [a.url for a in message.attachments]
    wish = '\n'.join(part for part in parts if part)
    if not wish:
        return NO_WISH
    if len(wish) > MAX_WISH_LENGTH:
        wish = wish[:MAX_WISH_LENGTH] + '...'
    return wish


def can_manage(ctx, game):
    """True if whoever ran the command may use !check or !clear on this game."""
    return ctx.author.id == game.organizer.id or ctx.author.guild_permissions.manage_guild


# --- Discord events ---
# `@client.event` registers a function that discord.py calls when that event
# happens. The function name says which event it handles.

@client.event
async def on_ready():
    """Called once the bot has connected to Discord."""
    print(f'Successfully logged in as {client.user}.')


@client.event
async def on_command_error(ctx, error):
    """Called when a command fails. Turns common mistakes into friendly replies."""
    if isinstance(error, commands.MemberNotFound):
        # Something after !start wasn't a member of this server.
        await ctx.send(f"Error: I couldn't find the member {error.argument}.")
    elif isinstance(error, commands.NoPrivateMessage):
        # A command was typed in a DM instead of a server channel.
        await ctx.send('Error: Use this command in a server channel.')
    elif isinstance(error, commands.CommandNotFound):
        # Ignore "!something" that isn't one of our commands.
        return
    else:
        # Anything unexpected is printed to the console by discord.py.
        raise error


async def collect_wish(ctx, game, member, dm_channel):
    """Wait for one participant's wish and store it in game.gift_ideas.

    One copy of this runs for every participant at the same time (see
    asyncio.gather in secret_santa), so a slow replier doesn't hold up anyone else.
    """
    def check(message):
        # Only accept messages from this participant, in their DM with the bot.
        return message.author.id == member.id and message.channel.id == dm_channel.id

    try:
        # Pause until a message passes `check`, or give up after RESPONSE_TIMEOUT.
        msg = await client.wait_for('message', check=check, timeout=RESPONSE_TIMEOUT)
    except asyncio.TimeoutError:
        game.gift_ideas[member.id] = NO_WISH
        await safe_send(dm_channel, "Time's up! Your Secret Santa will have to surprise you.")
        await safe_send(game.organizer, f'{label(member)} did not respond in time.')
        return

    game.gift_ideas[member.id] = wish_text(msg)
    await safe_send(game.organizer, f'{label(member)} has responded to Santa Claws.')
    await safe_send(ctx, random.choice(chat_messages))
    await safe_send(dm_channel, random.choice(received_confirmed))


# --- Commands ---
# `@client.command` turns a function into a "!" command. `ctx` (context)
# describes where the command was typed and who typed it; ctx.send() replies
# in that channel. `@commands.guild_only()` blocks the command in DMs.

@client.command(name='start', help='starts the secret santa')
@commands.guild_only()
async def secret_santa(ctx, *users: discord.Member):
    """!start @a @b @c ... runs a whole Secret Santa, from asking for wishes to sending pairings.

    discord.py turns each mention after !start into a discord.Member in `users`.
    """
    # Step 1: check the request is valid before starting anything.
    if ctx.guild.id in games:
        await ctx.send('Error: A secret santa is already running here. Use !clear to cancel it.')
        return

    # Drop duplicate mentions before counting.
    participants = list({user.id: user for user in users}.values())
    if any(user.bot for user in participants):
        await ctx.send('Error: Bots cannot take part.')
        return
    if len(participants) < 3:
        await ctx.send('Error: Please mention at least 3 different users.')
        return
    busy = [label(user) for user in participants if user.id in active_member_ids]
    if busy:
        await ctx.send(f"Error: Already in another secret santa: {', '.join(busy)}.")
        return

    # Step 2: record the game, so !check and !clear can find it.
    game = Game(ctx.author, participants)
    game.task = asyncio.current_task()
    games[ctx.guild.id] = game
    active_member_ids.update(user.id for user in participants)

    # `finally` below makes sure the game is cleaned up however this ends:
    # finished, failed, or cancelled by !clear.
    try:
        # Step 3: DM everyone the question. If anyone can't be reached, cancel
        # now rather than leaving their Secret Santa without a match later.
        dm_channels = {}  # member id -> their DM channel with the bot
        unreachable = []
        for member in participants:
            try:
                dm_channel = await member.create_dm()
                await dm_channel.send('What gift would you like for your secret santa?')
                dm_channels[member.id] = dm_channel
            except discord.HTTPException:
                unreachable.append(label(member))
        if unreachable:
            await safe_send(ctx, f"Error: I can't DM {', '.join(unreachable)}. "
                                 'They need to allow DMs from server members. Secret santa cancelled.')
            for dm_channel in dm_channels.values():
                await safe_send(dm_channel, 'This secret santa was cancelled.')
            return

        # Step 4: wait for everyone's wish. gather() runs all the collect_wish
        # calls at once and continues when every one of them has finished.
        await safe_send(ctx, f'Sandy Claws has messaged {len(participants)} people. Check your DMs!')
        await asyncio.gather(*(collect_wish(ctx, game, member, dm_channels[member.id])
                               for member in participants))

        # Step 5: pair people up and DM each giver their match.
        # Shuffle into one loop: each person gives to the next, never to themselves.
        # The last person in the list wraps around and gives to the first.
        givers = participants[:]
        random.shuffle(givers)
        undelivered = []
        for i, giver in enumerate(givers):
            recipient = givers[(i + 1) % len(givers)]
            sent = await safe_send(dm_channels[giver.id],
                                   f'You are the secret santa for {label(recipient)}! '
                                   f'They would like: {game.gift_ideas[recipient.id]}')
            if not sent:
                undelivered.append(label(giver))

        # Step 6: tell the organizer how it went.
        if undelivered:
            # Only name the givers, so the organizer doesn't learn any pairing.
            await safe_send(game.organizer, "I couldn't send a secret santa to: "
                                            f"{', '.join(undelivered)}. They may have closed their DMs.")
        else:
            await safe_send(game.organizer, 'All users have received their secret santa.')
    finally:
        end_game(ctx.guild.id, game)


@client.command(name='clear', help='cancels the running secret santa')
@commands.guild_only()
async def clear(ctx):
    """!clear cancels this server's running game. Organizer or server managers only."""
    game = games.get(ctx.guild.id)
    if not game:
        await ctx.send('No secret santa is running.')
        return
    if not can_manage(ctx, game):
        await ctx.send('Only the organizer or a server manager can cancel the secret santa.')
        return
    # Stops secret_santa wherever it is paused (usually waiting for wishes).
    game.task.cancel()
    end_game(ctx.guild.id, game)
    for member in game.participants:
        await safe_send(member, 'This secret santa was cancelled.')
    await ctx.send('Secret santa cancelled and lists cleared.')


@client.command(name='check', help='shows who has sent their wish')
@commands.guild_only()
async def check(ctx):
    """!check DMs who has replied and who hasn't. Never shows pairings. Organizer or server managers only."""
    game = games.get(ctx.guild.id)
    if not game:
        await ctx.send('No secret santa is running.')
        return
    if not can_manage(ctx, game):
        await ctx.send('Only the organizer or a server manager can check progress.')
        return
    done = [label(m) for m in game.participants if m.id in game.gift_ideas]
    waiting = [label(m) for m in game.participants if m.id not in game.gift_ideas]
    sent = await safe_send(ctx.author, f"Responded: {', '.join(done) or 'nobody yet'}\n"
                                       f"Waiting on: {', '.join(waiting) or 'nobody'}")
    if not sent:
        await ctx.send("I can't DM you. Allow DMs from server members and try again.")


# --- Start the bot ---
# client.run() connects to Discord and keeps running until the bot is stopped.
token = os.environ.get('DISCORD_TOKEN')
if not token:
    raise SystemExit('Set the DISCORD_TOKEN environment variable to your bot token.')
client.run(token)
