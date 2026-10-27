# Secret Sandy Claws Bot

A Discord bot that runs a Secret Santa: it DMs everyone for a gift wish, then
privately tells each person who they're buying for and what that person wants.

## Setup

1. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications)
   and turn on the **Message Content Intent** under *Bot → Privileged Gateway Intents*.
2. Invite the bot to your server with permission to read and send messages.
3. Install and run:

   ```sh
   pip install -r requirements.txt
   export DISCORD_TOKEN="your-bot-token"
   python "Secret Santa Up.py"
   ```

Optional: set `SANTA_RESPONSE_TIMEOUT` (in seconds, default 86400 = 24 hours)
to change how long people have to answer.

## Commands

| Command | Who | What it does |
| --- | --- | --- |
| `!start @a @b @c ...` | anyone | Starts a Secret Santa with at least 3 different people. Everyone is DMed at once. |
| `!check` | organizer or server manager | DMs you who has responded and who is still pending. Never shows pairings. |
| `!clear` | organizer or server manager | Cancels the running Secret Santa and clears its lists. |

Anyone who doesn't reply within the timeout is still included; their Secret
Santa is told to surprise them. Participants must allow DMs from server members.

Games are kept in memory only: if the bot restarts while a Secret Santa is
running, that game is lost and has to be started again with `!start`.
