"""Interactive, local-only operator reconciliation of ambiguous uploads.

Run as the database-owning service user, with upload workers stopped.
No Telegram API calls are made by this command.
"""
import argparse
import getpass
from pathlib import Path
import sys

from .upload_reconciliation import (
    ambiguous_uploads, confirm_delivered, confirm_not_delivered,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manually resolve a verified ambiguous Telegram delivery")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--task-id", type=int, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--delivered", action="store_true",
                        help="Message confirmed in Telegram; enter its file_id")
    action.add_argument("--not-delivered", action="store_true",
                        help="Independently verified Telegram did not accept message")
    args = parser.parse_args(argv)
    if args.task_id <= 0 or not args.db.is_file():
        parser.error("Invalid task ID or SQLite database does not exist")
    if not sys.stdin.isatty():
        print("Refusing non-interactive reconciliation", file=sys.stderr)
        return 2
    record = next((r for r in ambiguous_uploads(args.db)
                   if r["task_id"] == args.task_id), None)
    if record is None or record["reserved_utc_day"] is None:
        print("Task is not an ambiguous reserved upload", file=sys.stderr)
        return 1
    print(f"Task {args.task_id}, user {record['user_id']}, "
          f"reserved UTC day {record['reserved_utc_day']}")
    if args.delivered:
        print("Verify the Telegram message and its file_id independently.")
    else:
        print("Verify Telegram did NOT accept the message; a retry may duplicate it.")
    expected = f"CONFIRM {args.task_id}"
    if input(f"Type {expected} to proceed: ").strip() != expected:
        print("Cancelled")
        return 1
    if args.delivered:
        file_id = getpass.getpass("Confirmed Telegram file_id: ")
        if not file_id.strip():
            print("Empty file_id; cancelled", file=sys.stderr)
            return 1
        success = confirm_delivered(args.db, task_id=args.task_id,
                                    telegram_file_id=file_id)
    else:
        success = confirm_not_delivered(args.db, task_id=args.task_id)
    if not success:
        print("Task changed or was already resolved; no update", file=sys.stderr)
        return 1
    print("Reconciliation recorded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
