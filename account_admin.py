"""Local-only recovery tools. Run on the computer that owns the SQLite database."""

import argparse
from datetime import date, datetime, timezone
import getpass
import hashlib
from pathlib import Path
import secrets
import time
from urllib.parse import urlparse

from backup_db import backup_database, database_path
from db import SCHEMA_VERSION, connect


def checked_date(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Use a date in YYYY-MM-DD format")
    return value


def run(args):
    path = Path(args.db or database_path()).resolve()
    if not path.is_file():
        raise ValueError(f"Database not found: {path}")
    db = connect(path)
    try:
        if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise ValueError("Run py setup_db.py before using the admin tools")
        if args.command == "list-orphans":
            rows = db.execute("""SELECT id,name,category,amount_cents,legacy_user_id,expense_date
                FROM expenses WHERE user_id IS NULL ORDER BY id""").fetchall()
            if not rows:
                print("No ownerless expenses.")
            for row in rows:
                print(f"ID {row['id']}: {row['name']!r}, {row['category']!r}, "
                      f"Rs. {row['amount_cents']//100:,}.{row['amount_cents']%100:02d}, original user ID {row['legacy_user_id']}, "
                      f"date {row['expense_date'] or 'unknown'}")
            return
        if args.command == "list-undated":
            rows = db.execute("""SELECT e.id,e.name,e.category,e.user_id,u.username
                FROM expenses e LEFT JOIN users u ON u.id=e.user_id
                WHERE e.expense_date IS NULL ORDER BY e.id""").fetchall()
            if not rows:
                print("No undated expenses.")
            for row in rows:
                print(f"ID {row['id']}: {row['name']!r}, {row['category']!r}, "
                      f"owner {row['username'] or 'unassigned'}")
            return
        if args.command == "assign-expense":
            if not args.verified:
                raise ValueError("Confirm verified ownership with --verified")
            user = db.execute("SELECT id,username FROM users WHERE username=? COLLATE NOCASE",
                              (args.username,)).fetchone()
            expense = db.execute("SELECT * FROM expenses WHERE id=? AND user_id IS NULL",
                                 (args.expense_id,)).fetchone()
            if user is None or expense is None:
                raise ValueError("Account or ownerless expense not found")
            expense_date = checked_date(args.date) if args.date else expense["expense_date"]
            backup = backup_database(path)
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("""UPDATE expenses SET user_id=?,expense_date=?
                WHERE id=? AND user_id IS NULL""", (user["id"], expense_date, expense["id"]))
            if updated.rowcount != 1:
                raise RuntimeError("Expense was assigned by another process; no changes saved")
            db.execute("INSERT OR IGNORE INTO categories(user_id,name) VALUES (?,?)",
                       (user["id"], expense["category"]))
            db.execute("""INSERT INTO legacy_assignment_audit
                (expense_id,user_id,previous_legacy_user_id,operator,assigned_at)
                VALUES (?,?,?,?,?)""", (expense["id"], user["id"], expense["legacy_user_id"],
                getpass.getuser(), datetime.now(timezone.utc).isoformat(timespec="seconds")))
            db.commit()
            print(f"Assigned expense {expense['id']} to {user['username']}. Backup: {backup}")
            return
        if args.command == "set-date":
            expense = db.execute("SELECT id FROM expenses WHERE id=?", (args.expense_id,)).fetchone()
            if expense is None:
                raise ValueError("Expense not found")
            checked_date(args.date)
            backup = backup_database(path)
            db.execute("UPDATE expenses SET expense_date=? WHERE id=?", (args.date, args.expense_id))
            db.commit()
            print(f"Updated date for expense {args.expense_id}. Backup: {backup}")
            return
        if args.command == "reset-link":
            user = db.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE",
                              (args.username,)).fetchone()
            if user is None:
                raise ValueError("Account not found")
            parsed = urlparse(args.base_url)
            local = parsed.hostname in {"127.0.0.1", "localhost"}
            if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
                raise ValueError("Use HTTPS except for localhost")
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            now = int(time.time())
            db.execute("UPDATE account_tokens SET used_at=? WHERE user_id=? AND used_at IS NULL",
                       (now, user["id"]))
            db.execute("""INSERT INTO account_tokens(token_hash,user_id,purpose,expires_at)
                VALUES (?,?,'password_reset',?)""", (token_hash, user["id"], now + 900))
            db.commit()
            print(f"One-time link (expires in 15 minutes): {args.base_url.rstrip('/')}/reset-password/{token}")
            return
        raise ValueError("Unknown command")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="SQLite database path; defaults to the app database")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-orphans", help="Review expenses with no verified owner")
    commands.add_parser("list-undated", help="Review expenses with no known expense date")
    assign = commands.add_parser("assign-expense", help="Assign one reviewed legacy expense")
    assign.add_argument("--expense-id", type=int, required=True)
    assign.add_argument("--username", required=True)
    assign.add_argument("--date", help="Optional verified expense date (YYYY-MM-DD)")
    assign.add_argument("--verified", action="store_true", help="Confirm you verified the owner")
    set_date = commands.add_parser("set-date", help="Correct a legacy expense date")
    set_date.add_argument("--expense-id", type=int, required=True)
    set_date.add_argument("--date", required=True)
    reset = commands.add_parser("reset-link", help="Issue a local-admin single-use recovery link")
    reset.add_argument("--username", required=True)
    reset.add_argument("--base-url", default="http://127.0.0.1:5000")
    options = parser.parse_args()
    try:
        run(options)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
