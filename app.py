from flask import Flask, render_template, request, redirect
import sqlite3
from flask import Response
from datetime import datetime

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


def is_valid_10min_time(value):
    try:
        dt = datetime.strptime(value, "%H:%M")
    except (TypeError, ValueError):
        return False
    return dt.minute % 10 == 0


def build_time_from_form(prefix):
    hour = request.form.get(f"{prefix}_hour")
    minute = request.form.get(f"{prefix}_minute")
    if hour is not None and minute is not None:
        try:
            return f"{int(hour):02d}:{int(minute):02d}"
        except ValueError:
            return ""
    return request.form.get(prefix, "")


def normalize_status(value):
    status_map = {
        "参加": "参加",
        "不参加": "不参加",
        "未定": "未定",
        "蜿ょ刈": "参加",
        "荳榊盾蜉": "不参加"
    }
    return status_map.get(value, value)

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
        attendance_dict[(row["match_id"], row["name"])] = normalize_status(row["status"])

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
    start_time = build_time_from_form("start_time")
    end_time = build_time_from_form("end_time")
    if not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
        return "start_time/end_time must be in 10-minute increments.", 400

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute("""
    INSERT INTO matches (date, start_time, end_time, opponent, place)
    VALUES (?, ?, ?, ?, ?)
    """, (
        request.form["date"],
        start_time,
        end_time,
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
@app.route("/duplicate/<int:id>")
def duplicate_match(id):

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute("""
    INSERT INTO matches (date, start_time, end_time, opponent, place)
    SELECT date, start_time, end_time, opponent, place
    FROM matches
    WHERE id=?
    """, (id,))

    conn.commit()
    conn.close()
    return redirect("/")

@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_match(id):

    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if request.method == "POST":
        start_time = build_time_from_form("start_time")
        end_time = build_time_from_form("end_time")
        if not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
            conn.close()
            return "start_time/end_time must be in 10-minute increments.", 400

        c.execute("""
        UPDATE matches
        SET date=?, start_time=?, end_time=?, opponent=?, place=?
        WHERE id=?
        """, (
            request.form["date"],
            start_time,
            end_time,
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
        status = normalize_status(request.form["status"])

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
            attendance_dict = {
                row["match_id"]: normalize_status(row["status"])
                for row in c.fetchall()
            }

    conn.close()

    return render_template(
        "attendance_month.html",
        months=months,
        selected_month=selected_month,
        matches=matches,
        name=name,
        attendance_dict=attendance_dict
    )

@app.route("/sitemap.xml")
def sitemap():
    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://mossan-store.com/</loc>
  </url>
</urlset>"""
    return Response(sitemap_xml, content_type="application/xml; charset=utf-8")


@app.route("/robots.txt")
def robots():
    robots_txt = """User-agent: *
Allow: /
Sitemap: https://mossan-store.com/sitemap.xml"""
    return Response(robots_txt, content_type="text/plain; charset=utf-8")

# ==========================
if __name__ == "__main__":
    app.run(debug=True)
