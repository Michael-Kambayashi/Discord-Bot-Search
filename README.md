# Roblox Loot Tracker & Discord Inventory Search Bot

**Luau · Python · Discord Webhooks · JSON · Data Extraction · Database Search**

A personal project that connects **in-game loot collection and reporting** with a **searchable Discord inventory database**. It has two separate components:

1. **`ChestFarm.luau`** — a client-side Luau script that extracts item information from a Roblox game session, classifies the items, and posts structured loot reports to Discord through an HTTP webhook.
2. **`discord-bot/bot.py`** — a Python Discord bot, hosted separately on Replit, that can scan historical loot messages, **import them into a database when a user runs a backfill command**, and provide tools for searching and inspecting the stored items.

The Python bot **does not run the Luau script**, and the webhook **does not directly write records to the database**. Importing the existing Discord loot reports is a **manual command that triggers automated message parsing and storage**.

## System architecture

```text
Roblox game session
   │
   │ Game inventory/chest events
   ▼
ChestFarm.luau (third-party executor)
   ├─ Extracts item names, quantities, and optional attributes
   ├─ Filters and classifies items
   └─ Serializes categorized reports as JSON
   │
   │ HTTP POST to a Discord-compatible webhook
   ▼
Discord channel (loot report messages)
   │
   │ User manually invokes !backfill or !backfillfrom
   ▼
Python Discord bot (bot.py, hosted on Replit)
   ├─ Scans historical channel messages
   ├─ Parses loot reports and stores item records
   └─ Answers inventory search and database commands
   ▼
Searchable item database
```

**Important:** Replit hosts the Python bot. The Luau script runs separately in a Roblox session through an executor. The provided client code sends messages to a webhook-compatible endpoint; Replit is **not claimed to be an intermediary** for that HTTP request.

## Features

### Luau client — `roblox-client/ChestFarm.luau`

- **Event-driven extraction:** listens for game-specific inventory/container updates and item notifications.
- **Data transformation:** extracts item names, quantities and available modifiers/attributes; normalizes names and applies an item blacklist.
- **Classification:** groups items into categories including armor, neckwear, weapons, equipment/accessories and consumables.
- **JSON and HTTP integration:** creates Discord embed-style payloads using `HttpService:JSONEncode()` and submits them through an HTTP POST request.
- **Automation and recovery:** contains game-specific chest selection, retry, timeout monitoring and server-switching logic.

### Example Webhook Message
<br>
<img width="643" height="310" alt="Untitled" src="https://github.com/user-attachments/assets/836d331c-8641-44bf-ae9a-263f50b4ce50" />

### Python Discord bot — `discord-bot/bot.py`

- **Command-triggered data ingestion:** scans historical messages containing loot reports and adds parsed records to its database.
- **Inventory lookup:** lets the user retrieve stored item information through Discord.
- **Database inspection:** provides summary and debugging commands to review stored drops and parsed messages.
- **Separate hosting:** runs as a Python application on Replit, rather than in the Roblox executor.

## Database and debugging commands

The following command descriptions come from the bot's help text:

| Command | Purpose |
| --- | --- |
| `!backfill [limit]` | Scan the last N messages and store parsed drops (default: 500). |
| `!backfillfrom <message_id>` | Backfill from a specified message ID onward. |
| `!dbwipe` | Clear stored drops and backfill the last 500 messages. |
| `!dbwipe <message_id>` | Clear stored drops and backfill from the specified message. |
| `!dbstats` | Show total items logged and the oldest/newest entry dates. |
| `!dbitems` | List unique item names with drop counts. |
| `!dboldest [n]` | Show the oldest N stored drops (default: 5). |
| `!dbnewest [n]` | Show the newest N stored drops (default: 5). |
| `!debug [n]` | Inspect recent messages and see what the bot parsed. |
| `!debugitem <name>` | Inspect exactly how an item is stored in the database. |

**Example workflow:** Receive webhook reports in a Discord channel → run `!backfill 1000` → review `!dbstats` or `!dbitems` → use the bot's item-search commands to retrieve saved loot information.
### `!backfill 1000`

<img width="330" height="87" alt="Untitled" src="https://github.com/user-attachments/assets/c65e86b1-66be-48f9-9a9f-cd5fb63e1d2a" />

### `!dbstats`

<img width="305" height="96" alt="image" src="https://github.com/user-attachments/assets/4157a25d-0e0f-42ee-83e5-e3593fd04396" />

- `!dbitems`

<br>

<img width="356" height="252" alt="image" src="https://github.com/user-attachments/assets/da5ccfbe-c00d-4c3a-b1e3-28d3a5d1bf1d" />

> This is **not continuous automatic ingestion**: the database import is initiated by a Discord command. The bot performs the parsing and insertion after that command is issued.

## Repository structure

```text
Discord-Bot-Search/
├── README.md                       # This overview (repository root)
├── roblox-client/
│   └── ChestFarm.luau             # Client-side data extraction + webhook reports
├── discord-bot/
│   └── bot.py                     # Python bot: backfill, database and item search
└── ...                            # Keep all other existing repository files
```

The directory above illustrates the relevant parts of the repository, not a complete list of its files. Add the new `roblox-client/` folder alongside the existing `discord-bot/` folder.

## Runtime and limitations

- **Luau:** `ChestFarm.luau` is a game-specific script written for a **third-party Roblox executor**. It uses executor-only functions and game-specific events, so it **will not run unchanged in Roblox Studio, Replit or standard Lua environments**. Game updates may break it. It is included to document a personal programming project, not as an official Roblox integration.
- **Python bot:** The Discord bot is a separate Python application hosted on Replit. See the existing `discord-bot/` source and Replit project configuration for its dependencies and deployment requirements.
- **Database:** Historical loot reports are imported on demand using backfill commands; they are not automatically inserted when the webhook posts a message.
- **Platform rules:** Use scripts only in environments where you have permission and follow applicable Roblox, game and Discord rules.

## Security and privacy

**Never commit an active Discord webhook URL, bot token, database password, or `.env` file.** The public Luau sample should use a placeholder such as `YOUR_WEBHOOK_URL_HERE`. If a webhook URL was ever shared in an uploaded or public copy, **revoke and regenerate it** before using the repository. Do not include private server IDs, personal inventory data or credentials in screenshots.

## Skills demonstrated

- **Luau and Python** programming in separate execution environments
- **Event-driven data extraction** from application events
- **Data normalization, filtering and classification**
- **JSON serialization and HTTP/webhook integration**
- **Command-triggered ETL** (extract Discord messages → parse loot reports → load database records)
- **Database querying, debugging and error handling**

## Portfolio note

This is a **personal technical project** showing how game-generated data can be collected, transformed, published to a message channel and subsequently indexed for retrieval. The key engineering distinction is the **separation between the Luau data-producing client and the Python data-ingestion/search bot**.
