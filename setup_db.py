"""Run on a fresh install or to migrate a legacy database."""

import os
from pathlib import Path

from db import migrate

if __name__ == "__main__":
    app_dir = Path(__file__).resolve().parent
    path = Path(os.environ.get("EXPENSE_DB_PATH", app_dir / "expenses.db"))
    if not path.is_absolute():
        path = app_dir / path
    print(migrate(path))
