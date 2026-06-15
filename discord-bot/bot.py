import discord
from discord.ext import commands
import os
import aiosqlite
from datetime import datetime
import unicodedata

DB_PATH = "discord-bot/loot.db"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)


# ─────────────────────────── DATABASE ───────────────────────────────────────

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
        await db.execute("CREATE INDEX IF NOT EXISTS idx_item_name   ON drops (item_name COLLATE NOCASE)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_curse_count ON drops (curse_count)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_message_id  ON drops (message_id)")
        await db.commit()


async def store_drop(message, item):
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


# ─────────────────────────── PARSER ─────────────────────────────────────────

def is_item_line(line):
    """
    Matches item lines regardless of exact bullet character.
    Looks for patterns like: • [1x] : Warhammer  or  · [18x] : Lunari
    Handles any leading bullet/arrow/emoji Unicode before the bracket.
    """
    stripped = line.strip()
    # Strip any leading non-alphanumeric characters (bullets, arrows, emoji, etc.)
    import re
    return bool(re.match(r'^[^\w\[]*\[\d+x\]\s*:\s*.+', stripped))


def extract_item_name(line):
    """Pull the item name from a line like '• [1x] : Warhammer'."""
    import re
    m = re.search(r'\[\d+x\]\s*:\s*(.+)', line.strip())
    return m.group(1).strip() if m else None


def is_curse_line(line):
    return 'Curses:' in line or 'curses:' in line


def extract_curses(line):
    part = line.split('Curses:')[-1] if 'Curses:' in line else line.split('curses:')[-1]
    return [c.strip() for c in part.strip().split(',') if c.strip()]


def get_embed_text(embed):
    """
    Collect all text from an embed: description + all field values.
    Returns a single newline-joined string.
    """
    parts = []
    if embed.description:
        parts.append(embed.description)
    for field in embed.fields:
        if field.value:
            parts.append(field.value)
    return "\n".join(parts)


def parse_loot_text(text):
    """
    Parse loot text (from any embed source) into structured items.
    Returns: [{'name': 'Warhammer', 'curses': ['Curse of Vanishing']}]
    """
    inventory = []
    current_item = None

    for line in text.split('\n'):
        if is_item_line(line):
            name = extract_item_name(line)
            if name:
                current_item = {"name": name, "curses": []}
                inventory.append(current_item)
        elif is_curse_line(line) and current_item is not None:
            current_item["curses"] = extract_curses(line)

    return inventory


def is_loot_message(message):
    """
    Accept messages from webhooks OR bots.
    Webhooks: message.webhook_id is set (author.bot may or may not be True).
    Regular bots: message.author.bot is True.
    """
    return bool(message.webhook_id) or message.author.bot


async def store_message_drops(message):
    """Parse and store all loot items from a message. Returns count stored."""
    if not is_loot_message(message):
        return 0
    if not message.embeds:
        return 0

    text = get_embed_text(message.embeds[0])
    if not text:
        return 0

    items = parse_loot_text(text)
    for item in items:
        await store_drop(message, item)

    if items:
        print(f"[loot] stored {len(items)} item(s) from msg {message.id}: {[i['name'] for i in items]}")

    return len(items)


# ─────────────────────────── EVENTS ─────────────────────────────────────────

@bot.event
async def on_ready():
    await init_db()
    print(f'Logged in as {bot.user.name} — database ready at {DB_PATH}')


@bot.event
async def on_message(message):
    await store_message_drops(message)
    await bot.process_commands(message)


# ─────────────────────────── SEARCH ─────────────────────────────────────────

async def search_db(guild_id, where_clause, params, limit=50):
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
    """Search the drop database (instant, all history)."""
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
        await ctx.send(f"❌ Unknown type `{search_type}`. Use `!loothelp` for options.")


# ─────────────────────────── UTILITIES ──────────────────────────────────────

@bot.command()
async def debug(ctx, limit: int = 5):
    """
    Inspect the last N messages in this channel and show exactly what the bot sees.
    Use this to diagnose why webhook drops aren't being parsed.
    Usage: !debug       (last 5 messages)
           !debug 10
    """
    lines = [f"🔍 **Debug — last {limit} messages:**\n"]
    async for msg in ctx.channel.history(limit=limit):
        is_hook  = bool(msg.webhook_id)
        is_bot   = msg.author.bot
        n_embeds = len(msg.embeds)
        line = f"**[{msg.author.name}]** webhook={is_hook} bot={is_bot} embeds={n_embeds}"

        if msg.embeds:
            embed = msg.embeds[0]
            desc_preview = (embed.description or "")[:80].replace('\n', '↵')
            field_count  = len(embed.fields)
            text_sample  = get_embed_text(embed)[:120].replace('\n', '↵')
            items        = parse_loot_text(get_embed_text(embed))
            line += f"\n  └ desc=`{desc_preview}` fields={field_count}"
            line += f"\n  └ full_text=`{text_sample}`"
            line += f"\n  └ parsed_items={[i['name'] for i in items]}"
        lines.append(line)

    await ctx.send("\n".join(lines)[:2000])


@bot.command()
async def backfill(ctx, limit: int = 500):
    """
    Scan recent channel history and store any drops not yet in the database.
    Usage: !backfill          (last 500 messages)
           !backfill 1000
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
    await ctx.send(f"📊 Database: **{row[0]}** item(s) logged from **{row[1]}** drop message(s) in this server.")


@bot.command()
async def loothelp(ctx):
    """Show all available commands."""
    help_text = """**🔮 Loot Search Bot Commands**

**Search (instant, all history):**
`!searchloot 2curses` — items with 2+ curses
`!searchloot ncurses <N>` — items with N+ curses
`!searchloot item <name>` — e.g. `!searchloot item Warhammer`
`!searchloot curse <curse>` — e.g. `!searchloot curse Curse of Vanishing`
`!searchloot specific <item>, <curse>` — e.g. `!searchloot specific Warhammer, Curse of Vanishing`

**Database:**
`!backfill [limit]` — scan channel history and store drops (default: last 500 msgs)
`!dbstats` — show how many drops are logged

**Diagnostics:**
`!debug [n]` — inspect the last N messages so you can see exactly what the bot is reading

The bot **automatically logs every new drop** as it appears."""
    await ctx.send(help_text)


token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN is not set.")

bot.run(token)
