import discord
from discord.ext import commands
import os
import aiosqlite
import re
from datetime import datetime, timezone, timedelta

GST = timezone(timedelta(hours=4))  # Gulf Standard Time (UTC+4)

def to_gst(utc_str: str) -> str:
    """Convert a stored UTC ISO string to a GST display string."""
    try:
        dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
        return dt.astimezone(GST).strftime("%Y-%m-%d %H:%M GST")
    except Exception:
        return utc_str

DB_PATH = "discord-bot/loot.db"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Deduplicate command processing — keeps the last 500 message IDs seen
from collections import deque
_processed_ids: deque = deque(maxlen=500)


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
                player      TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL,
                UNIQUE (message_id, item_name)
            )
        """)
        # Migrate existing DB: add player column if it doesn't exist yet
        try:
            await db.execute("ALTER TABLE drops ADD COLUMN player TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # column already exists
        await db.execute("CREATE INDEX IF NOT EXISTS idx_item_name   ON drops (item_name COLLATE NOCASE)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_curse_count ON drops (curse_count)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_message_id  ON drops (message_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_player      ON drops (player COLLATE NOCASE)")
        await db.commit()


async def store_drop(message, item, player: str = ""):
    curses_str = ",".join(item["curses"])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO drops
              (message_id, channel_id, guild_id, jump_url, item_name, curses, curse_count, player, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(message.id),
            str(message.channel.id),
            str(message.guild.id) if message.guild else "dm",
            message.jump_url,
            item["name"],
            curses_str,
            len(item["curses"]),
            player,
            datetime.now(timezone.utc).isoformat(),
        ))
        await db.commit()


# ─────────────────────────── PARSER ─────────────────────────────────────────

def is_item_line(line):
    return bool(re.match(r'^[^\w\[]*\[\d+x\]\s*:\s*.+', line.strip()))

def extract_item_name(line):
    m = re.search(r'\[\d+x\]\s*:\s*(.+)', line.strip())
    return m.group(1).strip() if m else None

def is_curse_line(line):
    return 'Curses:' in line or 'curses:' in line

def extract_curses(line):
    part = line.split('Curses:')[-1] if 'Curses:' in line else line.split('curses:')[-1]
    return [c.strip() for c in part.strip().split(',') if c.strip()]

def get_embed_text(embed):
    parts = []
    if embed.description:
        parts.append(embed.description)
    for field in embed.fields:
        if field.value:
            parts.append(field.value)
    return "\n".join(parts)

def get_embed_player(embed):
    """Extract player name from footer text like 'Player: apocgaem | Auto Looter•...'"""
    footer = getattr(embed.footer, "text", None) if embed.footer else None
    if not footer:
        return ""
    m = re.search(r'Player:\s*([^\|]+)', footer)
    if m:
        return m.group(1).strip()
    return ""

def parse_loot_text(text):
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
    return bool(message.webhook_id) or message.author.bot

async def store_message_drops(message):
    try:
        if not is_loot_message(message):
            return 0
        if not message.embeds:
            return 0
        embed = message.embeds[0]
        text = get_embed_text(embed)
        if not text:
            return 0
        player = get_embed_player(embed)
        all_items = parse_loot_text(text)
        # Only store items that actually have curses
        cursed_items = [i for i in all_items if i["curses"]]
        for item in cursed_items:
            await store_drop(message, item, player)
        if cursed_items:
            player_tag = f" [{player}]" if player else ""
            print(f"[loot] stored {len(cursed_items)} cursed item(s) from msg {message.id}{player_tag}: {[i['name'] for i in cursed_items]}")
        return len(cursed_items)
    except Exception as e:
        print(f"[loot] ERROR storing message {message.id}: {e}")
        return 0


# ─────────────────────────── EVENTS ─────────────────────────────────────────

@bot.event
async def on_ready():
    await init_db()
    print(f'Logged in as {bot.user.name} — database ready at {DB_PATH}')

@bot.event
async def on_message(message):
    try:
        # Never process the bot's own messages
        if message.author == bot.user:
            return

        # Store loot drops from webhooks/bots regardless
        await store_message_drops(message)

        # Deduplicate command processing — Discord can deliver the same
        # message twice (reconnect replay, startup race), so skip if we've
        # already handled this message ID
        if message.id in _processed_ids:
            return
        _processed_ids.append(message.id)

        await bot.process_commands(message)
    except Exception as e:
        print(f"[bot] ERROR in on_message: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument. Use `!loothelp` for usage.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # silently ignore unknown commands
    else:
        print(f"[bot] command error: {error}")
        await ctx.send(f"❌ An error occurred: {error}")


# ─────────────────────────── SEARCH HELPERS ─────────────────────────────────

async def search_db(guild_id, where_clause, params, limit=50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(f"""
            SELECT DISTINCT jump_url, item_name, curses, curse_count, player
            FROM drops
            WHERE guild_id = ? AND {where_clause}
            ORDER BY id DESC
            LIMIT {limit}
        """, (guild_id, *params))
        return await cursor.fetchall()

BATCH_SIZE = 5

def format_results_batched(rows, label):
    """
    Returns a list of messages to send, each containing up to BATCH_SIZE items.
    First message has the header; subsequent messages are continuations.
    Returns a single-element list with an error string if no results.
    """
    if not rows:
        return [f"❌ No drops found matching: **{label}**"]

    # Build one line per result
    item_lines = []
    for r in rows:
        curse_info = f"\n    *{r['curses']}*" if r['curses'] else ""
        player_info = f" — `{r['player']}`" if r['player'] else ""
        item_lines.append(f"• [{r['item_name']}]({r['jump_url']}) ({r['curse_count']} curse(s)){player_info}{curse_info}")

    # Chunk into batches
    batches = [item_lines[i:i + BATCH_SIZE] for i in range(0, len(item_lines), BATCH_SIZE)]
    total = len(rows)
    total_pages = len(batches)

    messages = []
    for idx, batch in enumerate(batches):
        page = f"({idx + 1}/{total_pages})" if total_pages > 1 else ""
        if idx == 0:
            header = f"✅ Found **{total}** result(s) for **{label}**: {page}"
        else:
            header = f"📄 Continued {page}"
        messages.append(header + "\n" + "\n".join(batch))

    return messages


async def send_results(ctx, rows, label):
    for msg in format_results_batched(rows, label):
        await ctx.send(msg)


async def scan_channel_history(ctx, limit: int = 5000):
    """Scan this channel's history and store any loot drops found. Returns (scanned, stored)."""
    scanned, stored = 0, 0
    async for message in ctx.channel.history(limit=limit):
        scanned += 1
        stored += await store_message_drops(message)
    return scanned, stored


async def search_or_scan(ctx, guild_id, where_clause, params, label, limit=50):
    """
    Run a search. If nothing is found, transparently scan channel history for
    new drops, then retry once. This way the user never has to run !backfill.
    """
    rows = await search_db(guild_id, where_clause, params, limit)
    if not rows:
        status = await ctx.send(
            "🔍 Nothing found in DB — scanning channel history (this may take a moment)..."
        )
        scanned, stored = await scan_channel_history(ctx)
        await status.edit(content=(
            f"✅ Scanned **{scanned}** messages, found **{stored}** new item(s). Searching again..."
        ))
        rows = await search_db(guild_id, where_clause, params, limit)
    await send_results(ctx, rows, label)


# ─────────────────────────── SEARCH COMMANDS ────────────────────────────────

@bot.command()
async def searchloot(ctx, search_type: str, *, query: str = ""):
    """
    Search the drop database.

    !searchloot 2curses
    !searchloot ncurses 3
    !searchloot item Warhammer
    !searchloot curse Curse of Mercy
    !searchloot has <item>, <curse>           — item that includes a specific curse
    !searchloot combo <item>, <curse>, <N>    — item with curse AND at least N total curses
    !searchloot all <item>, <c1>, <c2>, ...   — item with ALL listed curses
    !searchloot specific <item>, <curse>      — exact item + curse match
    """
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"

    # ── 2curses ───────────────────────────────────────────────────────────────
    if search_type == "2curses":
        await search_or_scan(ctx, guild_id, "curse_count >= 2", (), "2+ curses")

    # ── ncurses ───────────────────────────────────────────────────────────────
    elif search_type == "ncurses":
        try:
            n = int(query)
        except ValueError:
            await ctx.send("❌ Usage: `!searchloot ncurses <number>`"); return
        await search_or_scan(ctx, guild_id, "curse_count >= ?", (n,), f"{n}+ curses")

    # ── item ──────────────────────────────────────────────────────────────────
    elif search_type == "item":
        if not query:
            await ctx.send("❌ Usage: `!searchloot item <name>`"); return
        await search_or_scan(ctx, guild_id, "item_name LIKE ?", (f"%{query}%",), query)

    # ── curse ─────────────────────────────────────────────────────────────────
    elif search_type == "curse":
        if not query:
            await ctx.send("❌ Usage: `!searchloot curse <curse name>`"); return
        await search_or_scan(ctx, guild_id, "curses LIKE ?", (f"%{query}%",), query)

    # ── has: item + one specific curse ───────────────────────────────────────
    elif search_type in ("has", "specific"):
        parts = [p.strip() for p in query.split(',', 1)]
        if len(parts) < 2:
            await ctx.send("❌ Usage: `!searchloot has <item>, <curse>`"); return
        item_q, curse_q = parts
        await search_or_scan(
            ctx, guild_id,
            "item_name LIKE ? AND curses LIKE ?",
            (f"%{item_q}%", f"%{curse_q}%"),
            f"{item_q} + {curse_q}"
        )

    # ── combo: item + specific curse + minimum curse count ───────────────────
    elif search_type == "combo":
        parts = [p.strip() for p in query.split(',')]
        if len(parts) < 2:
            await ctx.send("❌ Usage:\n"
                           "`!searchloot combo <item>, <N>` — item with N+ curses\n"
                           "`!searchloot combo <item>, <curse>, <N>` — item with a specific curse and N+ curses"); return

        item_q = parts[0]
        try:
            min_n = int(parts[-1])
        except ValueError:
            await ctx.send("❌ Last argument must be a number (minimum curse count).\n"
                           "Example: `!searchloot combo Archangel's, 2`"); return

        if len(parts) == 2:
            await search_or_scan(
                ctx, guild_id,
                "item_name LIKE ? AND curse_count >= ?",
                (f"%{item_q}%", min_n),
                f"{item_q} with {min_n}+ curses"
            )
        else:
            curse_q = ",".join(parts[1:-1]).strip()
            await search_or_scan(
                ctx, guild_id,
                "item_name LIKE ? AND curses LIKE ? AND curse_count >= ?",
                (f"%{item_q}%", f"%{curse_q}%", min_n),
                f"{item_q} + {curse_q} + {min_n}+ curses"
            )

    # ── cursewith: any item that has a specific curse + N+ total curses ─────────
    elif search_type == "cursewith":
        parts = [p.strip() for p in query.rsplit(',', 1)]
        if len(parts) < 2:
            await ctx.send("❌ Usage: `!searchloot cursewith <curse>, <N>`\n"
                           "Example: `!searchloot cursewith Curse of Transfiguration, 3`"); return
        curse_q = parts[0]
        try:
            min_n = int(parts[1])
        except ValueError:
            await ctx.send("❌ Last argument must be a number (minimum curse count).\n"
                           "Example: `!searchloot cursewith Curse of Transfiguration, 2`"); return
        await search_or_scan(
            ctx, guild_id,
            "curses LIKE ? AND curse_count >= ?",
            (f"%{curse_q}%", min_n),
            f"{curse_q} + {min_n}+ curses"
        )

    # ── all: item that has ALL listed curses ──────────────────────────────────
    elif search_type == "all":
        parts = [p.strip() for p in query.split(',')]
        if len(parts) < 2:
            await ctx.send("❌ Usage: `!searchloot all <item>, <curse1>, <curse2>, ...`\n"
                           "Example: `!searchloot all Dunestrider Chestplate, Curse of Mercy, Curse of Fear`"); return
        item_q   = parts[0]
        curses_q = parts[1:]
        curse_conditions = " AND ".join(["curses LIKE ?"] * len(curses_q))
        curse_params = tuple(f"%{c}%" for c in curses_q)
        await search_or_scan(
            ctx, guild_id,
            f"item_name LIKE ? AND {curse_conditions}",
            (f"%{item_q}%", *curse_params),
            f"{item_q} with ALL of: {', '.join(curses_q)}"
        )

    else:
        await ctx.send(f"❌ Unknown type `{search_type}`. Use `!loothelp` for options.")


# ─────────────────────────── DATABASE COMMANDS ──────────────────────────────

@bot.command()
async def dbwipe(ctx, arg: str = "500"):
    """
    Wipe all logged drops for this server and immediately re-run backfill.
    Usage: !dbwipe                       — wipe + backfill last 500 messages
           !dbwipe 1000                  — wipe + backfill last 1000 messages
           !dbwipe 1515712207919255605   — wipe + backfill from that message ID onwards
    """
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"

    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute("DELETE FROM drops WHERE guild_id = ?", (guild_id,))
        deleted = result.rowcount
        await db.commit()

    # Distinguish between a message ID (large number) and a plain limit (small number)
    is_message_id = len(arg) >= 17
    if is_message_id:
        try:
            after_id = int(arg)
        except ValueError:
            await ctx.send("❌ Invalid argument — provide a message ID or a message limit number."); return
        await ctx.send(f"🗑️ Wiped **{deleted}** item(s). Backfilling all messages from ID `{after_id}` onwards (cursed items only)...")
        stored, scanned = 0, 0
        after_obj = discord.Object(id=after_id - 1)
        async for message in ctx.channel.history(limit=None, after=after_obj, oldest_first=True):
            scanned += 1
            stored += await store_message_drops(message)
        await ctx.send(f"✅ Done. Scanned **{scanned}** messages, stored **{stored}** cursed item(s). Try `!dboldest` now!")
    else:
        try:
            limit = int(arg)
        except ValueError:
            await ctx.send("❌ Invalid argument — provide a message ID or a message limit number."); return
        await ctx.send(f"🗑️ Wiped **{deleted}** item(s). Backfilling last {limit} messages (cursed items only)...")
        stored, scanned = 0, 0
        async for message in ctx.channel.history(limit=limit):
            scanned += 1
            stored += await store_message_drops(message)
        await ctx.send(f"✅ Done. Scanned **{scanned}** messages, stored **{stored}** cursed item(s). Try `!dboldest` now!")


@bot.command()
async def backfillfrom(ctx, message_id: str):
    """
    Backfill all messages from a specific message ID onwards (no wipe).
    Duplicate entries are automatically skipped.
    Usage: !backfillfrom 1515712207919255605
    """
    try:
        after_id = int(message_id)
    except ValueError:
        await ctx.send("❌ Provide a valid Discord message ID."); return

    await ctx.send(f"⏳ Backfilling all messages from ID `{after_id}` onwards (cursed items only, duplicates skipped)...")
    stored, scanned = 0, 0
    after_obj = discord.Object(id=after_id - 1)
    async for message in ctx.channel.history(limit=None, after=after_obj, oldest_first=True):
        scanned += 1
        stored += await store_message_drops(message)
    await ctx.send(f"✅ Done. Scanned **{scanned}** messages, stored **{stored}** cursed item(s).")


@bot.command()
async def backfill(ctx, limit: int = 500):
    """Scan channel history and store drops. !backfill 1000"""
    await ctx.send(f"⏳ Backfilling last {limit} messages...")
    stored, scanned = 0, 0
    async for message in ctx.channel.history(limit=limit):
        scanned += 1
        stored += await store_message_drops(message)
    await ctx.send(f"✅ Done. Scanned **{scanned}** messages, stored **{stored}** item(s).")

@bot.command()
async def dbstats(ctx):
    """Show database summary."""
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) as total, COUNT(DISTINCT message_id) as messages, "
            "MAX(recorded_at) as newest, MIN(recorded_at) as oldest "
            "FROM drops WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
    oldest = to_gst(row[3]) if row[3] else "—"
    newest = to_gst(row[2]) if row[2] else "—"
    await ctx.send(
        f"📊 **Database stats for this server:**\n"
        f"• **{row[0]}** items logged from **{row[1]}** drop messages\n"
        f"• Oldest entry: `{oldest}`\n"
        f"• Newest entry: `{newest}`"
    )

@bot.command()
async def dboldest(ctx, limit: int = 5):
    """Show the oldest N logged drops. !dboldest 10"""
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT item_name, curses, curse_count, jump_url, recorded_at FROM drops "
            "WHERE guild_id = ? ORDER BY id ASC LIMIT ?", (guild_id, limit)
        )
        rows = await cur.fetchall()
    if not rows:
        await ctx.send("❌ No drops in the database yet."); return
    lines = [f"📜 **Oldest {limit} logged drop(s):**"]
    for r in rows:
        ts = to_gst(r["recorded_at"])
        curse_info = f" | *{r['curses']}*" if r['curses'] else ""
        lines.append(f"• `{ts}` [{r['item_name']}]({r['jump_url']}) ({r['curse_count']} curse(s)){curse_info}")
    await ctx.send("\n".join(lines)[:2000])

@bot.command()
async def dbnewest(ctx, limit: int = 5):
    """Show the most recent N logged drops. !dbnewest 10"""
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT item_name, curses, curse_count, jump_url, recorded_at FROM drops "
            "WHERE guild_id = ? ORDER BY id DESC LIMIT ?", (guild_id, limit)
        )
        rows = await cur.fetchall()
    if not rows:
        await ctx.send("❌ No drops in the database yet."); return
    lines = [f"🆕 **Most recent {limit} logged drop(s):**"]
    for r in rows:
        ts = to_gst(r["recorded_at"])
        curse_info = f" | *{r['curses']}*" if r['curses'] else ""
        lines.append(f"• `{ts}` [{r['item_name']}]({r['jump_url']}) ({r['curse_count']} curse(s)){curse_info}")
    await ctx.send("\n".join(lines)[:2000])

@bot.command()
async def dbitems(ctx):
    """List all unique item names in the database with their drop counts."""
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT item_name, COUNT(*) as cnt FROM drops WHERE guild_id = ? "
            "GROUP BY item_name COLLATE NOCASE ORDER BY cnt DESC LIMIT 50",
            (guild_id,)
        )
        rows = await cur.fetchall()
    if not rows:
        await ctx.send("❌ No drops in the database yet."); return
    lines = ["📦 **All unique items in database (top 50 by drop count):**"]
    for name, cnt in rows:
        lines.append(f"• `{name}` — {cnt}x")
    await ctx.send("\n".join(lines)[:2000])


# ─────────────────────────── PLAYER COMMAND ─────────────────────────────────

@bot.command()
async def player(ctx, *, query: str = ""):
    """
    Search drops by player name, with optional filters.

    !player apocgaem
    !player apocgaem, item Warhammer
    !player apocgaem, curse Curse of Mercy
    !player apocgaem, 2curses
    !player apocgaem, ncurses 3
    """
    if not query:
        await ctx.send("❌ Usage: `!player <name>` or `!player <name>, item <item>` etc. See `!loothelp`.")
        return

    guild_id = str(ctx.guild.id) if ctx.guild else "dm"

    # Split on first comma to get player name and optional filter
    if "," in query:
        player_name, _, filter_part = query.partition(",")
        player_name = player_name.strip()
        filter_part = filter_part.strip()
    else:
        player_name = query.strip()
        filter_part = ""

    if not player_name:
        await ctx.send("❌ Please provide a player name."); return

    # Parse optional filter
    if not filter_part:
        await search_or_scan(ctx, guild_id, "player LIKE ?", (f"%{player_name}%",), f"player: {player_name}")

    elif filter_part.lower().startswith("item "):
        item_q = filter_part[5:].strip()
        await search_or_scan(
            ctx, guild_id,
            "player LIKE ? AND item_name LIKE ?",
            (f"%{player_name}%", f"%{item_q}%"),
            f"{player_name} + item: {item_q}"
        )

    elif filter_part.lower().startswith("curse "):
        curse_q = filter_part[6:].strip()
        await search_or_scan(
            ctx, guild_id,
            "player LIKE ? AND curses LIKE ?",
            (f"%{player_name}%", f"%{curse_q}%"),
            f"{player_name} + curse: {curse_q}"
        )

    elif filter_part.lower() == "2curses":
        await search_or_scan(
            ctx, guild_id,
            "player LIKE ? AND curse_count >= 2",
            (f"%{player_name}%",),
            f"{player_name} + 2+ curses"
        )

    elif filter_part.lower().startswith("ncurses"):
        parts = filter_part.split()
        if len(parts) < 2:
            await ctx.send("❌ Usage: `!player <name>, ncurses <N>`"); return
        try:
            n = int(parts[1])
        except ValueError:
            await ctx.send("❌ N must be a number."); return
        await search_or_scan(
            ctx, guild_id,
            "player LIKE ? AND curse_count >= ?",
            (f"%{player_name}%", n),
            f"{player_name} + {n}+ curses"
        )

    else:
        await ctx.send(f"❌ Unknown filter `{filter_part}`. See `!loothelp` for options.")


# ─────────────────────────── DEBUG COMMANDS ─────────────────────────────────

@bot.command()
async def debug(ctx, limit: int = 5):
    """Inspect the last N messages — shows what the bot reads from each. !debug 10"""
    lines = [f"🔍 **Debug — last {limit} messages:**\n"]
    async for msg in ctx.channel.history(limit=limit):
        is_hook  = bool(msg.webhook_id)
        is_bot_  = msg.author.bot
        n_embeds = len(msg.embeds)
        line = f"**[{msg.author.name}]** webhook={is_hook} bot={is_bot_} embeds={n_embeds}"
        if msg.embeds:
            embed     = msg.embeds[0]
            full_text = get_embed_text(embed)
            items     = parse_loot_text(full_text)
            desc_prev = (embed.description or "")[:80].replace('\n', '↵')
            line += f"\n  └ desc=`{desc_prev}`"
            line += f"\n  └ parsed={[i['name'] for i in items]}"
            if items:
                for i in items:
                    line += f"\n      • {i['name']} → curses: {i['curses']}"
        lines.append(line)
    await ctx.send("\n".join(lines)[:2000])

@bot.command()
async def debugitem(ctx, *, item_name: str):
    """
    Show how a specific item is stored in the DB — useful to verify it was logged correctly.
    !debugitem Dunestrider Chestplate
    """
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT item_name, curses, curse_count, jump_url, recorded_at FROM drops "
            "WHERE guild_id = ? AND item_name LIKE ? ORDER BY id DESC LIMIT 10",
            (guild_id, f"%{item_name}%")
        )
        rows = await cur.fetchall()
    if not rows:
        await ctx.send(f"❌ No entries found for `{item_name}` — it may not be backfilled yet."); return
    lines = [f"🔎 **DB entries for `{item_name}` (last 10):**"]
    for r in rows:
        ts = to_gst(r["recorded_at"])
        lines.append(f"• `{ts}` **{r['item_name']}** | curses ({r['curse_count']}x): `{r['curses']}`")
        lines.append(f"  → {r['jump_url']}")
    await ctx.send("\n".join(lines)[:2000])


# ─────────────────────────── HELP ───────────────────────────────────────────

@bot.command()
async def loothelp(ctx):
    """Show all available commands."""
    help_text = """**🔮 Loot Search Bot — Commands**

**🔍 Search (searches entire logged history):**

`!searchloot item <name>`
  → Any drop of that item
  → e.g. `!searchloot item Archangel's Halo`

`!searchloot curse <curse>`
  → Any item that has that curse
  → e.g. `!searchloot curse Curse of Ruin`

`!searchloot cursewith <curse>, <N>`
  → Any item that has a specific curse AND N+ total curses
  → e.g. `!searchloot cursewith Curse of Transfiguration, 3`

`!searchloot has <item>, <curse>`
  → Item that includes a specific curse (among any number)
  → e.g. `!searchloot has Dunestrider Chestplate, Curse of Mercy`

`!searchloot combo <item>, <N>`
  → Item with N or more curses total
  → e.g. `!searchloot combo Archangel's, 2`

`!searchloot combo <item>, <curse>, <N>`
  → Item with a specific curse AND N+ total curses
  → e.g. `!searchloot combo Dunestrider Chestplate, Curse of Mercy, 3`

`!searchloot all <item>, <curse1>, <curse2>, ...`
  → Item that has ALL of the listed curses
  → e.g. `!searchloot all Dunestrider Chestplate, Curse of Mercy, Curse of Fear`

`!searchloot 2curses`
  → Any item with 2 or more curses

`!searchloot ncurses <N>`
  → Any item with N or more curses
  → e.g. `!searchloot ncurses 4`

**👤 Player search:**

`!player <name>`
  → All cursed drops for that player
  → e.g. `!player apocgaem`

`!player <name>, item <item>`
  → That player's drops of a specific item
  → e.g. `!player apocgaem, item Warhammer`

`!player <name>, curse <curse>`
  → That player's drops with a specific curse
  → e.g. `!player apocgaem, curse Curse of Mercy`

`!player <name>, 2curses`
  → That player's drops with 2 or more curses

`!player <name>, ncurses <N>`
  → That player's drops with N or more curses
  → e.g. `!player apocgaem, ncurses 3`

**📦 Database:**
`!backfill [limit]` — backfill last N messages (default 500)
`!backfillfrom <message_id>` — backfill from a specific message ID onwards (no wipe)
`!dbwipe` — wipe all drops and backfill last 500 messages
`!dbwipe <message_id>` — wipe and backfill from a specific message ID onwards
`!dbstats` — total items logged, oldest and newest entry dates
`!dbitems` — all unique item names with drop counts
`!dboldest [n]` — oldest N logged drops (default 5)
`!dbnewest [n]` — most recent N logged drops (default 5)

**🛠 Debug:**
`!debug [n]` — inspect last N messages and show what the bot parsed
`!debugitem <name>` — show exactly how an item is stored in the DB"""
    await ctx.send(help_text)


# ─────────────────────────── RUN ────────────────────────────────────────────

token = os.environ.get("DISCORD_BOT_TOKEN")
if not token:
    raise RuntimeError("DISCORD_BOT_TOKEN is not set.")

bot.run(token)
