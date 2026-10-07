"""Verify and restore a SQLite backup after preserving the current database."""

import argparse
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from backup_db import backup_database, database_path
from db import SCHEMA_VERSION


def restore_database(source, target=None, apply=False):
    source = Path(source).resolve()
    target = Path(target or database_path()).resolve()
    if not source.is_file() or source == target:
        raise ValueError("Choose an existing backup different from the live database.")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Backup failed SQLite integrity check.")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError(f"Backup schema version {version} is newer than this app.")
        count = db.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    if not apply:
        return {"backup": str(source), "expenses": count, "schema_version": version,
                "target": str(target), "applied": False}
    if any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm")):
        raise RuntimeError("SQLite WAL files are present. Stop the app and checkpoint the database before restoring.")
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = backup_database(target) if target.is_file() else None
    temporary = target.parent / f".restore-{uuid4().hex}.sqlite3"
    try:
        shutil.copy2(source, temporary)
        with closing(sqlite3.connect(temporary)) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Copied database failed integrity check.")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"backup": str(source), "expenses": count, "schema_version": version,
            "target": str(target), "previous_backup": str(previous) if previous else None,
            "applied": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", help="SQLite backup to restore")
    parser.add_argument("--target", help="Override the configured live database path")
    parser.add_argument("--apply", action="store_true", help="Actually replace the target; stop the app first")
    args = parser.parse_args()
    print(restore_database(args.backup, args.target, args.apply))
