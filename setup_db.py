import sqlite3

conn = sqlite3.connect('expenses.db')
cursor = conn.cursor()

#CREATE USER TABLE
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL           
    )
''')

#ADD user_id column to expenses table
try:
    cursor.execute("ALTER TABLE expenses ADD COLUMN user_id INTERGER")
except:
    pass

conn.commit()
conn.close()

print("Database Setup Completed Successfully!")