from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import psycopg2
from psycopg2.extras import DictCursor, Json
from werkzeug.security import check_password_hash, generate_password_hash

from flask import Response, Flask, jsonify, redirect, render_template, request, session, url_for


BASE_DIR = Path(__file__).resolve().parent
PROJECTS_SCHEMA = "lightsketch_projects_v1"
DATABASE_URL = os.environ.get("LIGHTSKETCH_DATABASE_URL", "").strip()
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
RESEND_API_BASE_URL = os.environ.get("RESEND_API_BASE_URL", "https://api.resend.com").strip().rstrip("/")
LIGHTSKETCH_MAIL_FROM = os.environ.get("LIGHTSKETCH_MAIL_FROM", "").strip()
PUBLIC_SIGNUP_ENABLED = os.environ.get("LIGHTSKETCH_PUBLIC_SIGNUP_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
APP_NAME = "LightSketch+"
PASSWORD_RESET_EXPIRES_HOURS = 2
SIGNUP_EXPIRES_HOURS = 24
_DB_READY = False
_RATE_LIMIT_BUCKETS: dict[str, list[datetime]] = {}


DEFAULT_STATE: dict[str, Any] = {
    "project_name": "sample",
    "source": {
        "type": "point",
        "x": 360,
        "y": 350,
        "angle_deg": 270,
        "spread_deg": 180,
        "ray_count": 90,
    },
    "reflector": {
        "reflectance": 0.85,
        "points": [
            {"x": 140, "y": 145},
            {"x": 185, "y": 260},
            {"x": 250, "y": 335},
            {"x": 360, "y": 398},
            {"x": 470, "y": 335},
            {"x": 535, "y": 260},
            {"x": 580, "y": 145},
        ],
    },
    "reflectors": [
        {
            "id": "reflector-1",
            "name": "反射面 1",
            "reflectance": 0.85,
            "points": [
                {"x": 140, "y": 145},
                {"x": 185, "y": 260},
                {"x": 250, "y": 335},
                {"x": 360, "y": 398},
                {"x": 470, "y": 335},
                {"x": 535, "y": 260},
                {"x": 580, "y": 145},
            ],
            "segments": [
                {"type": "line"},
                {"type": "line"},
                {"type": "line"},
                {"type": "line"},
                {"type": "line"},
                {"type": "line"},
            ],
        }
    ],
    "lenses": [],
    "screen": {
        "x1": 100,
        "y1": 55,
        "x2": 620,
        "y2": 55,
    },
    "compare": {
        "enabled": False,
        "snapshot": None,
    },
}

NEW_PROJECT_STATE: dict[str, Any] = {
    "project_name": "新規プロジェクト",
    "source": {
        "type": "point",
        "x": 360,
        "y": 350,
        "angle_deg": 270,
        "spread_deg": 90,
        "ray_count": 90,
    },
    "reflector": {
        "reflectance": 0.85,
        "points": [],
    },
    "reflectors": [],
    "lenses": [],
    "screen": {
        "x1": 100,
        "y1": 55,
        "x2": 620,
        "y2": 55,
    },
    "compare": {
        "enabled": False,
        "snapshot": None,
    },
}


SAMPLES: dict[str, dict[str, Any]] = {
    "soft_bowl": DEFAULT_STATE,
    "narrow_throw": {
        **DEFAULT_STATE,
        "project_name": "narrow_throw",
        "source": {**DEFAULT_STATE["source"], "spread_deg": 42, "ray_count": 80},
        "reflector": {
            "reflectance": 0.9,
            "points": [
                {"x": 230, "y": 355},
                {"x": 245, "y": 250},
                {"x": 310, "y": 150},
                {"x": 360, "y": 125},
                {"x": 410, "y": 150},
                {"x": 475, "y": 250},
                {"x": 490, "y": 355},
            ],
        },
        "reflectors": [
            {
                "id": "reflector-1",
                "name": "反射面 1",
                "reflectance": 0.9,
                "points": [
                    {"x": 230, "y": 355},
                    {"x": 245, "y": 250},
                    {"x": 310, "y": 150},
                    {"x": 360, "y": 125},
                    {"x": 410, "y": 150},
                    {"x": 475, "y": 250},
                    {"x": 490, "y": 355},
                ],
                "segments": [
                    {"type": "line"},
                    {"type": "arc", "bulge": -0.18},
                    {"type": "line"},
                    {"type": "line"},
                    {"type": "arc", "bulge": -0.18},
                    {"type": "line"},
                ],
            }
        ],
    },
    "wide_wash": {
        **DEFAULT_STATE,
        "project_name": "wide_wash",
        "source": {**DEFAULT_STATE["source"], "spread_deg": 105, "ray_count": 120},
        "reflector": {
            "reflectance": 0.78,
            "points": [
                {"x": 175, "y": 335},
                {"x": 205, "y": 275},
                {"x": 285, "y": 220},
                {"x": 360, "y": 205},
                {"x": 435, "y": 220},
                {"x": 515, "y": 275},
                {"x": 545, "y": 335},
            ],
        },
        "reflectors": [
            {
                "id": "reflector-1",
                "name": "反射面 1",
                "reflectance": 0.78,
                "points": [
                    {"x": 175, "y": 335},
                    {"x": 205, "y": 275},
                    {"x": 285, "y": 220},
                    {"x": 360, "y": 205},
                    {"x": 435, "y": 220},
                    {"x": 515, "y": 275},
                    {"x": 545, "y": 335},
                ],
                "segments": [
                    {"type": "arc", "bulge": 0.16},
                    {"type": "line"},
                    {"type": "arc", "bulge": 0.16},
                    {"type": "arc", "bulge": 0.16},
                    {"type": "line"},
                    {"type": "arc", "bulge": 0.16},
                ],
            }
        ],
    },
}


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("LIGHTSKETCH_SECRET_KEY", "lightsketch-dev")
app.permanent_session_lifetime = timedelta(days=30)


DXF_HEIGHT = 430
ARC_STEPS = 12


def dxf_y(value: float) -> float:
    return DXF_HEIGHT - float(value)


def dxf_point(point: dict[str, Any]) -> tuple[float, float]:
    return float(point.get("x", 0)), dxf_y(float(point.get("y", 0)))


def dxf_line(lines: list[str], start: dict[str, Any], end: dict[str, Any], layer: str) -> None:
    x1, y1 = dxf_point(start)
    x2, y2 = dxf_point(end)
    lines.extend(
        [
            "0",
            "LINE",
            "8",
            layer,
            "10",
            f"{x1:.4f}",
            "20",
            f"{y1:.4f}",
            "30",
            "0",
            "11",
            f"{x2:.4f}",
            "21",
            f"{y2:.4f}",
            "31",
            "0",
        ]
    )


def dxf_circle(lines: list[str], point: dict[str, Any], radius: float, layer: str) -> None:
    x, y = dxf_point(point)
    lines.extend(
        [
            "0",
            "CIRCLE",
            "8",
            layer,
            "10",
            f"{x:.4f}",
            "20",
            f"{y:.4f}",
            "30",
            "0",
            "40",
            f"{radius:.4f}",
        ]
    )


def add_point(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    return {"x": float(a.get("x", 0)) + float(b.get("x", 0)), "y": float(a.get("y", 0)) + float(b.get("y", 0))}


def multiply_point(point: dict[str, Any], scalar: float) -> dict[str, float]:
    return {"x": float(point.get("x", 0)) * scalar, "y": float(point.get("y", 0)) * scalar}


def arc_control_point(start: dict[str, Any], end: dict[str, Any], segment: dict[str, Any]) -> dict[str, float]:
    midpoint = multiply_point(add_point(start, end), 0.5)
    dx = float(end.get("x", 0)) - float(start.get("x", 0))
    dy = float(end.get("y", 0)) - float(start.get("y", 0))
    length = (dx * dx + dy * dy) ** 0.5 or 1
    normal = {"x": -dy / length, "y": dx / length}
    bulge = float(segment.get("bulge", 0.22))
    return {"x": midpoint["x"] + normal["x"] * length * bulge, "y": midpoint["y"] + normal["y"] * length * bulge}


def quadratic_point(start: dict[str, Any], control: dict[str, Any], end: dict[str, Any], t: float) -> dict[str, float]:
    inv = 1 - t
    return {
        "x": inv * inv * float(start.get("x", 0)) + 2 * inv * t * float(control.get("x", 0)) + t * t * float(end.get("x", 0)),
        "y": inv * inv * float(start.get("y", 0)) + 2 * inv * t * float(control.get("y", 0)) + t * t * float(end.get("y", 0)),
    }


def reflector_segments(reflector: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    points = reflector.get("points") or []
    segments = reflector.get("segments") or []
    output: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index in range(max(0, len(points) - 1)):
        start = points[index]
        end = points[index + 1]
        segment = segments[index] if index < len(segments) else {"type": "line"}
        if segment.get("type") != "arc":
            output.append((start, end))
            continue
        control = arc_control_point(start, end, segment)
        previous = start
        for step in range(1, ARC_STEPS + 1):
            current = quadratic_point(start, control, end, step / ARC_STEPS)
            output.append((previous, current))
            previous = current
    return output


def lens_segments(lens: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    points = lens.get("points") or []
    segments = lens.get("segments") or []
    if len(points) < 3:
        return []
    output: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index in range(len(points)):
        start = points[index]
        end = points[(index + 1) % len(points)]
        segment = segments[index] if index < len(segments) else {"type": "line"}
        if segment.get("type") != "arc":
            output.append((start, end))
            continue
        control = arc_control_point(start, end, segment)
        previous = start
        for step in range(1, ARC_STEPS + 1):
            current = quadratic_point(start, control, end, step / ARC_STEPS)
            output.append((previous, current))
            previous = current
    return output


def state_to_dxf(state: dict[str, Any]) -> str:
    lines = ["0", "SECTION", "2", "HEADER", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    source = state.get("source") or {}
    source_point = {"x": source.get("x", 0), "y": source.get("y", 0)}
    dxf_circle(lines, source_point, 6, "SOURCE")
    angle = float(source.get("angle_deg", 270))
    direction = {"x": math.cos(math.radians(angle)), "y": math.sin(math.radians(angle))}
    source_end = {"x": float(source_point["x"]) + direction["x"] * 36, "y": float(source_point["y"]) + direction["y"] * 36}
    dxf_line(lines, source_point, source_end, "SOURCE")

    screen = state.get("screen") or {}
    dxf_line(lines, {"x": screen.get("x1", 0), "y": screen.get("y1", 0)}, {"x": screen.get("x2", 0), "y": screen.get("y2", 0)}, "DETECTOR")

    reflectors = state.get("reflectors")
    if not isinstance(reflectors, list):
        legacy = state.get("reflector") or {}
        reflectors = [{"points": legacy.get("points") or [], "segments": []}]
    for reflector in reflectors:
        for point in reflector.get("points") or []:
            dxf_circle(lines, point, 2.5, "CONTROL_POINTS")
        for start, end in reflector_segments(reflector):
            dxf_line(lines, start, end, "REFLECTOR")

    lenses = state.get("lenses") or []
    if isinstance(lenses, list):
        for lens in lenses:
            for point in lens.get("points") or []:
                dxf_circle(lines, point, 2.5, "LENS_CONTROL_POINTS")
            for start, end in lens_segments(lens):
                dxf_line(lines, start, end, "LENS")

    lines.extend(["0", "ENDSEC", "0", "EOF"])
    return "\n".join(lines) + "\n"


@app.after_request
def prevent_stale_pages(response):
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def clone_state(state: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(state))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def is_valid_email(value: str) -> bool:
    email = normalize_email(value)
    return "@" in email and "." in email.split("@")[-1]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def rate_limit_key(prefix: str, value: str = "") -> str:
    remote_addr = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip() or request.remote_addr or "unknown"
    return f"{prefix}:{remote_addr}:{normalize_email(value)}"


def check_rate_limit(key: str, *, window_seconds: int, max_attempts: int) -> bool:
    now = utc_now()
    window_start = now - timedelta(seconds=window_seconds)
    attempts = [attempt for attempt in _RATE_LIMIT_BUCKETS.get(key, []) if attempt >= window_start]
    if len(attempts) >= max_attempts:
        _RATE_LIMIT_BUCKETS[key] = attempts
        return False
    attempts.append(now)
    _RATE_LIMIT_BUCKETS[key] = attempts
    return True


def check_login_rate_limit() -> bool:
    return check_rate_limit(rate_limit_key("login"), window_seconds=15 * 60, max_attempts=12)


def check_signup_rate_limit(email: str) -> bool:
    return check_rate_limit(rate_limit_key("signup-ip"), window_seconds=60 * 60, max_attempts=8) and check_rate_limit(
        rate_limit_key("signup-email", email), window_seconds=60 * 60, max_attempts=4
    )


def check_password_reset_rate_limit(email: str) -> bool:
    return check_rate_limit(rate_limit_key("reset-ip"), window_seconds=60 * 60, max_attempts=8) and check_rate_limit(
        rate_limit_key("reset-email", email), window_seconds=60 * 60, max_attempts=4
    )


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("LIGHTSKETCH_DATABASE_URL is required.")
    ensure_db()
    return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)


def ensure_db() -> None:
    global _DB_READY
    if _DB_READY:
        return
    if not DATABASE_URL:
        return
    with psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS lightsketch_admins (
                    id SERIAL PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    active_project_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    confirmed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_login_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS lightsketch_pending_admin_signups (
                    id SERIAL PRIMARY KEY,
                    email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    remote_addr TEXT,
                    user_agent TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lightsketch_pending_admin_signups_email
                ON lightsketch_pending_admin_signups (email)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS lightsketch_password_reset_tokens (
                    id SERIAL PRIMARY KEY,
                    admin_id INTEGER NOT NULL REFERENCES lightsketch_admins(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    remote_addr TEXT,
                    user_agent TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    used_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lightsketch_password_reset_tokens_admin
                ON lightsketch_password_reset_tokens (admin_id)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS lightsketch_projects (
                    id TEXT PRIMARY KEY,
                    admin_id INTEGER NOT NULL REFERENCES lightsketch_admins(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    state JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lightsketch_projects_admin
                ON lightsketch_projects (admin_id)
                """
            )
        conn.commit()
    _DB_READY = True


def row_to_dict(row):
    return dict(row) if row else None


def get_admin_by_email(email: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM lightsketch_admins WHERE email=%s", (normalize_email(email),))
            return row_to_dict(cursor.fetchone())


def get_admin(admin_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM lightsketch_admins WHERE id=%s", (admin_id,))
            return row_to_dict(cursor.fetchone())


def create_admin(email: str, password_hash: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO lightsketch_admins (email, password_hash)
                VALUES (%s, %s)
                RETURNING *
                """,
                (normalize_email(email), password_hash),
            )
            admin = row_to_dict(cursor.fetchone())
        conn.commit()
    ensure_default_project(admin["id"])
    return admin


def authenticate_admin(email: str, password: str):
    admin = get_admin_by_email(email)
    if not admin or not check_password_hash(admin.get("password_hash") or "", password):
        return None
    touch_admin_last_login(admin["id"])
    return admin


def touch_admin_last_login(admin_id: int) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE lightsketch_admins SET last_login_at=NOW() WHERE id=%s", (admin_id,))
        conn.commit()


def create_pending_signup(email: str, password: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(hours=SIGNUP_EXPIRES_HOURS)
    remote_addr = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip() or request.remote_addr or ""
    user_agent = request.headers.get("User-Agent", "")[:1000]
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM lightsketch_pending_admin_signups WHERE email=%s", (normalize_email(email),))
            cursor.execute(
                """
                INSERT INTO lightsketch_pending_admin_signups
                    (email, password_hash, token_hash, remote_addr, user_agent, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    normalize_email(email),
                    generate_password_hash(password),
                    hash_token(token),
                    remote_addr,
                    user_agent,
                    expires_at,
                ),
            )
        conn.commit()
    return token


def confirm_pending_signup(token: str):
    token_digest = hash_token(token)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM lightsketch_pending_admin_signups
                WHERE token_hash=%s
                """,
                (token_digest,),
            )
            pending = row_to_dict(cursor.fetchone())
            if not pending:
                return None, "invalid"
            if pending["expires_at"] < utc_now():
                cursor.execute("DELETE FROM lightsketch_pending_admin_signups WHERE id=%s", (pending["id"],))
                conn.commit()
                return None, "expired"
            cursor.execute("SELECT * FROM lightsketch_admins WHERE email=%s", (pending["email"],))
            existing = row_to_dict(cursor.fetchone())
            if existing:
                cursor.execute("DELETE FROM lightsketch_pending_admin_signups WHERE email=%s", (pending["email"],))
                conn.commit()
                ensure_default_project(existing["id"])
                return existing, "already_exists"
            cursor.execute(
                """
                INSERT INTO lightsketch_admins (email, password_hash)
                VALUES (%s, %s)
                RETURNING *
                """,
                (pending["email"], pending["password_hash"]),
            )
            admin = row_to_dict(cursor.fetchone())
            cursor.execute("DELETE FROM lightsketch_pending_admin_signups WHERE id=%s", (pending["id"],))
        conn.commit()
    ensure_default_project(admin["id"])
    return admin, "created"


def create_password_reset(admin: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(hours=PASSWORD_RESET_EXPIRES_HOURS)
    remote_addr = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip() or request.remote_addr or ""
    user_agent = request.headers.get("User-Agent", "")[:1000]
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE lightsketch_password_reset_tokens
                SET used_at=NOW()
                WHERE admin_id=%s AND used_at IS NULL
                """,
                (admin["id"],),
            )
            cursor.execute(
                """
                INSERT INTO lightsketch_password_reset_tokens
                    (admin_id, token_hash, remote_addr, user_agent, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (admin["id"], hash_token(token), remote_addr, user_agent, expires_at),
            )
        conn.commit()
    return token


def reset_admin_password(token: str, new_password: str):
    token_digest = hash_token(token)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT reset_tokens.*, admins.email
                FROM lightsketch_password_reset_tokens reset_tokens
                JOIN lightsketch_admins admins ON admins.id = reset_tokens.admin_id
                WHERE reset_tokens.token_hash=%s AND reset_tokens.used_at IS NULL
                """,
                (token_digest,),
            )
            reset_row = row_to_dict(cursor.fetchone())
            if not reset_row:
                return None, "invalid"
            if reset_row["expires_at"] < utc_now():
                cursor.execute(
                    "UPDATE lightsketch_password_reset_tokens SET used_at=NOW() WHERE id=%s",
                    (reset_row["id"],),
                )
                conn.commit()
                return None, "expired"
            cursor.execute(
                "UPDATE lightsketch_admins SET password_hash=%s WHERE id=%s RETURNING *",
                (generate_password_hash(new_password), reset_row["admin_id"]),
            )
            admin = row_to_dict(cursor.fetchone())
            cursor.execute(
                "UPDATE lightsketch_password_reset_tokens SET used_at=NOW() WHERE id=%s",
                (reset_row["id"],),
            )
        conn.commit()
    return admin, "reset"


def mail_is_configured() -> bool:
    return bool(RESEND_API_KEY and LIGHTSKETCH_MAIL_FROM)


def send_mail(*, to_email: str, subject: str, body: str) -> None:
    if not mail_is_configured():
        raise RuntimeError("Resend mail is not configured.")
    payload = {
        "from": LIGHTSKETCH_MAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    data = json.dumps(payload).encode("utf-8")
    request_payload = Request(
        f"{RESEND_API_BASE_URL}/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "LightSketchPlus/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request_payload, timeout=10) as response:
            if response.status >= 300:
                raise RuntimeError(f"Resend API returned HTTP {response.status}.")
    except urllib_error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"Resend API returned HTTP {exc.code}: {error_body}") from exc


def send_signup_confirmation_email(email: str, confirmation_url: str) -> None:
    send_mail(
        to_email=email,
        subject=f"{APP_NAME} アカウント確認",
        body=f"{APP_NAME} の登録を完了するには、以下のURLを開いてください。\n\n{confirmation_url}\n\nこのURLは{SIGNUP_EXPIRES_HOURS}時間で期限切れになります。",
    )


def send_password_reset_email(email: str, reset_url: str) -> None:
    send_mail(
        to_email=email,
        subject=f"{APP_NAME} パスワード再設定",
        body=f"{APP_NAME} のパスワードを再設定するには、以下のURLを開いてください。\n\n{reset_url}\n\nこのURLは{PASSWORD_RESET_EXPIRES_HOURS}時間で期限切れになります。",
    )


def safe_next_url(value: str | None) -> str:
    fallback_url = url_for("index")
    raw_value = (value or "").strip()
    if not raw_value:
        return fallback_url
    parsed = urlsplit(raw_value)
    if parsed.scheme or parsed.netloc or not raw_value.startswith("/"):
        return fallback_url
    return raw_value


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id or not get_admin(admin_id):
            session.pop("admin_id", None)
            session.pop("admin_email", None)
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login", next=request.full_path if request.query_string else request.path))
        return view_func(*args, **kwargs)

    return wrapped


def current_admin_id() -> int:
    return int(session["admin_id"])


def project_id() -> str:
    return f"project-{uuid.uuid4().hex[:12]}"


def project_name_from_state(state: dict[str, Any], fallback: str = "プロジェクト 1") -> str:
    name = str(state.get("project_name") or "").strip()
    return name or fallback


def make_project(name: str, state: dict[str, Any], project_identifier: str | None = None) -> dict[str, Any]:
    next_state = clone_state(state)
    next_state["project_name"] = name
    return {
        "id": project_identifier or project_id(),
        "name": name,
        "state": next_state,
    }


def ensure_default_project(admin_id: int) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM lightsketch_projects WHERE admin_id=%s LIMIT 1", (admin_id,))
            if cursor.fetchone():
                return
            name = "プロジェクト 1"
            project = make_project(name, DEFAULT_STATE)
            cursor.execute(
                """
                INSERT INTO lightsketch_projects (id, admin_id, name, state)
                VALUES (%s, %s, %s, %s)
                """,
                (project["id"], admin_id, project["name"], Json(project["state"])),
            )
            cursor.execute(
                "UPDATE lightsketch_admins SET active_project_id=%s WHERE id=%s",
                (project["id"], admin_id),
            )
        conn.commit()


def normalize_project_row(row) -> dict[str, Any]:
    state = row["state"]
    if isinstance(state, str):
        state = json.loads(state)
    state = clone_state(state if isinstance(state, dict) else DEFAULT_STATE)
    name = str(row["name"] or project_name_from_state(state, "プロジェクト"))
    state["project_name"] = name
    return {
        "id": str(row["id"]),
        "name": name,
        "state": state,
    }


def read_project_store(admin_id: int) -> dict[str, Any]:
    ensure_default_project(admin_id)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT active_project_id FROM lightsketch_admins WHERE id=%s", (admin_id,))
            admin = row_to_dict(cursor.fetchone())
            cursor.execute(
                """
                SELECT * FROM lightsketch_projects
                WHERE admin_id=%s
                ORDER BY updated_at DESC, created_at DESC
                """,
                (admin_id,),
            )
            projects = [normalize_project_row(row) for row in cursor.fetchall()]
    active_project_id = str(admin.get("active_project_id") or "") if admin else ""
    if not any(project["id"] == active_project_id for project in projects):
        active_project_id = projects[0]["id"]
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE lightsketch_admins SET active_project_id=%s WHERE id=%s",
                    (active_project_id, admin_id),
                )
            conn.commit()
    return {
        "schema": PROJECTS_SCHEMA,
        "active_project_id": active_project_id,
        "projects": projects,
    }


def active_project(store: dict[str, Any]) -> dict[str, Any]:
    active_project_id = store.get("active_project_id")
    for project in store.get("projects", []):
        if project.get("id") == active_project_id:
            return project
    return store["projects"][0]


def read_state() -> dict[str, Any]:
    return clone_state(active_project(read_project_store(current_admin_id()))["state"])


def write_state(state: dict[str, Any]) -> None:
    admin_id = current_admin_id()
    store = read_project_store(admin_id)
    project = active_project(store)
    name = project_name_from_state(state, project["name"])
    next_state = clone_state(state)
    next_state["project_name"] = name
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE lightsketch_projects
                SET name=%s, state=%s, updated_at=NOW()
                WHERE id=%s AND admin_id=%s
                """,
                (name, Json(next_state), project["id"], admin_id),
            )
            cursor.execute(
                "UPDATE lightsketch_admins SET active_project_id=%s WHERE id=%s",
                (project["id"], admin_id),
            )
        conn.commit()


def project_summary(project: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(project["id"]),
        "name": str(project["name"]),
    }


def project_payload(store: dict[str, Any]) -> dict[str, Any]:
    project = active_project(store)
    return {
        "active_project_id": project["id"],
        "projects": [project_summary(item) for item in store["projects"]],
        "state": clone_state(project["state"]),
    }


def request_state_payload(fallback: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or fallback.get("project_name") or "プロジェクト").strip() or "プロジェクト"
    state = payload.get("state")
    if not isinstance(state, dict):
        state = fallback
    state = clone_state(state)
    state["project_name"] = name
    return name, state


@app.get("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    next_url = safe_next_url(request.args.get("next") or request.form.get("next"))
    error_message = request.args.get("error_message", "").strip()
    info_message = request.args.get("info_message", "").strip()

    if session.get("admin_id") and request.method == "GET":
        return redirect(next_url)

    if request.method == "POST":
        email = normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "1"

        if not is_valid_email(email):
            error_message = "メールアドレスを入力してください。"
        elif len(password) < 8:
            error_message = "パスワードは8文字以上で入力してください。"
        elif not check_login_rate_limit():
            error_message = "ログイン試行が多すぎます。時間をおいて再度お試しください。"
        else:
            existing_admin = get_admin_by_email(email)
            if existing_admin:
                admin = authenticate_admin(email, password)
                if admin:
                    ensure_default_project(admin["id"])
                    session.permanent = remember
                    session["admin_id"] = admin["id"]
                    session["admin_email"] = admin["email"]
                    return redirect(next_url)
                error_message = "メールアドレスまたはパスワードが正しくありません。"
            else:
                if not PUBLIC_SIGNUP_ENABLED:
                    error_message = "新規登録は現在停止中です。"
                elif not mail_is_configured():
                    error_message = "確認メールを送信できないため、新規登録を完了できません。"
                elif not check_signup_rate_limit(email):
                    error_message = "新規登録の試行が多すぎます。時間をおいて再度お試しください。"
                else:
                    token = create_pending_signup(email, password)
                    confirmation_url = url_for("confirm_signup", token=token, _external=True)
                    try:
                        send_signup_confirmation_email(email, confirmation_url)
                        info_message = "確認メールを送信しました。\nメール内のURLを開くと登録が完了します。"
                    except Exception as exc:
                        app.logger.warning("LightSketch+ signup confirmation email failed for %s: %s", email, exc)
                        error_message = "確認メールを送信できませんでした。時間をおいて再度お試しください。"

    if not error_message and not info_message:
        info_message = "メールアドレスが未登録の場合、新規アカウント登録を行います。"

    return render_template(
        "login.html",
        error_message=error_message,
        info_message=info_message,
        next_url=next_url,
        remember=request.form.get("remember") == "1",
    )


@app.get("/signup/confirm/<token>")
def confirm_signup(token):
    admin, status = confirm_pending_signup(token)
    if not admin:
        if status == "expired":
            return redirect(url_for("login", error_message="確認URLの有効期限が切れています。もう一度登録してください。"))
        return redirect(url_for("login", error_message="確認URLが無効です。もう一度登録してください。"))
    touch_admin_last_login(admin["id"])
    session["admin_id"] = admin["id"]
    session["admin_email"] = admin["email"]
    success_message = "アカウントの登録が完了しました。"
    if status == "already_exists":
        success_message = "登録済みのアカウントでログインしました。"
    return redirect(url_for("index", info_message=success_message))


@app.route("/password/forgot", methods=["GET", "POST"])
def password_forgot():
    error_message = ""
    info_message = ""
    submitted_email = normalize_email(request.form.get("email", ""))
    if request.method == "POST":
        if not is_valid_email(submitted_email):
            error_message = "メールアドレスを入力してください。"
        elif not mail_is_configured():
            error_message = "パスワード再設定メールを送信できません。管理者にお問い合わせください。"
        elif not check_password_reset_rate_limit(submitted_email):
            error_message = "パスワード再設定の試行が多すぎます。時間をおいて再度お試しください。"
        else:
            admin = get_admin_by_email(submitted_email)
            if admin:
                token = create_password_reset(admin)
                reset_url = url_for("password_reset", token=token, _external=True)
                try:
                    send_password_reset_email(submitted_email, reset_url)
                except Exception as exc:
                    app.logger.warning("LightSketch+ password reset email failed for %s: %s", submitted_email, exc)
                    error_message = "パスワード再設定メールを送信できませんでした。時間をおいて再度お試しください。"
            if not error_message:
                info_message = "登録済みのメールアドレスの場合、パスワード再設定用のメールを送信しました。"
    return render_template(
        "password_forgot.html",
        error_message=error_message,
        info_message=info_message,
        email=submitted_email,
    )


@app.route("/password/reset/<token>", methods=["GET", "POST"])
def password_reset(token):
    error_message = request.args.get("error_message", "").strip()
    info_message = request.args.get("info_message", "").strip()
    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(new_password) < 8:
            error_message = "パスワードは8文字以上で入力してください。"
        elif new_password != confirm_password:
            error_message = "確認用パスワードが一致しません。"
        else:
            admin, status = reset_admin_password(token, new_password)
            if admin:
                session.pop("admin_id", None)
                session.pop("admin_email", None)
                session.permanent = False
                return redirect(url_for("login", info_message="パスワードを再設定しました。新しいパスワードでログインしてください。"))
            if status == "expired":
                error_message = "再設定URLの有効期限が切れています。もう一度お手続きください。"
            else:
                error_message = "再設定URLが無効です。もう一度お手続きください。"
    return render_template("password_reset.html", error_message=error_message, info_message=info_message, token=token)


@app.post("/logout")
def logout():
    session.pop("admin_id", None)
    session.pop("admin_email", None)
    session.permanent = False
    return redirect(url_for("login"))


@app.get("/viewer-3d")
@login_required
def viewer_3d():
    return render_template("viewer_3d.html")


@app.get("/api/state")
@login_required
def get_state():
    return jsonify(read_state())


@app.post("/api/state")
@login_required
def save_state():
    state = request.get_json(silent=True)
    if not isinstance(state, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    write_state(state)
    return jsonify({"ok": True})


@app.get("/api/projects")
@login_required
def get_projects():
    return jsonify(project_payload(read_project_store(current_admin_id())))


@app.post("/api/projects/save")
@login_required
def save_project():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    state = payload.get("state")
    if not isinstance(state, dict):
        return jsonify({"error": "Invalid project state"}), 400

    admin_id = current_admin_id()
    store = read_project_store(admin_id)
    project_identifier = str(payload.get("id") or store.get("active_project_id") or "")
    project = next((item for item in store["projects"] if item["id"] == project_identifier), None)
    if project is None:
        return jsonify({"error": "Project not found"}), 404

    name = str(payload.get("name") or project["name"]).strip() or project["name"]
    next_state = clone_state(state)
    next_state["project_name"] = name
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE lightsketch_projects
                SET name=%s, state=%s, updated_at=NOW()
                WHERE id=%s AND admin_id=%s
                """,
                (name, Json(next_state), project["id"], admin_id),
            )
            cursor.execute(
                "UPDATE lightsketch_admins SET active_project_id=%s WHERE id=%s",
                (project["id"], admin_id),
            )
        conn.commit()
    return jsonify({"ok": True, **project_payload(read_project_store(admin_id))})


@app.post("/api/projects/select")
@login_required
def select_project():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    admin_id = current_admin_id()
    store = read_project_store(admin_id)
    project_identifier = str(payload.get("id") or "")
    if not any(project["id"] == project_identifier for project in store["projects"]):
        return jsonify({"error": "Project not found"}), 404
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE lightsketch_admins SET active_project_id=%s WHERE id=%s",
                (project_identifier, admin_id),
            )
        conn.commit()
    return jsonify({"ok": True, **project_payload(read_project_store(admin_id))})


@app.post("/api/projects/create")
@login_required
def create_project():
    admin_id = current_admin_id()
    name, state = request_state_payload(NEW_PROJECT_STATE)
    project = make_project(name, state)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO lightsketch_projects (id, admin_id, name, state)
                VALUES (%s, %s, %s, %s)
                """,
                (project["id"], admin_id, project["name"], Json(project["state"])),
            )
            cursor.execute(
                "UPDATE lightsketch_admins SET active_project_id=%s WHERE id=%s",
                (project["id"], admin_id),
            )
        conn.commit()
    return jsonify({"ok": True, **project_payload(read_project_store(admin_id))})


@app.post("/api/projects/duplicate")
@login_required
def duplicate_project():
    admin_id = current_admin_id()
    store = read_project_store(admin_id)
    current = active_project(store)
    default_name = f"{current['name']} コピー"
    name, state = request_state_payload(current["state"])
    if name == project_name_from_state(current["state"], current["name"]):
        name = default_name
        state["project_name"] = name
    project = make_project(name, state)
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO lightsketch_projects (id, admin_id, name, state)
                VALUES (%s, %s, %s, %s)
                """,
                (project["id"], admin_id, project["name"], Json(project["state"])),
            )
            cursor.execute(
                "UPDATE lightsketch_admins SET active_project_id=%s WHERE id=%s",
                (project["id"], admin_id),
            )
        conn.commit()
    return jsonify({"ok": True, **project_payload(read_project_store(admin_id))})


@app.post("/api/projects/delete")
@login_required
def delete_project():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    admin_id = current_admin_id()
    store = read_project_store(admin_id)
    if len(store["projects"]) <= 1:
        return jsonify({"error": "Last project cannot be deleted"}), 400
    project_identifier = str(payload.get("id") or store.get("active_project_id") or "")
    next_projects = [project for project in store["projects"] if project["id"] != project_identifier]
    if len(next_projects) == len(store["projects"]):
        return jsonify({"error": "Project not found"}), 404
    next_active_project_id = store.get("active_project_id")
    if next_active_project_id == project_identifier:
        next_active_project_id = next_projects[0]["id"]
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM lightsketch_projects WHERE id=%s AND admin_id=%s",
                (project_identifier, admin_id),
            )
            cursor.execute(
                "UPDATE lightsketch_admins SET active_project_id=%s WHERE id=%s",
                (next_active_project_id, admin_id),
            )
        conn.commit()
    return jsonify({"ok": True, **project_payload(read_project_store(admin_id))})


@app.get("/api/samples")
@login_required
def get_samples():
    return jsonify({name: clone_state(state) for name, state in SAMPLES.items()})


@app.post("/api/export/dxf")
@login_required
def export_dxf():
    state = request.get_json(silent=True)
    if not isinstance(state, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    dxf = state_to_dxf(state)
    return Response(
        dxf,
        mimetype="application/dxf",
        headers={"Content-Disposition": "attachment; filename=lightsketch.dxf"},
    )


if __name__ == "__main__":
    app.run(debug=True)
