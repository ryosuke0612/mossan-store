import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, Response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


def get_db_connection():
    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        start_time TEXT,
        end_time TEXT,
        opponent TEXT,
        place TEXT
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        name TEXT,
        status TEXT,
        UNIQUE(match_id, name)
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        plan_name TEXT NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """
    )

    # Backward-compatible migration for old payments schema.
    c.execute("PRAGMA table_info(payments)")
    payment_info = c.fetchall()
    payment_columns = [row[1] for row in payment_info]

    if "user_id" not in payment_columns:
        c.execute("ALTER TABLE payments ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
        payment_columns.append("user_id")

    # If legacy columns (e.g. payer_name/payer_email) still exist, recreate table
    # so inserts using the current schema do not fail with NOT NULL constraints.
    expected_columns = {"id", "user_id", "plan_name", "amount", "status", "created_at"}
    if set(payment_columns) != expected_columns:
        c.execute("ALTER TABLE payments RENAME TO payments_legacy")
        c.execute(
            """
        CREATE TABLE payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_name TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
        )
        c.execute(
            """
        INSERT INTO payments (user_id, plan_name, amount, status, created_at)
        SELECT
            COALESCE(user_id, 0),
            plan_name,
            amount,
            status,
            created_at
        FROM payments_legacy
        """
        )
        c.execute("DROP TABLE payments_legacy")

    conn.commit()
    conn.close()


init_db()


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return func(*args, **kwargs)

    return wrapper


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
        "荳榊盾蜉": "不参加",
        "譛ｪ螳・": "未定",
    }
    return status_map.get(value, value)


def format_date_mmdd_with_weekday(date_text):
    try:
        date_obj = datetime.strptime(date_text, "%Y-%m-%d")
    except (TypeError, ValueError):
        return date_text
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    return f"{date_obj.strftime('%m月%d日')}（{weekdays[date_obj.weekday()]}）"


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    error_message = ""

    if request.method == "POST":
        team_name = request.form.get("team_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not team_name or not email or not password:
            error_message = "チーム名・メールアドレス・パスワードは必須です。"
        elif len(password) < 6:
            error_message = "パスワードは6文字以上で入力してください。"
        else:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE username=? OR email=?", (team_name, email))
            exists = c.fetchone()

            if exists:
                error_message = "同じチーム名またはメールアドレスが既に登録されています。"
            else:
                c.execute(
                    """
                    INSERT INTO users (username, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        team_name,
                        email,
                        generate_password_hash(password),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
                conn.close()
                return redirect(url_for("login"))

            conn.close()

    return render_template("register.html", error_message=error_message)


@app.route("/login", methods=["GET", "POST"])
def login():
    error_message = ""
    next_url = request.args.get("next") or request.form.get("next") or "/app"

    if request.method == "POST":
        team_or_email = request.form.get("team_or_email", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "SELECT id, username, password_hash FROM users WHERE username=? OR email=?",
            (team_or_email, team_or_email.lower()),
        )
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["team_name"] = user["username"]
            session["username"] = user["username"]
            return redirect(next_url)

        error_message = "ログイン情報が正しくありません。"

    return render_template("login.html", error_message=error_message, next_url=next_url)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/payment", methods=["GET", "POST"])
@login_required
def payment():
    plan_prices = {
        "ベーシックプラン": 980,
        "スタンダードプラン": 1980,
        "プレミアムプラン": 2980,
    }

    error_message = ""
    success_message = ""

    if request.method == "POST":
        plan_name = request.form.get("plan_name", "").strip()

        if plan_name not in plan_prices:
            error_message = "プランを選択してください。"
        else:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO payments (user_id, plan_name, amount, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session["user_id"],
                    plan_name,
                    plan_prices[plan_name],
                    "PAID",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            conn.commit()
            conn.close()
            success_message = f"{plan_name} の決済が完了しました。"

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT plan_name, amount, status, created_at
        FROM payments
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 10
        """,
        (session["user_id"],),
    )
    recent_payments = c.fetchall()
    conn.close()

    return render_template(
        "payment.html",
        plan_prices=plan_prices,
        error_message=error_message,
        success_message=success_message,
        recent_payments=recent_payments,
        team_name=session.get("team_name") or session.get("username", ""),
    )


@app.route("/app")
@login_required
def index():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT DISTINCT substr(date,1,7) as month FROM matches ORDER BY month")
    months = [row["month"] for row in c.fetchall()]

    c.execute("SELECT * FROM matches ORDER BY date, start_time")
    all_matches = c.fetchall()
    all_matches_with_labels = []
    for match in all_matches:
        match_data = dict(match)
        match_data["date_label"] = format_date_mmdd_with_weekday(match["date"])
        all_matches_with_labels.append(match_data)

    month_data = {}
    for month in months:
        month_data[month] = [m for m in all_matches_with_labels if m["date"].startswith(month)]

    c.execute(
        """
        SELECT
            substr(m.date,1,7) as month,
            a.name,
            MIN(a.id) as first_attendance_id
        FROM attendance a
        JOIN matches m ON m.id = a.match_id
        GROUP BY substr(m.date,1,7), a.name
        ORDER BY month, first_attendance_id
        """
    )
    month_member_rows = c.fetchall()
    members_by_month = {month: [] for month in months}
    for row in month_member_rows:
        month = row["month"]
        if month in members_by_month:
            members_by_month[month].append(row["name"])

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
        members_by_month=members_by_month,
        attendance_dict=attendance_dict,
        team_name=session.get("team_name") or session.get("username", ""),
    )


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_match():
    if request.method == "GET":
        return render_template("add.html")

    start_time = build_time_from_form("start_time")
    end_time = build_time_from_form("end_time")
    if not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
        return "start_time/end_time must be in 10-minute increments.", 400

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute(
        """
    INSERT INTO matches (date, start_time, end_time, opponent, place)
    VALUES (?, ?, ?, ?, ?)
    """,
        (
            request.form["date"],
            start_time,
            end_time,
            request.form["opponent"],
            request.form["place"],
        ),
    )

    conn.commit()
    conn.close()
    return redirect("/app")


@app.route("/delete/<int:id>")
@login_required
def delete_match(id):
    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute("DELETE FROM matches WHERE id=?", (id,))
    c.execute("DELETE FROM attendance WHERE match_id=?", (id,))

    conn.commit()
    conn.close()
    return redirect("/app")


@app.route("/duplicate/<int:id>")
@login_required
def duplicate_match(id):
    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute(
        """
    INSERT INTO matches (date, start_time, end_time, opponent, place)
    SELECT date, start_time, end_time, opponent, place
    FROM matches
    WHERE id=?
    """,
        (id,),
    )

    conn.commit()
    conn.close()
    return redirect("/app")


@app.route("/matches/action", methods=["POST"])
@login_required
def bulk_match_action():
    action = request.form.get("action", "")
    selected_ids_raw = request.form.getlist("selected_ids")

    if not selected_ids_raw:
        return redirect("/app")

    try:
        selected_ids = [int(match_id) for match_id in selected_ids_raw]
    except ValueError:
        return redirect("/app")

    if action == "edit":
        return redirect(f"/edit/{selected_ids[0]}")

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    if action == "duplicate":
        c.executemany(
            """
        INSERT INTO matches (date, start_time, end_time, opponent, place)
        SELECT date, start_time, end_time, opponent, place
        FROM matches
        WHERE id=?
        """,
            [(match_id,) for match_id in selected_ids],
        )
    elif action == "delete":
        placeholders = ",".join("?" for _ in selected_ids)
        c.execute(f"DELETE FROM attendance WHERE match_id IN ({placeholders})", selected_ids)
        c.execute(f"DELETE FROM matches WHERE id IN ({placeholders})", selected_ids)
    else:
        conn.close()
        return redirect("/app")

    conn.commit()
    conn.close()
    return redirect("/app")


@app.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
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

        c.execute(
            """
        UPDATE matches
        SET date=?, start_time=?, end_time=?, opponent=?, place=?
        WHERE id=?
        """,
            (
                request.form["date"],
                start_time,
                end_time,
                request.form["opponent"],
                request.form["place"],
                id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect("/app")

    c.execute("SELECT * FROM matches WHERE id=?", (id,))
    match = c.fetchone()
    conn.close()

    return render_template("edit.html", match=match)


@app.route("/attendance/month", methods=["GET", "POST"])
@login_required
def attendance_month():
    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT DISTINCT substr(date,1,7) as month FROM matches ORDER BY month")
    months = [row["month"] for row in c.fetchall()]

    selected_month = request.args.get("month")
    name = request.args.get("name")
    error_message = ""

    if not selected_month and months:
        selected_month = months[0]

    if request.method == "POST":
        selected_month = request.form.get("month") or selected_month
        name = request.form.get("name", "").strip()
        match_id = request.form["match_id"]
        status = normalize_status(request.form["status"])

        if not name:
            error_message = "名前を入力してから出欠を登録してください。"
        else:
            c.execute(
                """
            INSERT INTO attendance (match_id, name, status)
            VALUES (?, ?, ?)
            ON CONFLICT(match_id, name)
            DO UPDATE SET status=excluded.status
            """,
                (match_id, name, status),
            )

            conn.commit()

    matches = []
    attendance_dict = {}

    if selected_month:
        c.execute(
            """
        SELECT * FROM matches
        WHERE substr(date,1,7)=?
        ORDER BY date, start_time
        """,
            (selected_month,),
        )
        matches = []
        for row in c.fetchall():
            match_data = dict(row)
            match_data["date_label"] = format_date_mmdd_with_weekday(row["date"])
            matches.append(match_data)

        if name:
            c.execute(
                """
            SELECT match_id, status FROM attendance
            WHERE name=?
            """,
                (name,),
            )
            attendance_dict = {
                row["match_id"]: normalize_status(row["status"]) for row in c.fetchall()
            }

    conn.close()

    return render_template(
        "attendance_month.html",
        months=months,
        selected_month=selected_month,
        matches=matches,
        name=name,
        attendance_dict=attendance_dict,
        error_message=error_message,
        edit_mode=bool(name),
    )


@app.route("/attendance/member/delete", methods=["POST"])
@login_required
def delete_member_attendance_by_month():
    month = request.args.get("month", "").strip()
    name = request.args.get("name", "").strip()

    if not month or not name:
        return redirect("/app")

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()
    c.execute(
        """
        DELETE FROM attendance
        WHERE name=?
          AND match_id IN (
              SELECT id
              FROM matches
              WHERE substr(date,1,7)=?
          )
        """,
        (name, month),
    )
    conn.commit()
    conn.close()

    return redirect("/app")


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


if __name__ == "__main__":
    app.run(debug=True)
