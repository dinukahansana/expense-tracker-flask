"""Make a consistent online SQLite backup without changing the source database."""

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

APP_DIR = Path(__file__).resolve().parent
source = Path(os.environ.get("EXPENSE_DB_PATH", APP_DIR / "expenses.db"))
if not source.is_absolute():
    source = APP_DIR / source
source = source.resolve()
if not source.is_file():
    raise SystemExit(f"Database does not exist: {source}")

backup_dir = source.parent / "backups"
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
destination = backup_dir / f"{source.stem}-backup-{stamp}.sqlite3"
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
    if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise SystemExit("Source database failed integrity check; backup was not created.")
    with closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise SystemExit("Backup failed integrity check.")
print(destination)
