"""Explicit, backed-up SQLite setup and migration."""

from datetime import datetime, timezone
from contextlib import closing
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import json
import sqlite3

SCHEMA_VERSION = 3
DEFAULT_CATEGORIES = ("Food", "Travel", "Bills", "Shopping")


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _table_exists(connection, name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _backup(connection, path):
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{path.stem}-pre-migration-{stamp}.sqlite3"
    with closing(sqlite3.connect(backup_path)) as destination:
        connection.backup(destination)
        if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"Backup failed integrity check: {backup_path}")
    return backup_path


def _upgrade_v3(connection):
    connection.execute("ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0")
    connection.execute("""CREATE TABLE account_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        purpose TEXT NOT NULL CHECK (purpose = 'password_reset'),
        expires_at INTEGER NOT NULL,
        used_at INTEGER
    )""")
    connection.execute("CREATE INDEX idx_account_tokens_user ON account_tokens(user_id, purpose)")
    connection.execute("""CREATE TABLE category_budgets (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        month TEXT NOT NULL,
        category TEXT NOT NULL,
        amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
        PRIMARY KEY (user_id, month, category)
    )""")
    connection.execute("""CREATE TABLE recurring_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
        day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
        start_month TEXT NOT NULL,
        generate_from_month TEXT NOT NULL,
        end_month TEXT,
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at TEXT NOT NULL
    )""")
    connection.execute("CREATE INDEX idx_recurring_rules_user ON recurring_rules(user_id, active)")
    connection.execute("""CREATE TABLE recurring_occurrences (
        rule_id INTEGER NOT NULL REFERENCES recurring_rules(id) ON DELETE CASCADE,
        occurrence_month TEXT NOT NULL,
        due_date TEXT NOT NULL,
        expense_id INTEGER REFERENCES expenses(id) ON DELETE SET NULL,
        PRIMARY KEY (rule_id, occurrence_month)
    )""")
    connection.execute("""CREATE TABLE import_batches (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        sha256 TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        row_count INTEGER NOT NULL,
        PRIMARY KEY (user_id, sha256)
    )""")
    connection.execute("""CREATE TABLE legacy_assignment_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        expense_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        previous_legacy_user_id INTEGER,
        operator TEXT NOT NULL,
        assigned_at TEXT NOT NULL
    )""")


def migrate(path):
    """Create or upgrade the database. Never modify an existing DB without a backup."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    connection = connect(path)
    backup_path = None
    report = {"backup": None, "orphan_expense_ids": [], "rounded_expense_ids": [],
              "undated_expense_ids": []}
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"Database version {version} is newer than this application")
        if version == SCHEMA_VERSION:
            return report
        if existed:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Database failed integrity check; migration aborted")
            backup_path = _backup(connection, path)
            report["backup"] = str(backup_path)

        if version == 2:
            required = {"users", "expenses", "categories", "budgets", "login_attempts"}
            missing = [name for name in required if not _table_exists(connection, name)]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(expenses)")}
            if missing or not {"amount_cents", "user_id", "expense_date", "created_at"}.issubset(columns):
                raise RuntimeError(f"Incomplete version 2 schema (missing tables: {missing}); migration aborted")
            report["orphan_expense_ids"] = [row[0] for row in connection.execute(
                "SELECT id FROM expenses WHERE user_id IS NULL ORDER BY id")]
            report["undated_expense_ids"] = [row[0] for row in connection.execute(
                "SELECT id FROM expenses WHERE expense_date IS NULL ORDER BY id")]
            connection.execute("BEGIN IMMEDIATE")
            _upgrade_v3(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
            if backup_path:
                backup_path.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            return report

        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )""")
        valid_users = {row[0] for row in connection.execute("SELECT id FROM users")}
        old_expenses = _table_exists(connection, "expenses")
        if old_expenses:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(expenses)")}
            if "amount_cents" in columns and version != SCHEMA_VERSION:
                raise RuntimeError("Unexpected expense schema; inspect backup before migrating")
            rows = connection.execute("SELECT * FROM expenses ORDER BY id").fetchall()
            connection.execute("ALTER TABLE expenses RENAME TO expenses_legacy")
        else:
            rows, columns = [], set()

        connection.execute("""CREATE TABLE expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            legacy_user_id INTEGER,
            expense_date TEXT,
            created_at TEXT NOT NULL
        )""")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for row in rows:
            original_owner = row["user_id"] if "user_id" in columns else None
            owner = original_owner if original_owner in valid_users else None
            if owner is None:
                report["orphan_expense_ids"].append(row["id"])
            try:
                decimal_amount = Decimal(str(row["amount"]))
                if not decimal_amount.is_finite() or decimal_amount <= 0:
                    raise ValueError(f"Invalid amount on expense {row['id']}")
                cents_decimal = decimal_amount * 100
                cents = int(cents_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                if cents_decimal != cents:
                    report["rounded_expense_ids"].append(row["id"])
            except (InvalidOperation, OverflowError) as exc:
                raise ValueError(f"Invalid amount on expense {row['id']}") from exc
            if cents <= 0 or cents > 9_000_000_000_000_000:
                raise ValueError(f"Amount out of range on expense {row['id']}")
            report["undated_expense_ids"].append(row["id"])
            connection.execute("""INSERT INTO expenses
                (id, name, category, amount_cents, user_id, legacy_user_id, expense_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?)""",
                (row["id"], row["name"], row["category"], cents,
                 owner, original_owner if owner is None else None, now))
        if old_expenses:
            connection.execute("DROP TABLE expenses_legacy")
        connection.execute("CREATE INDEX idx_expenses_user_date ON expenses(user_id, expense_date DESC, id DESC)")
        connection.execute("CREATE INDEX idx_expenses_user_category ON expenses(user_id, category)")
        connection.execute("""CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            UNIQUE(user_id, name)
        )""")
        for user_id in valid_users:
            for category in DEFAULT_CATEGORIES:
                connection.execute("INSERT INTO categories(user_id,name) VALUES (?,?)", (user_id, category))
        connection.execute("""INSERT OR IGNORE INTO categories(user_id,name)
            SELECT DISTINCT user_id, category FROM expenses WHERE user_id IS NOT NULL""")
        connection.execute("""CREATE TABLE budgets (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            month TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
            PRIMARY KEY(user_id, month)
        )""")
        connection.execute("""CREATE TABLE login_attempts (
            key TEXT PRIMARY KEY,
            failures INTEGER NOT NULL,
            window_start INTEGER NOT NULL
        )""")
        _upgrade_v3(connection)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
        if backup_path:
            report_path = backup_path.with_suffix(".json")
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
