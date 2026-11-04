# Этап 2 — отмена задач

Команда Telegram: `/cancel ID_задачи`. Проверяется Telegram ID владельца;
несуществующие и чужие задачи не раскрываются. Повторная отмена безопасна.

## Состояния
- `queued`: помечается `cancelled`, диспетчер больше не захватывает задачу.
- `downloading`, `processing`: в одной SQLite-транзакции фиксируется
  `cancelled` и отзывается offered/running lease. Offline IPC-контур
  замечает отмену, отменяет ожидание результата и отправляет worker
  `cancel_reservation`; worker останавливает offline execution.
- `upload_pending`: отмена допускается до отправки.
- `uploading`: намеренно не отменяется командой, поскольку отправка в
  Telegram может уже завершиться, а результат ещё не записан.
  Это требует отдельной сверки в этапе 3.
- `completed`, `failed`, `cancelled`: неизменяемые терминальные состояния.

Внутренний `cancel_user_tasks` также отзывает leases и не трогает
неоднозначные Telegram-отправки.

## Проверка
`python -m pytest -q tests/test_cancel_worker_lifecycle.py tests/test_offline_active_cancellation.py`

Offline worker не скачивает медиа. Отмена работающего IPC проверяется
тестом с контролируемым зависшим исполнением; никакие реальные URL не
исполняются. Этап 3 отдельно проверяет аварийные завершения и рестарты.
