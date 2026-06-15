import discord
from discord.ext import commands
import os
import aiosqlite
import asyncio
from datetime import datetime

DB_PATH = "discord-bot/loot.db"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS drops (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id  TEXT NOT NULL,
                channel_id  TEXT NOT NULL,
                guild_id    TEXT NOT NULL,
                jump_url    TEXT NOT NULL,
                item_name   TEXT NOT NULL,
                curses      TEXT NOT NULL DEFAULT '',
                curse_count INTEGER NOT NULL DEFAULT 0,
                recorded_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_item_name   ON drops (item_name COLLATE NOCASE)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_curse_count ON drops (curse_count)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_id  ON drops (message_id)
        """)
        await db.commit()


def parse_loot_message(text):
    """
    Parses embed text into structured items.
    Returns: [{'name': 'Staff', 'curses': ['Curse of Crippling', 'Curse of Envy']}]
    """
    inventory = []
    current_item = None

    for line in text.split('\n'):
        line = line.strip()

        if line.startswith('•'):
            parts = line.split(' : ')
            if len(parts) > 1:
                item_name = parts[1].strip()
                current_item = {"name": item_name, "curses": []}
                inventory.append(current_item)

        elif 'Curses:' in line and current_item is not None:
            curse_string = line.split('Curses:')[1].strip()
            current_item["curses"] = [c.strip() for c in curse_string.split(',')]

    return inventory


async def store_drop(message, item):
    """Save a single parsed item to the database."""
    curses_str = ",".join(item["curses"])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO drops
              (message_id, channel_id, guild_id, jump_url, item_name, curses, curse_count, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(message.id),
            str(message.channel.id),
            str(message.guild.id) if message.guild else "dm",
            message.jump_url,
            item["name"],
            curses_str,
            len(item["curses"]),
            datetime.utcnow().isoformat(),
        ))
        await db.commit()


async def store_message_drops(message):
    """Parse a bot embed message and store all items found in it."""
    if not (message.embeds and message.author.bot):
        return 0
    embed_text = message.embeds[0].description
    if not embed_text:
        return 0
    items = parse_loot_message(embed_text)
    for item in items:
        await store_drop(message, item)
    return len(items)


@bot.event
async def on_ready():
    await init_db()
    print(f'Logged in as {bot.user.name} — database ready at {DB_PATH}')


@bot.event
async def on_message(message):
    """Live listener: parse and store every new drop automatically."""
    await store_message_drops(message)
    await bot.process_commands(message)


# ─────────────────────────── SEARCH COMMANDS ────────────────────────────────

async def search_db(guild_id, where_clause, params, limit=50):
    """Run a SELECT against the drops table and return rows."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(f"""
            SELECT DISTINCT jump_url, item_name, curses, curse_count
            FROM drops
            WHERE guild_id = ? AND {where_clause}
            ORDER BY id DESC
            LIMIT {limit}
        """, (guild_id, *params))
        return await cursor.fetchall()


def format_results(rows, label):
    if not rows:
        return f"❌ No drops found matching: **{label}**"
    lines = [f"✅ Found **{len(rows)}** result(s) for **{label}**:"]
    for r in rows:
        curse_info = f" — *{r['curses']}*" if r['curses'] else ""
        lines.append(f"[{r['item_name']}{curse_info}]({r['jump_url']})")
    return "\n".join(lines)[:2000]


@bot.command()
async def searchloot(ctx, search_type: str, *, query: str = ""):
    """
    Search the drop database (instant, all history).

    !searchloot 2curses
    !searchloot ncurses 3
    !searchloot item Staff
    !searchloot curse Curse of Magnitude
    !searchloot specific Staff, Curse of Envy
    """
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"

    if search_type == "2curses":
        rows = await search_db(guild_id, "curse_count >= 2", ())
        await ctx.send(format_results(rows, "2+ curses"))

    elif search_type == "ncurses":
        try:
            n = int(query)
        except ValueError:
            await ctx.send("❌ Usage: `!searchloot ncurses <number>`"); return
        rows = await search_db(guild_id, "curse_count >= ?", (n,))
        await ctx.send(format_results(rows, f"{n}+ curses"))

    elif search_type == "item":
        if not query:
            await ctx.send("❌ Usage: `!searchloot item <name>`"); return
        rows = await search_db(guild_id, "item_name LIKE ?", (f"%{query}%",))
        await ctx.send(format_results(rows, query))

    elif search_type == "curse":
        if not query:
            await ctx.send("❌ Usage: `!searchloot curse <curse name>`"); return
        rows = await search_db(guild_id, "curses LIKE ?", (f"%{query}%",))
        await ctx.send(format_results(rows, query))

    elif search_type == "specific":
        parts = [p.strip() for p in query.split(',')]
        if len(parts) < 2:
            await ctx.send("❌ Usage: `!searchloot specific <item>, <curse>`"); return
        rows = await search_db(
            guild_id,
            "item_name LIKE ? AND curses LIKE ?",
            (f"%{parts[0]}%", f"%{parts[1]}%")
        )
        await ctx.send(format_results(rows, f"{parts[0]} + {parts[1]}"))

    else:
        await ctx.send(f"❌ Unknown search type `{search_type}`. Type `!loothelp` for options.")


@bot.command()
async def backfill(ctx, limit: int = 500):
    """
    Scan recent channel history and store any drops not yet in the database.
    Usage: !backfill          (last 500 messages)
           !backfill 1000     (last 1000 messages)
    """
    await ctx.send(f"⏳ Backfilling last {limit} messages in this channel...")
    stored = 0
    scanned = 0
    async for message in ctx.channel.history(limit=limit):
        scanned += 1
        stored += await store_message_drops(message)
    await ctx.send(f"✅ Done. Scanned **{scanned}** messages, stored **{stored}** item(s) into the database.")


@bot.command()
async def dbstats(ctx):
    """Show how many drops are stored in the database."""
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) as total, COUNT(DISTINCT message_id) as messages FROM drops WHERE guild_id = ?",
            (guild_id,)
        )
        row = await cursor.fetchone()
        total, messages = row[0], row[1]
    await ctx.send(f"📊 Database: **{total}** item(s) logged from **{messages}** drop message(s) in this server.")


@bot.command()
async def loothelp(ctx):
    """Show all available commands."""
    help_text = """**🔮 Loot Search Bot Commands**

**Search (instant, all history):**
`!searchloot 2curses` — items with 2+ curses
`!searchloot ncurses <N>` — items with N+ curses
`!searchloot item <name>` — e.g. `!searchloot item Staff`
`!searchloot curse <curse>` — e.g. `!searchloot curse Curse of Magnitude`
`!searchloot specific <item>, <curse>` — e.g. `!searchloot specific Staff, Curse of Envy`

**Database:**
`!backfill [limit]` — scan channel history and store drops (default: last 500 msgs)
`!dbstats` — show how many drops are logged

The bot **automatically logs every new drop** as it appears — no manual scanning needed."""
    await ctx.send(help_text)


token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN is not set.")

bot.run(token)
