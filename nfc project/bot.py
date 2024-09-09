import discord
from discord.ext.commands import Bot
from discord.ext import commands, tasks
intents = discord.Intents.all()
client = commands.Bot(command_prefix = '!',intents=intents)

@client.event
async def on_ready():
    await client.change_presence(status=discord.Status.online, activity=discord.Game("USSR National Anthem"))
    print('Online!')

client.run("MTI4Mjc5NTI1MDMyMTk4MTU5Mw.Gq_MXq.bx9FWu9G6z8nuyDIf0K5LgK4XfwkXMnoT2o100")