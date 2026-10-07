# Expense Tracker

Flask and SQLite expense tracker with per-account expenses, filters, charts, CSV import/export, category management, monthly budgets, and recurring bills.

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
| `EXPENSE_BACKUP_DIR` | Optional backup folder, ideally on an external or synced drive. |

Session cookies are HTTP only and SameSite Lax. Use HTTPS and `FLASK_COOKIE_SECURE=1` in production.

## Existing database migration

Run `python setup_db.py` once before starting this version. It makes a consistent SQLite copy in `backups/` **before** altering an existing database. Migration is transactional and errors are reported. Re-running it is safe. A JSON report next to the backup lists expenses with missing owners, legacy dates, and amounts rounded to cents.

Existing amounts become integer cents. Any existing amount with fractions of a cent is rounded half up and listed in the report. Old expenses have an **unknown date** because the previous schema stored no date. Their `created_at` records the migration time because the original creation time is unknown. Expenses whose `user_id` is missing or does not match a current user remain in the database with `user_id=NULL`; an invalid original ID is retained in `legacy_user_id`. They are hidden from every account until an administrator verifies ownership and assigns them deliberately. The migration never guesses an owner.

### Review old records

Six expenses in the current local database have no verified owner, and 16 have no known expense date. Review original records before changing them:

```powershell
py account_admin.py list-orphans
py account_admin.py list-undated
py account_admin.py assign-expense --expense-id 7 --username YOUR_USERNAME --verified --date 2026-01-15
py account_admin.py set-date --expense-id 8 --date 2026-01-15
```

Replace sample IDs, user, and dates with verified values. `assign-expense` refuses to run without `--verified`, makes a fresh backup, and records the assignment in an audit table. `set-date` also makes a backup. Signed-in users can edit the dates of their own records on the dashboard.

The live SQLite database and `backups/` are ignored by Git. The preexisting tracked database was removed from the Git index without deleting the local file. Preserve the `backups/` directory separately from source control.

## Backup and restore

Run `py backup_db.py` at any time to create a verified online backup in `backups/`. Once you choose an external or synced folder, use `--destination` or `EXPENSE_BACKUP_DIR`:

```powershell
py backup_db.py --destination 'E:\ExpenseTrackerBackups'
py restore_db.py 'E:\ExpenseTrackerBackups\expenses-backup-YYYYMMDDTHHMMSSZ.sqlite3'
```

The restore command above only checks the backup and shows what it contains. To apply it, **stop the app**, rerun the command with `--apply`, then run `py setup_db.py`. The restore tool verifies the backup and saves the current database before replacing it. Replace the sample filename with the actual one. Restoring replaces newer data with the selected backup.

To schedule daily backups on Windows after the external/synced folder is ready:

```powershell
.\install_backup_task.ps1 -Destination 'E:\ExpenseTrackerBackups' -At '20:00'
```

The task runs `scheduled_backup.ps1`, which creates at most one verified backup per UTC day. The destination must exist, remain available, and be writable by your Windows user. Run `Get-ScheduledTask -TaskName 'ExpenseTracker Daily Backup'` to inspect it. The task has not been installed automatically because no destination has been chosen yet. If using a custom database path, add `-Database 'C:\path\to\expenses.db'` when installing. Backups contain account data and password hashes; protect the backup folder.

## Accounts and reports

New passwords need 12–128 characters, including a letter and a number. Login is limited to five failed attempts per username and IP address per 15 minutes. Signed-in users can change passwords under **Settings**; other sessions are signed out. Self-service password reset stays disabled while email delivery is unconfigured. A trusted local administrator can issue a 15-minute, single-use reset link on the database computer:

```powershell
py account_admin.py reset-link --username YOUR_USERNAME
```

Open the printed local link promptly. Do not share it; it grants access to reset that account. The old username-only web form cannot change a password.

The dashboard's search, category, month, and date range filters apply to the table, cards, charts, and CSV export. Pagination affects only the table page; totals and charts cover the whole filtered set. The budget panel always compares its selected **full month** of spending against the monthly target, regardless of search or category filters. Category targets show their own full-month spending. Targets turn yellow at 50% and red at 80%, and show a warning when near or over budget. Manage categories from the Add Expense page: rename changes linked expenses, bills, and targets; merge combines target amounts; removal is allowed only for unused categories.

**Recurring bills:** create, edit, pause, resume, or remove rules on the Recurring page. When you open the dashboard, it sends a protected request to create due expenses. It generates one expense per rule per month, uses the last day for months shorter than day 29–31, and does not recreate a manually deleted occurrence. Existing expenses remain when a rule is changed or removed. Paused months are skipped when resumed. The app must be opened for due bills to be generated; it does not run as a background service.

**CSV import:** export from the dashboard, then choose Import CSV to add the rows to the signed-in account. An import must use this app's five-column export format, have at most 2,000 rows and 1 MB, and pass validation as a whole. The exact same file cannot be imported twice into one account. Importing a modified copy or a different export may duplicate records; make a database backup first. Blank legacy dates are preserved. CSV is for expense rows only; use a SQLite backup to preserve accounts, budgets, categories, and recurring rules.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests create separate short-lived SQLite files; they do not use `expenses.db`.
