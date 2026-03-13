import csv
import io
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
        user_id INTEGER NOT NULL DEFAULT 0,
        date TEXT,
        start_time TEXT,
        end_time TEXT,
        opponent TEXT,
        place TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 0,
        match_id INTEGER,
        name TEXT,
        status TEXT,
        UNIQUE(match_id, name),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
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

    c.execute("PRAGMA table_info(matches)")
    match_columns = [row[1] for row in c.fetchall()]
    if "user_id" not in match_columns:
        c.execute("ALTER TABLE matches ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")

    c.execute("PRAGMA table_info(attendance)")
    attendance_columns = [row[1] for row in c.fetchall()]
    if "user_id" not in attendance_columns:
        c.execute("ALTER TABLE attendance ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")

    c.execute("PRAGMA table_info(users)")
    user_info = c.fetchall()
    user_columns = [row[1] for row in user_info]
    expected_user_columns = {"id", "username", "password_hash", "created_at"}
    if set(user_columns) != expected_user_columns:
        c.execute("ALTER TABLE users RENAME TO users_legacy")
        c.execute(
            """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
        )
        c.execute(
            """
        INSERT INTO users (id, username, password_hash, created_at)
        SELECT id, username, password_hash, created_at
        FROM users_legacy
        """
        )
        c.execute("DROP TABLE users_legacy")

    # Backfill attendance.user_id from related matches for legacy rows.
    c.execute(
        """
        UPDATE attendance
        SET user_id = (
            SELECT m.user_id
            FROM matches m
            WHERE m.id = attendance.match_id
        )
        WHERE user_id = 0
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
        "\u53c2\u52a0": "\u53c2\u52a0",
        "\u4e0d\u53c2\u52a0": "\u4e0d\u53c2\u52a0",
        "\u672a\u5b9a": "\u672a\u5b9a",
        "\u873f\u3087\u5208": "\u53c2\u52a0",
        "\u8373\u6994\u76fe\u8709\uf8f0": "\u4e0d\u53c2\u52a0",
        "\u8b5b\uff6a\u87b3\u30fb": "\u672a\u5b9a",
    }
    return status_map.get(value, value)


def format_date_mmdd_with_weekday(date_text):
    try:
        date_obj = datetime.strptime(date_text, "%Y-%m-%d")
    except (TypeError, ValueError):
        return date_text
    weekdays = ["\u6708", "\u706b", "\u6c34", "\u6728", "\u91d1", "\u571f", "\u65e5"]
    return f"{date_obj.strftime('%m\u6708%d\u65e5')}\uff08{weekdays[date_obj.weekday()]}\uff09"


def redirect_to_app_with_month(month=None):
    month_value = (month or "").strip()
    if month_value:
        return redirect(url_for("index", month=month_value))
    return redirect(url_for("index"))


def authenticate_user(team_name, password):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, username, password_hash FROM users WHERE username=?",
        (team_name,),
    )
    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def login_user(user):
    session["user_id"] = user["id"]
    session["team_name"] = user["username"]
    session["username"] = user["username"]


def build_event_list_csv_response(user_id, month="all"):
    conn = get_db_connection()
    c = conn.cursor()

    match_sql = """
        SELECT id, date, start_time, end_time, opponent, place
        FROM matches
        WHERE user_id=?
    """
    match_params = [user_id]
    if month and month != "all":
        match_sql += " AND substr(date,1,7)=?"
        match_params.append(month)
    match_sql += " ORDER BY date, start_time"
    c.execute(match_sql, match_params)
    matches = c.fetchall()

    member_sql = """
        SELECT
            a.name,
            MIN(a.id) AS first_attendance_id
        FROM attendance a
        JOIN matches m ON m.id = a.match_id
        WHERE m.user_id=?
    """
    member_params = [user_id]
    if month and month != "all":
        member_sql += " AND substr(m.date,1,7)=?"
        member_params.append(month)
    member_sql += """
        GROUP BY a.name
        ORDER BY first_attendance_id
    """
    c.execute(member_sql, member_params)
    members = [row["name"] for row in c.fetchall()]

    attendance_sql = """
        SELECT a.match_id, a.name, a.status
        FROM attendance a
        JOIN matches m ON m.id = a.match_id
        WHERE m.user_id=?
    """
    attendance_params = [user_id]
    if month and month != "all":
        attendance_sql += " AND substr(m.date,1,7)=?"
        attendance_params.append(month)
    c.execute(attendance_sql, attendance_params)
    attendance_rows = c.fetchall()
    conn.close()

    attendance_dict = {}
    for row in attendance_rows:
        attendance_dict[(row["match_id"], row["name"])] = normalize_status(row["status"])

    status_symbol_map = {"参加": "○", "不参加": "×", "未定": "△"}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["日付", "時間", "内容", "場所", "参加", "不参加", "未定", *members])

    for match in matches:
        date_value = match["date"]
        time_value = f"{match['start_time']}~{match['end_time']}"
        content_value = match["opponent"]
        place_value = match["place"]

        join_count = 0
        absent_count = 0
        undecided_count = 0
        member_cells = []

        for member in members:
            status = attendance_dict.get((match["id"], member), "")
            if status == "参加":
                join_count += 1
            elif status == "不参加":
                absent_count += 1
            elif status == "未定":
                undecided_count += 1
            member_cells.append(status_symbol_map.get(status, "-"))

        writer.writerow(
            [
                date_value,
                time_value,
                content_value,
                place_value,
                join_count,
                absent_count,
                undecided_count,
                *member_cells,
            ]
        )

    csv_text = "\ufeff" + output.getvalue()
    filename_suffix = month if month and month != "all" else "all"
    filename = f"event_list_export_{filename_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/apps/attendance/app/description")
def attendance_description():
    return render_template("landing.html")


@app.route("/apps")
def apps_list():
    return render_template("apps.html")


@app.route("/apps/shift")
def shift_app():
    return render_template("shift.html")


@app.route("/apps/qrcode")
def qrcode_app():
    return render_template("qrcode.html")


@app.route("/apps/noticeboard")
def noticeboard_app():
    return render_template("noticeboard.html")


@app.route("/blog")
def blog_index():
    return render_template("blog.html")


@app.route("/blog/sports-attendance")
def blog_sports_attendance():
    return render_template("blog_sports_attendance.html")


@app.route("/blog/pta-attendance")
def blog_pta_attendance():
    return render_template("blog_pta_attendance.html")


@app.route("/apps/attendance/app/register", methods=["GET", "POST"])
def register():
    error_message = ""

    if request.method == "POST":
        team_name = request.form.get("team_name", "").strip()
        password = request.form.get("password", "")

        if not team_name or not password:
            error_message = "チーム名・パスワードは必須です。"
        elif len(password) < 6:
            error_message = "パスワードは6文字以上で入力してください。"
        else:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE username=?", (team_name,))
            exists = c.fetchone()

            if exists:
                error_message = "同じチーム名が既に登録されています。"
            else:
                c.execute(
                    """
                    INSERT INTO users (username, password_hash, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        team_name,
                        generate_password_hash(password),
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
                conn.close()
                return redirect(url_for("login"))

            conn.close()

    return render_template("register.html", error_message=error_message)


@app.route("/apps/attendance/app/login", methods=["GET", "POST"])
def login():
    error_message = ""
    next_url = request.args.get("next") or request.form.get("next") or url_for("index")

    auto_team_name = request.args.get("team_name", "").strip()
    auto_password = request.args.get("password", "")
    if request.method == "GET" and auto_team_name and auto_password:
        user = authenticate_user(auto_team_name, auto_password)
        if user:
            login_user(user)
            return redirect(next_url)
        error_message = "自動ログイン用URLの情報が正しくありません。"

    if request.method == "POST":
        team_name = request.form.get("team_name", "").strip()
        password = request.form.get("password", "")
        user = authenticate_user(team_name, password)
        if user:
            login_user(user)
            return redirect(next_url)

        error_message = "ログイン情報が正しくありません。"

    return render_template("login.html", error_message=error_message, next_url=next_url)


@app.route("/apps/attendance/app/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/apps/attendance/app/payment", methods=["GET", "POST"])
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


@app.route("/apps/attendance/app")
@login_required
def index():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT DISTINCT substr(date,1,7) as month
        FROM matches
        WHERE user_id=?
        ORDER BY month
        """,
        (session["user_id"],),
    )
    months = [row["month"] for row in c.fetchall()]
    active_month = request.args.get("month", "").strip()
    if active_month not in months:
        active_month = months[0] if months else ""

    c.execute(
        """
        SELECT *
        FROM matches
        WHERE user_id=?
        ORDER BY date, start_time
        """,
        (session["user_id"],),
    )
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
        WHERE m.user_id=?
        GROUP BY substr(m.date,1,7), a.name
        ORDER BY month, first_attendance_id
        """,
        (session["user_id"],),
    )
    month_member_rows = c.fetchall()
    members_by_month = {month: [] for month in months}
    for row in month_member_rows:
        month = row["month"]
        if month in members_by_month:
            members_by_month[month].append(row["name"])

    c.execute(
        """
        SELECT a.match_id, a.name, a.status
        FROM attendance a
        JOIN matches m ON m.id = a.match_id
        WHERE m.user_id=?
        """,
        (session["user_id"],),
    )
    attendance_rows = c.fetchall()

    attendance_dict = {}
    for row in attendance_rows:
        attendance_dict[(row["match_id"], row["name"])] = normalize_status(row["status"])

    conn.close()

    return render_template(
        "index.html",
        months=months,
        active_month=active_month,
        month_data=month_data,
        members_by_month=members_by_month,
        attendance_dict=attendance_dict,
        team_name=session.get("team_name") or session.get("username", ""),
    )


@app.route("/apps/attendance/app/csv")
@login_required
def export_attendance_csv():
    month = request.args.get("month", "all").strip() or "all"
    return build_event_list_csv_response(session["user_id"], month)


@app.route("/apps/attendance/app/add", methods=["GET", "POST"])
@login_required
def add_match():
    current_month = request.args.get("month", "").strip()
    if request.method == "GET":
        return render_template("add.html", current_month=current_month)

    start_time = build_time_from_form("start_time")
    end_time = build_time_from_form("end_time")
    if not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
        return "start_time/end_time must be in 10-minute increments.", 400

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute(
        """
    INSERT INTO matches (user_id, date, start_time, end_time, opponent, place)
    VALUES (?, ?, ?, ?, ?, ?)
    """,
        (
            session["user_id"],
            request.form["date"],
            start_time,
            end_time,
            request.form["opponent"],
            request.form["place"],
        ),
    )

    conn.commit()
    conn.close()
    return_month = request.form.get("return_month", "").strip() or current_month
    if not return_month:
        return_month = request.form.get("date", "")[:7]
    return redirect_to_app_with_month(return_month)


@app.route("/apps/attendance/app/delete/<int:id>")
@login_required
def delete_match(id):
    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute("DELETE FROM attendance WHERE match_id=? AND user_id=?", (id, session["user_id"]))
    c.execute("DELETE FROM matches WHERE id=? AND user_id=?", (id, session["user_id"]))

    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/apps/attendance/app/duplicate/<int:id>")
@login_required
def duplicate_match(id):
    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()

    c.execute(
        """
    INSERT INTO matches (user_id, date, start_time, end_time, opponent, place)
    SELECT ?, date, start_time, end_time, opponent, place
    FROM matches
    WHERE id=? AND user_id=?
    """,
        (session["user_id"], id, session["user_id"]),
    )

    conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/apps/attendance/app/matches/action", methods=["POST"])
@login_required
def bulk_match_action():
    action = request.form.get("action", "")
    current_month = request.form.get("current_month", "").strip()
    selected_ids_raw = request.form.getlist("selected_ids")

    if not selected_ids_raw:
        return redirect_to_app_with_month(current_month)

    try:
        selected_ids = [int(match_id) for match_id in selected_ids_raw]
    except ValueError:
        return redirect_to_app_with_month(current_month)

    placeholders = ",".join("?" for _ in selected_ids)
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        f"""
        SELECT id, date, start_time, end_time, opponent, place
        FROM matches
        WHERE user_id=? AND id IN ({placeholders})
        ORDER BY date, start_time
        """,
        [session["user_id"], *selected_ids],
    )
    target_matches = c.fetchall()
    target_ids = [row["id"] for row in target_matches]

    if not target_ids:
        conn.close()
        return redirect_to_app_with_month(current_month)

    if action == "edit":
        conn.close()
        return redirect(url_for("edit_match", id=target_ids[0], month=current_month))
    if action == "attendance_check":
        conn.close()
        return redirect(url_for("attendance_check", match_id=target_ids[0], month=current_month))

    target_placeholders = ",".join("?" for _ in target_ids)

    if action == "duplicate":
        c.executemany(
            """
            INSERT INTO matches (user_id, date, start_time, end_time, opponent, place)
            SELECT ?, date, start_time, end_time, opponent, place
            FROM matches
            WHERE id=? AND user_id=?
            """,
            [(session["user_id"], match_id, session["user_id"]) for match_id in target_ids],
        )
    elif action == "delete":
        c.execute(
            f"DELETE FROM attendance WHERE user_id=? AND match_id IN ({target_placeholders})",
            [session["user_id"], *target_ids],
        )
        c.execute(
            f"DELETE FROM matches WHERE user_id=? AND id IN ({target_placeholders})",
            [session["user_id"], *target_ids],
        )
    else:
        conn.close()
        return redirect_to_app_with_month(current_month)

    conn.commit()
    conn.close()
    return redirect_to_app_with_month(current_month)


@app.route("/apps/attendance/app/attendance/check/<int:match_id>")
@login_required
def attendance_check(match_id):
    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM matches WHERE id=? AND user_id=?", (match_id, session["user_id"]))
    match = c.fetchone()
    if not match:
        conn.close()
        return redirect(url_for("index"))

    c.execute(
        """
        SELECT name, status
        FROM attendance
        WHERE match_id=? AND user_id=?
        ORDER BY id
        """,
        (match_id, session["user_id"]),
    )
    rows = c.fetchall()
    conn.close()

    grouped_members = {"\u53c2\u52a0": [], "\u4e0d\u53c2\u52a0": [], "\u672a\u5b9a": []}
    for row in rows:
        status = normalize_status(row["status"])
        if status in grouped_members:
            grouped_members[status].append(row["name"])

    match_data = dict(match)
    match_data["date_label"] = format_date_mmdd_with_weekday(match["date"])

    return render_template(
        "attendance_check.html",
        match=match_data,
        join_members=grouped_members["\u53c2\u52a0"],
        absent_members=grouped_members["\u4e0d\u53c2\u52a0"],
        undecided_members=grouped_members["\u672a\u5b9a"],
    )


@app.route("/apps/attendance/app/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_match(id):
    current_month = request.args.get("month", "").strip()
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
        WHERE id=? AND user_id=?
        """,
            (
                request.form["date"],
                start_time,
                end_time,
                request.form["opponent"],
                request.form["place"],
                id,
                session["user_id"],
            ),
        )
        conn.commit()
        conn.close()
        return_month = request.form.get("return_month", "").strip() or current_month
        if not return_month:
            return_month = request.form.get("date", "")[:7]
        return redirect_to_app_with_month(return_month)

    c.execute("SELECT * FROM matches WHERE id=? AND user_id=?", (id, session["user_id"]))
    match = c.fetchone()
    conn.close()

    if not match:
        return redirect_to_app_with_month(current_month)

    return render_template("edit.html", match=match, current_month=current_month)


@app.route("/apps/attendance/app/attendance/month", methods=["GET", "POST"])
@login_required
def attendance_month():
    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute(
        """
        SELECT DISTINCT substr(date,1,7) as month
        FROM matches
        WHERE user_id=?
        ORDER BY month
        """,
        (session["user_id"],),
    )
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
                "SELECT id FROM matches WHERE id=? AND user_id=?",
                (match_id, session["user_id"]),
            )
            match = c.fetchone()
            if not match:
                conn.close()
                return redirect_to_app_with_month(selected_month)

            c.execute(
                """
            INSERT INTO attendance (user_id, match_id, name, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(match_id, name)
            DO UPDATE SET status=excluded.status, user_id=excluded.user_id
            """,
                (session["user_id"], match_id, name, status),
            )

            conn.commit()

    matches = []
    attendance_dict = {}

    if selected_month:
        c.execute(
            """
        SELECT * FROM matches
        WHERE user_id=? AND substr(date,1,7)=?
        ORDER BY date, start_time
        """,
            (session["user_id"], selected_month),
        )
        for row in c.fetchall():
            match_data = dict(row)
            match_data["date_label"] = format_date_mmdd_with_weekday(row["date"])
            matches.append(match_data)

        if name:
            c.execute(
                """
            SELECT a.match_id, a.status
            FROM attendance a
            JOIN matches m ON m.id = a.match_id
            WHERE m.user_id=? AND a.name=?
            """,
                (session["user_id"], name),
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


@app.route("/apps/attendance/app/attendance/member/delete", methods=["POST"])
@login_required
def delete_member_attendance_by_month():
    month = request.args.get("month", "").strip()
    name = request.args.get("name", "").strip()

    if not month or not name:
        return redirect_to_app_with_month(month)

    conn = sqlite3.connect("schedule.db")
    c = conn.cursor()
    c.execute(
        """
        DELETE FROM attendance
        WHERE user_id=?
          AND name=?
          AND match_id IN (
              SELECT id
              FROM matches
              WHERE user_id=? AND substr(date,1,7)=?
          )
        """,
        (session["user_id"], name, session["user_id"], month),
    )
    conn.commit()
    conn.close()

    return redirect_to_app_with_month(month)


@app.route("/sitemap.xml")
def sitemap():
    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://mossan-store.com/</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/apps</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/apps/attendance/app/description</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/blog</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/blog/sports-attendance</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/blog/pta-attendance</loc>
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
