import csv
from contextlib import closing, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
import hashlib
import sqlite3
import time
import unittest
from types import SimpleNamespace
from uuid import uuid4

from werkzeug.security import check_password_hash, generate_password_hash

from account_admin import run as admin_run
from app import APP_DIR, create_app
from backup_db import backup_database
from db import connect, migrate
from recurring import generate_due
from restore_db import restore_database


PASSWORD = "StrongPassword123"


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.path = APP_DIR / f".test-feature-{uuid4().hex}.sqlite3"
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        self.addCleanup(self.clean_backups)
        self.extra_test_stems = []
        migrate(self.path)
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret-key-of-at-least-32-characters",
                               "DATABASE": str(self.path)})
        self.client = self.app.test_client()
        with closing(connect(self.path)) as db:
            for name in ("alice", "bob"):
                cursor = db.execute("INSERT INTO users(username,password) VALUES (?,?)",
                                    (name, generate_password_hash(PASSWORD)))
                db.execute("INSERT INTO categories(user_id,name) VALUES (?, 'Food')", (cursor.lastrowid,))
                db.execute("INSERT INTO categories(user_id,name) VALUES (?, 'Travel')", (cursor.lastrowid,))
            db.commit()

    def clean_backups(self):
        for stem in [self.path.stem, *self.extra_test_stems]:
            for file in (APP_DIR / "backups").glob(stem + "-*"):
                if file.is_file():
                    file.unlink()

    def token(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def login(self, username="alice", password=PASSWORD):
        response = self.client.post("/login", data={"csrf_token": self.token(),
                                                     "username": username, "password": password})
        self.assertEqual(response.status_code, 302)
        return self.token()

    def test_account_settings_reset_token_and_session_invalidation(self):
        csrf = self.login()
        self.assertEqual(self.client.get("/settings").status_code, 200)
        self.assertEqual(self.client.post("/settings", data={"csrf_token": csrf,
            "current_password": "wrong", "new_password": "EvenStronger456",
            "confirm_password": "EvenStronger456"}).status_code, 400)
        good = self.client.post("/settings", data={"csrf_token": csrf,
            "current_password": PASSWORD, "new_password": "EvenStronger456",
            "confirm_password": "EvenStronger456"})
        self.assertEqual(good.status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertTrue(check_password_hash(db.execute("SELECT password FROM users WHERE id=1").fetchone()[0],
                                                "EvenStronger456"))
        self.client.post("/logout", data={"csrf_token": csrf})
        self.login(password="EvenStronger456")
        self.client.post("/logout", data={"csrf_token": self.token()})
        output = StringIO()
        with redirect_stdout(output):
            admin_run(SimpleNamespace(db=str(self.path), command="reset-link", username="alice",
                                      base_url="http://127.0.0.1:5000"))
        raw_token = output.getvalue().split("/reset-password/")[1].strip()
        with closing(connect(self.path)) as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM account_tokens WHERE token_hash=?",
                                            (hashlib.sha256(raw_token.encode()).hexdigest(),)).fetchone())
        self.assertEqual(self.client.post(f"/reset-password/{raw_token}", data={
            "new_password": "AnotherPassword789", "confirm_password": "AnotherPassword789"}).status_code, 400)
        reset = self.client.post(f"/reset-password/{raw_token}", data={"csrf_token": self.token(),
            "new_password": "AnotherPassword789", "confirm_password": "AnotherPassword789"})
        self.assertEqual(reset.status_code, 302)
        self.assertEqual(self.client.get(f"/reset-password/{raw_token}").status_code, 400)
        self.login(password="AnotherPassword789")
        with closing(connect(self.path)) as db:
            db.execute("UPDATE account_tokens SET used_at=NULL,expires_at=? WHERE user_id=1", (int(time.time()) - 1,))
            db.commit()
        self.assertEqual(self.client.get(f"/reset-password/{raw_token}").status_code, 400)

    def test_new_pages_require_login_and_render(self):
        for path in ("/settings", "/categories/manage", "/recurring", "/import.csv"):
            self.assertEqual(self.client.get(path).status_code, 302)
        csrf = self.login()
        for path in ("/settings", "/categories/manage", "/recurring", "/import.csv"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(csrf, response.get_data(as_text=True))
        self.assertEqual(self.client.post("/recurring/generate").status_code, 400)
        self.assertEqual(self.client.post("/recurring/generate", data={"csrf_token": csrf}).json,
                         {"created": 0})

    def test_password_change_rate_limit(self):
        csrf = self.login()
        bad = {"csrf_token": csrf, "current_password": "wrong",
               "new_password": "EvenStronger456", "confirm_password": "EvenStronger456"}
        for _ in range(5):
            self.assertEqual(self.client.post("/settings", data=bad).status_code, 400)
        good = dict(bad, current_password=PASSWORD)
        self.assertEqual(self.client.post("/settings", data=good).status_code, 429)
        with closing(connect(self.path)) as db:
            self.assertTrue(check_password_hash(db.execute("SELECT password FROM users WHERE id=1").fetchone()[0], PASSWORD))

    def test_admin_recovery_and_orphan_assignment(self):
        with closing(connect(self.path)) as db:
            db.execute("""INSERT INTO expenses(name,category,amount_cents,user_id,legacy_user_id,created_at)
                VALUES ('Old lunch','Food',199,NULL,44,'2020-01-01')""")
            db.commit()
        output = StringIO()
        with redirect_stdout(output):
            admin_run(SimpleNamespace(db=str(self.path), command="list-orphans"))
        self.assertIn("Old lunch", output.getvalue())
        output = StringIO()
        with redirect_stdout(output):
            admin_run(SimpleNamespace(db=str(self.path), command="list-undated"))
        self.assertIn("owner unassigned", output.getvalue())
        with self.assertRaises(ValueError):
            admin_run(SimpleNamespace(db=str(self.path), command="assign-expense", verified=False,
                username="alice", expense_id=1, date="2025-01-01"))
        with redirect_stdout(StringIO()):
            admin_run(SimpleNamespace(db=str(self.path), command="assign-expense", verified=True,
                username="alice", expense_id=1, date="2025-01-01"))
        with closing(connect(self.path)) as db:
            row = db.execute("SELECT user_id,expense_date FROM expenses WHERE id=1").fetchone()
            self.assertEqual(tuple(row), (1, "2025-01-01"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM legacy_assignment_audit").fetchone()[0], 1)
        self.login("bob")
        self.assertEqual(self.client.get("/").get_data(as_text=True).find("Old lunch"), -1)

    def test_category_merge_rename_and_safe_delete(self):
        csrf = self.login()
        self.client.post("/add", data={"csrf_token": csrf, "name": "Trip", "category": "Travel",
            "amount": "10.00", "expense_date": "2026-01-01"})
        self.client.post("/budget/category", data={"csrf_token": csrf, "month": "2026-01",
            "category": "Travel", "amount": "20.00"})
        self.client.post("/budget/category", data={"csrf_token": csrf, "month": "2026-01",
            "category": "Food", "amount": "30.00"})
        self.assertEqual(self.client.post("/categories/2/merge", data={"csrf_token": csrf,
            "target_id": 1}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT category FROM expenses WHERE user_id=1").fetchone()[0], "Food")
            self.assertEqual(db.execute("SELECT amount_cents FROM category_budgets WHERE user_id=1").fetchone()[0], 5000)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM categories WHERE user_id=2").fetchone()[0], 2)
        self.assertEqual(self.client.post("/categories/1/rename", data={"csrf_token": csrf,
            "name": "Dining"}).status_code, 302)
        self.assertEqual(self.client.post("/categories/1/delete", data={"csrf_token": csrf}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT name FROM categories WHERE id=1").fetchone()[0], "Dining")
            self.assertEqual(db.execute("SELECT category FROM category_budgets WHERE user_id=1").fetchone()[0], "Dining")
        self.assertEqual(self.client.post("/categories/3/delete", data={"csrf_token": csrf}).status_code, 404)

    def test_full_month_budget_and_category_alert_ignore_search_filter(self):
        csrf = self.login()
        self.client.post("/add", data={"csrf_token": csrf, "name": "Lunch", "category": "Food",
            "amount": "85.00", "expense_date": "2026-01-15"})
        self.client.post("/budget", data={"csrf_token": csrf, "month": "2026-01", "amount": "100.00"})
        self.client.post("/budget/category", data={"csrf_token": csrf, "month": "2026-01",
            "category": "Food", "amount": "100.00"})
        page = self.client.get("/?month=2026-01&search=Nothing").get_data(as_text=True)
        self.assertIn("No expenses found", page)
        self.assertIn("Spent: <strong>Rs. 85.00</strong> of Rs. 100.00", page)
        self.assertIn("You are close to your monthly target", page)
        self.assertIn("Food target is nearly used", page)
        self.assertEqual(self.client.post("/budget/category/reset", data={"csrf_token": csrf,
            "month": "2026-01", "category": "Food"}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM category_budgets WHERE user_id=1").fetchone()[0], 0)

    def test_recurring_due_idempotent_month_end_and_owner(self):
        csrf = self.login()
        month = date.today().strftime("%Y-%m")
        start = "2026-01"
        form = {"csrf_token": csrf, "name": "Internet", "category": "Food", "amount": "19.99",
                "day_of_month": "31", "start_month": start, "end_month": "2026-03"}
        self.assertEqual(self.client.post("/recurring", data=form).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(generate_due(db, 1, date(2026, 2, 28)), 2)
            self.assertEqual(generate_due(db, 1, date(2026, 2, 28)), 0)
            self.assertEqual(db.execute("SELECT expense_date FROM expenses WHERE user_id=1 ORDER BY expense_date DESC LIMIT 1").fetchone()[0], "2026-02-28")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses WHERE user_id=2").fetchone()[0], 0)
        self.assertEqual(self.client.post("/recurring/1/toggle", data={"csrf_token": csrf}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(generate_due(db, 1, date(2026, 3, 31)), 0)
        self.assertEqual(self.client.post("/recurring/1/toggle", data={"csrf_token": csrf}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT generate_from_month FROM recurring_rules WHERE id=1").fetchone()[0],
                             date.today().strftime("%Y-%m"))
            self.assertEqual(generate_due(db, 1, date(2026, 3, 31)), 0)
        self.assertEqual(self.client.post("/recurring/1/delete", data={"csrf_token": csrf}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses WHERE user_id=1").fetchone()[0], 2)
        self.client.post("/logout", data={"csrf_token": csrf})
        csrf = self.login("bob")
        self.assertEqual(self.client.post("/recurring/1/toggle", data={"csrf_token": csrf}).status_code, 404)

    def test_csv_roundtrip_rejects_duplicate_and_invalid(self):
        csrf = self.login()
        self.client.post("/add", data={"csrf_token": csrf, "name": "=SUM(1,2)",
            "category": "Food", "amount": "3.45", "expense_date": "2026-01-15"})
        exported = self.client.get("/export.csv").data
        self.assertEqual(list(csv.reader(StringIO(exported.decode())))[1][1], "'=SUM(1,2)")
        self.client.post("/logout", data={"csrf_token": csrf})
        csrf = self.login("bob")
        # Werkzeug expects bytes for uploaded files.
        from io import BytesIO
        imported = self.client.post("/import.csv", data={"csrf_token": csrf,
            "file": (BytesIO(exported), "expenses.csv")}, content_type="multipart/form-data")
        self.assertEqual(imported.status_code, 302)
        duplicate = self.client.post("/import.csv", data={"csrf_token": csrf,
            "file": (BytesIO(exported), "expenses.csv")}, content_type="multipart/form-data")
        self.assertEqual(duplicate.status_code, 400)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT name FROM expenses WHERE user_id=2").fetchone()[0], "=SUM(1,2)")
        bad = exported + b"2026-01-16,Bad,Food,3.456,2026-01-16T00:00:00+00:00\r\n"
        self.assertEqual(self.client.post("/import.csv", data={"csrf_token": csrf,
            "file": (BytesIO(bad), "expenses.csv")}, content_type="multipart/form-data").status_code, 400)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses WHERE user_id=2").fetchone()[0], 1)

    def test_verified_backup_restore_and_v2_upgrade(self):
        v2 = APP_DIR / f".test-v2-{uuid4().hex}.sqlite3"
        self.extra_test_stems.append(v2.stem)
        self.addCleanup(lambda: v2.unlink(missing_ok=True))
        with closing(sqlite3.connect(v2)) as db:
            db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, password TEXT)")
            db.execute("CREATE TABLE expenses(id INTEGER PRIMARY KEY, name TEXT, category TEXT, amount_cents INTEGER, user_id INTEGER, legacy_user_id INTEGER, expense_date TEXT, created_at TEXT)")
            db.execute("CREATE TABLE categories(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT)")
            db.execute("CREATE TABLE budgets(user_id INTEGER, month TEXT, amount_cents INTEGER)")
            db.execute("CREATE TABLE login_attempts(key TEXT, failures INTEGER, window_start INTEGER)")
            db.execute("INSERT INTO users VALUES (1,'alice','hash')")
            db.execute("INSERT INTO expenses VALUES (1,'Old','Food',1234,NULL,99,NULL,'2020-01-01')")
            db.execute("INSERT INTO categories VALUES (1,1,'Food')")
            db.execute("INSERT INTO budgets VALUES (1,'2026-01',5000)")
            db.execute("PRAGMA user_version=2")
            db.commit()
        report = migrate(v2)
        self.assertTrue(Path(report["backup"]).is_file())
        with closing(connect(v2)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            row = db.execute("SELECT user_id,amount_cents FROM expenses").fetchone()
            self.assertIsNone(row["user_id"])
            self.assertEqual(row["amount_cents"], 1234)
            self.assertEqual(db.execute("SELECT amount_cents FROM budgets").fetchone()[0], 5000)
        saved = backup_database(self.path)
        self.assertFalse(restore_database(saved, self.path)["applied"])
        with closing(connect(self.path)) as db:
            db.execute("INSERT INTO expenses(name,category,amount_cents,user_id,expense_date,created_at) VALUES ('New','Food',100,1,'2026-01-01','now')")
            db.commit()
        restored = restore_database(saved, self.path, apply=True)
        self.assertTrue(Path(restored["previous_backup"]).is_file())
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses").fetchone()[0], 0)
