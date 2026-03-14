import csv
import io
import json
import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, Response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
PORTAL_DATA_PATH = Path("portal_data.json")


def generate_public_id():
    return secrets.token_urlsafe(12)


def generate_unique_public_id(cursor):
    while True:
        public_id = generate_public_id()
        cursor.execute("SELECT 1 FROM teams WHERE public_id=?", (public_id,))
        if not cursor.fetchone():
            return public_id


def portal_now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_portal_data():
    if not PORTAL_DATA_PATH.exists():
        return {
            "admins": [],
            "teams": [],
            "members": [],
            "events": [],
            "attendance": [],
            "counters": {
                "admin_id": 1,
                "team_id": 1,
                "member_id": 1,
                "event_id": 1,
                "attendance_id": 1,
            },
        }
    return json.loads(PORTAL_DATA_PATH.read_text(encoding="utf-8"))


def save_portal_data(data):
    PORTAL_DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def next_portal_id(data, counter_name):
    value = data["counters"][counter_name]
    data["counters"][counter_name] += 1
    return value


def portal_get_admin_by_email(email):
    data = load_portal_data()
    for admin in data["admins"]:
        if admin["email"] == email:
            return admin
    return None


def portal_get_admin(admin_id):
    data = load_portal_data()
    for admin in data["admins"]:
        if admin["id"] == admin_id:
            return admin
    return None


def portal_find_or_create_admin(email):
    data = load_portal_data()
    for admin in data["admins"]:
        if admin["email"] == email:
            return admin

    admin = {
        "id": next_portal_id(data, "admin_id"),
        "email": email,
        "created_at": portal_now_text(),
    }
    data["admins"].append(admin)
    save_portal_data(data)
    return admin


def portal_get_teams_for_admin(admin_id):
    data = load_portal_data()
    return [team for team in data["teams"] if team["admin_id"] == admin_id]


def portal_get_team_by_public_id(public_id):
    data = load_portal_data()
    for team in data["teams"]:
        if team["public_id"] == public_id:
            return team
    return None


def portal_get_team(team_id):
    data = load_portal_data()
    for team in data["teams"]:
        if team["id"] == team_id:
            return team
    return None


def portal_create_team(admin_id, name):
    data = load_portal_data()
    team = {
        "id": next_portal_id(data, "team_id"),
        "admin_id": admin_id,
        "name": name,
        "public_id": generate_public_id(),
        "created_at": portal_now_text(),
    }
    data["teams"].append(team)
    save_portal_data(data)
    return team


def portal_delete_team(admin_id, team_id):
    data = load_portal_data()
    target_team = next(
        (
            team
            for team in data["teams"]
            if team["id"] == team_id and team["admin_id"] == admin_id
        ),
        None,
    )
    if not target_team:
        return False

    data["teams"] = [team for team in data["teams"] if team["id"] != team_id]
    data["members"] = [member for member in data["members"] if member["team_id"] != team_id]
    data["events"] = [event for event in data["events"] if event["team_id"] != team_id]
    data["attendance"] = [row for row in data["attendance"] if row["team_id"] != team_id]
    save_portal_data(data)
    return True


def portal_get_members(team_id):
    data = load_portal_data()
    return sorted(
        [member for member in data["members"] if member["team_id"] == team_id],
        key=lambda item: item["name"].lower(),
    )


def portal_add_member(team_id, name):
    data = load_portal_data()
    for member in data["members"]:
        if member["team_id"] == team_id and member["name"] == name:
            return member

    member = {
        "id": next_portal_id(data, "member_id"),
        "team_id": team_id,
        "name": name,
        "created_at": portal_now_text(),
    }
    data["members"].append(member)
    save_portal_data(data)
    return member


def portal_delete_member(team_id, name):
    data = load_portal_data()
    target_name = (name or "").strip()
    if not target_name:
        return False

    had_member = any(
        member["team_id"] == team_id and member["name"] == target_name
        for member in data["members"]
    )
    had_attendance = any(
        row["team_id"] == team_id and row["member_name"] == target_name
        for row in data["attendance"]
    )
    if not had_member and not had_attendance:
        return False

    data["members"] = [
        member
        for member in data["members"]
        if not (member["team_id"] == team_id and member["name"] == target_name)
    ]
    data["attendance"] = [
        row
        for row in data["attendance"]
        if not (row["team_id"] == team_id and row["member_name"] == target_name)
    ]
    save_portal_data(data)
    return True


def portal_get_events(team_ids):
    data = load_portal_data()
    team_id_set = set(team_ids)
    return sorted(
        [event for event in data["events"] if event["team_id"] in team_id_set],
        key=lambda item: (item.get("date", ""), item.get("start_time", ""), item["id"]),
    )


def portal_create_event(team_id, date, start_time, end_time, opponent, place):
    data = load_portal_data()
    event = {
        "id": next_portal_id(data, "event_id"),
        "team_id": team_id,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "opponent": opponent,
        "place": place,
        "created_at": portal_now_text(),
    }
    data["events"].append(event)
    save_portal_data(data)
    return event


def portal_get_event(team_id, event_id):
    data = load_portal_data()
    for event in data["events"]:
        if event["team_id"] == team_id and event["id"] == event_id:
            return event
    return None


def portal_update_event(team_id, event_id, date, start_time, end_time, opponent, place):
    data = load_portal_data()
    for event in data["events"]:
        if event["team_id"] == team_id and event["id"] == event_id:
            event["date"] = date
            event["start_time"] = start_time
            event["end_time"] = end_time
            event["opponent"] = opponent
            event["place"] = place
            save_portal_data(data)
            return event
    return None


def portal_delete_event(team_id, event_id):
    data = load_portal_data()
    data["events"] = [
        event for event in data["events"] if not (event["team_id"] == team_id and event["id"] == event_id)
    ]
    data["attendance"] = [
        row for row in data["attendance"] if not (row["team_id"] == team_id and row.get("event_id") == event_id)
    ]
    save_portal_data(data)


def portal_duplicate_event(team_id, event_id):
    event = portal_get_event(team_id, event_id)
    if not event:
        return None
    return portal_create_event(
        team_id,
        event["date"],
        event["start_time"],
        event["end_time"],
        event["opponent"],
        event["place"],
    )


def portal_upsert_attendance(team_id, event_id, member_name, status):
    data = load_portal_data()
    existing = None
    for row in data["attendance"]:
        if row["team_id"] == team_id and row.get("event_id") == event_id and row["member_name"] == member_name:
            existing = row
            break

    if existing:
        existing["status"] = status
        existing["updated_at"] = portal_now_text()
    else:
        data["attendance"].append(
            {
                "id": next_portal_id(data, "attendance_id"),
                "team_id": team_id,
                "event_id": event_id,
                "member_name": member_name,
                "status": status,
                "updated_at": portal_now_text(),
            }
        )
    save_portal_data(data)


def portal_get_attendance(team_id):
    data = load_portal_data()
    order = {"参加": 0, "未定": 1, "不参加": 2}
    return sorted(
        [row for row in data["attendance"] if row["team_id"] == team_id],
        key=lambda item: (order.get(item["status"], 99), item["member_name"].lower()),
    )


def portal_get_attendance_for_event(team_id, event_id):
    data = load_portal_data()
    rows = [row for row in data["attendance"] if row["team_id"] == team_id and row.get("event_id") == event_id]
    return sorted(rows, key=lambda item: item["member_name"].lower())


def portal_delete_member_attendance_by_month(team_id, month, name):
    data = load_portal_data()
    month_event_ids = {
        event["id"]
        for event in data["events"]
        if event["team_id"] == team_id and event.get("date", "").startswith(month)
    }
    data["attendance"] = [
        row
        for row in data["attendance"]
        if not (
            row["team_id"] == team_id
            and row["member_name"] == name
            and row.get("event_id") in month_event_ids
        )
    ]
    save_portal_data(data)


def portal_build_event_list_csv_response(team_id, month="all"):
    events = portal_get_events([team_id])
    if month and month != "all":
        events = [event for event in events if event.get("date", "").startswith(month)]

    data = load_portal_data()
    target_event_ids = {event["id"] for event in events}
    attendance_rows = [
        row
        for row in data["attendance"]
        if row["team_id"] == team_id and row.get("event_id") in target_event_ids
    ]
    attendance_rows.sort(key=lambda item: item["id"])

    members = []
    seen_members = set()
    for row in attendance_rows:
        member_name = row["member_name"]
        if member_name not in seen_members:
            seen_members.add(member_name)
            members.append(member_name)

    attendance_dict = {}
    for row in attendance_rows:
        attendance_dict[(row.get("event_id"), row["member_name"])] = normalize_status(row["status"])

    status_symbol_map = {"参加": "○", "不参加": "×", "未定": "△"}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["日付", "時間", "内容", "場所", "参加", "不参加", "未定", *members])

    for event in events:
        join_count = 0
        absent_count = 0
        undecided_count = 0
        member_cells = []

        for member in members:
            status = attendance_dict.get((event["id"], member), "")
            if status == "参加":
                join_count += 1
            elif status == "不参加":
                absent_count += 1
            elif status == "未定":
                undecided_count += 1
            member_cells.append(status_symbol_map.get(status, "-"))

        writer.writerow(
            [
                event["date"],
                f"{event['start_time']}~{event['end_time']}",
                event["opponent"],
                event["place"],
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


def build_member_legacy_index_context(team, active_month=""):
    events = portal_get_events([team["id"]])
    data = load_portal_data()
    attendance_rows = [
        row for row in data["attendance"] if row["team_id"] == team["id"]
    ]
    attendance_rows.sort(key=lambda item: item["id"])

    months = sorted({event["date"][:7] for event in events if event.get("date")})
    if active_month not in months:
        active_month = months[0] if months else ""

    events_with_labels = []
    for event in events:
        event_data = dict(event)
        event_data["date_label"] = format_date_mmdd_with_weekday(event["date"])
        events_with_labels.append(event_data)

    month_data = {
        month: [event for event in events_with_labels if event["date"].startswith(month)]
        for month in months
    }
    members_by_month = {}
    for month in months:
        month_event_ids = {
            event["id"]
            for event in month_data[month]
        }
        month_members = []
        seen_members = set()
        for row in attendance_rows:
            member_name = row["member_name"]
            if row.get("event_id") not in month_event_ids or member_name in seen_members:
                continue
            seen_members.add(member_name)
            month_members.append(member_name)
        members_by_month[month] = month_members

    attendance_dict = {}
    for row in attendance_rows:
        attendance_dict[(row.get("event_id"), row["member_name"])] = normalize_status(row["status"])

    return {
        "team_name": team["name"],
        "months": months,
        "active_month": active_month,
        "month_data": month_data,
        "members_by_month": members_by_month,
        "attendance_dict": attendance_dict,
        "public_id": team["public_id"],
    }


def redirect_to_team_month(public_id, month=None):
    month_value = (month or "").strip()
    if month_value:
        return redirect(url_for("member_team_page", public_id=public_id, month=month_value))
    return redirect(url_for("member_team_page", public_id=public_id))


def get_db_connection():
    conn = sqlite3.connect("schedule.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    try:
        conn = sqlite3.connect("schedule.db")
        c = conn.cursor()
    except sqlite3.Error:
        return

    # New admin/team foundation for role separation and fixed member URLs.
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        name TEXT NOT NULL,
        public_id TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        FOREIGN KEY(admin_id) REFERENCES admins(id)
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS team_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(team_id, name),
        FOREIGN KEY(team_id) REFERENCES teams(id)
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS team_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        member_name TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, member_name),
        FOREIGN KEY(team_id) REFERENCES teams(id)
    )
    """
    )

    c.execute("PRAGMA table_info(admins)")
    admin_columns = [row[1] for row in c.fetchall()]
    if "email" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN email TEXT")
    if "created_at" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN created_at TEXT")

    c.execute("PRAGMA table_info(teams)")
    team_columns = [row[1] for row in c.fetchall()]
    if "admin_id" not in team_columns:
        c.execute("ALTER TABLE teams ADD COLUMN admin_id INTEGER")
    if "public_id" not in team_columns:
        c.execute("ALTER TABLE teams ADD COLUMN public_id TEXT")
    if "created_at" not in team_columns:
        c.execute("ALTER TABLE teams ADD COLUMN created_at TEXT")

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
    if "email" not in user_columns:
        c.execute("ALTER TABLE users ADD COLUMN email TEXT")
        user_columns.append("email")

    expected_user_columns = {"id", "username", "password_hash", "created_at", "email"}
    if set(user_columns) != expected_user_columns:
        c.execute("ALTER TABLE users RENAME TO users_legacy")
        c.execute(
            """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            email TEXT
        )
        """
        )
        c.execute(
            """
        INSERT INTO users (id, username, password_hash, created_at, email)
        SELECT id, username, password_hash, created_at, email
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

    # Ensure all team rows have a public ID for the fixed member URL and a timestamp.
    c.execute("SELECT id, public_id, created_at FROM teams")
    existing_teams = c.fetchall()
    for team_id, public_id, created_at in existing_teams:
        if not public_id:
            c.execute(
                "UPDATE teams SET public_id=? WHERE id=?",
                (generate_unique_public_id(c), team_id),
            )
        if not created_at:
            c.execute(
                "UPDATE teams SET created_at=? WHERE id=?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), team_id),
            )

    try:
        conn.commit()
    except sqlite3.Error:
        pass
    conn.close()


try:
    init_db()
except sqlite3.Error:
    pass


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return func(*args, **kwargs)

    return wrapper


def admin_login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin_login_entry", next=request.path))
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


def get_team_by_public_id(public_id):
    return portal_get_team_by_public_id(public_id)


def get_admin_by_email(email):
    return portal_get_admin_by_email(email)


def get_teams_for_admin(admin_id):
    return portal_get_teams_for_admin(admin_id)


def normalize_member_attendance_status(value):
    status_map = {
        "参加": "参加",
        "出席": "参加",
        "attend": "参加",
        "不参加": "不参加",
        "欠席": "不参加",
        "absent": "不参加",
        "未定": "未定",
        "undecided": "未定",
    }
    return status_map.get((value or "").strip(), "")


def get_team_members(team_id):
    return portal_get_members(team_id)


def get_team_attendance_rows(team_id):
    return portal_get_attendance(team_id)


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


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login_entry():
    next_url = request.args.get("next") or request.form.get("next") or url_for("admin_dashboard")
    error_message = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or "@" not in email:
            error_message = "メールアドレスを入力してください。"
        else:
            admin = portal_find_or_create_admin(email)
            session["admin_id"] = admin["id"]
            session["admin_email"] = admin["email"]
            return redirect(next_url)

    return render_template(
        "admin_portal_login.html",
        error_message=error_message,
        next_url=next_url,
    )


@app.route("/admin")
@app.route("/admin/dashboard", methods=["GET", "POST"])
@admin_login_required
def admin_dashboard():
    teams = get_teams_for_admin(session["admin_id"])
    error_message = request.args.get("error_message", "").strip()
    success_message = request.args.get("success_message", "").strip()

    if request.method == "POST":
        team_name = request.form.get("team_name", "").strip()
        if not team_name:
            error_message = "チーム名を入力してください。"
        else:
            portal_create_team(session["admin_id"], team_name)
            success_message = "チームを作成しました。"
            teams = get_teams_for_admin(session["admin_id"])

    return render_template(
        "admin_dashboard_cards_v2.html",
        admin_email=session.get("admin_email", ""),
        teams=teams,
        error_message=error_message,
        success_message=success_message,
    )


@app.route("/admin/teams/<int:team_id>/delete", methods=["POST"])
@admin_login_required
def admin_delete_team(team_id):
    if portal_delete_team(session["admin_id"], team_id):
        return redirect(url_for("admin_dashboard", success_message="チームを削除しました。"))
    return redirect(url_for("admin_dashboard", error_message="チームを削除できませんでした。"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_email", None)
    return redirect(url_for("admin_login_entry"))


@app.route("/team/<public_id>", methods=["GET", "POST"])
def member_team_page(public_id):
    team = get_team_by_public_id(public_id)
    if not team:
        return render_template("public_index_v2.html", team_name="Guest", months=[]), 404

    active_month = request.args.get("month", "").strip()
    context = build_member_legacy_index_context(team, active_month)
    return render_template("public_index_v2.html", **context)


@app.route("/team/<public_id>/add", methods=["GET", "POST"])
def public_add_match(public_id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))

    current_month = request.args.get("month", "").strip()
    if request.method == "GET":
        return render_template("public_add.html", public_id=public_id, current_month=current_month)

    start_time = build_time_from_form("start_time")
    end_time = build_time_from_form("end_time")
    if not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
        return "start_time/end_time must be in 10-minute increments.", 400

    portal_create_event(
        team["id"],
        request.form["date"],
        start_time,
        end_time,
        request.form["opponent"],
        request.form["place"],
    )

    return_month = request.form.get("return_month", "").strip() or current_month
    if not return_month:
        return_month = request.form.get("date", "")[:7]
    return redirect_to_team_month(public_id, return_month)


@app.route("/team/<public_id>/delete/<int:id>")
def public_delete_match(public_id, id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))
    portal_delete_event(team["id"], id)
    return redirect(url_for("member_team_page", public_id=public_id))


@app.route("/team/<public_id>/duplicate/<int:id>")
def public_duplicate_match(public_id, id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))
    portal_duplicate_event(team["id"], id)
    return redirect(url_for("member_team_page", public_id=public_id))


@app.route("/team/<public_id>/matches/action", methods=["POST"])
def public_bulk_match_action(public_id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))

    action = request.form.get("action", "")
    current_month = request.form.get("current_month", "").strip()
    selected_ids_raw = request.form.getlist("selected_ids")
    if not selected_ids_raw:
        return redirect_to_team_month(public_id, current_month)

    try:
        selected_ids = [int(match_id) for match_id in selected_ids_raw]
    except ValueError:
        return redirect_to_team_month(public_id, current_month)

    events = portal_get_events([team["id"]])
    target_ids = [event["id"] for event in events if event["id"] in selected_ids]
    if not target_ids:
        return redirect_to_team_month(public_id, current_month)

    if action == "edit":
        return redirect(url_for("public_edit_match", public_id=public_id, id=target_ids[0], month=current_month))
    if action == "attendance_check":
        return redirect(url_for("public_attendance_check", public_id=public_id, match_id=target_ids[0], month=current_month))
    if action == "duplicate":
        for match_id in target_ids:
            portal_duplicate_event(team["id"], match_id)
    elif action == "delete":
        for match_id in target_ids:
            portal_delete_event(team["id"], match_id)

    return redirect_to_team_month(public_id, current_month)


@app.route("/team/<public_id>/attendance/check/<int:match_id>")
def public_attendance_check(public_id, match_id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))

    match = portal_get_event(team["id"], match_id)
    if not match:
        return redirect(url_for("member_team_page", public_id=public_id))

    rows = portal_get_attendance_for_event(team["id"], match_id)
    grouped_members = {"参加": [], "不参加": [], "未定": []}
    for row in rows:
        status = normalize_status(row["status"])
        if status in grouped_members:
            grouped_members[status].append(row["member_name"])

    match_data = dict(match)
    match_data["date_label"] = format_date_mmdd_with_weekday(match["date"])
    return render_template(
        "public_attendance_check.html",
        public_id=public_id,
        match=match_data,
        join_members=grouped_members["参加"],
        absent_members=grouped_members["不参加"],
        undecided_members=grouped_members["未定"],
    )


@app.route("/team/<public_id>/edit/<int:id>", methods=["GET", "POST"])
def public_edit_match(public_id, id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))

    current_month = request.args.get("month", "").strip()
    match = portal_get_event(team["id"], id)
    if not match:
        return redirect_to_team_month(public_id, current_month)

    if request.method == "POST":
        start_time = build_time_from_form("start_time")
        end_time = build_time_from_form("end_time")
        if not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
            return "start_time/end_time must be in 10-minute increments.", 400

        portal_update_event(
            team["id"],
            id,
            request.form["date"],
            start_time,
            end_time,
            request.form["opponent"],
            request.form["place"],
        )
        return_month = request.form.get("return_month", "").strip() or current_month
        if not return_month:
            return_month = request.form.get("date", "")[:7]
        return redirect_to_team_month(public_id, return_month)

    return render_template("public_edit.html", public_id=public_id, match=match, current_month=current_month)


@app.route("/team/<public_id>/attendance/month", methods=["GET", "POST"])
def public_attendance_month(public_id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))

    events = portal_get_events([team["id"]])
    months = sorted({event["date"][:7] for event in events if event.get("date")})
    selected_month = request.args.get("month")
    name = request.args.get("name")
    error_message = ""

    if not selected_month and months:
        selected_month = months[0]

    if request.method == "POST":
        selected_month = request.form.get("month") or selected_month
        name = request.form.get("name", "").strip()
        match_id = int(request.form["match_id"])
        status = normalize_status(request.form["status"])

        if not name:
            error_message = "名前を入力してから出欠を登録してください。"
        else:
            match = portal_get_event(team["id"], match_id)
            if not match:
                return redirect_to_team_month(public_id, selected_month)

            portal_add_member(team["id"], name)
            portal_upsert_attendance(team["id"], match_id, name, status)

    matches = []
    attendance_dict = {}
    if selected_month:
        matches = [dict(event) for event in events if event["date"].startswith(selected_month)]
        for match in matches:
            match["date_label"] = format_date_mmdd_with_weekday(match["date"])

        if name:
            for row in portal_get_attendance(team["id"]):
                if row["member_name"] == name:
                    attendance_dict[row.get("event_id")] = normalize_status(row["status"])

    return render_template(
        "public_attendance_month.html",
        public_id=public_id,
        months=months,
        selected_month=selected_month,
        matches=matches,
        name=name,
        attendance_dict=attendance_dict,
        error_message=error_message,
        edit_mode=bool(name),
    )


@app.route("/team/<public_id>/attendance/member/delete", methods=["POST"])
def public_delete_member_attendance_by_month(public_id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))

    month = request.args.get("month", "").strip()
    name = request.args.get("name", "").strip()
    if name:
        portal_delete_member(team["id"], name)
    return redirect_to_team_month(public_id, month)


@app.route("/team/<public_id>/csv")
def public_export_attendance_csv(public_id):
    team = get_team_by_public_id(public_id)
    if not team:
        return redirect(url_for("attendance_description"))

    month = request.args.get("month", "all").strip() or "all"
    return portal_build_event_list_csv_response(team["id"], month)


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
    return redirect(url_for("admin_login_entry"))


@app.route("/apps/attendance/app/login", methods=["GET", "POST"])
def login():
    return redirect(url_for("admin_login_entry"))


@app.route("/apps/attendance/app/logout")
def logout():
    session.clear()
    return redirect(url_for("admin_login_entry"))


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
    return redirect(url_for("admin_dashboard"))


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
