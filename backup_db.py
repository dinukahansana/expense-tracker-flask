"""Create a verified SQLite backup, optionally in a synced or external folder."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3


APP_DIR = Path(__file__).resolve().parent


def database_path():
    path = Path(os.environ.get("EXPENSE_DB_PATH", APP_DIR / "expenses.db"))
    return (path if path.is_absolute() else APP_DIR / path).resolve()


def backup_database(source=None, destination_dir=None, daily=False):
    source = Path(source or database_path()).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Database does not exist: {source}")
    destination_dir = Path(destination_dir or os.environ.get("EXPENSE_BACKUP_DIR")
                           or source.parent / "backups").resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    if daily:
        existing = sorted(destination_dir.glob(f"{source.stem}-backup-{now:%Y%m%d}T*.sqlite3"))
        if existing:
            try:
                with closing(sqlite3.connect(existing[-1].as_uri() + "?mode=ro", uri=True)) as previous:
                    if previous.execute("PRAGMA quick_check").fetchone()[0] == "ok":
                        return existing[-1]
            except sqlite3.DatabaseError:
                pass
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    destination = destination_dir / f"{source.stem}-backup-{stamp}.sqlite3"
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Source database failed integrity check; backup was not created.")
        try:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("Backup failed integrity check.")
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", help="Backup folder, preferably on an external or synced drive")
    parser.add_argument("--daily", action="store_true", help="Make at most one backup per UTC day")
    args = parser.parse_args()
    print(backup_database(destination_dir=args.destination, daily=args.daily))
