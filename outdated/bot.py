import discord
from discord.ext.commands import Bot
from discord.ext import commands, tasks
import os
import asyncio
intents = discord.Intents.all()
intents.message_content = True
intents.voice_states = True
client = commands.Bot(command_prefix = '!',intents=intents)

@client.event
async def on_ready():
    await client.change_presence(status=discord.Status.online)
    print(f'Logged in as {client.user}')

async def Load():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await client.load_extension(f"cogs.{filename[:-3]}")

@client.command()
async def testbot(ctx):
    await ctx.send("The bot is working :)")

async def main():
    async with client:
        await Load()
        await client.start("MTI4Mjc5NTI1MDMyMTk4MTU5Mw.Gq_MXq.bx9FWu9G6z8nuyDIf0K5LgK4XfwkXMnoT2o100")

asyncio.run(main())