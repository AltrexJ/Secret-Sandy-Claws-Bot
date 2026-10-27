import asyncio
import os
import random

import discord
from discord.ext import commands

# Only the message content intent is needed (for "!" commands). It is
# privileged, so enable it for the bot in the Discord Developer Portal.
intents = discord.Intents.default()
intents.message_content = True

# Never ping anyone, even if a name or wish looks like a mention.
client = commands.Bot(command_prefix='!', intents=intents, allowed_mentions=discord.AllowedMentions.none())

# How long each participant has to send their wish, in seconds.
RESPONSE_TIMEOUT = int(os.environ.get('SANTA_RESPONSE_TIMEOUT', 24 * 60 * 60))
NO_WISH = 'No wish given, surprise them!'
# Keeps the pairing message under Discord's 2000 character limit.
MAX_WISH_LENGTH = 1500

chat_messages = ['Hes Coming', 'He Knows', 'Its simple, we kill the batman', 'Sandy Claws is coming to town']
received_confirmed = ['K', 'Why Though?', 'Really?', 'Nah, you are getting coal', 'Wow, everyone, and I mean everyone, is dumber with this is in world', 'Good idea!', 'Wow, this will be great!', 'I never would have thought of that.']


class Game:
    def __init__(self, organizer, participants):
        self.organizer = organizer
        self.participants = participants  # list of discord.Member
        self.gift_ideas = {}  # member id -> wish
        self.task = None


# One game per server, keyed by guild id.
games = {}
# Ids of members in any running game, so their DMs aren't claimed by two games.
active_member_ids = set()


def end_game(guild_id, game):
    # Only remove this game, in case a newer one already replaced it.
    if games.get(guild_id) is game:
        del games[guild_id]
        for member in game.participants:
            active_member_ids.discard(member.id)


async def safe_send(target, text):
    # A single failed message (closed DMs, missing permissions) shouldn't end the game.
    try:
        await target.send(text)
        return True
    except discord.HTTPException:
        return False


def label(member):
    # Usernames are unique, display names aren't.
    return f'{member.display_name} (@{member.name})'


def wish_text(message):
    parts = [message.content.strip()] + [a.url for a in message.attachments]
    wish = '\n'.join(part for part in parts if part)
    if not wish:
        return NO_WISH
    if len(wish) > MAX_WISH_LENGTH:
        wish = wish[:MAX_WISH_LENGTH] + '...'
    return wish


def can_manage(ctx, game):
    return ctx.author.id == game.organizer.id or ctx.author.guild_permissions.manage_guild


@client.event
async def on_ready():
    print(f'Successfully logged in as {client.user}.')


@client.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send(f"Error: I couldn't find the member {error.argument}.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send('Error: Use this command in a server channel.')
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        raise error


async def collect_wish(ctx, game, member, dm_channel):
    def check(message):
        return message.author.id == member.id and message.channel.id == dm_channel.id

    try:
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


@client.command(name='start', help='starts the secret santa')
@commands.guild_only()
async def secret_santa(ctx, *users: discord.Member):
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

    game = Game(ctx.author, participants)
    game.task = asyncio.current_task()
    games[ctx.guild.id] = game
    active_member_ids.update(user.id for user in participants)

    try:
        dm_channels = {}
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

        await safe_send(ctx, f'Sandy Claws has messaged {len(participants)} people. Check your DMs!')
        await asyncio.gather(*(collect_wish(ctx, game, member, dm_channels[member.id])
                               for member in participants))

        # Shuffle into one loop: each person gives to the next, never to themselves.
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
    game = games.get(ctx.guild.id)
    if not game:
        await ctx.send('No secret santa is running.')
        return
    if not can_manage(ctx, game):
        await ctx.send('Only the organizer or a server manager can cancel the secret santa.')
        return
    game.task.cancel()
    end_game(ctx.guild.id, game)
    for member in game.participants:
        await safe_send(member, 'This secret santa was cancelled.')
    await ctx.send('Secret santa cancelled and lists cleared.')


@client.command(name='check', help='shows who has sent their wish')
@commands.guild_only()
async def check(ctx):
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


token = os.environ.get('DISCORD_TOKEN')
if not token:
    raise SystemExit('Set the DISCORD_TOKEN environment variable to your bot token.')
client.run(token)
