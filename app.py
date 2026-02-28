from flask import Flask, render_template, request, redirect
import os
import sqlite3

app = Flask(__name__)
DB_NAME = "database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # 試合テーブル
    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            opponent TEXT,
            location TEXT
        )
    """)

    # 出欠テーブル
    c.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            name TEXT,
            status TEXT
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

@app.route("/match/<int:match_id>")
def match_detail(match_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("SELECT * FROM matches WHERE id=?", (match_id,))
    match = c.fetchone()

    c.execute("SELECT * FROM attendance WHERE match_id=?", (match_id,))
    attendance = c.fetchall()

    conn.close()

    return render_template("match.html", match=match, attendance=attendance)

@app.route("/attendance/<int:match_id>", methods=["POST"])
def add_attendance(match_id):
    name = request.form["name"]
    status = request.form["status"]

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO attendance (match_id, name, status) VALUES (?, ?, ?)",
              (match_id, name, status))
    conn.commit()
    conn.close()

    return redirect(f"/match/{match_id}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)