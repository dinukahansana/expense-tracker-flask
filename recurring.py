"""Materialize due recurring expenses once per rule and calendar month."""

import calendar
from datetime import date, datetime, timezone


def next_month(month):
    year, number = map(int, month.split("-"))
    return f"{year + (number == 12):04d}-{number % 12 + 1:02d}"


def generate_due(db, user_id, today=None):
    today = today or date.today()
    current_month = today.strftime("%Y-%m")
    rules = db.execute("SELECT * FROM recurring_rules WHERE user_id=? AND active=1", (user_id,)).fetchall()
    created = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        for rule in rules:
            month = max(rule["start_month"], rule["generate_from_month"])
            # Cap historical catch-up so one request cannot create an unbounded list.
            steps = 0
            while month <= current_month and (not rule["end_month"] or month <= rule["end_month"]):
                steps += 1
                if steps > 120:
                    raise ValueError("A recurring rule is more than 120 months behind; update its start month.")
                year, number = map(int, month.split("-"))
                day = min(rule["day_of_month"], calendar.monthrange(year, number)[1])
                due = date(year, number, day)
                if due <= today and not db.execute("""SELECT 1 FROM recurring_occurrences
                    WHERE rule_id=? AND occurrence_month=?""", (rule["id"], month)).fetchone():
                    expense = db.execute("""INSERT INTO expenses
                        (name,category,amount_cents,user_id,expense_date,created_at)
                        VALUES (?,?,?,?,?,?)""", (rule["name"], rule["category"], rule["amount_cents"],
                        user_id, due.isoformat(), datetime.now(timezone.utc).isoformat(timespec="seconds")))
                    db.execute("""INSERT INTO recurring_occurrences
                        (rule_id,occurrence_month,due_date,expense_id) VALUES (?,?,?,?)""",
                        (rule["id"], month, due.isoformat(), expense.lastrowid))
                    created += 1
                month = next_month(month)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return created
