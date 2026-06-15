import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')


def parse_loot_message(text):
    """
    Reads embed text line by line and groups items with their curses.
    Returns a list of dicts: [{'name': 'Staff', 'curses': ['Curse of Crippling']}]
    """
    inventory = []
    current_item = None

    lines = text.split('\n')

    for line in lines:
        line = line.strip()

        if line.startswith('•'):
            parts = line.split(' : ')
            if len(parts) > 1:
                item_name = parts[1].strip()
                current_item = {"name": item_name, "curses": []}
                inventory.append(current_item)

        elif 'Curses:' in line and current_item is not None:
            curse_string = line.split('Curses:')[1].strip()
            curses_list = [c.strip() for c in curse_string.split(',')]
            current_item["curses"] = curses_list

    return inventory


@bot.command()
async def searchloot(ctx, search_type: str, *, query: str = ""):
    """
    Search recent messages for loot matching your criteria.

    Usage:
      !searchloot 2curses                         — items with 2+ curses
      !searchloot specific Staff, Curse of Envy   — specific item + curse
      !searchloot item Staff                      — any Staff drop
      !searchloot curse Curse of Magnitude        — any item with that curse
    """
    await ctx.send(f"🔍 Searching last 200 messages for `{search_type}`...")

    found_messages = []

    async for message in ctx.channel.history(limit=200):
        if not (message.embeds and message.author.bot):
            continue

        embed_text = message.embeds[0].description
        if not embed_text:
            continue

        parsed_items = parse_loot_message(embed_text)
        match_found = False

        for item in parsed_items:
            if search_type == "2curses":
                if len(item['curses']) >= 2:
                    match_found = True
                    break

            elif search_type == "specific":
                query_parts = [q.strip().lower() for q in query.split(',')]
                target_item = query_parts[0]
                target_curse = query_parts[1] if len(query_parts) > 1 else ""

                if target_item in item['name'].lower():
                    if not target_curse:
                        match_found = True
                        break
                    elif any(target_curse in c.lower() for c in item['curses']):
                        match_found = True
                        break

            elif search_type == "item":
                if query.lower() in item['name'].lower():
                    match_found = True
                    break

            elif search_type == "curse":
                if any(query.lower() in c.lower() for c in item['curses']):
                    match_found = True
                    break

            elif search_type == "ncurses":
                try:
                    n = int(query)
                    if len(item['curses']) >= n:
                        match_found = True
                        break
                except ValueError:
                    await ctx.send("❌ `ncurses` needs a number, e.g. `!searchloot ncurses 3`")
                    return

        if match_found:
            found_messages.append(message.jump_url)

    if found_messages:
        lines = [f"✅ Found **{len(found_messages)}** matching drop(s)!"] + found_messages
        response = "\n".join(lines)
        await ctx.send(response[:2000])
    else:
        await ctx.send("❌ No matching loot found in recent messages.")


@bot.command()
async def loothelp(ctx):
    """Show all available search commands."""
    help_text = """**🔮 Loot Search Bot Commands**

`!searchloot 2curses`
  → Any item with **2 or more** curses

`!searchloot ncurses <N>`
  → Any item with **N or more** curses (e.g. `!searchloot ncurses 3`)

`!searchloot item <name>`
  → Any drop containing that item (e.g. `!searchloot item Staff`)

`!searchloot curse <curse name>`
  → Any item carrying that curse (e.g. `!searchloot curse Curse of Magnitude`)

`!searchloot specific <item>, <curse>`
  → Exact combo (e.g. `!searchloot specific Staff, Curse of Envy`)

All commands search the last **200 messages** in the current channel."""
    await ctx.send(help_text)


token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set. Add it as a secret.")

bot.run(token)
