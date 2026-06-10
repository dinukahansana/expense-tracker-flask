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
            category TEXT NOT NULL,
            amount REAL NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


# Home Page - Show Expenses
@app.route('/')
def index():

    search = request.args.get('search','')
    category = request.args.get('category','')

    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    #cursor.execute("SELECT * FROM expenses")

    query = "SELECT * FROM expenses WHERE 1=1"
    params = []

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")

    if category:
        query += " AND category = ?"
        params.append(category)
    
    cursor.execute(query, params)
    expenses = cursor.fetchall()

    total = sum(expense[3] for expense in expenses)

    conn.close()

    return render_template(
        "index.html",
        expenses=expenses,
        total=total,
        search=search,
        category=category
    )


# Add Expense Page
@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':

        name = request.form.get('name', '').strip()
        amount = request.form.get('amount', '').strip()
        category = request.form.get('category', '').strip()

        # name = request.form['name']
        # amount = request.form['amount']

        # Validation
        if not name or not amount or not category:
            return "Please fill in all fields."

        try:
            amount = float(amount)
        except ValueError:
            return "Please enter a valid amount."

        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO expenses (name, amount, category) VALUES (?, ?, ?)",
            (name, amount, category)
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

#Edit Expenses
@app.route('/edit/<int:id>', methods=['GET','POST'])
def edit(id):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        amount = request.form['amount']

        cursor.execute(
            '''
            UPDATE expenses
            SET name=?, category=?, amount=?
            WHERE id=?
            ''',
            (name, category, amount, id)
        )

        conn.commit()
        conn.close()

        return redirect('/')
    
    cursor.execute(
        "SELECT * FROM expenses WHERE id=?",
        (id,)
    )

    expense = cursor.fetchone()

    conn.close()

    return render_template('edit.html', expense=expense)


if __name__ == '__main__':
    init_db()
    app.run(debug=True)