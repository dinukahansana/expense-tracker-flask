"""Expense Tracker Flask application. Run setup_db.py before starting."""

import csv
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import time

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   Response, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from db import DEFAULT_CATEGORIES, SCHEMA_VERSION, connect


APP_DIR = Path(__file__).resolve().parent
AMOUNT_PATTERN = re.compile(r"\d+(?:\.\d{1,2})?\Z")
SORTS = {
    "date_desc": "expense_date DESC, id DESC",
    "date_asc": "expense_date ASC, id ASC",
    "amount_desc": "amount_cents DESC, id DESC",
    "amount_asc": "amount_cents ASC, id ASC",
    "name": "name COLLATE NOCASE ASC, id DESC",
}
PAGE_SIZE = 20


def money(cents):
    return f"{cents // 100:,}.{cents % 100:02d}"


def static_version(filename):
    return (APP_DIR / "static" / filename).stat().st_mtime_ns


def parse_amount(raw):
    raw = (raw or "").strip()
    if len(raw) > 20 or not AMOUNT_PATTERN.fullmatch(raw):
        raise ValueError("Enter a positive amount with at most two decimal places.")
    cents = int(Decimal(raw) * 100)
    if cents <= 0 or cents > 9_000_000_000_000_000:
        raise ValueError("Enter a positive amount within the supported range.")
    return cents


def valid_date(raw):
    try:
        value = date.fromisoformat(raw)
        if value.isoformat() != raw:
            raise ValueError
        return value
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid expense date.") from exc


def valid_month(raw):
    try:
        value = date.fromisoformat(raw + "-01")
        if value.strftime("%Y-%m") != raw:
            raise ValueError
        return value
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid month.") from exc


def password_error(password):
    if not 12 <= len(password) <= 128:
        return "Password must be 12 to 128 characters."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Password must contain a letter and a number."
    return None


def get_db():
    if "db" not in g:
        g.db = connect(g.app_db_path)
    return g.db


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        if not get_db().execute("SELECT 1 FROM users WHERE id=?", (session["user_id"],)).fetchone():
            session.clear()
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def categories_for(user_id):
    return [row[0] for row in get_db().execute(
        "SELECT name FROM categories WHERE user_id=? ORDER BY name COLLATE NOCASE", (user_id,))]


def expense_form_data(user_id):
    values = {key: request.form.get(key, "").strip() for key in
              ("name", "category", "amount", "expense_date")}
    errors = {}
    if not values["name"] or len(values["name"]) > 120:
        errors["name"] = "Enter a name of 1 to 120 characters."
    if values["category"] not in categories_for(user_id):
        errors["category"] = "Choose one of your categories."
    try:
        cents = parse_amount(values["amount"])
    except ValueError as exc:
        errors["amount"] = str(exc)
        cents = None
    try:
        valid_date(values["expense_date"])
    except ValueError as exc:
        errors["expense_date"] = str(exc)
    return values, errors, cents


def filters_from_request(user_id):
    values = {key: request.args.get(key, "").strip() for key in
              ("search", "category", "month", "date_from", "date_to", "sort")}
    if len(values["search"]) > 120:
        abort(400, "Search is too long.")
    if values["category"] and values["category"] not in categories_for(user_id):
        abort(400, "Unknown category.")
    if values["month"]:
        try:
            valid_month(values["month"])
        except ValueError:
            abort(400, "Invalid month.")
    for key in ("date_from", "date_to"):
        if values[key]:
            try:
                valid_date(values[key])
            except ValueError:
                abort(400, "Invalid date range.")
    if values["date_from"] and values["date_to"] and values["date_from"] > values["date_to"]:
        abort(400, "Start date must precede end date.")
    values["sort"] = values["sort"] if values["sort"] in SORTS else "date_desc"
    where = ["user_id = ?"]
    params = [user_id]
    if values["search"]:
        where.append("name LIKE ? ESCAPE '\\'")
        escaped = values["search"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"%{escaped}%")
    if values["category"]:
        where.append("category = ?")
        params.append(values["category"])
    if values["month"]:
        where.append("substr(expense_date, 1, 7) = ?")
        params.append(values["month"])
    if values["date_from"]:
        where.append("expense_date >= ?")
        params.append(values["date_from"])
    if values["date_to"]:
        where.append("expense_date <= ?")
        params.append(values["date_to"])
    return values, " AND ".join(where), params


def expense_or_404(expense_id, user_id):
    row = get_db().execute("SELECT * FROM expenses WHERE id=? AND user_id=?",
                           (expense_id, user_id)).fetchone()
    if row is None:
        abort(404)
    return row


def _login_key(username):
    ip = request.remote_addr or "unknown"
    return hashlib.sha256(f"{ip}|{username.casefold()}".encode()).hexdigest()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY"),
        DATABASE=os.environ.get("EXPENSE_DB_PATH", str(APP_DIR / "expenses.db")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FLASK_COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=16 * 1024,
        TEMPLATES_AUTO_RELOAD=True,
    )
    if test_config:
        app.config.update(test_config)
    secret = app.config["SECRET_KEY"]
    if not secret or len(secret) < 32:
        raise RuntimeError("Set FLASK_SECRET_KEY to a random value of at least 32 characters.")
    db_path = Path(app.config["DATABASE"])
    db_path = (db_path if db_path.is_absolute() else APP_DIR / db_path).resolve()
    if not db_path.exists():
        raise RuntimeError(f"Database missing: {db_path}. Run python setup_db.py first.")
    with closing(connect(db_path)) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise RuntimeError("Database migration required. Run python setup_db.py first.")

    @app.before_request
    def before_request():
        g.app_db_path = db_path
        protected = {"index", "add", "edit", "delete", "add_category", "budget", "reset_budget", "export_csv", "logout"}
        if request.endpoint in protected and "user_id" not in session:
            return redirect(url_for("login"))
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            submitted = request.form.get("csrf_token", "")
            stored = session.get("csrf_token", "")
            if not stored or not secrets.compare_digest(submitted, stored):
                abort(400, "Invalid CSRF token. Refresh the page and try again.")

    @app.teardown_appcontext
    def close_db(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def template_helpers():
        return {"csrf_token": csrf_token, "money": money,
                "static_version": static_version}

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.route("/")
    @login_required
    def index():
        user_id = session["user_id"]
        values, where, params = filters_from_request(user_id)
        db = get_db()
        summary = db.execute(f"""SELECT COUNT(*) AS count, COALESCE(SUM(amount_cents),0) AS total,
            COALESCE(MAX(amount_cents),0) AS highest, COUNT(DISTINCT category) AS category_count
            FROM expenses WHERE {where}""", params).fetchone()
        category_rows = db.execute(f"""SELECT category, SUM(amount_cents) AS cents
            FROM expenses WHERE {where} GROUP BY category ORDER BY cents DESC""", params).fetchall()
        trend_rows = db.execute(f"""SELECT COALESCE(substr(expense_date,1,7),'Undated') AS month,
            SUM(amount_cents) AS cents FROM expenses WHERE {where}
            GROUP BY month ORDER BY month""", params).fetchall()
        try:
            page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            abort(400, "Invalid page.")
        page_count = max(1, (summary["count"] + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, page_count)
        expenses = db.execute(f"""SELECT * FROM expenses WHERE {where}
            ORDER BY {SORTS[values['sort']]} LIMIT ? OFFSET ?""",
            [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE]).fetchall()
        budget_month = values["month"] or date.today().strftime("%Y-%m")
        budget_row = db.execute("SELECT amount_cents FROM budgets WHERE user_id=? AND month=?",
                                (user_id, budget_month)).fetchone()
        budget_where = where if values["month"] else where + " AND substr(expense_date,1,7)=?"
        budget_params = params if values["month"] else [*params, budget_month]
        budget_spent = db.execute(f"SELECT COALESCE(SUM(amount_cents),0) FROM expenses WHERE {budget_where}",
                                  budget_params).fetchone()[0]
        budget_tone = None
        if budget_row:
            budget_amount = budget_row["amount_cents"]
            if budget_spent * 100 >= budget_amount * 80:
                budget_tone = "high"
            elif budget_spent * 100 >= budget_amount * 50:
                budget_tone = "mid"
            else:
                budget_tone = "low"
        period_parts = []
        if values["month"]:
            period_parts.append(values["month"])
        if values["date_from"] or values["date_to"]:
            period_parts.append(f"{values['date_from'] or 'Beginning'} to {values['date_to'] or 'Today'}")
        period = ", ".join(period_parts) or "All dates"
        return render_template("index.html", expenses=expenses, filters=values, period=period,
            categories=categories_for(user_id), total=summary["total"],
            expense_count=summary["count"], category_count=summary["category_count"],
            highest_expense=summary["highest"],
            labels=[r["category"] for r in category_rows],
            amounts=[r["cents"] / 100 for r in category_rows],
            trend_labels=[r["month"] for r in trend_rows],
            trend_amounts=[r["cents"] / 100 for r in trend_rows],
            page=page, page_count=page_count, budget_month=budget_month,
            budget_amount=budget_row[0] if budget_row else None, budget_spent=budget_spent,
            budget_tone=budget_tone)

    @app.route("/add", methods=["GET", "POST"])
    @login_required
    def add():
        user_id = session["user_id"]
        values = {"name": "", "category": "", "amount": "", "expense_date": date.today().isoformat()}
        errors = {}
        if request.method == "POST":
            values, errors, cents = expense_form_data(user_id)
            if not errors:
                db = get_db()
                db.execute("""INSERT INTO expenses
                    (name, category, amount_cents, user_id, expense_date, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (values["name"], values["category"], cents, user_id, values["expense_date"],
                     datetime.now(timezone.utc).isoformat(timespec="seconds")))
                db.commit()
                flash("Expense added.", "success")
                return redirect(url_for("index"))
        return render_template("add.html", values=values, errors=errors,
                               categories=categories_for(user_id)), 400 if errors else 200

    @app.route("/edit/<int:id>", methods=["GET", "POST"])
    @login_required
    def edit(id):
        user_id = session["user_id"]
        expense = expense_or_404(id, user_id)
        values = {"name": expense["name"], "category": expense["category"],
                  "amount": money(expense["amount_cents"]).replace(",", ""),
                  "expense_date": expense["expense_date"] or ""}
        errors = {}
        if request.method == "POST":
            values, errors, cents = expense_form_data(user_id)
            if not errors:
                db = get_db()
                db.execute("""UPDATE expenses SET name=?, category=?, amount_cents=?, expense_date=?
                    WHERE id=? AND user_id=?""",
                    (values["name"], values["category"], cents, values["expense_date"], id, user_id))
                db.commit()
                flash("Expense updated.", "success")
                return redirect(url_for("index"))
        return render_template("edit.html", values=values, errors=errors,
                               categories=categories_for(user_id)), 400 if errors else 200

    @app.post("/delete/<int:id>")
    @login_required
    def delete(id):
        expense_or_404(id, session["user_id"])
        db = get_db()
        db.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (id, session["user_id"]))
        db.commit()
        flash("Expense deleted.", "success")
        return redirect(url_for("index"))

    @app.post("/categories")
    @login_required
    def add_category():
        name = request.form.get("name", "").strip()
        if not 1 <= len(name) <= 40 or any(ord(c) < 32 for c in name):
            flash("Category must be 1 to 40 printable characters.", "error")
            return redirect(url_for("add"))
        db = get_db()
        if db.execute("SELECT 1 FROM categories WHERE user_id=? AND name=? COLLATE NOCASE",
                      (session["user_id"], name)).fetchone():
            flash("Category already exists.", "error")
            return redirect(url_for("add"))
        db.execute("INSERT INTO categories(user_id,name) VALUES (?,?)", (session["user_id"], name))
        db.commit()
        flash("Category added.", "success")
        return redirect(url_for("add"))

    @app.post("/budget")
    @login_required
    def budget():
        month = request.form.get("month", "")
        return_filters = request.args.to_dict(flat=True)
        return_filters["month"] = month
        try:
            valid_month(month)
            cents = parse_amount(request.form.get("amount"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("index", **request.args.to_dict(flat=True)))
        db = get_db()
        db.execute("""INSERT INTO budgets(user_id,month,amount_cents) VALUES (?,?,?)
            ON CONFLICT(user_id,month) DO UPDATE SET amount_cents=excluded.amount_cents""",
            (session["user_id"], month, cents))
        db.commit()
        flash("Monthly budget saved.", "success")
        return redirect(url_for("index", **return_filters))

    @app.post("/budget/reset")
    @login_required
    def reset_budget():
        month = request.form.get("month", "")
        try:
            valid_month(month)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("index", **request.args.to_dict(flat=True)))
        db = get_db()
        db.execute("DELETE FROM budgets WHERE user_id=? AND month=?", (session["user_id"], month))
        db.commit()
        flash("Monthly target reset.", "success")
        return_filters = request.args.to_dict(flat=True)
        return_filters["month"] = month
        return redirect(url_for("index", **return_filters))

    @app.get("/export.csv")
    @login_required
    def export_csv():
        values, where, params = filters_from_request(session["user_id"])
        rows = get_db().execute(f"""SELECT expense_date, name, category, amount_cents, created_at
            FROM expenses WHERE {where} ORDER BY {SORTS[values['sort']]}""", params)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Date", "Name", "Category", "Amount", "Created at"])
        for row in rows:
            # Prevent spreadsheet applications from interpreting user text as formulas.
            safe = lambda text: "'" + text if text and text.lstrip().startswith(("=", "+", "-", "@")) else text
            writer.writerow([row["expense_date"] or "", safe(row["name"]), safe(row["category"]),
                             money(row["amount_cents"]).replace(",", ""), row["created_at"]])
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=expenses.csv"})

    @app.route("/register", methods=["GET", "POST"])
    def register():
        errors = {}
        username = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not 3 <= len(username) <= 50 or any(ord(c) < 32 for c in username):
                errors["username"] = "Username must be 3 to 50 printable characters."
            if problem := password_error(password):
                errors["password"] = problem
            if not errors:
                db = get_db()
                if db.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone():
                    errors["username"] = "Username already exists."
                else:
                    try:
                        cursor = db.execute("INSERT INTO users(username,password) VALUES (?,?)",
                                            (username, generate_password_hash(password)))
                        for category in DEFAULT_CATEGORIES:
                            db.execute("INSERT INTO categories(user_id,name) VALUES (?,?)",
                                       (cursor.lastrowid, category))
                        db.commit()
                        flash("Account created. Please sign in.", "success")
                        return redirect(url_for("login"))
                    except Exception:
                        db.rollback()
                        raise
        return render_template("register.html", errors=errors, username=username), 400 if errors else 200

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        username = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            key = _login_key(username)
            db = get_db()
            now = int(time.time())
            db.execute("DELETE FROM login_attempts WHERE window_start < ?", (now - 900,))
            attempt = db.execute("SELECT failures,window_start FROM login_attempts WHERE key=?", (key,)).fetchone()
            if attempt and attempt["window_start"] > now - 900 and attempt["failures"] >= 5:
                db.commit()
                return render_template("login.html", error="Too many attempts. Try again in 15 minutes.",
                                       username=username), 429
            user = db.execute("SELECT id,username,password FROM users WHERE username=?", (username,)).fetchone()
            if user and check_password_hash(user["password"], password):
                db.execute("DELETE FROM login_attempts WHERE key=?", (key,))
                db.commit()
                session.clear()
                session.permanent = bool(request.form.get("remember"))
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                return redirect(url_for("index"))
            failures = attempt["failures"] + 1 if attempt and attempt["window_start"] > now - 900 else 1
            db.execute("""INSERT INTO login_attempts(key,failures,window_start) VALUES (?,?,?)
                ON CONFLICT(key) DO UPDATE SET failures=excluded.failures,
                window_start=excluded.window_start""", (key, failures, now if failures == 1 else attempt["window_start"]))
            db.commit()
            error = "Invalid username or password."
        return render_template("login.html", error=error, username=username), 401 if error else 200

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            abort(403, "Self-service password reset is unavailable until verified email delivery is configured.")
        return render_template("forgot_password.html")

    return app


if __name__ == "__main__":
    create_app().run(debug=False)
