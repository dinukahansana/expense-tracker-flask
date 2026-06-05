from flask import Flask, render_template, request, redirect
import sqlite3

app = Flask(__name__)

# Create Database
def init_db():
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount REAL NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


# Home Page - Show Expenses
@app.route('/')
def index():
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM expenses")
    expenses = cursor.fetchall()

    total = sum(expense[2] for expense in expenses)

    conn.close()

    return render_template(
        "index.html",
        expenses=expenses,
        total=total
    )


# Add Expense Page
@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':

        name = request.form.get('name', '').strip()
        amount = request.form.get('amount', '').strip()

        # name = request.form['name']
        # amount = request.form['amount']

        # Validation
        if not name or not amount:
            return "Please fill in all fields."

        try:
            amount = float(amount)
        except ValueError:
            return "Please enter a valid amount."

        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO expenses (name, amount) VALUES (?, ?)",
            (name, amount)
        )

        conn.commit()
        conn.close()

        
        return render_template("add.html")

    return render_template("add.html")

#Delete Expenses
@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM expenses WHERE id = ?",
        (id,)
    )

    conn.commit()
    conn.close()

    return redirect('/')


if __name__ == '__main__':
    init_db()
    app.run(debug=True)