# Wallet Watch Bot

[Русская версия](README.ru.md)

A Telegram bot that watches BEP-20 token transfers on BNB Smart Chain. It sends a private message when a watched wallet sends or receives tokens worth at least its configured USD threshold. Each alert shows the wallet label, direction, token amount, USD value, counterparty and BscScan transaction link.

## Commands

Send these commands in a private chat with the bot.

| Command | What it does |
| --- | --- |
| `/start` | Show help |
| `/watch <address> [label] [min_usd]` | Watch a wallet with an optional label and USD threshold. The default is $1,000 |
| `/unwatch <number>` | Remove a wallet by its number from `/list` |
| `/list` | Show your numbered wallets, labels and thresholds |
| `/min <number> <usd>` | Change a wallet's threshold |
| `/lang uk`, `/lang ru`, `/lang en` | Switch replies and alerts to Ukrainian, Russian or English |

A BSC address consists of `0x` followed by 40 hexadecimal characters. Labels may contain spaces. Use a positive number as the last argument when setting a custom USD threshold. Each user can watch up to 30 wallets.

```text
/watch 0x1234567890abcdef1234567890abcdef12345678 Treasury wallet 2500
/list
/min 1 750
/unwatch 1
/lang en
```

On your first command, the bot uses Ukrainian for a Telegram language code beginning with `uk`, Russian for `ru` and English for the other codes. A language selected with `/lang` is saved in SQLite.

## How alerts work

- The bot reads new blocks in ranges of up to 500 and queries token `Transfer` logs separately for watched senders and recipients.
- It loads token metadata through `eth_call` and caches it in SQLite. It calculates USD value using the DexScreener price, cached for five minutes. Transfers with unavailable prices are logged and skipped.
- A built-in list labels known exchange counterparties. Transfers to listed exchange wallets can be identified as exchange deposits in alerts.
- Each user gets at most one alert for a given transaction hash and log index. SQLite also stores your watches, language and the last scanned block.
- On a fresh database, scan progress starts at the current block. When the bot falls more than 2,000 blocks behind, it logs the gap and resumes from the current block.

The bot reads public blockchain data. It uses USD prices available at scan time.

## Telegram token

Open `@BotFather`, send `/newbot` and choose a display name and unique username ending in `bot`. Save the returned token as `BOT_TOKEN` in your local `.env` file. [Open @BotFather](https://t.me/BotFather)

## Environment

Create `.env` from `.env.example`. Run one bot instance per Telegram token.

| Variable | Default | Purpose |
| --- | --- | --- |
| `BOT_TOKEN` | Required | Telegram bot token |
| `BSC_RPC_URL` | `https://bsc-rpc.publicnode.com` | BNB Smart Chain JSON-RPC endpoint |
| `RPC_RPS` | `3` | Maximum RPC requests per second |
| `CHECK_SECONDS` | `5` | Interval between block checks in seconds |
| `DB_PATH` | `data/wallets.sqlite3` | SQLite database path |

## Run locally

Install Python 3.11 or later and open a terminal in the project directory. The copy command creates `.env` on your first setup. Save the token in it before starting the bot.

**macOS or Linux**

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

```bash
./.venv/bin/python -m bot.main
```

**Windows PowerShell**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

```powershell
.\.venv\Scripts\python.exe -m bot.main
```

Open your bot's Telegram chat and send `/start`.

## Run with Docker

Fill in `.env` in the project directory. Keep the default database path so the named volume retains the SQLite state between container runs.

```bash
docker build -t wallet-watch-bot .
docker run --name wallet-watch-bot --env-file .env \
  -v wallet-watch-data:/app/data wallet-watch-bot
```

## Deploy on a VPS with systemd

The example uses a Linux VPS with systemd, Git and Python 3.11+ with venv support. Create the service user and install the project under `/opt/wallet-watch-bot`.

```bash
sudo useradd --system --user-group --home-dir /opt/wallet-watch-bot \
  --shell /usr/sbin/nologin wallet-watch
sudo git clone https://github.com/Bogdan131/Bogdan131-wallet-watch-bot.git /opt/wallet-watch-bot
sudo chown -R wallet-watch:wallet-watch /opt/wallet-watch-bot
cd /opt/wallet-watch-bot
sudo -u wallet-watch python3 -m venv .venv
sudo -u wallet-watch .venv/bin/python -m pip install -r requirements.txt
sudo -u wallet-watch install -m 600 .env.example .env
sudoedit .env
```

After setting `BOT_TOKEN`, save this unit as `/etc/systemd/system/wallet-watch-bot.service`.

```ini
[Unit]
Description=Wallet Watch Bot
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=wallet-watch
Group=wallet-watch
WorkingDirectory=/opt/wallet-watch-bot
ExecStart=/opt/wallet-watch-bot/.venv/bin/python -m bot.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wallet-watch-bot
sudo journalctl -u wallet-watch-bot -f
```

## Tests

The tests use local fixtures, temporary SQLite databases and mocked HTTP responses. Run them from the project directory after creating the virtual environment.

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest -q
```

On Windows PowerShell, run the same checks with the Windows virtual environment path.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions runs pytest on Python 3.11, 3.12 and 3.13.
