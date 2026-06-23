from flask import Flask, render_template, request, redirect, session
import sqlite3

app = Flask(__name__)
app.secret_key = 'my_secret_key'

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

    query = "SELECT * FROM expenses WHERE user_id = ?"
    params = [session['user_id']]

    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")

    if category:
        query += " AND category = ?"
        params.append(category)
    
    cursor.execute(query, params)
    expenses = cursor.fetchall()

    total = sum(expense[3] for expense in expenses)

    # Category totals for Pie Chart
    cursor.execute("""
        SELECT category, SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY category
        """,
        (session['user_id'],)
        )

    category_data = cursor.fetchall()

    labels = [row[0] for row in category_data]
    amounts = [row[1] for row in category_data]

    conn.close()

    return render_template(
        "index.html",
        expenses=expenses,
        total=total,
        search=search,
        category=category,
        category_data=category_data,
        labels=labels,
        amounts=amounts
    )


# Add Expense Page
@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':

        name = request.form.get('name', '').strip()
        amount = request.form.get('amount', '').strip()
        category = request.form.get('category', '').strip()

        if not name or not amount or not category:
            return "Please fill in all fields."

        try:
            amount = float(amount)
        except ValueError:
            return "Please enter a valid amount."

        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO expenses (name, category, amount, user_id) VALUES (?, ?, ?, ?)",
            (name, category, amount, session['user_id'])
        )

        conn.commit()
        conn.close()

        return redirect('/')

    return render_template("add.html")

#Delete Expenses
@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    conn = sqlite3.connect('expenses.db')
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM expenses WHERE id = ? AND user_id = ?",
        (id, session['user_id'])
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
        "SELECT * FROM expenses WHERE id=? AND user_id = ?",
        (id, session['user_id'])
    )

    expense = cursor.fetchone()

    conn.close()

    return render_template('edit.html', expense=expense)

#Implement Register
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            return "Please fill all fields"
        
        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()

        try:
            cursor.execute("INSERT INTO users (username, password) VALUES (?,?)",
                        (username, password))
            
            conn.commit()

        except sqlite3.IntegrityError:
            conn.close()
            return "Username Already Exists !"
        
        conn.close()
        return redirect("/login")
    return render_template('register.html')

#Implement Login
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()

        conn = sqlite3.connect('expenses.db')
        cursor = conn.cursor()

        cursor.execute('''
            SELECT *
            FROM users
            WHERE username = ? AND password = ?          
            ''',
            (username,password)
            )
        
        user = cursor.fetchone()

        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]

            return redirect('/')
        return "Invalid username or password!"
    return render_template('login.html')

#Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


if __name__ == '__main__':
    init_db()
    app.run(debug=True)