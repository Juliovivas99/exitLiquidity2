# NASDAQ Halt Discord Bot

Python service that polls the [NASDAQ Trader trade halt RSS feed](https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts) during the regular session window (9:25 AM–4:05 PM Eastern, with buffers around the normal 9:30–4:00 ET session). It detects **new** halt rows and **resumption** rows (reason codes `T5`, `MWCB`), tracks IDs in memory to avoid duplicate Discord alerts, and posts rich embeds to a channel webhook.

## What it monitors

| Topic | Source | Notes |
|--------|--------|--------|
| **LULD / circuit-breaker pauses** | Reason `LUDP` | Limit Up–Limit Down 5-minute volatility pause |
| **News / material event halts** | e.g. `T1` | Pending news or other regulatory reasons |
| **Volatility / regulatory halts** | e.g. `T12`, `H10` | Unusual activity, SEC suspension, etc. |
| **Market-wide events** | e.g. `M`, `MWCB` | Broad market halt or resume |
| **IPO-related** | e.g. `IPO1` | IPO not yet open for trading |
| **Resumptions** | `T5`, `MWCB` | Single-stock or market-wide **resume** (distinct from LULD *expected* resume times on halt rows) |

Only **NYSE trading days** (via `pandas_market_calendars`) are considered; weekends and holidays exit immediately with `No trading today`.

## Requirements

- Python 3.11+
- A Discord **Incoming Webhook** URL

## Setup

1. Clone or copy the `halt-bot/` directory.

2. Create a virtual environment (recommended):

   ```bash
   cd halt-bot
   python3.11 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Configure the webhook.

   Copy `.env.example` to `.env` and set secrets (`.env` is gitignored):

   ```bash
   cp .env.example .env
   ```

   ```env
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_TOKEN
   ```

   **Create a Discord webhook**

   - Open your server → channel → **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook**.
   - Copy the webhook URL and paste it into `DISCORD_WEBHOOK_URL`.

## Run

```bash
python main.py
```

On a trading day inside the 9:25 AM–4:05 PM ET window, the bot polls about every **20 seconds** (via the `schedule` library). Outside that window it sleeps **60 seconds** between checks so the process can stay running overnight.

On startup, after validating the calendar, it performs **one** RSS fetch and records all current halt IDs **without** sending alerts, so only **new** feed rows trigger notifications.

## Production

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_WEBHOOK_URL` | Yes | — | Incoming webhook URL |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `POLL_INTERVAL_SECONDS` | No | `20` | RSS poll interval in session (10–300) |
| `OUTSIDE_WINDOW_SLEEP_SECONDS` | No | `60` | Sleep between checks outside 9:25–4:05 ET (10–3600) |
| `HALT_BOT_IDLE_WHEN_CLOSED` | No | off | If `1`/`true`, **do not exit** on non-trading days; sleep and re-check the NYSE calendar (good for a long-running service) |
| `HALT_BOT_IDLE_SLEEP_SECONDS` | No | `3600` | Seconds between calendar checks when idle (60–86400) |

By default, on weekends and holidays the process **exits with code 0** after logging `No trading today`. Use **systemd** `Restart=` on weekdays, or set **`HALT_BOT_IDLE_WHEN_CLOSED=1`** so one service can stay up 24/7 and wake on the next session.

### Docker

From `halt-bot/`:

```bash
docker build -t halt-bot .
docker run --rm -e DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." halt-bot
```

Or with an env file:

```bash
docker run --rm --env-file .env halt-bot
```

### systemd

See `deploy/halt-bot.service` for a ready-to-edit unit. Install under `/etc/systemd/system/`, adjust `WorkingDirectory` and `ExecStart`, then enable the service.

The app handles **SIGTERM** (graceful shutdown after the current sleep/poll iteration).

## Halt code reference (embedded in alerts)

| Code | Label | Meaning (short) |
|------|--------|------------------|
| `LUDP` | Circuit Breaker | LULD volatility pause (~5 min) |
| `T1` | News Pending | Material news pending |
| `T12` | Volatility Halt | Unusual price movement |
| `H10` | SEC Suspension | SEC suspension |
| `M` | Market-Wide Halt | Market-wide circuit breaker |
| `IPO1` | IPO Halt | IPO not yet open |
| `T5` | Resume | Single-stock resumption |
| `MWCB` | Market-Wide Resume | Market-wide resume |
| *other* | Trading Halt | Generic label + reason text |

## Run as a persistent background service

### Linux (systemd)

Use `deploy/halt-bot.service` (see **Production**). After installing the unit:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now halt-bot
```

For a **user** unit, copy to `~/.config/systemd/user/` and use `systemctl --user`.

### macOS (launchd)

`~/Library/LaunchAgents/com.example.haltbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.example.haltbot</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/halt-bot/.venv/bin/python</string>
    <string>-u</string>
    <string>/Users/YOU/halt-bot/main.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/YOU/halt-bot</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DISCORD_WEBHOOK_URL</key>
    <string>https://discord.com/api/webhooks/...</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/YOU/halt-bot/halt-bot.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOU/halt-bot/halt-bot.err</string>
</dict>
</plist>
```

Load:

```bash
launchctl load ~/Library/LaunchAgents/com.example.haltbot.plist
```

### Windows

- **Task Scheduler:** Create a task that runs at logon or at startup, action “Start a program”, program `C:\path\to\.venv\Scripts\python.exe`, argument `C:\path\to\halt-bot\main.py`, “Start in” set to `C:\path\to\halt-bot`. Set `DISCORD_WEBHOOK_URL` in the task’s environment or use a small wrapper `.cmd` that sets it and runs Python.

- **NSSM (Non-Sucking Service Manager):** Install the service pointing to `python.exe` with arguments `main.py` and the application directory set to the project folder; add `DISCORD_WEBHOOK_URL` in the service environment tab.

## License

Use and modify freely for your own monitoring.
