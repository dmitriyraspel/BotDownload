# BotDownload

Telegram-бот для скачивания видео и MP3 с YouTube, Instagram и TikTok. Разработка поэтапная. **Этап 2 — Telegram-обработчики и анализ метаданных; скачивание пока не подключено к Telegram.**

## Требования

Основные требования к продукту, безопасности и переносимости закреплены в [docs/PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md). Офисный тестовый сервер не является эталоном сетевой конфигурации для VPS.

Основная целевая платформа — Linux VPS. Поддерживаемые сочетания ОС и Python уточняются по результатам интеграционных проверок; разработка и тесты также выполняются на Debian 12. Нужны FFmpeg, ffprobe и yt-dlp. Для первого этапа необходима установка Python-зависимостей. Локальный Telegram Bot API Server устанавливается отдельно и в данном проекте не разворачивается.

## Первичная подготовка

Все команды ниже выполняйте в терминале Linux, из каталога проекта, если не указано иное.

1. Проверьте текущий каталог командой `pwd` и версию Python командой `python3 --version`.
2. Создайте окружение командой `python3 -m venv .venv`. Это изолирует зависимости проекта.
3. Активируйте окружение командой `source .venv/bin/activate`.
4. Установите зависимости командой `python -m pip install -r requirements-dev.txt`.
5. Создайте локальный файл секретов командой `cp env.example .env`. Откройте его в локальном редакторе и задайте токен Telegram; не передавайте его в чат, терминальные аргументы или Git.
6. В `config.yaml` задайте собственный `admin_telegram_id` и при необходимости `trusted_users`. Этот файл не содержит секретов, но перед публикацией проверьте, нет ли в нём личных ID.
7. Проверьте наличие `ffmpeg -version`, `ffprobe -version` и `yt-dlp --version`.
8. Запустите `python -m bot`. Проверьте запуск и журнал; Telegram-функции развиваются поэтапно.
9. Выполните тесты командой `python -m pytest -q`.

Рабочая база хранится в `data/bot.sqlite`, журналы — в `logs/bot.log`. Удаление этих файлов приводит к потере состояния и диагностики. Никогда не добавляйте их в Git.

## Статус

Реализованы части Telegram-обработчиков, анализа URL и инфраструктуры. Безопасный загрузчик ещё не интегрирован в пользовательский поток. Не использовать текущую ветку для публичного запуска.

## Stage 2: project-local Deno (Windows and Debian)

Deno is optional for metadata inspection but recommended for YouTube format extraction. Install the pinned version using the project's Python interpreter; the installer downloads an official Deno release into the ignored `tools/deno/` directory and does not modify the global PATH.

Windows (VS Code terminal):
```powershell
.\.venv\Scripts\python.exe scripts\install_deno.py
.\tools\deno\deno.exe --version
```

Debian 13:
```sh
.venv/bin/python scripts/install_deno.py
./tools/deno/deno --version
```

The bot automatically configures yt-dlp to use the local Deno binary when present. Supported installer targets: Windows x86_64, Linux x86_64/aarch64. Downloads require HTTPS access to GitHub releases. The installer currently trusts the official HTTPS release; checksum/signature verification is not yet implemented. Do not run downloaded binaries from untrusted sources.

On Windows, `config.yaml` can use `telegram.api_mode: cloud`. Keep the bot token and optional `ADMIN_TELEGRAM_ID` in local `.env`, never commit secrets.

## Download engine (not enabled in Telegram yet)

`bot/downloader.py` prepares video/MP3 downloads with duration and size
checks, subprocess argument lists (no shell), timeouts and temporary-file cleanup.
The Telegram handler intentionally still provides metadata only. Before enabling
downloads from arbitrary users, implement and test network isolation against
SSRF (including redirects and extractor-internal requests), enforce quotas and
upload limits, and test the complete flow on Windows and Debian.
