import discord
from discord.ext import commands
import random

intents = discord.Intents.all()
intents.members = True

client = commands.Bot(command_prefix='!', intents=intents)

user_dict = {}
gift_dict = {}
gift_ideas = {}



@client.event
async def on_ready():
    print(f'Successfully logged in as {client.user}.')

@client.command(name='start', help = 'starts the secret santa')
async def secret_santa(ctx, *users: discord.Member):
    if len(users) < 3:
        await ctx.send("Error: Please mention at least 3 users.")
        return
    for user in users:
        user_dict[user.id] = user.name
        print(f'Adding user {user.name} to the dictionary')

    user_ids = list(user_dict.keys())
    random.shuffle(user_ids)
    for i in range(len(user_ids)):
        recipient_id = user_ids[(i + 1) % len(user_ids)]
        if recipient_id == user_ids[i]:
            recipient_id = user_ids[(i + 2) % len(user_ids)]
        gift_dict[user_dict[user_ids[i]]] = user_dict[recipient_id]
    chat_messages = ['Hes Coming', 'He Knows', 'Its simple, we kill the batman', 'Sandy Claws is coming to town']
    received_confirmed = ['K', 'Why Though?', 'Really?', 'Nah, you are getting coal', 'Wow, everyone, and I mean everyone, is dumber with this is in world', 'Good idea!', 'Wow, this will be great!', 'I never would have thought of that.']
    for user_name in gift_dict:
        user = client.get_user(next(iter([k for k, v in user_dict.items() if v == user_name])))
        dm_channel = await user.create_dm()
        await dm_channel.send(f'What gift would you like for your secret santa?')
        await ctx.author.send(f'Waiting on {user_name}...')
        def check(message):
            return message.author == user and message.channel == dm_channel
        msg = await client.wait_for('message', check=check)
        gift_ideas[user_name] = msg.content
        await ctx.author.send(f"{user_name} has responded to Santa Claws.")
        await ctx.send(random.choice(chat_messages))
        await dm_channel.send(random.choice(received_confirmed))

    for user_name in gift_dict:
        user = client.get_user(next(iter([k for k, v in user_dict.items() if v == user_name])))
        recipient = gift_dict[user_name]
        recipient = client.get_user(next(iter([k for k, v in user_dict.items() if v == recipient])))
        dm_channel = await recipient.create_dm()
        await dm_channel.send(f'{user_name} would like: {gift_ideas[user_name]}')
    await ctx.author.send(f'All users have submitted their requests')
    user_dict.clear()
    gift_dict.clear()
    gift_ideas.clear()
    await ctx.author.send("List's have been cleared.")

 

@client.command(name='clear', help = 'Clears variables')
async def clear(ctx):
    user_dict.clear()
    gift_dict.clear()
    gift_ideas.clear()
    await ctx.send("Lists have been cleared.")

@client.command(name='check', help='sends variables')
async def check(ctx):
    await ctx.author.send(user_dict)
    await ctx.author.send(gift_dict)
    await ctx.author.send(gift_ideas)
    return


client.run('ENTER TOKEN HERE')
        

