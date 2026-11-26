# Wallet Watch Bot

[English](README.md)

Telegram-бот отслеживает переводы токенов BEP-20 в сети BNB Smart Chain. Он присылает сообщение в личный чат, когда кошелёк отправляет или получает токены на сумму не ниже заданного порога. В уведомлении есть метка кошелька, направление перевода, количество токенов, сумма в USD, контрагент и ссылка на транзакцию в BscScan.

## Команды

Отправляй команды в личном чате с ботом.

| Команда | Действие |
| --- | --- |
| `/start` | Показать помощь |
| `/watch <адрес> [метка] [мин_usd]` | Добавить кошелёк. Метка и порог необязательны. Порог по умолчанию составляет $1000 |
| `/unwatch <номер>` | Удалить кошелёк по номеру из `/list` |
| `/list` | Показать кошельки с номерами, метками и порогами |
| `/min <номер> <usd>` | Изменить порог кошелька |
| `/lang uk`, `/lang ru`, `/lang en` | Переключить ответы и уведомления на украинский, русский или английский |

Адрес состоит из префикса `0x` и 40 шестнадцатеричных символов. В метке можно использовать пробелы. Чтобы задать свой порог, укажи положительное число последним аргументом. У одного пользователя может быть до 30 кошельков.

```text
/watch 0x1234567890abcdef1234567890abcdef12345678 Основной кошелёк 2500
/list
/min 1 750
/unwatch 1
/lang ru
```

При первой команде бот использует украинский для кода языка Telegram с префиксом `uk`, русский для `ru` и английский для остальных кодов. Выбор через `/lang` сохраняется в SQLite.

## Как работают алерты

- Бот сканирует новые блоки диапазонами до 500. События `Transfer` запрашиваются отдельно для адресов отправителей и получателей.
- Метаданные токена загружаются через `eth_call` и сохраняются в SQLite. Бот рассчитывает сумму в USD по цене DexScreener и кеширует цену на пять минут. Если цены нет, он записывает причину в лог и пропускает перевод.
- Встроенный список содержит известные адреса бирж. Для перевода на такой адрес в уведомлении указывается метка биржи.
- Цена берётся только из пар BSC с ликвидностью от $10 000. Так бот пропускает спам-токены, которые рассылают на популярные кошельки с поддельной ценой.
- Переводы нативного BNB не отслеживаются, только токены BEP-20, включая WBNB.
- Если пользователь заблокировал бота, его кошельки удаляются.
- По событию с одним и тем же хешем транзакции и индексом лога каждый пользователь получает не более одного уведомления. SQLite также хранит кошельки, выбранный язык и последний просмотренный блок.
- С пустой базой бот начинает просмотр с текущего блока. Если отставание превысит 2000 блоков, он запишет это в лог и продолжит с текущего блока.

Бот читает публичные данные блокчейна. Сумма в USD рассчитывается по цене, доступной на момент просмотра блока.

## Токен Telegram

Открой `@BotFather`, отправь `/newbot` и выбери имя и уникальный username, заканчивающийся на `bot`. Сохрани выданный токен в переменной `BOT_TOKEN` в своём локальном файле `.env`. [Открыть @BotFather](https://t.me/BotFather)

## Переменные окружения

Создай `.env` из `.env.example`. Запускай один экземпляр бота на токен.

| Переменная | Значение по умолчанию | Назначение |
| --- | --- | --- |
| `BOT_TOKEN` | Обязательная | Токен Telegram-бота |
| `BSC_RPC_URL` | `https://bsc-rpc.publicnode.com` | JSON-RPC BNB Smart Chain |
| `RPC_RPS` | `3` | Максимум RPC-запросов в секунду |
| `CHECK_SECONDS` | `5` | Интервал между проверками блоков в секундах |
| `DB_PATH` | `data/wallets.sqlite3` | Путь к базе SQLite |

## Локальный запуск

Нужен Python 3.11 или новее. Открой терминал в папке проекта. Команда копирования создаёт `.env` при первой настройке. Впиши туда токен перед запуском.

**macOS или Linux**

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

Открой личный чат со своим ботом в Telegram и отправь `/start`.

## Docker

Заполни `.env` в папке проекта. Оставь путь к базе по умолчанию, чтобы именованный том сохранял данные SQLite между запусками контейнера.

```bash
docker build -t wallet-watch-bot .
docker run --name wallet-watch-bot --env-file .env \
  -v wallet-watch-data:/app/data wallet-watch-bot
```

## VPS с systemd

Для примера нужен Linux VPS с systemd, Git и Python 3.11+ с поддержкой venv. Создай системного пользователя и установи проект в `/opt/wallet-watch-bot`.

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

Заполни `BOT_TOKEN` и сохрани unit-файл в `/etc/systemd/system/wallet-watch-bot.service`.

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

## Тесты

Тесты используют подготовленные данные, временные базы SQLite и заглушки HTTP. Запускай их из папки проекта после создания виртуального окружения.

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest -q
```

В Windows PowerShell используй путь к Python из виртуального окружения.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions запускает pytest на Python 3.11, 3.12 и 3.13.
