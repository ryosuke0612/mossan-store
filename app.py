from flask import Flask, render_template, request, redirect
import os
import sqlite3

app = Flask(__name__)
DB_NAME = "database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            opponent TEXT,
            location TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM matches ORDER BY date DESC")
    matches = c.fetchall()
    conn.close()
    return render_template("index.html", matches=matches)

@app.route("/add", methods=["POST"])
def add_match():
    date = request.form["date"]
    opponent = request.form["opponent"]
    location = request.form["location"]

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO matches (date, opponent, location) VALUES (?, ?, ?)",
              (date, opponent, location))
    conn.commit()
    conn.close()

    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)