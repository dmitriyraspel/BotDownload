# Debian 12: развёртывание BotDownload (текущий тестовый сервер)

**Текущий режим — ручной запуск от `tgbot`. systemd откладывается до окончания разработки и тестов.** Скачивание в Telegram пока отключено; доступны анализ ссылок и интерфейс очереди.

## Существующая установка

- Репозиторий: `/opt/BotDownload`, ветка `feature/stage-2-telegram`.
- Системный пользователь: `tgbot` (без домашнего каталога, shell `/usr/sbin/nologin`).
- Код, `.venv`, `.git`: владелец `root`, доступны `tgbot` на чтение.
- `.env` и `config.yaml`: `root:tgbot`, права `640`.
- `data/`, `logs/`: `tgbot:tgbot`, права на каталог `750`.
- Каталог загрузок: `/var/www/botdownload_files`, `tgbot:tgbot`, права `750`. Должен существовать до запуска задач. Отдельный диск можно смонтировать в этот путь.
- Конфигурация `storage.download_dir: "/var/www/botdownload_files"`; `storage.unknown_size_fallback_mib: 2048`.
- SQLite: `data/bot.sqlite`; лог: `logs/bot.log`.

Права на код не следует передавать `tgbot`: иначе процесс сможет изменять собственные исполняемые файлы. Для проверки:

```bash
id tgbot
runuser -u tgbot -- test -r /opt/BotDownload/.env && echo 'ENV OK'
runuser -u tgbot -- test -w /opt/BotDownload/data && echo 'DATA OK'
runuser -u tgbot -- test -w /opt/BotDownload/logs && echo 'LOGS OK'
runuser -u tgbot -- test -w /var/www/botdownload_files && echo 'DOWNLOADS OK'
runuser -u tgbot -- test -w /opt/BotDownload/bot && echo 'WARNING: code writable' || echo 'CODE PROTECTED'
```

## Обновление без потери настроек

`config.yaml` изменён локально и отслеживается Git. Перед обновлением остановить бот и сохранить файл:

```bash
cd /opt/BotDownload
cp -p config.yaml /root/botdownload-config-backup.yaml
git status --short
```

Если upstream изменил тот же файл, `git pull --ff-only` может отказать. Не выполнять `git reset --hard` и не удалять `.env` или `data/`. Разрешать конфликты отдельно, сохраняя локальные параметры. После разрешения:

```bash
git status --short
.venv/bin/python -m pytest -q
```

На 2026-11-03 на сервере подтверждено **52 passed**. Новые коммиты требуют повторной проверки.

## Ручной запуск от tgbot

```bash
cd /opt/BotDownload
runuser -u tgbot -- .venv/bin/python -m bot
```

Остановить `Ctrl+C`. Не запускать одновременно два экземпляра Telegram polling. Просмотр логов: `tail -n 50 /opt/BotDownload/logs/bot.log`. Запуск из `/opt/BotDownload` важен для относительных путей.

## Файлы загрузок

`bot/download_storage.py` предоставляет отдельные каталоги задач `task-<id>-<random>` с правами `700` и очистку только конкретного каталога. Он **пока не подключён к очереди и загрузчику**. Не удалять вручную чужие файлы в корне `/var/www/botdownload_files`. В случае отсутствия смонтированного каталога задача должна останавливаться, а не записывать файлы на системный диск. Контроль свободного места и политика хранения ещё в разработке.

## Финальный этап: systemd

Службу `systemd`, ограничения процессов и сетевую изоляцию настроить **только после** завершения функциональности и тестов. Не использовать старую конфигурацию с пользователем `botdownload`: фактическая учётная запись — `tgbot`.
