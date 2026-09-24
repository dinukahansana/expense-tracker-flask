# Expense Tracker

Flask and SQLite expense tracker with per-account expenses, filters, charts, CSV export, custom categories, and monthly budgets.

## Setup and run (PowerShell)

```powershell
cd 'D:\D I N U K A\Learning\PYTHON PROJECTS\ExpenseTracker_WEB-APP'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
[Environment]::SetEnvironmentVariable('FLASK_SECRET_KEY', (python -c "import secrets; print(secrets.token_urlsafe(48))"), 'User')
python setup_db.py
python app.py
```

Run the secret-key command only once per Windows user account; if you already set it, skip that line. The app reads the saved Windows user variable even from a terminal opened before it was set. On other systems, configure `FLASK_SECRET_KEY` in the process environment. Save it in your deployment secret store so sessions survive restarts. It must have at least 32 characters. Never commit it. The app refuses to start without it or without a migrated database. The development server runs with debug mode off; use a production WSGI server for deployment.

Environment variables:

| Variable | Purpose |
| --- | --- |
| `FLASK_SECRET_KEY` | Required random secret, at least 32 characters. |
| `EXPENSE_DB_PATH` | Optional database path. Relative paths are resolved from this project directory; default is `expenses.db` here. |
| `FLASK_COOKIE_SECURE` | Set to `1` when serving over HTTPS so session cookies require HTTPS. |

Session cookies are HTTP only and SameSite Lax. Use HTTPS and `FLASK_COOKIE_SECURE=1` in production.

## Existing database migration

Run `python setup_db.py` once before starting this version. It makes a consistent SQLite copy in `backups/` **before** altering an existing database. Migration is transactional and errors are reported. Re-running it is safe. A JSON report next to the backup lists expenses with missing owners, legacy dates, and amounts rounded to cents.

Existing amounts become integer cents. Any existing amount with fractions of a cent is rounded half up and listed in the report. Old expenses have an **unknown date** because the previous schema stored no date. Edit them to add the correct date. Their `created_at` records the migration time because the original creation time is unknown. Expenses whose `user_id` is missing or does not match a current user remain in the database with `user_id=NULL`; an invalid original ID is retained in `legacy_user_id`. They are hidden from every account until an administrator verifies ownership and assigns them deliberately. The migration never guesses an owner.

The live SQLite database and `backups/` are ignored by Git. The preexisting tracked database was removed from the Git index without deleting the local file. Preserve the `backups/` directory separately from source control.

## Backup and restore

Run `python backup_db.py` at any time to create a verified online backup in `backups/`. Keep an off-device copy. To restore, stop the app, back up the current database first, then copy the chosen `.sqlite3` backup over `expenses.db` (or the configured `EXPENSE_DB_PATH`). For example:

```powershell
python backup_db.py
Copy-Item -LiteralPath '.\backups\expenses-backup-YYYYMMDDTHHMMSSZ.sqlite3' -Destination '.\expenses.db' -Force
python setup_db.py
```

Replace the example backup name with the actual one. The restore replaces current data. `setup_db.py` checks and upgrades an older restored schema, making another backup first. Keep the app stopped during the copy.

## Accounts and reports

New passwords need 12–128 characters, including a letter and a number. Login is limited to five failed attempts per username and IP address per 15 minutes. Self-service password reset is disabled until verified email delivery and single-use expiring tokens can be implemented. The old username-only reset route cannot change a password.

The dashboard's search, category, month, and date range filters apply to the table, cards, charts, and CSV export. Pagination affects only the table page; totals and charts cover the whole filtered set. The monthly budget panel shows the chosen month, or the current month when no month is selected, and its spending also respects search, category, and date range filters.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests create separate short-lived SQLite files; they do not use `expenses.db`.
