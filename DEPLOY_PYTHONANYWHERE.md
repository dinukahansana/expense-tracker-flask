# Deploy this expense tracker on PythonAnywhere

This guide is for a public multi-user site that keeps your existing accounts and SQLite data. PythonAnywhere's free Beginner account offers one web app, one worker, and 512 MiB of storage, so monitor usage as new users join. New free accounts must renew the web app monthly and cannot schedule automatic tasks. See [current free account limits](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/). Keep a downloaded backup of the database; the free account is not a backup service.

Replace every `YOURNAME`, `YOUR-GITHUB-NAME`, `YOUR-REPO`, and backup filename below with your real values. Use the `.eu.pythonanywhere.com` domain instead if you signed up on PythonAnywhere's EU site.

## 1. Save your code and data separately

On your Windows laptop, first commit and push the source changes to GitHub. The live database is intentionally ignored by Git. Make a fresh verified database backup:

```powershell
python backup_db.py
```

Keep the printed `.sqlite3` file. It contains your accounts, password hashes, and expenses. Do not commit or upload it to a public GitHub repository. Store another copy somewhere safe before transferring it.

## 2. Clone the project on PythonAnywhere

Create a [PythonAnywhere account](https://www.pythonanywhere.com/), then open a **Bash console**. The commands below run on PythonAnywhere, not on your Windows laptop:

```bash
git clone https://github.com/YOUR-GITHUB-NAME/YOUR-REPO.git ~/expense-tracker
cd ~/expense-tracker
mkvirtualenv --python=/usr/bin/python3.13 expense-tracker
pip install -r requirements.txt
```

If the GitHub repository is private, use PythonAnywhere's [code upload instructions](https://help.pythonanywhere.com/pages/UploadingAndDownloadingFiles/) or configure GitHub authentication. Never paste a GitHub token into the project files.

## 3. Restore your existing database

Use PythonAnywhere's **Files** page to upload the backup `.sqlite3` file into `/home/YOURNAME/`, outside the Git checkout. Back in the Bash console:

```bash
cd ~/expense-tracker
mkdir -p ~/expense-data
python restore_db.py ~/YOUR-BACKUP-FILENAME.sqlite3 --target ~/expense-data/expenses.db
python restore_db.py ~/YOUR-BACKUP-FILENAME.sqlite3 --target ~/expense-data/expenses.db --apply
EXPENSE_DB_PATH="$HOME/expense-data/expenses.db" python setup_db.py
```

The first restore command verifies the backup and reports its expense count; the second performs the restore. `setup_db.py` confirms the schema is current. Existing usernames and passwords continue to work. Expenses with no verified owner remain preserved but hidden from accounts.

## 4. Create a private server secret

In the Bash console, create a random secret in your PythonAnywhere home folder, outside Git:

```bash
python -c "import secrets; from pathlib import Path; p=Path.home()/'.expense-tracker-secret'; p.write_text(secrets.token_urlsafe(48)); p.chmod(0o600); print(p)"
```

Keep this file private. Changing it later signs out existing browser sessions but does not change account passwords or expenses.

## 5. Create the web app

In PythonAnywhere's **Web** tab, select **Add a new web app → Manual configuration → Python 3.13**. Set the virtualenv to `/home/YOURNAME/.virtualenvs/expense-tracker`. Open the WSGI configuration file linked on the Web page and replace its sample content with:

```python
import os
import sys
from pathlib import Path

home = Path("/home/YOURNAME")
sys.path.insert(0, str(home / "expense-tracker"))

os.environ["FLASK_SECRET_KEY"] = (home / ".expense-tracker-secret").read_text().strip()
os.environ["FLASK_COOKIE_SECURE"] = "1"
os.environ["EXPENSE_DB_PATH"] = str(home / "expense-data" / "expenses.db")
os.environ["EXPENSE_ALLOW_REGISTRATION"] = "1"
os.environ["EXPENSE_TRUSTED_HOSTS"] = "YOURNAME.pythonanywhere.com"

from app import create_app
application = create_app()
```

This uses PythonAnywhere's production web server, HTTPS cookies, your private database path, and your existing accounts. Registration remains open so new users can create their own accounts. Setting `EXPENSE_ALLOW_REGISTRATION` to `0` would close signup; do not use that setting for this public deployment.

In the Web tab's **Static files** section, map `/static/` to `/home/YOURNAME/expense-tracker/static`. Click **Reload**. Visit `https://YOURNAME.pythonanywhere.com` and sign in with your existing username and password. The `/register` page should show the signup form. Each user's expenses, budgets, categories, and exports are scoped to that account.

Email delivery is not configured yet, so users cannot recover a forgotten password by email. Configure verified email and secure self-service recovery before depending on the site for a broad public audience.

If the page fails, check the **Error log** link in the Web tab. Common causes are a mismatched `YOURNAME`, missing backup restore, or a virtualenv using a different Python version from the Web app. See PythonAnywhere's [Flask setup guide](https://help.pythonanywhere.com/pages/Flask/).

## 6. Back up the online database

New free accounts cannot schedule backup jobs. Make one manually in a Bash console, then **download the resulting `.sqlite3` file** using the Files page and keep a copy away from PythonAnywhere:

```bash
cd ~/expense-tracker
EXPENSE_DB_PATH="$HOME/expense-data/expenses.db" python backup_db.py --destination "$HOME/expense-backups"
```

Do this after important changes and regularly while using the app. Check free account storage usage; old online backup files consume the 512 MiB quota. The Windows scheduled task in this repository only runs on your laptop, not on PythonAnywhere.

For future code updates, pull from GitHub in `~/expense-tracker` and click **Reload** in the Web tab. The database lives in `~/expense-data`, so updating the Git checkout does not replace it. Run `EXPENSE_DB_PATH="$HOME/expense-data/expenses.db" python setup_db.py` before reloading when a future release changes the database schema.
