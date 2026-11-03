# Debian 12: запуск Telegram-бота через systemd

Этот этап запускает **только анализ ссылок и очередь**. Загрузка файлов отключена до завершения защиты сетевых соединений yt-dlp.

## 1. Создать отдельного пользователя

Выполнять от root:

```bash
useradd --system --home-dir /opt/BotDownload --shell /usr/sbin/nologin botdownload
cd /opt/BotDownload
chown -R botdownload:botdownload data logs
chown root:botdownload /opt/BotDownload/.env /opt/BotDownload/config.yaml
chmod 640 /opt/BotDownload/.env /opt/BotDownload/config.yaml
chmod 750 /opt/BotDownload/data /opt/BotDownload/logs
```

Если папок `data` и `logs` нет, предварительно создать их командой `mkdir -p data logs`. Код и виртуальное окружение должны быть доступны для чтения пользователю `botdownload`, но не должны быть доступны ему для записи. Не делайте `chown -R botdownload` для всего репозитория.

## 2. Установить службу

Создать файл `/etc/systemd/system/botdownload.service`:

```ini
[Unit]
Description=BotDownload Telegram bot (metadata-only)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botdownload
Group=botdownload
WorkingDirectory=/opt/BotDownload
ExecStart=/opt/BotDownload/.venv/bin/python -m bot
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/opt/BotDownload/.venv/bin:/usr/local/bin:/usr/bin:/bin
Restart=on-failure
RestartSec=5
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/BotDownload/data /opt/BotDownload/logs
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
AmbientCapabilities=
MemoryMax=512M
TasksMax=64

[Install]
WantedBy=multi-user.target
```

Пока не используйте `PrivateNetwork=true`: боту нужен доступ к Telegram API. Для реального скачивания понадобятся отдельные ограничения сетевых запросов и изоляция рабочих процессов.

## 3. Запуск и диагностика

```bash
systemctl daemon-reload
systemctl enable --now botdownload
systemctl status botdownload --no-pager
journalctl -u botdownload -n 50 --no-pager
```

Перед запуском остановить ручной процесс `python -m bot`, если он работает, иначе два экземпляра будут одновременно получать Telegram updates.

При ошибке доступа проверить права `.env`, `config.yaml`, `data`, `logs` и родительских каталогов командой `namei -l /opt/BotDownload/.env`.

После изменения кода: `git pull`, затем `systemctl restart botdownload`. Не редактируйте секреты через Git и не отправляйте их в чат.
