import asyncio
import os
import random

import discord
from discord.ext import commands

# Only the message content intent is needed (for "!" commands). It is
# privileged, so enable it for the bot in the Discord Developer Portal.
intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix='!', intents=intents)

# How long each participant has to send their wish, in seconds.
RESPONSE_TIMEOUT = int(os.environ.get('SANTA_RESPONSE_TIMEOUT', 24 * 60 * 60))
NO_WISH = 'No wish given, surprise them!'

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


async def notify_organizer(game, text):
    # The organizer may have DMs closed; that shouldn't break the game.
    try:
        await game.organizer.send(text)
    except discord.Forbidden:
        pass


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
        await dm_channel.send("Time's up! Your Secret Santa will have to surprise you.")
        await notify_organizer(game, f'{member.display_name} did not respond in time.')
        return

    game.gift_ideas[member.id] = msg.content
    await notify_organizer(game, f'{member.display_name} has responded to Santa Claws.')
    await ctx.send(random.choice(chat_messages))
    await dm_channel.send(random.choice(received_confirmed))


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
    busy = [user.display_name for user in participants if user.id in active_member_ids]
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
            except discord.Forbidden:
                unreachable.append(member.display_name)
        if unreachable:
            await ctx.send(f"Error: I can't DM {', '.join(unreachable)}. "
                           'They need to allow DMs from server members. Secret santa cancelled.')
            for dm_channel in dm_channels.values():
                await dm_channel.send('This secret santa was cancelled.')
            return

        await ctx.send(f'Sandy Claws has messaged {len(participants)} people. Check your DMs!')
        await asyncio.gather(*(collect_wish(ctx, game, member, dm_channels[member.id])
                               for member in participants))

        # Shuffle into one loop: each person gives to the next, never to themselves.
        givers = participants[:]
        random.shuffle(givers)
        for i, giver in enumerate(givers):
            recipient = givers[(i + 1) % len(givers)]
            await dm_channels[giver.id].send(
                f"You are the secret santa for {recipient.display_name}! "
                f"They would like: {game.gift_ideas[recipient.id]}")

        await notify_organizer(game, 'All users have received their secret santa.')
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
    done = [m.display_name for m in game.participants if m.id in game.gift_ideas]
    waiting = [m.display_name for m in game.participants if m.id not in game.gift_ideas]
    await ctx.author.send(f"Responded: {', '.join(done) or 'nobody yet'}\n"
                          f"Waiting on: {', '.join(waiting) or 'nobody'}")


token = os.environ.get('DISCORD_TOKEN')
if not token:
    raise SystemExit('Set the DISCORD_TOKEN environment variable to your bot token.')
client.run(token)
