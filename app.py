from flask import Flask, render_template, request, redirect
import sqlite3

app = Flask(__name__)

# ==========================
# DB初期化
# ==========================
def init_db():
    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        start_time TEXT,
        end_time TEXT,
        opponent TEXT,
        place TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        name TEXT,
        status TEXT,
        UNIQUE(match_id, name)
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ==========================
# トップページ（月タブ完全対応版）
# ==========================
@app.route("/")
def index():

    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 月一覧取得
    c.execute("SELECT DISTINCT substr(date,1,7) as month FROM matches ORDER BY month")
    months = [row["month"] for row in c.fetchall()]

    # 全イベント取得
    c.execute("SELECT * FROM matches ORDER BY date, start_time")
    all_matches = c.fetchall()

    # 月ごとに分類
    month_data = {}
    for month in months:
        month_data[month] = [
            m for m in all_matches if m["date"].startswith(month)
        ]

    # メンバー取得
    c.execute("SELECT DISTINCT name FROM attendance ORDER BY name")
    members = [row["name"] for row in c.fetchall()]

    # 出欠データ取得
    c.execute("SELECT match_id, name, status FROM attendance")
    attendance_rows = c.fetchall()

    attendance_dict = {}
    for row in attendance_rows:
        attendance_dict[(row["match_id"], row["name"])] = row["status"]

    conn.close()

    return render_template(
        "index.html",
        months=months,
        month_data=month_data,
        members=members,
        attendance_dict=attendance_dict
    )

# ==========================
# イベント追加
# ==========================
@app.route("/add", methods=["POST"])
def add_match():

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute("""
    INSERT INTO matches (date, start_time, end_time, opponent, place)
    VALUES (?, ?, ?, ?, ?)
    """, (
        request.form["date"],
        request.form["start_time"],
        request.form["end_time"],
        request.form["opponent"],
        request.form["place"]
    ))

    conn.commit()
    conn.close()
    return redirect("/")

# ==========================
# イベント削除
# ==========================
@app.route("/delete/<int:id>")
def delete_match(id):

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute("DELETE FROM matches WHERE id=?", (id,))
    c.execute("DELETE FROM attendance WHERE match_id=?", (id,))

    conn.commit()
    conn.close()
    return redirect("/")

# ==========================
# イベント編集
# ==========================
@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_match(id):

    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == "POST":
        c.execute("""
        UPDATE matches
        SET date=?, start_time=?, end_time=?, opponent=?, place=?
        WHERE id=?
        """, (
            request.form["date"],
            request.form["start_time"],
            request.form["end_time"],
            request.form["opponent"],
            request.form["place"],
            id
        ))
        conn.commit()
        conn.close()
        return redirect("/")

    c.execute("SELECT * FROM matches WHERE id=?", (id,))
    match = c.fetchone()
    conn.close()

    return render_template("edit.html", match=match)

# ==========================
# 月別出欠登録
# ==========================
@app.route("/attendance/month", methods=["GET", "POST"])
def attendance_month():

    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT DISTINCT substr(date,1,7) as month FROM matches ORDER BY month")
    months = [row["month"] for row in c.fetchall()]

    selected_month = request.args.get("month")
    name = request.args.get("name")

    if not selected_month and months:
        selected_month = months[0]

    if request.method == "POST":
        name = request.form["name"]
        match_id = request.form["match_id"]
        status = request.form["status"]

        c.execute("""
        INSERT INTO attendance (match_id, name, status)
        VALUES (?, ?, ?)
        ON CONFLICT(match_id, name)
        DO UPDATE SET status=excluded.status
        """, (match_id, name, status))

        conn.commit()

    matches = []
    attendance_dict = {}

    if selected_month:
        c.execute("""
        SELECT * FROM matches
        WHERE substr(date,1,7)=?
        ORDER BY date, start_time
        """, (selected_month,))
        matches = c.fetchall()

        if name:
            c.execute("""
            SELECT match_id, status FROM attendance
            WHERE name=?
            """, (name,))
            attendance_dict = {row["match_id"]: row["status"] for row in c.fetchall()}

    conn.close()

    return render_template(
        "attendance_month.html",
        months=months,
        selected_month=selected_month,
        matches=matches,
        name=name,
        attendance_dict=attendance_dict
    )

# ==========================
if __name__ == "__main__":
    app.run(debug=True)