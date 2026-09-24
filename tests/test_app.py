import csv
from contextlib import closing
import io
import sqlite3
import unittest
from pathlib import Path
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app import APP_DIR, create_app
from db import connect, migrate


PASSWORD = "StrongPassword123"


class ExpenseTrackerTests(unittest.TestCase):
    def setUp(self):
        self.path = APP_DIR / f".test-{uuid4().hex}.sqlite3"
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))
        migrate(self.path)
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret-key-of-at-least-32-characters", "DATABASE": str(self.path)})
        self.client = self.app.test_client()
        with closing(connect(self.path)) as db:
            for name in ("alice", "bob"):
                cursor = db.execute("INSERT INTO users(username,password) VALUES (?,?)",
                                    (name, generate_password_hash(PASSWORD)))
                for category in ("Food", "Travel", "Bills", "Shopping"):
                    db.execute("INSERT INTO categories(user_id,name) VALUES (?,?)", (cursor.lastrowid, category))
            db.commit()

    def token(self):
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            return sess["csrf_token"]

    def login(self, username="alice"):
        response = self.client.post("/login", data={"csrf_token": self.token(),
            "username": username, "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        return self.token()

    def add(self, token, name="Lunch", category="Food", amount="12.34", expense_date="2026-09-01"):
        return self.client.post("/add", data={"csrf_token": token, "name": name,
            "category": category, "amount": amount, "expense_date": expense_date})

    def test_fresh_schema(self):
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_list(expenses)").fetchone()[2], "users")
            self.assertTrue({"users", "expenses", "categories", "budgets"}.issubset({
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}))

    def test_csrf_and_authentication(self):
        self.assertEqual(self.client.get("/add").status_code, 302)
        self.assertEqual(self.client.get("/export.csv").status_code, 302)
        self.assertEqual(self.client.post("/login", data={"username": "alice", "password": PASSWORD}).status_code, 400)
        token = self.login()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/add", data={"name": "bad"}).status_code, 400)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": token}).status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_ownership_for_read_write_delete(self):
        token = self.login("alice")
        self.add(token)
        with closing(connect(self.path)) as db:
            expense_id = db.execute("SELECT id FROM expenses").fetchone()[0]
        self.client.post("/logout", data={"csrf_token": token})
        token = self.login("bob")
        self.assertEqual(self.client.get(f"/edit/{expense_id}").status_code, 404)
        self.assertEqual(self.client.post(f"/edit/{expense_id}", data={"csrf_token": token}).status_code, 404)
        self.assertEqual(self.client.post(f"/delete/{expense_id}", data={"csrf_token": token}).status_code, 404)
        self.assertNotIn("Lunch", self.client.get("/").get_data(as_text=True))
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses").fetchone()[0], 1)

    def test_crud_validation_and_money(self):
        token = self.login()
        bad = self.add(token, amount="1.999", expense_date="2026-02-30")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("1.999", bad.get_data(as_text=True))
        self.assertIn("valid expense date", bad.get_data(as_text=True))
        self.assertEqual(self.add(token, amount="0").status_code, 400)
        self.assertEqual(self.add(token, category="Other").status_code, 400)
        self.assertEqual(self.add(token).status_code, 302)
        with closing(connect(self.path)) as db:
            row = db.execute("SELECT * FROM expenses").fetchone()
            self.assertEqual(row["amount_cents"], 1234)
            self.assertEqual(row["expense_date"], "2026-09-01")
            self.assertTrue(row["created_at"])
            expense_id = row["id"]
        response = self.client.post(f"/edit/{expense_id}", data={"csrf_token": token,
            "name": "Dinner", "category": "Food", "amount": "19.50", "expense_date": "2026-09-02"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("Expense updated", self.client.get("/").get_data(as_text=True))
        self.assertEqual(self.client.post(f"/delete/{expense_id}", data={"csrf_token": token}).status_code, 302)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses").fetchone()[0], 0)

    def test_filters_reports_budget_export_and_category(self):
        token = self.login()
        self.add(token, "Lunch", "Food", "10.20", "2026-09-01")
        self.add(token, "Train", "Travel", "5.10", "2026-08-01")
        self.add(token, "Dinner", "Food", "3.00", "2026-09-02")
        response = self.client.get("/?month=2026-09&category=Food&search=Lunch")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Rs. 10.20", html)
        self.assertIn("Selected period", html)
        self.assertIn('id="barChart"', html)
        self.assertIn('id="trendChart"', html)
        self.assertNotIn("Train", html)
        self.assertNotIn("Dinner", html)
        rows = list(csv.reader(io.StringIO(self.client.get(
            "/export.csv?month=2026-09&category=Food&search=Lunch").get_data(as_text=True))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][3], "10.20")
        budget_response = self.client.post("/budget?search=Lunch&category=Food", data={"csrf_token": token,
            "month": "2026-09", "amount": "20.00"})
        self.assertEqual(budget_response.status_code, 302)
        self.assertIn("search=Lunch", budget_response.headers["Location"])
        self.assertIn("Rs. 20.00", self.client.get("/?month=2026-09").get_data(as_text=True))
        self.assertEqual(self.client.post("/categories", data={"csrf_token": token,
            "name": "Medical"}).status_code, 302)
        self.assertEqual(self.add(token, "Medicine", "Medical").status_code, 302)

    def test_budget_can_be_changed_and_reset_for_one_user_and_month(self):
        token = self.login("alice")
        self.add(token, "Lunch", "Food", "10.20", "2026-09-01")
        self.assertEqual(self.client.post("/budget/reset", data={"month": "2026-09"}).status_code, 400)
        for amount in ("20.00", "30.00"):
            response = self.client.post("/budget", data={"csrf_token": token,
                "month": "2026-09", "amount": amount})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.post("/budget", data={"csrf_token": token,
            "month": "2026-08", "amount": "15.00"}).status_code, 302)
        self.assertIn("of Rs. 30.00", self.client.get("/?month=2026-09").get_data(as_text=True))
        self.assertIn("Update Target", self.client.get("/?month=2026-09").get_data(as_text=True))
        self.assertIn("Reset Target", self.client.get("/?month=2026-09").get_data(as_text=True))

        self.client.post("/logout", data={"csrf_token": token})
        token = self.login("bob")
        self.client.post("/budget", data={"csrf_token": token,
            "month": "2026-09", "amount": "40.00"})
        self.client.post("/logout", data={"csrf_token": token})
        token = self.login("alice")
        response = self.client.post("/budget/reset?search=Lunch", data={"csrf_token": token,
            "month": "2026-09"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("search=Lunch", response.headers["Location"])
        self.assertIn("month=2026-09", response.headers["Location"])
        html = self.client.get("/?month=2026-09").get_data(as_text=True)
        self.assertIn("Spent: <strong>Rs. 10.20</strong>", html)
        self.assertIn("no target set", html)
        self.assertNotIn("Reset Target", html)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM expenses").fetchone()[0], 1)
            budgets = db.execute("SELECT u.username, b.month, b.amount_cents FROM budgets b "
                "JOIN users u ON u.id=b.user_id ORDER BY u.username, b.month").fetchall()
            self.assertEqual([(row["username"], row["month"], row["amount_cents"])
                for row in budgets], [("alice", "2026-08", 1500), ("bob", "2026-09", 4000)])

    def test_budget_progress_changes_color_as_spending_grows(self):
        token = self.login()
        self.client.post("/budget", data={"csrf_token": token,
            "month": "2026-09", "amount": "100.00"})

        def dashboard():
            return self.client.get("/?month=2026-09").get_data(as_text=True)

        self.add(token, "First", "Food", "25.00", "2026-09-01")
        self.assertIn("budget-progress-low", dashboard())
        self.add(token, "Second", "Food", "25.00", "2026-09-02")
        self.assertIn("budget-progress-mid", dashboard())
        self.add(token, "Third", "Food", "30.00", "2026-09-03")
        self.assertIn("budget-progress-high", dashboard())
        self.add(token, "Fourth", "Food", "30.00", "2026-09-04")
        self.assertIn('max="10000" value="10000"', dashboard())
        self.assertIn("budget-progress-high", dashboard())

    def test_date_range_sort_pagination_and_filtered_totals(self):
        token = self.login()
        for day in range(1, 23):
            self.add(token, f"Item {day:02d}", "Food", "1.00", f"2026-09-{day:02d}")
        first = self.client.get("/?month=2026-09")
        self.assertEqual(first.status_code, 200)
        html = first.get_data(as_text=True)
        self.assertIn("Page 1 of 2", html)
        self.assertIn("Rs. 22.00", html)
        self.assertIn("Item 22", html)
        self.assertNotIn("Item 01", html)
        second = self.client.get("/?month=2026-09&page=2")
        self.assertIn("Item 01", second.get_data(as_text=True))
        oldest = self.client.get("/?month=2026-09&sort=date_asc")
        self.assertIn("Item 01", oldest.get_data(as_text=True))
        ranged = self.client.get("/?date_from=2026-09-20&date_to=2026-09-22")
        self.assertIn("Rs. 3.00", ranged.get_data(as_text=True))
        self.assertNotIn("Item 19", ranged.get_data(as_text=True))

    def test_password_reset_disabled_and_rate_limit(self):
        token = self.token()
        self.assertIn("unavailable", self.client.get("/forgot-password").get_data(as_text=True))
        self.assertEqual(self.client.post("/forgot-password", data={"csrf_token": token,
            "username": "alice", "new_password": "ChangedPassword123"}).status_code, 403)
        for _ in range(5):
            self.assertEqual(self.client.post("/login", data={"csrf_token": token,
                "username": "alice", "password": "bad"}).status_code, 401)
        self.assertEqual(self.client.post("/login", data={"csrf_token": token,
            "username": "alice", "password": PASSWORD}).status_code, 429)
        with closing(connect(self.path)) as db:
            self.assertTrue(db.execute("SELECT password FROM users WHERE username='alice'").fetchone()[0])

    def test_registration_password_rule(self):
        token = self.token()
        self.assertEqual(self.client.post("/register", data={"csrf_token": token,
            "username": "newuser", "password": "short"}).status_code, 400)
        self.assertEqual(self.client.post("/register", data={"csrf_token": token,
            "username": "newuser", "password": PASSWORD}).status_code, 302)


class MigrationTests(unittest.TestCase):
    def test_legacy_backup_orphans_and_exact_cents(self):
        path = APP_DIR / f".test-legacy-{uuid4().hex}.sqlite3"
        try:
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)")
                db.execute("INSERT INTO users VALUES (1,'owner','hash')")
                db.execute("CREATE TABLE expenses(id INTEGER PRIMARY KEY, name TEXT, category TEXT, amount REAL, user_id INTERGER)")
                db.execute("INSERT INTO expenses VALUES (1,'Owned','Food',1.23,1)")
                db.execute("INSERT INTO expenses VALUES (2,'Orphan','Travel',2.34,99)")
                db.commit()
            report = migrate(path)
            self.assertTrue(Path(report["backup"]).exists())
            self.assertEqual(report["orphan_expense_ids"], [2])
            with closing(connect(path)) as db:
                self.assertEqual(db.execute("SELECT amount_cents FROM expenses WHERE id=1").fetchone()[0], 123)
                self.assertIsNone(db.execute("SELECT expense_date FROM expenses WHERE id=1").fetchone()[0])
                self.assertEqual(tuple(db.execute("SELECT user_id,legacy_user_id FROM expenses WHERE id=2").fetchone()), (None, 99))
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            with closing(sqlite3.connect(report["backup"])) as backup:
                self.assertEqual(backup.execute("SELECT COUNT(*) FROM expenses").fetchone()[0], 2)
            self.assertIsNone(migrate(path)["backup"])
        finally:
            path.unlink(missing_ok=True)
            if 'report' in locals() and report["backup"]:
                Path(report["backup"]).unlink(missing_ok=True)
                Path(report["backup"]).with_suffix(".json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
