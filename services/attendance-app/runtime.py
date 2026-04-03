import csv
import io
import json
import os
import random
import secrets
import sqlite3
import hashlib
import hmac
import smtplib
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
import sys
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from flask import Flask, Response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from service_modules.admin_core_routes import register_admin_core_routes
from service_modules.admin_team_collection_routes import register_admin_team_collection_routes
from service_modules.admin_team_event_routes import register_admin_team_event_routes
from service_modules.admin_team_member_routes import register_admin_team_member_routes
from service_modules.attendance_portal_routes import register_attendance_portal_routes
from service_modules.legacy_attendance_routes import register_legacy_attendance_routes
from service_modules.public_attendance_tool_routes import register_public_attendance_tool_routes
from service_modules.public_team_core_routes import register_public_team_core_routes
from service_modules.site_admin_routes import register_site_admin_routes
from shared.db_runtime import (
    DBConnection,
    DBCursor,
    get_db_connection as build_shared_db_connection,
    row_to_dict,
    rows_to_dict,
    to_db_query,
)
from shared.contact_runtime import (
    build_contact_page_context as build_shared_contact_page_context,
    is_valid_email as is_valid_contact_email,
    load_contact_mail_settings,
    send_contact_form_email as send_shared_contact_form_email,
)
from shared.runtime_config import load_default_env_files
from shared.runtime_settings import load_runtime_settings

try:
    import psycopg2
    from psycopg2 import Error as Psycopg2Error
    from psycopg2.extras import DictCursor
except ImportError:
    psycopg2 = None
    Psycopg2Error = None
    DictCursor = None

try:
    import psycopg
    from psycopg import Error as Psycopg3Error
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    Psycopg3Error = None
    dict_row = None

app = Flask(
    __name__,
    template_folder=str(SERVICE_ROOT / "templates"),
    static_folder=str(SERVICE_ROOT / "static"),
)
_APP_INITIALIZED = False

load_default_env_files(
    candidate_paths=(
        REPO_ROOT / ".env",
        REPO_ROOT / ".env.local",
        SERVICE_ROOT / ".env",
        SERVICE_ROOT / ".env.local",
    )
)
RUNTIME_SETTINGS = load_runtime_settings("mossan-attendance-app")

app.secret_key = RUNTIME_SETTINGS.secret_key

PORTAL_DATA_PATH = Path("portal_data.json")
DATABASE_URL = RUNTIME_SETTINGS.database_url
USE_POSTGRES = RUNTIME_SETTINGS.use_postgres
SQLITE_DB_PATH = RUNTIME_SETTINGS.sqlite_db_path
RENDER_ENV = RUNTIME_SETTINGS.render_env
PORTAL_JSON_MIGRATION_ENABLED = RUNTIME_SETTINGS.portal_json_migration_enabled
ADMIN_TRIAL_DAYS = 30
ADMIN_EXPIRY_UNLIMITED = "UNLIMITED"
ADMIN_STATUS_FREE = "free"
ADMIN_STATUS_PAID = "paid"
ADMIN_STATUS_EXPIRED = "expired"
ADMIN_STATUS_SUSPENDED = "suspended"
ADMIN_PLAN_FREE = "free"
ADMIN_PLAN_PAID = "paid"
ADMIN_ACCOUNT_STATUS_ACTIVE = "active"
ADMIN_ACCOUNT_STATUS_SUSPENDED = "suspended"
ADMIN_ACCOUNT_STATUS_EXPIRED = "expired"
ADMIN_BILLING_STATUS_UNPAID = "unpaid"
ADMIN_BILLING_STATUS_PAID = "paid"
ADMIN_FREE_TEAM_LIMIT = 2
ADMIN_PLAN_REQUEST_STATUS_PENDING = "pending"
ADMIN_PLAN_REQUEST_STATUS_APPROVED = "approved"
ADMIN_PLAN_REQUEST_STATUS_REJECTED = "rejected"
ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS = "paid_plan_30_days"
ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE = "stripe"
ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_PENDING = "pending"
ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED = "verified"
ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_UNVERIFIED = "unverified"
ADMIN_STRIPE_STATUS_CREATED = "created"
ADMIN_STRIPE_STATUS_OPEN = "open"
ADMIN_STRIPE_STATUS_RETURNED = "returned"
ADMIN_STRIPE_STATUS_COMPLETED = "completed"
ADMIN_STRIPE_STATUS_FAILED = "failed"
ADMIN_STRIPE_STATUS_CANCELED = "canceled"
ADMIN_STRIPE_STATUS_EXPIRED = "expired"
ADMIN_STRIPE_STATUS_UNKNOWN = "unknown"
ADMIN_PLAN_REQUEST_TYPE_LABELS = {
    ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS: "+30日",
}
ADMIN_PLAN_REQUEST_PAYMENT_AMOUNT_OPTIONS = [500, 900, 1200]
ADMIN_PLAN_PAYMENT_AMOUNT_EXTENSION_DAYS = {
    500: 30,
    900: 60,
    1200: 90,
}
ADMIN_PLAN_REQUEST_EXTENSION_DAYS = {
    ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS: 30,
}
ADMIN_PLAN_REQUEST_PAYMENT_METHOD_LABELS = {
    ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE: "Stripe",
    "paypay": "旧PayPay",
}
ADMIN_PLAN_REQUEST_STATUS_LABELS = {
    ADMIN_PLAN_REQUEST_STATUS_PENDING: "申請中",
    ADMIN_PLAN_REQUEST_STATUS_APPROVED: "承認済み",
    ADMIN_PLAN_REQUEST_STATUS_REJECTED: "却下",
}
ADMIN_PLAN_REQUESTS_ENABLED = False
ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_LABELS = {
    ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_PENDING: "確認待ち",
    ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED: "確認済み",
    ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_UNVERIFIED: "未確認",
}
ADMIN_STRIPE_STATUS_LABELS = {
    ADMIN_STRIPE_STATUS_CREATED: "作成済み",
    ADMIN_STRIPE_STATUS_OPEN: "決済画面を表示",
    ADMIN_STRIPE_STATUS_RETURNED: "戻り済み",
    ADMIN_STRIPE_STATUS_COMPLETED: "支払い完了",
    ADMIN_STRIPE_STATUS_FAILED: "失敗",
    ADMIN_STRIPE_STATUS_CANCELED: "キャンセル",
    ADMIN_STRIPE_STATUS_EXPIRED: "期限切れ",
    ADMIN_STRIPE_STATUS_UNKNOWN: "確認中",
}
PLAN_FEATURE_TEAM_CREATE = "team_create"
PLAN_FEATURE_CSV_EXPORT = "csv_export"
PLAN_FEATURE_ATTENDANCE_CHECK = "attendance_check"
PLAN_FEATURE_TEAM_SPLIT = "team_split"
PLAN_FEATURE_RANDOM_PICK = "random_pick"
COLLECTION_STATUS_PENDING = "pending"
COLLECTION_STATUS_COLLECTED = "collected"
COLLECTION_STATUS_EXEMPT = "exempt"
TRANSPORT_ROLE_NONE = "none"
TRANSPORT_ROLE_DRIVER = "driver"
TRANSPORT_ROLE_PASSENGER = "passenger"
TRANSPORT_ROLE_DIRECT = "direct"
COLLECTION_STATUS_LABELS = {
    COLLECTION_STATUS_PENDING: "未集金",
    COLLECTION_STATUS_COLLECTED: "集金済み",
    COLLECTION_STATUS_EXEMPT: "免除",
}
TRANSPORT_ROLE_LABELS = {
    TRANSPORT_ROLE_NONE: "不要",
    TRANSPORT_ROLE_DRIVER: "運転する",
    TRANSPORT_ROLE_PASSENGER: "乗せてほしい",
    TRANSPORT_ROLE_DIRECT: "現地集合",
}
ADMIN_SELECT_COLUMNS = """
id,
email,
password_hash,
created_at,
expires_at,
status,
plan_type,
account_status,
billing_status,
last_billed_at,
total_billing_amount,
billing_count,
last_login_at,
last_attendance_updated_at,
admin_memo
"""
ADMIN_PLAN_LABELS = {
    ADMIN_PLAN_FREE: "無料",
    ADMIN_PLAN_PAID: "有料",
}
ADMIN_ACCOUNT_STATUS_LABELS = {
    ADMIN_ACCOUNT_STATUS_ACTIVE: "利用中",
    ADMIN_ACCOUNT_STATUS_SUSPENDED: "停止中",
    ADMIN_ACCOUNT_STATUS_EXPIRED: "期限切れ",
}
ADMIN_STATUS_LABELS = {
    ADMIN_STATUS_FREE: "無料",
    ADMIN_STATUS_PAID: "有料",
    ADMIN_STATUS_EXPIRED: "期限切れ",
    ADMIN_STATUS_SUSPENDED: "停止中",
}
ADMIN_BILLING_STATUS_LABELS = {
    ADMIN_BILLING_STATUS_UNPAID: "未課金",
    ADMIN_BILLING_STATUS_PAID: "課金済",
}
PLAN_RESTRICTION_MESSAGES = {
    PLAN_FEATURE_TEAM_CREATE: f"無料プランではチームは{ADMIN_FREE_TEAM_LIMIT}つまで作成できます。",
    PLAN_FEATURE_CSV_EXPORT: "CSV出力は有料プランで利用できます。",
    PLAN_FEATURE_ATTENDANCE_CHECK: "出欠確認は有料プランで利用できます。",
    PLAN_FEATURE_TEAM_SPLIT: "自動チーム分けは有料プランで利用できます。",
    PLAN_FEATURE_RANDOM_PICK: "代表者選出は有料プランで利用できます。",
}


def parse_email_allowlist(raw_value):
    normalized = (raw_value or "").replace(";", ",").replace("\n", ",")
    return {entry.strip().lower() for entry in normalized.split(",") if "@" in entry}


def is_valid_email(value):
    return is_valid_contact_email(value)


def is_contact_email_configured():
    return CONTACT_MAIL_SETTINGS.is_configured


def send_contact_form_email(*, name, email, subject, message, remote_addr="", user_agent=""):
    send_shared_contact_form_email(
        CONTACT_MAIL_SETTINGS,
        name=name,
        email=email,
        subject=subject,
        message=message,
        remote_addr=remote_addr,
        user_agent=user_agent,
    )


def build_contact_page_context(*, status="", error_message="", prefill=None):
    return build_shared_contact_page_context(
        CONTACT_MAIL_SETTINGS,
        status=status,
        error_message=error_message,
        prefill=prefill,
    )


SITE_ADMIN_EMAILS = parse_email_allowlist(os.environ.get("SITE_ADMIN_EMAILS", ""))
bootstrap_admin_email = os.environ.get("ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
if "@" in bootstrap_admin_email:
    SITE_ADMIN_EMAILS.add(bootstrap_admin_email)
CONTACT_FORM_TO_EMAIL = os.environ.get("CONTACT_FORM_TO_EMAIL", "").strip()
CONTACT_FORM_FROM_EMAIL = os.environ.get("CONTACT_FORM_FROM_EMAIL", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587").strip() or "587")
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1").strip().lower() not in {"0", "false", "no", "off"}
CONTACT_MAIL_SETTINGS = load_contact_mail_settings()
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_REDIRECT_BASE_URL = os.environ.get("STRIPE_REDIRECT_BASE_URL", "").strip().rstrip("/")
STRIPE_API_BASE_URL = os.environ.get("STRIPE_API_BASE_URL", "https://api.stripe.com").strip().rstrip("/")
STRIPE_CONNECT_TIMEOUT_SECONDS = max(1, int(os.environ.get("STRIPE_CONNECT_TIMEOUT_SECONDS", "10") or "10"))
STRIPE_REQUEST_TIMEOUT_SECONDS = max(5, int(os.environ.get("STRIPE_REQUEST_TIMEOUT_SECONDS", "30") or "30"))
STRIPE_WEBHOOK_TOLERANCE_SECONDS = max(
    0, int(os.environ.get("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "300") or "300")
)
STRIPE_LOG_RAW_RESPONSE = os.environ.get("STRIPE_LOG_RAW_RESPONSE", "").strip() == "1"
if USE_POSTGRES:
    pg_errors = []
    if Psycopg2Error is not None:
        pg_errors.append(Psycopg2Error)
    if Psycopg3Error is not None:
        pg_errors.append(Psycopg3Error)
    DatabaseError = tuple(pg_errors) if pg_errors else Exception
else:
    DatabaseError = sqlite3.Error

if RENDER_ENV and not USE_POSTGRES:
    raise RuntimeError("Render deployment requires DATABASE_URL (PostgreSQL).")



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


def parse_portal_datetime(value):
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def is_unlimited_expiry(value):
    return (value or "").strip().upper() == ADMIN_EXPIRY_UNLIMITED


def build_admin_expiry_text(created_at=None, base_datetime=None, extend_days=0):
    base_dt = base_datetime or parse_portal_datetime(created_at) or datetime.now()
    expire_dt = base_dt + timedelta(days=ADMIN_TRIAL_DAYS + max(0, extend_days))
    return expire_dt.strftime("%Y-%m-%d %H:%M:%S")


def resolve_admin_expiry_datetime(created_at, expires_at):
    if is_unlimited_expiry(expires_at):
        return None
    return parse_portal_datetime(expires_at) or parse_portal_datetime(
        build_admin_expiry_text(created_at=created_at)
    )


def normalize_collection_status(value):
    normalized = (value or "").strip().lower()
    status_map = {
        COLLECTION_STATUS_PENDING: COLLECTION_STATUS_PENDING,
        "unpaid": COLLECTION_STATUS_PENDING,
        "未集金": COLLECTION_STATUS_PENDING,
        COLLECTION_STATUS_COLLECTED: COLLECTION_STATUS_COLLECTED,
        "paid": COLLECTION_STATUS_COLLECTED,
        "済": COLLECTION_STATUS_COLLECTED,
        "集金済み": COLLECTION_STATUS_COLLECTED,
        COLLECTION_STATUS_EXEMPT: COLLECTION_STATUS_EXEMPT,
        "免除": COLLECTION_STATUS_EXEMPT,
    }
    return status_map.get(normalized, "")


def normalize_transport_role(value):
    normalized = (value or "").strip().lower()
    role_map = {
        TRANSPORT_ROLE_NONE: TRANSPORT_ROLE_NONE,
        "不要": TRANSPORT_ROLE_NONE,
        "なし": TRANSPORT_ROLE_NONE,
        TRANSPORT_ROLE_DRIVER: TRANSPORT_ROLE_DRIVER,
        "運転": TRANSPORT_ROLE_DRIVER,
        "運転する": TRANSPORT_ROLE_DRIVER,
        TRANSPORT_ROLE_PASSENGER: TRANSPORT_ROLE_PASSENGER,
        "乗車": TRANSPORT_ROLE_PASSENGER,
        "乗せてほしい": TRANSPORT_ROLE_PASSENGER,
        TRANSPORT_ROLE_DIRECT: TRANSPORT_ROLE_DIRECT,
        "現地集合": TRANSPORT_ROLE_DIRECT,
    }
    return role_map.get(normalized, "")


def format_collection_collected_at(value):
    parsed = parse_portal_datetime(value)
    if not parsed:
        return ""
    return parsed.strftime("%m/%d")


def append_query_params(url, **params):
    split = urlsplit(url)
    current_params = dict(parse_qsl(split.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None:
            current_params.pop(key, None)
        else:
            current_params[key] = value
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(current_params), split.fragment))


def stripe_checkout_is_configured():
    return bool(STRIPE_SECRET_KEY and stripe_build_redirect_base_url())


def stripe_webhook_is_configured():
    return bool(STRIPE_WEBHOOK_SECRET)


def stripe_is_configured():
    return bool(stripe_checkout_is_configured() and stripe_webhook_is_configured())


def stripe_build_redirect_base_url():
    if STRIPE_REDIRECT_BASE_URL:
        return STRIPE_REDIRECT_BASE_URL
    try:
        return request.url_root.rstrip("/")
    except RuntimeError:
        return ""


def stripe_build_success_url():
    base_url = stripe_build_redirect_base_url()
    if not base_url:
        return ""
    return append_query_params(
        f"{base_url}{url_for('admin_stripe_success')}",
        session_id="{CHECKOUT_SESSION_ID}",
    )


def stripe_build_cancel_url():
    base_url = stripe_build_redirect_base_url()
    if not base_url:
        return ""
    return append_query_params(
        f"{base_url}{url_for('admin_create_plan_request')}",
        error_message="Stripe決済はまだ完了していません。必要に応じて再確認してください。",
    )


def stripe_now_epoch():
    return int(time.time())


def stripe_json_dumps(payload):
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return "{}"


def stripe_form_encode_pairs(data, prefix=""):
    if isinstance(data, dict):
        pairs = []
        for key, value in data.items():
            key_text = f"{prefix}[{key}]" if prefix else str(key)
            pairs.extend(stripe_form_encode_pairs(value, key_text))
        return pairs
    if isinstance(data, list):
        pairs = []
        for index, value in enumerate(data):
            key_text = f"{prefix}[{index}]"
            pairs.extend(stripe_form_encode_pairs(value, key_text))
        return pairs
    if data is None:
        return []
    return [(prefix, str(data))]


def stripe_build_order_description(admin_email, request_type, amount):
    request_label = ADMIN_PLAN_REQUEST_TYPE_LABELS.get(request_type, "有料プラン申請")
    return f"{request_label} / {format_currency_yen(amount)} / {admin_email or 'admin'}"


def stripe_extract_reference(payment_row):
    checkout_session_id = (payment_row.get("stripe_checkout_session_id") or "").strip()
    payment_intent_id = (payment_row.get("stripe_payment_intent_id") or "").strip()
    if checkout_session_id and payment_intent_id:
        return f"{checkout_session_id} / pi:{payment_intent_id}"
    return checkout_session_id or payment_intent_id or ""


def normalize_admin_stripe_status(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_STRIPE_STATUS_LABELS else ""


def map_stripe_status(session_data, has_return=False):
    session_status = ((session_data or {}).get("status") or "").strip().lower()
    payment_status = ((session_data or {}).get("payment_status") or "").strip().lower()
    payment_intent = (session_data or {}).get("payment_intent") or {}
    if not isinstance(payment_intent, dict):
        payment_intent = {}
    payment_intent_status = (payment_intent.get("status") or "").strip().lower()
    if session_status == "complete" and payment_status == "paid":
        return ADMIN_STRIPE_STATUS_COMPLETED
    if session_status == "expired":
        return ADMIN_STRIPE_STATUS_EXPIRED
    if payment_intent_status == "canceled":
        return ADMIN_STRIPE_STATUS_CANCELED
    if payment_intent_status in {"requires_payment_method", "requires_payment_confirmation"} and has_return:
        return ADMIN_STRIPE_STATUS_FAILED
    if session_status == "open":
        return ADMIN_STRIPE_STATUS_RETURNED if has_return else ADMIN_STRIPE_STATUS_OPEN
    if has_return:
        return ADMIN_STRIPE_STATUS_RETURNED
    return ADMIN_STRIPE_STATUS_UNKNOWN


def stripe_extract_paid_at(session_data):
    payment_intent = (session_data or {}).get("payment_intent") or {}
    if isinstance(payment_intent, dict):
        paid_at = epoch_to_portal_text(payment_intent.get("created"))
        if paid_at:
            return paid_at
    return epoch_to_portal_text((session_data or {}).get("created"))


def stripe_api_request(method, request_path, payload=None, raw_body=None, extra_headers=None):
    body_bytes = None
    headers = {
        "Authorization": f"Bearer {STRIPE_SECRET_KEY}",
    }
    if payload is not None:
        body_bytes = urlencode(stripe_form_encode_pairs(payload)).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif raw_body is not None:
        body_bytes = raw_body.encode("utf-8")
    if extra_headers:
        headers.update(extra_headers)
    req = urllib_request.Request(
        f"{STRIPE_API_BASE_URL}{request_path}",
        data=body_bytes,
        headers=headers,
        method=method.upper(),
    )
    timeout_seconds = STRIPE_REQUEST_TIMEOUT_SECONDS if method.upper() == "POST" else 15
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            parsed_json = json.loads(body) if body else {}
            return {
                "ok": 200 <= response.status < 300,
                "status_code": response.status,
                "body": body,
                "json": parsed_json if isinstance(parsed_json, dict) else {},
                "error": "",
            }
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        parsed_json = {}
        try:
            parsed_json = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed_json = {}
        return {
            "ok": False,
            "status_code": exc.code,
            "body": body,
            "json": parsed_json if isinstance(parsed_json, dict) else {},
            "error": str(exc),
        }
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "status_code": 0,
            "body": "",
            "json": {},
            "error": str(exc),
        }


def stripe_create_checkout_session(admin, request_type, amount):
    payload = {
        "mode": "payment",
        "success_url": stripe_build_success_url(),
        "cancel_url": stripe_build_cancel_url(),
        "locale": "ja",
        "client_reference_id": f"admin-{admin['id']}-{secrets.token_hex(8)}",
        "payment_method_types": ["card"],
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": "jpy",
                    "unit_amount": amount,
                    "product_data": {
                        "name": stripe_build_order_description(admin.get("email", ""), request_type, amount),
                    },
                },
            }
        ],
        "metadata": {
            "admin_id": str(admin["id"]),
            "request_type": request_type,
            "payment_amount": str(amount),
        },
    }
    return payload, stripe_api_request("POST", "/v1/checkout/sessions", payload=payload)


def stripe_get_checkout_session(checkout_session_id):
    quoted_session_id = quote(checkout_session_id or "", safe="")
    return stripe_api_request(
        "GET",
        f"/v1/checkout/sessions/{quoted_session_id}?expand[]=payment_intent",
    )


def stripe_parse_signature_header(signature_header):
    values = {}
    for part in (signature_header or "").split(","):
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        values.setdefault(key, []).append(value)
    return values


def stripe_verify_webhook_signature(payload_text, signature_header):
    parsed = stripe_parse_signature_header(signature_header)
    timestamp_values = parsed.get("t") or []
    signature_values = parsed.get("v1") or []
    if not timestamp_values or not signature_values or not STRIPE_WEBHOOK_SECRET:
        return False
    try:
        timestamp = int(timestamp_values[0])
    except (TypeError, ValueError):
        return False
    if STRIPE_WEBHOOK_TOLERANCE_SECONDS and abs(stripe_now_epoch() - timestamp) > STRIPE_WEBHOOK_TOLERANCE_SECONDS:
        return False
    signed_payload = f"{timestamp}.{payload_text}"
    expected_signature = hmac.new(
        STRIPE_WEBHOOK_SECRET.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return any(hmac.compare_digest(expected_signature, candidate) for candidate in signature_values)


def parse_json_object(raw_text):
    if not raw_text:
        return {}
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_admin_plan_request_payment_verification_status(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_LABELS else ""


def epoch_to_portal_text(value):
    try:
        epoch = int(value)
    except (TypeError, ValueError):
        return ""
    if epoch <= 0:
        return ""
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def portal_get_admin_by_email(email):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        f"SELECT {ADMIN_SELECT_COLUMNS} FROM admins WHERE email=?",
        (email,),
    )
    admin = row_to_dict(c.fetchone())
    conn.close()
    return sync_admin_plan_by_expiry(admin)


def portal_get_admin(admin_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        f"SELECT {ADMIN_SELECT_COLUMNS} FROM admins WHERE id=?",
        (admin_id,),
    )
    admin = row_to_dict(c.fetchone())
    conn.close()
    return sync_admin_plan_by_expiry(admin)


def portal_get_admin_plan_request(request_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            apr.id,
            apr.admin_id,
            apr.request_type,
            apr.payment_method,
            apr.payment_amount,
            apr.payment_date,
            apr.payment_reference,
            apr.request_note,
            apr.status,
            apr.review_note,
            apr.reviewed_by_admin_id,
            apr.reviewed_at,
            apr.stripe_payment_id,
            apr.payment_verification_status,
            apr.payment_verified_at,
            apr.created_at,
            apr.updated_at,
            a.email AS admin_email,
            reviewer.email AS reviewer_email
        FROM admin_plan_requests apr
        INNER JOIN admins a ON a.id = apr.admin_id
        LEFT JOIN admins reviewer ON reviewer.id = apr.reviewed_by_admin_id
        WHERE apr.id=?
        """,
        (request_id,),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    return row


def portal_get_pending_admin_plan_request_by_admin(admin_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            id,
            admin_id,
            request_type,
            payment_method,
            payment_amount,
            payment_date,
            payment_reference,
            request_note,
            status,
            review_note,
            reviewed_by_admin_id,
            reviewed_at,
            stripe_payment_id,
            payment_verification_status,
            payment_verified_at,
            created_at,
            updated_at
        FROM admin_plan_requests
        WHERE admin_id=? AND status=?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (admin_id, ADMIN_PLAN_REQUEST_STATUS_PENDING),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    return row


def portal_get_admin_plan_request_history(admin_id, limit=20):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            apr.id,
            apr.admin_id,
            apr.request_type,
            apr.payment_method,
            apr.payment_amount,
            apr.payment_date,
            apr.payment_reference,
            apr.request_note,
            apr.status,
            apr.review_note,
            apr.reviewed_by_admin_id,
            apr.reviewed_at,
            apr.stripe_payment_id,
            apr.payment_verification_status,
            apr.payment_verified_at,
            apr.created_at,
            apr.updated_at,
            reviewer.email AS reviewer_email
        FROM admin_plan_requests apr
        LEFT JOIN admins reviewer ON reviewer.id = apr.reviewed_by_admin_id
        WHERE apr.admin_id=?
        ORDER BY apr.created_at DESC, apr.id DESC
        LIMIT ?
        """,
        (admin_id, limit),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_get_admin_plan_requests(status=None, limit=200):
    conn = get_db_connection()
    c = conn.cursor()
    params = []
    where_clause = ""
    if status:
        where_clause = "WHERE apr.status=?"
        params.append(status)
    params.append(limit)
    c.execute(
        f"""
        SELECT
            apr.id,
            apr.admin_id,
            apr.request_type,
            apr.payment_method,
            apr.payment_amount,
            apr.payment_date,
            apr.payment_reference,
            apr.request_note,
            apr.status,
            apr.review_note,
            apr.reviewed_by_admin_id,
            apr.reviewed_at,
            apr.stripe_payment_id,
            apr.payment_verification_status,
            apr.payment_verified_at,
            apr.created_at,
            apr.updated_at,
            a.email AS admin_email,
            reviewer.email AS reviewer_email,
            asp.stripe_checkout_session_id AS stripe_checkout_session_id,
            asp.status AS stripe_order_status,
            asp.stripe_status AS stripe_remote_status,
            asp.stripe_payment_status AS stripe_remote_payment_status
        FROM admin_plan_requests apr
        INNER JOIN admins a ON a.id = apr.admin_id
        LEFT JOIN admins reviewer ON reviewer.id = apr.reviewed_by_admin_id
        LEFT JOIN admin_stripe_payments asp ON asp.id = apr.stripe_payment_id
        {where_clause}
        ORDER BY
            CASE WHEN apr.status = '{ADMIN_PLAN_REQUEST_STATUS_PENDING}' THEN 0 ELSE 1 END,
            apr.created_at DESC,
            apr.id DESC
        LIMIT ?
        """,
        tuple(params),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_get_admin_summaries():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            a.id,
            a.email,
            a.password_hash,
            a.created_at,
            a.expires_at,
            a.status,
            a.plan_type,
            a.account_status,
            a.billing_status,
            a.last_billed_at,
            a.total_billing_amount,
            a.billing_count,
            a.last_login_at,
            a.last_attendance_updated_at,
            a.admin_memo,
            COUNT(t.id) AS team_count
        FROM admins a
        LEFT JOIN teams t ON t.admin_id = a.id
        GROUP BY
            a.id,
            a.email,
            a.password_hash,
            a.created_at,
            a.expires_at,
            a.status,
            a.plan_type,
            a.account_status,
            a.billing_status,
            a.last_billed_at,
            a.total_billing_amount,
            a.billing_count,
            a.last_login_at,
            a.last_attendance_updated_at,
            a.admin_memo
        ORDER BY a.created_at ASC, a.id ASC
        """
    )
    admins = rows_to_dict(c.fetchall())
    conn.close()
    return [sync_admin_plan_by_expiry(admin) for admin in admins]


def portal_get_team_details_by_admin():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            t.id,
            t.admin_id,
            t.name,
            t.public_id,
            t.created_at,
            (
                SELECT COUNT(1)
                FROM portal_members pm
                WHERE pm.team_id = t.id
            ) AS member_count,
            (
                SELECT COUNT(1)
                FROM portal_events pe
                WHERE pe.team_id = t.id
            ) AS event_count,
            (
                SELECT COUNT(1)
                FROM portal_collection_events pce
                WHERE pce.team_id = t.id
            ) AS collection_event_count,
            (
                SELECT MAX(updated_value)
                FROM (
                    SELECT pa.updated_at AS updated_value
                    FROM portal_attendance pa
                    WHERE pa.team_id = t.id
                    UNION ALL
                    SELECT paa.confirmed_at AS updated_value
                    FROM portal_actual_attendees paa
                    WHERE paa.team_id = t.id
                ) attendance_updates
            ) AS last_attendance_updated_at
        FROM teams t
        ORDER BY t.created_at ASC, t.id ASC
        """
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()

    grouped = {}
    for row in rows:
        grouped.setdefault(row["admin_id"], []).append(row)
    return grouped


def portal_get_team_details_for_admin(admin_id):
    return portal_get_team_details_by_admin().get(admin_id, [])


def portal_find_or_create_admin(email):
    existing = portal_get_admin_by_email(email)
    if existing:
        return existing

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO admins (email, created_at, expires_at) VALUES (?, ?, ?)",
        (
            email,
            portal_now_text(),
            build_admin_expiry_text(base_datetime=datetime.now()),
        ),
    )
    conn.commit()
    c.execute(
        f"SELECT {ADMIN_SELECT_COLUMNS} FROM admins WHERE email=?",
        (email,),
    )
    admin = row_to_dict(c.fetchone())
    conn.close()
    return admin


def portal_save_admin(updated_admin):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE admins
        SET email=?, password_hash=?, created_at=?, expires_at=?
        WHERE id=?
        """,
        (
            updated_admin.get("email"),
            updated_admin.get("password_hash"),
            updated_admin.get("created_at"),
            updated_admin.get("expires_at"),
            updated_admin.get("id"),
        ),
    )
    conn.commit()
    c.execute(
        f"SELECT {ADMIN_SELECT_COLUMNS} FROM admins WHERE id=?",
        (updated_admin.get("id"),),
    )
    admin = row_to_dict(c.fetchone())
    conn.close()
    return admin


def portal_authenticate_admin(email, password):
    admin = portal_get_admin_by_email(email)
    if not admin:
        return None, "not_found"

    password_hash = admin.get("password_hash", "")
    if not password_hash:
        admin["password_hash"] = generate_password_hash(password)
        portal_save_admin(admin)
        return admin, "password_initialized"

    if check_password_hash(password_hash, password):
        return admin, "authenticated"

    return None, "invalid_password"


def portal_create_admin(email, password):
    if portal_get_admin_by_email(email):
        return None

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO admins (email, password_hash, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            email,
            generate_password_hash(password),
            portal_now_text(),
            build_admin_expiry_text(base_datetime=datetime.now()),
        ),
    )
    conn.commit()
    c.execute(
        f"SELECT {ADMIN_SELECT_COLUMNS} FROM admins WHERE email=?",
        (email,),
    )
    admin = c.fetchone()
    conn.close()
    return admin


def portal_update_admin_credentials(admin_id, current_password, new_email, new_password):
    admin = portal_get_admin(admin_id)
    if not admin:
        return None, "not_found"

    password_hash = admin.get("password_hash", "")
    if not password_hash or not check_password_hash(password_hash, current_password):
        return None, "invalid_password"

    normalized_email = (new_email or "").strip().lower()
    if not normalized_email or "@" not in normalized_email:
        return None, "invalid_email"

    existing_admin = portal_get_admin_by_email(normalized_email)
    if existing_admin and existing_admin["id"] != admin_id:
        return None, "email_taken"

    admin["email"] = normalized_email
    if new_password:
        admin["password_hash"] = generate_password_hash(new_password)

    portal_save_admin(admin)
    return admin, "updated"


def portal_delete_admin(admin_id, current_password):
    admin = portal_get_admin(admin_id)
    if not admin:
        return False, "not_found"

    password_hash = admin.get("password_hash", "")
    if not password_hash or not check_password_hash(password_hash, current_password):
        return False, "invalid_password"

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM teams WHERE admin_id=?", (admin_id,))
    team_ids = [row["id"] for row in c.fetchall()]
    for team_id in team_ids:
        delete_team_related_records(c, team_id)
    c.execute("DELETE FROM teams WHERE admin_id=?", (admin_id,))
    c.execute("DELETE FROM admin_billing_history WHERE admin_id=?", (admin_id,))
    c.execute("DELETE FROM admins WHERE id=?", (admin_id,))
    conn.commit()
    conn.close()
    return True, "deleted"


def portal_force_delete_admin(admin_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM teams WHERE admin_id=?", (admin_id,))
    team_ids = [row["id"] for row in c.fetchall()]
    for team_id in team_ids:
        delete_team_related_records(c, team_id)
    c.execute("DELETE FROM teams WHERE admin_id=?", (admin_id,))
    c.execute("DELETE FROM admin_billing_history WHERE admin_id=?", (admin_id,))
    c.execute("DELETE FROM admins WHERE id=?", (admin_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def portal_set_admin_expiry(admin_id, expires_at_text):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE admins SET expires_at=? WHERE id=?", (expires_at_text, admin_id))
    updated = c.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def portal_update_admin_profile_fields(admin_id, **fields):
    allowed_fields = {
        "status",
        "plan_type",
        "account_status",
        "billing_status",
        "last_billed_at",
        "total_billing_amount",
        "billing_count",
        "last_login_at",
        "last_attendance_updated_at",
        "admin_memo",
    }
    updates = []
    params = []
    for field_name, value in fields.items():
        if field_name not in allowed_fields:
            continue
        updates.append(f"{field_name}=?")
        params.append(value)
    if not updates:
        return False

    params.append(admin_id)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE admins SET {', '.join(updates)} WHERE id=?", params)
    updated = c.rowcount > 0
    conn.commit()
    if not updated:
        c.execute("SELECT 1 FROM admins WHERE id=?", (admin_id,))
        updated = c.fetchone() is not None
    conn.close()
    return updated


def portal_touch_admin_last_login(admin_id):
    return portal_update_admin_profile_fields(admin_id, last_login_at=portal_now_text())


def portal_touch_admin_last_attendance_updated_by_team(team_id):
    team = portal_get_team(team_id)
    if not team or not team.get("admin_id"):
        return False
    return portal_update_admin_profile_fields(team["admin_id"], last_attendance_updated_at=portal_now_text())


def portal_record_admin_billing_history(
    admin_id,
    billing_status,
    billed_at,
    amount,
    total_amount,
    billing_count,
    note="",
):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO admin_billing_history (
            admin_id,
            billing_status,
            billed_at,
            amount,
            total_amount,
            billing_count,
            note,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            admin_id,
            billing_status,
            billed_at,
            amount,
            total_amount,
            billing_count,
            note,
            portal_now_text(),
        ),
    )
    conn.commit()
    conn.close()
    return True


def portal_create_admin_stripe_payment(admin_id, request_type, request_amount, create_response):
    now_text = portal_now_text()
    session_data = (create_response or {}).get("json", {}) or {}
    raw_response = ""
    if STRIPE_LOG_RAW_RESPONSE and create_response is not None:
        raw_response = (create_response.get("body") or "")[:10000]
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO admin_stripe_payments (
            admin_id,
            stripe_checkout_session_id,
            stripe_payment_intent_id,
            request_type,
            request_amount,
            currency,
            checkout_url,
            status,
            stripe_status,
            stripe_payment_status,
            payment_reference,
            requested_at,
            raw_create_response,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            admin_id,
            session_data.get("id") or "",
            session_data.get("payment_intent") or "",
            request_type,
            request_amount,
            (session_data.get("currency") or "jpy").upper(),
            session_data.get("url") or "",
            ADMIN_STRIPE_STATUS_OPEN if create_response.get("ok") else ADMIN_STRIPE_STATUS_UNKNOWN,
            session_data.get("status") or "",
            session_data.get("payment_status") or "",
            session_data.get("id") or "",
            epoch_to_portal_text(session_data.get("created")) or now_text,
            raw_response,
            now_text,
            now_text,
        ),
    )
    conn.commit()
    conn.close()


def portal_ensure_admin_stripe_payment_from_remote(checkout_session_id, payment_details=None):
    existing = portal_get_admin_stripe_payment_by_checkout_session_id(checkout_session_id)
    if existing:
        return existing
    session_data = (payment_details or {}).get("json", {}) or {}
    if not isinstance(session_data, dict):
        return None
    metadata = (session_data.get("metadata") or {})
    if not isinstance(metadata, dict):
        metadata = {}
    try:
        admin_id = int((metadata.get("admin_id") or "").strip() or "0")
    except (TypeError, ValueError, AttributeError):
        admin_id = 0
    request_type = normalize_admin_plan_request_type(metadata.get("request_type")) or ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS
    try:
        request_amount = int((metadata.get("payment_amount") or 0) or 0)
    except (TypeError, ValueError):
        request_amount = 0
    if admin_id <= 0 or request_amount not in ADMIN_PLAN_REQUEST_PAYMENT_AMOUNT_OPTIONS:
        return None
    admin = portal_get_admin(admin_id)
    if not admin:
        return None
    payment_intent = session_data.get("payment_intent")
    if isinstance(payment_intent, dict):
        stripe_payment_intent_id = (payment_intent.get("id") or "").strip()
    else:
        stripe_payment_intent_id = (payment_intent or "").strip()
    now_text = portal_now_text()
    requested_at_text = epoch_to_portal_text(session_data.get("created")) or now_text
    raw_response = ""
    if STRIPE_LOG_RAW_RESPONSE and payment_details is not None:
        raw_response = (payment_details.get("body") or "")[:10000]
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO admin_stripe_payments (
                admin_id,
                stripe_checkout_session_id,
                stripe_payment_intent_id,
                request_type,
                request_amount,
                currency,
                checkout_url,
                status,
                stripe_status,
                stripe_payment_status,
                payment_reference,
                stripe_paid_at,
                requested_at,
                raw_create_response,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                admin_id,
                checkout_session_id,
                stripe_payment_intent_id,
                request_type,
                request_amount,
                (session_data.get("currency") or "jpy").upper(),
                session_data.get("url") or "",
                map_stripe_status(session_data, has_return=False),
                session_data.get("status") or "",
                session_data.get("payment_status") or "",
                checkout_session_id,
                stripe_extract_paid_at(session_data) or "",
                requested_at_text,
                raw_response,
                now_text,
                now_text,
            ),
        )
        conn.commit()
    except DatabaseError:
        conn.rollback()
    finally:
        conn.close()
    return portal_get_admin_stripe_payment_by_checkout_session_id(checkout_session_id)


def portal_get_admin_stripe_payment_by_checkout_session_id(checkout_session_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            id,
            admin_id,
            stripe_checkout_session_id,
            stripe_payment_intent_id,
            request_type,
            request_amount,
            currency,
            checkout_url,
            status,
            stripe_status,
            stripe_payment_status,
            payment_reference,
            stripe_paid_at,
            requested_at,
            returned_at,
            confirmed_at,
            last_checked_at,
            linked_plan_request_id,
            applied_at,
            applied_billing_history_id,
            last_error_code,
            last_error_message,
            raw_create_response,
            raw_payment_details,
            raw_last_webhook,
            created_at,
            updated_at
        FROM admin_stripe_payments
        WHERE stripe_checkout_session_id=?
        LIMIT 1
        """,
        (checkout_session_id,),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    return row


def portal_get_admin_stripe_payment_by_payment_intent_id(payment_intent_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            id,
            admin_id,
            stripe_checkout_session_id,
            stripe_payment_intent_id,
            request_type,
            request_amount,
            currency,
            checkout_url,
            status,
            stripe_status,
            stripe_payment_status,
            payment_reference,
            stripe_paid_at,
            requested_at,
            returned_at,
            confirmed_at,
            last_checked_at,
            linked_plan_request_id,
            applied_at,
            applied_billing_history_id,
            last_error_code,
            last_error_message,
            raw_create_response,
            raw_payment_details,
            raw_last_webhook,
            created_at,
            updated_at
        FROM admin_stripe_payments
        WHERE stripe_payment_intent_id=?
        LIMIT 1
        """,
        (payment_intent_id,),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    return row


def portal_get_admin_stripe_payment(payment_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            id,
            admin_id,
            stripe_checkout_session_id,
            stripe_payment_intent_id,
            request_type,
            request_amount,
            currency,
            checkout_url,
            status,
            stripe_status,
            stripe_payment_status,
            payment_reference,
            stripe_paid_at,
            requested_at,
            returned_at,
            confirmed_at,
            last_checked_at,
            linked_plan_request_id,
            applied_at,
            applied_billing_history_id,
            last_error_code,
            last_error_message,
            raw_create_response,
            raw_payment_details,
            raw_last_webhook,
            created_at,
            updated_at
        FROM admin_stripe_payments
        WHERE id=?
        LIMIT 1
        """,
        (payment_id,),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    return row


def portal_get_latest_unlinked_completed_admin_stripe_payment(admin_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            id,
            admin_id,
            stripe_checkout_session_id,
            stripe_payment_intent_id,
            request_type,
            request_amount,
            currency,
            checkout_url,
            status,
            stripe_status,
            stripe_payment_status,
            payment_reference,
            stripe_paid_at,
            requested_at,
            returned_at,
            confirmed_at,
            last_checked_at,
            linked_plan_request_id,
            applied_at,
            applied_billing_history_id,
            last_error_code,
            last_error_message,
            raw_create_response,
            raw_payment_details,
            raw_last_webhook,
            created_at,
            updated_at
        FROM admin_stripe_payments
        WHERE admin_id=? AND linked_plan_request_id IS NULL AND status=?
        ORDER BY COALESCE(NULLIF(confirmed_at, ''), NULLIF(returned_at, ''), created_at) DESC, id DESC
        LIMIT 1
        """,
        (admin_id, ADMIN_STRIPE_STATUS_COMPLETED),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    return row


def portal_get_admin_stripe_payments_for_admin(admin_id, limit=20):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            id,
            admin_id,
            stripe_checkout_session_id,
            stripe_payment_intent_id,
            request_type,
            request_amount,
            currency,
            checkout_url,
            status,
            stripe_status,
            stripe_payment_status,
            payment_reference,
            stripe_paid_at,
            requested_at,
            returned_at,
            confirmed_at,
            last_checked_at,
            linked_plan_request_id,
            applied_at,
            applied_billing_history_id,
            last_error_code,
            last_error_message,
            raw_create_response,
            raw_payment_details,
            raw_last_webhook,
            created_at,
            updated_at
        FROM admin_stripe_payments
        WHERE admin_id=?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (admin_id, limit),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_get_stripe_webhook_event(event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, event_id, event_type, stripe_checkout_session_id, stripe_payment_intent_id,
               processing_status, error_message, processed_at, created_at, updated_at
        FROM admin_stripe_webhook_events
        WHERE event_id=?
        LIMIT 1
        """,
        (event_id,),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    return row


def portal_create_stripe_webhook_event(
    event_id,
    event_type,
    checkout_session_id="",
    payment_intent_id="",
    payload_text="",
    processing_status="received",
):
    now_text = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO admin_stripe_webhook_events (
            event_id,
            event_type,
            stripe_checkout_session_id,
            stripe_payment_intent_id,
            payload_json,
            processing_status,
            processed_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            event_type,
            checkout_session_id,
            payment_intent_id,
            payload_text[:10000],
            processing_status,
            now_text if processing_status in {"processed", "ignored", "duplicate"} else "",
            now_text,
            now_text,
        ),
    )
    conn.commit()
    conn.close()
    return True


def portal_update_stripe_webhook_event(
    event_id,
    processing_status,
    error_message="",
    checkout_session_id="",
    payment_intent_id="",
):
    now_text = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE admin_stripe_webhook_events
        SET processing_status=?,
            error_message=?,
            stripe_checkout_session_id=COALESCE(NULLIF(?, ''), stripe_checkout_session_id),
            stripe_payment_intent_id=COALESCE(NULLIF(?, ''), stripe_payment_intent_id),
            processed_at=?,
            updated_at=?
        WHERE event_id=?
        """,
        (
            processing_status,
            error_message[:500],
            checkout_session_id,
            payment_intent_id,
            now_text if processing_status in {"processed", "ignored", "duplicate", "failed"} else "",
            now_text,
            event_id,
        ),
    )
    conn.commit()
    conn.close()
    return True


def portal_update_admin_stripe_payment_from_remote(
    checkout_session_id,
    payment_details=None,
    webhook_payload=None,
    mark_returned=False,
    error_code="",
    error_message="",
):
    existing = portal_get_admin_stripe_payment_by_checkout_session_id(checkout_session_id)
    if not existing:
        existing = portal_ensure_admin_stripe_payment_from_remote(checkout_session_id, payment_details=payment_details)
    if not existing:
        return None
    session_data = (payment_details or {}).get("json", {}) or {}
    if not isinstance(session_data, dict):
        session_data = {}
    webhook_object = ((webhook_payload or {}).get("data") or {}).get("object") or {}
    if not isinstance(webhook_object, dict):
        webhook_object = {}
    if not session_data and webhook_object:
        session_data = webhook_object
    now_text = portal_now_text()
    updated_status = map_stripe_status(session_data, has_return=mark_returned or bool(existing.get("returned_at")))
    confirmed_at = existing.get("confirmed_at") or ""
    if updated_status in {
        ADMIN_STRIPE_STATUS_COMPLETED,
        ADMIN_STRIPE_STATUS_FAILED,
        ADMIN_STRIPE_STATUS_CANCELED,
        ADMIN_STRIPE_STATUS_EXPIRED,
    }:
        confirmed_at = confirmed_at or now_text
    returned_at = existing.get("returned_at") or ""
    if mark_returned:
        returned_at = now_text
        if updated_status == ADMIN_STRIPE_STATUS_OPEN:
            updated_status = ADMIN_STRIPE_STATUS_RETURNED
    payment_intent = session_data.get("payment_intent")
    if isinstance(payment_intent, dict):
        stripe_payment_intent_id = payment_intent.get("id") or existing.get("stripe_payment_intent_id") or ""
    else:
        stripe_payment_intent_id = payment_intent or existing.get("stripe_payment_intent_id") or ""
    payment_reference = existing.get("payment_reference") or checkout_session_id
    if session_data:
        payment_reference = checkout_session_id or payment_reference
    raw_details = existing.get("raw_payment_details") or ""
    if STRIPE_LOG_RAW_RESPONSE and payment_details is not None:
        raw_details = (payment_details.get("body") or "")[:10000]
    raw_webhook = existing.get("raw_last_webhook") or ""
    if webhook_payload is not None:
        raw_webhook = stripe_json_dumps(webhook_payload)[:10000]
    stripe_paid_at = existing.get("stripe_paid_at") or ""
    if session_data:
        stripe_paid_at = stripe_extract_paid_at(session_data) or stripe_paid_at
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE admin_stripe_payments
        SET stripe_payment_intent_id=?,
            checkout_url=?,
            status=?,
            stripe_status=?,
            stripe_payment_status=?,
            payment_reference=?,
            stripe_paid_at=?,
            returned_at=?,
            confirmed_at=?,
            last_checked_at=?,
            last_error_code=?,
            last_error_message=?,
            raw_payment_details=?,
            raw_last_webhook=?,
            updated_at=?
        WHERE stripe_checkout_session_id=?
        """,
        (
            stripe_payment_intent_id,
            session_data.get("url") or existing.get("checkout_url") or "",
            updated_status,
            session_data.get("status") or existing.get("stripe_status") or "",
            session_data.get("payment_status") or existing.get("stripe_payment_status") or "",
            payment_reference,
            stripe_paid_at,
            returned_at,
            confirmed_at,
            now_text,
            error_code,
            error_message,
            raw_details,
            raw_webhook,
            now_text,
            checkout_session_id,
        ),
    )
    conn.commit()
    conn.close()
    return portal_get_admin_stripe_payment_by_checkout_session_id(checkout_session_id)


def portal_sync_plan_request_verification_with_payment(
    request_id,
    payment_method,
    payment_status,
    payment_date="",
    payment_reference="",
):
    normalized_method = normalize_admin_plan_request_payment_method(payment_method)
    if not request_id or not normalized_method:
        return False
    normalized_verification = ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_UNVERIFIED
    if (
        normalized_method == ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE
        and payment_status == ADMIN_STRIPE_STATUS_COMPLETED
    ):
        normalized_verification = ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED
    now_text = portal_now_text()
    verified_at = now_text if normalized_verification == ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED else None
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE admin_plan_requests
        SET payment_verification_status=?,
            payment_verified_at=?,
            payment_date=COALESCE(NULLIF(?, ''), payment_date),
            payment_reference=COALESCE(NULLIF(?, ''), payment_reference),
            updated_at=?
        WHERE id=?
        """,
        (
            normalized_verification,
            verified_at,
            payment_date or "",
            payment_reference or "",
            now_text,
            request_id,
        ),
    )
    conn.commit()
    conn.close()
    return True


def portal_create_admin_plan_request(
    admin_id,
    request_type,
    payment_method,
    payment_amount,
    payment_date,
    payment_reference,
    request_note="",
    stripe_payment_id=None,
    payment_verification_status="",
    payment_verified_at=None,
):
    now_text = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM admin_plan_requests WHERE admin_id=? AND status=? LIMIT 1",
        (admin_id, ADMIN_PLAN_REQUEST_STATUS_PENDING),
    )
    if c.fetchone():
        conn.close()
        return False, "pending_exists"

    stripe_payment = None
    normalized_verification_status = (
        normalize_admin_plan_request_payment_verification_status(payment_verification_status)
        or ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_PENDING
    )
    if stripe_payment_id:
        c.execute(
            """
            SELECT
                id,
                admin_id,
                stripe_checkout_session_id,
                request_type,
                request_amount,
                status,
                payment_reference,
                stripe_paid_at,
                linked_plan_request_id
            FROM admin_stripe_payments
            WHERE id=?
            LIMIT 1
            """,
            (stripe_payment_id,),
        )
        stripe_payment = row_to_dict(c.fetchone())
        if not stripe_payment or int(stripe_payment.get("admin_id") or 0) != int(admin_id):
            conn.close()
            return False, "stripe_payment_not_found"
        if stripe_payment.get("linked_plan_request_id"):
            conn.close()
            return False, "stripe_payment_already_linked"
        if stripe_payment.get("status") != ADMIN_STRIPE_STATUS_COMPLETED:
            conn.close()
            return False, "stripe_payment_incomplete"
        request_type = stripe_payment.get("request_type") or request_type
        payment_amount = int(stripe_payment.get("request_amount") or payment_amount or 0)
        payment_date = stripe_payment.get("stripe_paid_at") or payment_date
        payment_reference = stripe_payment.get("payment_reference") or payment_reference
        normalized_verification_status = ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED
        payment_verified_at = payment_verified_at or now_text

    c.execute(
        """
        INSERT INTO admin_plan_requests (
            admin_id,
            request_type,
            payment_method,
            payment_amount,
            payment_date,
            payment_reference,
            request_note,
            status,
            review_note,
            reviewed_by_admin_id,
            reviewed_at,
            stripe_payment_id,
            payment_verification_status,
            payment_verified_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            admin_id,
            request_type,
            payment_method,
            payment_amount,
            payment_date,
            payment_reference,
            request_note,
            ADMIN_PLAN_REQUEST_STATUS_PENDING,
            "",
            None,
            None,
            stripe_payment_id,
            normalized_verification_status,
            payment_verified_at,
            now_text,
            now_text,
        ),
    )
    request_id = c.lastrowid if not USE_POSTGRES else None
    if USE_POSTGRES and not request_id:
        c.execute("SELECT currval(pg_get_serial_sequence('admin_plan_requests', 'id')) AS id")
        latest_row = c.fetchone()
        request_id = (latest_row["id"] if isinstance(latest_row, dict) or hasattr(latest_row, "keys") else latest_row[0])
    if stripe_payment_id and request_id:
        c.execute(
            """
            UPDATE admin_stripe_payments
            SET linked_plan_request_id=?, updated_at=?
            WHERE id=? AND linked_plan_request_id IS NULL
            """,
            (request_id, now_text, stripe_payment_id),
        )
    conn.commit()
    conn.close()
    return True, "created", request_id


def portal_get_admin_billing_history(admin_id, limit=20):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, admin_id, billing_status, billed_at, amount, total_amount, billing_count, note, created_at
        FROM admin_billing_history
        WHERE admin_id=?
        ORDER BY COALESCE(NULLIF(billed_at, ''), created_at) DESC, id DESC
        LIMIT ?
        """,
        (admin_id, limit),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_get_admin_billing_history_timeline(admin_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, admin_id, billing_status, billed_at, amount, total_amount, billing_count, note, created_at
        FROM admin_billing_history
        WHERE admin_id=?
        ORDER BY COALESCE(NULLIF(billed_at, ''), created_at) ASC, id ASC
        """,
        (admin_id,),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_get_teams_for_admin(admin_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, admin_id, name, public_id, created_at
        FROM teams
        WHERE admin_id=?
        ORDER BY created_at ASC, id ASC
        """,
        (admin_id,),
    )
    teams = rows_to_dict(c.fetchall())
    conn.close()
    return teams


def build_admin_dashboard_team_guides(teams):
    if not teams:
        return []

    team_ids = [team.get("id") for team in teams if team.get("id") is not None]
    if not team_ids:
        return [dict(team) for team in teams]

    placeholders = ",".join("?" for _ in team_ids)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        f"""
        SELECT team_id, COUNT(1) AS cnt
        FROM portal_members
        WHERE is_active=1 AND team_id IN ({placeholders})
        GROUP BY team_id
        """,
        team_ids,
    )
    member_counts = {row["team_id"]: row["cnt"] for row in c.fetchall()}
    c.execute(
        f"""
        SELECT team_id, COUNT(1) AS cnt
        FROM portal_events
        WHERE team_id IN ({placeholders})
        GROUP BY team_id
        """,
        team_ids,
    )
    event_counts = {row["team_id"]: row["cnt"] for row in c.fetchall()}
    conn.close()

    guided_teams = []
    for team in teams:
        guided_team = dict(team)
        team_id = guided_team.get("id")
        member_count = member_counts.get(team_id, 0)
        event_count = event_counts.get(team_id, 0)
        has_public_content = member_count > 0 or event_count > 0
        guided_team["member_count"] = member_count
        guided_team["event_count"] = event_count
        guided_team["has_public_content"] = has_public_content
        guided_team["highlight_member_setup"] = not has_public_content
        guided_team["highlight_event_setup"] = not has_public_content
        guided_team["highlight_member_url_copy"] = has_public_content
        guided_teams.append(guided_team)
    return guided_teams


def portal_get_team_by_public_id(public_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, admin_id, name, public_id, created_at FROM teams WHERE public_id=?",
        (public_id,),
    )
    team = row_to_dict(c.fetchone())
    conn.close()
    return team


def portal_get_team(team_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, admin_id, name, public_id, created_at FROM teams WHERE id=?",
        (team_id,),
    )
    team = row_to_dict(c.fetchone())
    conn.close()
    return team


def portal_create_team(admin_id, name):
    conn = get_db_connection()
    c = conn.cursor()
    public_id = generate_unique_public_id(c)
    c.execute(
        """
        INSERT INTO teams (admin_id, name, public_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (admin_id, name, public_id, portal_now_text()),
    )
    conn.commit()
    c.execute(
        "SELECT id, admin_id, name, public_id, created_at FROM teams WHERE public_id=?",
        (public_id,),
    )
    team = row_to_dict(c.fetchone())
    conn.close()
    return team


def delete_team_related_records(cursor, team_id):
    cursor.execute(
        """
        DELETE FROM portal_collection_event_members
        WHERE collection_event_id IN (
            SELECT id FROM portal_collection_events WHERE team_id=?
        )
        """,
        (team_id,),
    )
    cursor.execute("DELETE FROM portal_collection_events WHERE team_id=?", (team_id,))
    cursor.execute("DELETE FROM portal_attendance WHERE team_id=?", (team_id,))
    cursor.execute("DELETE FROM portal_events WHERE team_id=?", (team_id,))
    cursor.execute("DELETE FROM portal_members WHERE team_id=?", (team_id,))
    cursor.execute("DELETE FROM team_attendance WHERE team_id=?", (team_id,))
    cursor.execute("DELETE FROM team_members WHERE team_id=?", (team_id,))


def portal_delete_team(admin_id, team_id):
    target_team = portal_get_team(team_id)
    if target_team and target_team["admin_id"] != admin_id:
        target_team = None
    if not target_team:
        return False

    conn = get_db_connection()
    c = conn.cursor()
    delete_team_related_records(c, team_id)
    c.execute("DELETE FROM teams WHERE id=? AND admin_id=?", (team_id, admin_id))
    conn.commit()
    conn.close()
    return True


def portal_get_members(team_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, team_id, name, display_order, note, is_active, created_at, updated_at
        FROM portal_members
        WHERE team_id=?
        ORDER BY display_order ASC, id ASC
        """,
        (team_id,),
    )
    members = rows_to_dict(c.fetchall())
    conn.close()
    return members


def _coerce_positive_int(value):
    try:
        converted = int(value)
    except (TypeError, ValueError):
        return None
    return converted if converted > 0 else None


def _normalize_member_rows(cursor, team_id):
    cursor.execute(
        """
        SELECT id
        FROM portal_members
        WHERE team_id=?
        ORDER BY display_order ASC, id ASC
        """,
        (team_id,),
    )
    member_ids = [row["id"] for row in cursor.fetchall()]
    now_text = portal_now_text()
    for index, member_id in enumerate(member_ids, start=1):
        cursor.execute(
            """
            UPDATE portal_members
            SET display_order=?, updated_at=?
            WHERE team_id=? AND id=?
            """,
            (index, now_text, team_id, member_id),
        )


def portal_get_member(team_id, member_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, team_id, name, display_order, note, is_active, created_at, updated_at
        FROM portal_members
        WHERE team_id=? AND id=?
        """,
        (team_id, member_id),
    )
    member = row_to_dict(c.fetchone())
    conn.close()
    return member


def portal_get_members_for_team(team_id, include_inactive=False):
    conn = get_db_connection()
    c = conn.cursor()
    if include_inactive:
        c.execute(
            """
            SELECT id, team_id, name, display_order, note, is_active, created_at, updated_at
            FROM portal_members
            WHERE team_id=?
            ORDER BY display_order ASC, id ASC
            """,
            (team_id,),
        )
    else:
        c.execute(
            """
            SELECT id, team_id, name, display_order, note, is_active, created_at, updated_at
            FROM portal_members
            WHERE team_id=? AND is_active=1
            ORDER BY display_order ASC, id ASC
            """,
            (team_id,),
        )
    members = rows_to_dict(c.fetchall())
    conn.close()
    return members


def portal_add_member(team_id, name, note="", display_order=None):
    target_name = (name or "").strip()
    if not target_name:
        return None, "invalid_name"

    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT id, team_id, name, display_order, note, is_active, created_at, updated_at
        FROM portal_members
        WHERE team_id=? AND name=?
        """,
        (team_id, target_name),
    )
    existing = row_to_dict(c.fetchone())
    desired_order = _coerce_positive_int(display_order)

    if existing:
        update_fields = ["note=?", "updated_at=?"]
        update_params = [note or "", portal_now_text()]
        if desired_order is not None:
            update_fields.append("display_order=?")
            update_params.append(desired_order)
        if not existing.get("is_active"):
            update_fields.append("is_active=1")
        update_params.extend([team_id, existing["id"]])
        c.execute(
            f"UPDATE portal_members SET {', '.join(update_fields)} WHERE team_id=? AND id=?",
            update_params,
        )
        _normalize_member_rows(c, team_id)
        conn.commit()
        c.execute(
            """
            SELECT id, team_id, name, display_order, note, is_active, created_at, updated_at
            FROM portal_members
            WHERE team_id=? AND id=?
            """,
            (team_id, existing["id"]),
        )
        member = row_to_dict(c.fetchone())
        conn.close()
        return member, "reactivated" if not existing.get("is_active") else "exists"

    c.execute("SELECT COALESCE(MAX(display_order), 0) AS max_display_order FROM portal_members WHERE team_id=?", (team_id,))
    max_display_order = (row_to_dict(c.fetchone()) or {}).get("max_display_order", 0) or 0
    final_order = desired_order if desired_order is not None else max_display_order + 1
    now_text = portal_now_text()
    c.execute(
        """
        INSERT INTO portal_members (team_id, name, display_order, note, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (team_id, target_name, final_order, note or "", 1, now_text, now_text),
    )
    member_id = c.lastrowid if not USE_POSTGRES else None
    _normalize_member_rows(c, team_id)
    if not member_id:
        c.execute("SELECT id FROM portal_members WHERE team_id=? AND name=?", (team_id, target_name))
        row = c.fetchone()
        member_id = row["id"] if row else None
    conn.commit()
    c.execute(
        """
        SELECT id, team_id, name, display_order, note, is_active, created_at, updated_at
        FROM portal_members
        WHERE team_id=? AND id=?
        """,
        (team_id, member_id),
    )
    member = row_to_dict(c.fetchone())
    conn.close()
    return member, "created"


def portal_update_member(team_id, member_id, name=None, note=None, is_active=None):
    current_member = portal_get_member(team_id, member_id)
    if not current_member:
        return None, "not_found"

    update_name = (name if name is not None else current_member.get("name") or "").strip()
    if not update_name:
        return None, "invalid_name"
    update_note = note if note is not None else (current_member.get("note") or "")
    active_value = current_member.get("is_active", 1) if is_active is None else (1 if bool(is_active) else 0)

    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            UPDATE portal_members
            SET name=?, note=?, is_active=?, updated_at=?
            WHERE team_id=? AND id=?
            """,
            (update_name, update_note, active_value, portal_now_text(), team_id, member_id),
        )
    except DatabaseError:
        conn.close()
        return None, "validation_error"

    _normalize_member_rows(c, team_id)
    conn.commit()
    c.execute(
        """
        SELECT id, team_id, name, display_order, note, is_active, created_at, updated_at
        FROM portal_members
        WHERE team_id=? AND id=?
        """,
        (team_id, member_id),
    )
    member = row_to_dict(c.fetchone())
    conn.close()
    return member, "updated"


def portal_reorder_members(team_id, ordered_member_ids):
    if not ordered_member_ids:
        return False, "invalid_order"

    normalized_ids = []
    seen_ids = set()
    for raw_id in ordered_member_ids:
        member_id = _coerce_positive_int(raw_id)
        if member_id is None or member_id in seen_ids:
            return False, "invalid_order"
        seen_ids.add(member_id)
        normalized_ids.append(member_id)

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id
        FROM portal_members
        WHERE team_id=?
        ORDER BY display_order ASC, id ASC
        """,
        (team_id,),
    )
    existing_ids = [row["id"] for row in c.fetchall()]
    existing_id_set = set(existing_ids)
    if not set(normalized_ids).issubset(existing_id_set):
        conn.close()
        return False, "not_found"

    remaining_ids = [member_id for member_id in existing_ids if member_id not in seen_ids]
    final_ids = normalized_ids + remaining_ids
    now_text = portal_now_text()
    for order_no, member_id in enumerate(final_ids, start=1):
        c.execute(
            """
            UPDATE portal_members
            SET display_order=?, updated_at=?
            WHERE team_id=? AND id=?
            """,
            (order_no, now_text, team_id, member_id),
        )
    conn.commit()
    conn.close()
    return True, "updated"


def portal_deactivate_member(team_id, member_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE portal_members
        SET is_active=0, updated_at=?
        WHERE team_id=? AND id=?
        """,
        (portal_now_text(), team_id, member_id),
    )
    updated = c.rowcount > 0
    if updated:
        _normalize_member_rows(c, team_id)
    conn.commit()
    conn.close()
    return updated


def portal_delete_member_by_id(team_id, member_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT name
        FROM portal_members
        WHERE team_id=? AND id=?
        """,
        (team_id, member_id),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return False

    member_name = row["name"]
    c.execute(
        "DELETE FROM portal_members WHERE team_id=? AND id=?",
        (team_id, member_id),
    )
    c.execute(
        "DELETE FROM portal_attendance WHERE team_id=? AND member_name=?",
        (team_id, member_name),
    )
    _normalize_member_rows(c, team_id)
    conn.commit()
    conn.close()
    return True


def portal_move_member(team_id, member_id, direction):
    direction_value = (direction or "").strip().lower()
    if direction_value not in {"up", "down"}:
        return False, "invalid_direction"

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id
        FROM portal_members
        WHERE team_id=?
        ORDER BY display_order ASC, id ASC
        """,
        (team_id,),
    )
    member_ids = [row["id"] for row in c.fetchall()]
    if member_id not in member_ids:
        conn.close()
        return False, "not_found"

    current_index = member_ids.index(member_id)
    if direction_value == "up" and current_index > 0:
        member_ids[current_index - 1], member_ids[current_index] = member_ids[current_index], member_ids[current_index - 1]
    elif direction_value == "down" and current_index < len(member_ids) - 1:
        member_ids[current_index + 1], member_ids[current_index] = member_ids[current_index], member_ids[current_index + 1]
    else:
        conn.close()
        return True, "unchanged"

    now_text = portal_now_text()
    for order_no, target_member_id in enumerate(member_ids, start=1):
        c.execute(
            "UPDATE portal_members SET display_order=?, updated_at=? WHERE team_id=? AND id=?",
            (order_no, now_text, team_id, target_member_id),
        )
    conn.commit()
    conn.close()
    return True, "updated"


def portal_delete_member(team_id, name):
    target_name = (name or "").strip()
    if not target_name:
        return False

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM portal_members WHERE team_id=? AND name=? LIMIT 1",
        (team_id, target_name),
    )
    had_member = c.fetchone() is not None
    c.execute(
        "SELECT 1 FROM portal_attendance WHERE team_id=? AND member_name=? LIMIT 1",
        (team_id, target_name),
    )
    had_attendance = c.fetchone() is not None
    if not had_member and not had_attendance:
        conn.close()
        return False

    c.execute(
        "DELETE FROM portal_members WHERE team_id=? AND name=?",
        (team_id, target_name),
    )
    c.execute(
        "DELETE FROM portal_attendance WHERE team_id=? AND member_name=?",
        (team_id, target_name),
    )
    conn.commit()
    conn.close()
    return True


def portal_get_events(team_ids):
    if not team_ids:
        return []

    placeholders = ",".join("?" for _ in team_ids)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        f"""
        SELECT id, team_id, date, start_time, end_time, opponent, place, created_at
        FROM portal_events
        WHERE team_id IN ({placeholders})
        ORDER BY date, start_time, id
        """,
        list(team_ids),
    )
    events = rows_to_dict(c.fetchall())
    conn.close()
    return events


def portal_create_event(team_id, date, start_time, end_time, opponent, place):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO portal_events (team_id, date, start_time, end_time, opponent, place, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (team_id, date, start_time, end_time, opponent, place, portal_now_text()),
    )
    conn.commit()
    if USE_POSTGRES:
        event_id = c.lastrowid if hasattr(c, "lastrowid") else None
    else:
        event_id = c.lastrowid
    if event_id:
        c.execute(
            """
            SELECT id, team_id, date, start_time, end_time, opponent, place, created_at
            FROM portal_events
            WHERE id=?
            """,
            (event_id,),
        )
    else:
        c.execute(
            """
            SELECT id, team_id, date, start_time, end_time, opponent, place, created_at
            FROM portal_events
            WHERE team_id=? AND date=? AND start_time=? AND end_time=? AND opponent=? AND place=?
            ORDER BY id DESC LIMIT 1
            """,
            (team_id, date, start_time, end_time, opponent, place),
        )
    event = row_to_dict(c.fetchone())
    conn.close()
    return event


def portal_get_event(team_id, event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, team_id, date, start_time, end_time, opponent, place, created_at
        FROM portal_events
        WHERE team_id=? AND id=?
        """,
        (team_id, event_id),
    )
    event = row_to_dict(c.fetchone())
    conn.close()
    return event


def build_collection_event_summary(collection_event, member_rows):
    amount = int(collection_event.get("amount") or 0)
    target_count = len(member_rows)
    collected_count = len(
        [row for row in member_rows if normalize_collection_status(row.get("status")) == COLLECTION_STATUS_COLLECTED]
    )
    pending_count = len(
        [row for row in member_rows if normalize_collection_status(row.get("status")) == COLLECTION_STATUS_PENDING]
    )
    exempt_count = len(
        [row for row in member_rows if normalize_collection_status(row.get("status")) == COLLECTION_STATUS_EXEMPT]
    )
    return {
        "target_count": target_count,
        "collected_count": collected_count,
        "pending_count": pending_count,
        "exempt_count": exempt_count,
        "collected_total": amount * collected_count,
        "pending_total": amount * pending_count,
    }


def _get_collection_target_members(team_id, target_member_ids=None, select_all_active=False):
    members = portal_get_members_for_team(team_id, include_inactive=True)
    active_members = [member for member in members if member.get("is_active")]
    if select_all_active:
        return active_members

    selected_ids = []
    seen_ids = set()
    for raw_member_id in target_member_ids or []:
        member_id = _coerce_positive_int(raw_member_id)
        if member_id is None or member_id in seen_ids:
            continue
        seen_ids.add(member_id)
        selected_ids.append(member_id)
    if not selected_ids:
        return []

    selected_set = set(selected_ids)
    return [member for member in active_members if member.get("id") in selected_set]


def portal_create_collection_event(
    team_id,
    title,
    collection_date,
    amount,
    note,
    target_member_ids=None,
    target_mode="manual",
    attendance_event_id=None,
):
    target_members = _get_collection_target_members(
        team_id,
        target_member_ids=target_member_ids,
        select_all_active=(target_mode == "all_active"),
    )
    if not target_members:
        return None, "members_required"

    now_text = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO portal_collection_events (
            team_id,
            title,
            collection_date,
            amount,
            note,
            target_mode,
            attendance_event_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            team_id,
            title,
            collection_date,
            amount,
            note,
            target_mode,
            attendance_event_id,
            now_text,
            now_text,
        ),
    )
    collection_event_id = c.lastrowid if not USE_POSTGRES else None
    if not collection_event_id:
        c.execute(
            """
            SELECT id
            FROM portal_collection_events
            WHERE team_id=? AND title=? AND collection_date=? AND amount=? AND created_at=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (team_id, title, collection_date, amount, now_text),
        )
        created_row = c.fetchone()
        collection_event_id = created_row["id"] if created_row else None
    if not collection_event_id:
        conn.rollback()
        conn.close()
        return None, "create_failed"

    for member in target_members:
        c.execute(
            """
            INSERT INTO portal_collection_event_members (
                collection_event_id,
                member_id,
                member_name,
                status,
                collected_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection_event_id,
                member.get("id"),
                member.get("name") or "",
                COLLECTION_STATUS_PENDING,
                None,
                now_text,
                now_text,
            ),
        )
    conn.commit()
    conn.close()
    return portal_get_collection_event(team_id, collection_event_id), "created"


def portal_get_collection_events(team_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            id,
            team_id,
            title,
            collection_date,
            amount,
            note,
            target_mode,
            attendance_event_id,
            created_at,
            updated_at
        FROM portal_collection_events
        WHERE team_id=?
        ORDER BY collection_date DESC, id DESC
        """,
        (team_id,),
    )
    events = rows_to_dict(c.fetchall())
    conn.close()
    return events


def portal_get_collection_event(team_id, collection_event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            id,
            team_id,
            title,
            collection_date,
            amount,
            note,
            target_mode,
            attendance_event_id,
            created_at,
            updated_at
        FROM portal_collection_events
        WHERE team_id=? AND id=?
        """,
        (team_id, collection_event_id),
    )
    event = row_to_dict(c.fetchone())
    conn.close()
    return event


def portal_get_collection_event_members(team_id, collection_event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            cem.id,
            cem.collection_event_id,
            cem.member_id,
            cem.member_name,
            cem.status,
            cem.collected_at,
            cem.created_at,
            cem.updated_at,
            pm.name AS current_member_name,
            pm.display_order,
            pm.is_active AS current_member_is_active
        FROM portal_collection_event_members cem
        INNER JOIN portal_collection_events ce
            ON ce.id = cem.collection_event_id
        LEFT JOIN portal_members pm
            ON pm.team_id = ce.team_id AND pm.id = cem.member_id
        WHERE ce.team_id=? AND cem.collection_event_id=?
        ORDER BY
            CASE WHEN pm.display_order IS NULL THEN 1 ELSE 0 END,
            pm.display_order ASC,
            cem.id ASC
        """,
        (team_id, collection_event_id),
    )
    members = rows_to_dict(c.fetchall())
    conn.close()
    return members


def portal_update_collection_event(
    team_id,
    collection_event_id,
    title,
    collection_date,
    amount,
    note,
    target_member_ids=None,
    target_mode="manual",
    attendance_event_id=None,
):
    current_event = portal_get_collection_event(team_id, collection_event_id)
    if not current_event:
        return None, "not_found"

    target_members = _get_collection_target_members(
        team_id,
        target_member_ids=target_member_ids,
        select_all_active=(target_mode == "all_active"),
    )
    if not target_members:
        return None, "members_required"

    current_member_rows = portal_get_collection_event_members(team_id, collection_event_id)
    preserved_by_member_id = {}
    for row in current_member_rows:
        member_id = _coerce_positive_int(row.get("member_id"))
        if member_id is not None:
            preserved_by_member_id[member_id] = row

    now_text = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE portal_collection_events
        SET title=?, collection_date=?, amount=?, note=?, target_mode=?, attendance_event_id=?, updated_at=?
        WHERE team_id=? AND id=?
        """,
        (
            title,
            collection_date,
            amount,
            note,
            target_mode,
            attendance_event_id,
            now_text,
            team_id,
            collection_event_id,
        ),
    )
    c.execute("DELETE FROM portal_collection_event_members WHERE collection_event_id=?", (collection_event_id,))
    for member in target_members:
        preserved = preserved_by_member_id.get(member.get("id"))
        preserved_status = normalize_collection_status((preserved or {}).get("status")) or COLLECTION_STATUS_PENDING
        preserved_collected_at = (
            preserved.get("collected_at") if preserved_status == COLLECTION_STATUS_COLLECTED and preserved else None
        )
        c.execute(
            """
            INSERT INTO portal_collection_event_members (
                collection_event_id,
                member_id,
                member_name,
                status,
                collected_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection_event_id,
                member.get("id"),
                member.get("name") or "",
                preserved_status,
                preserved_collected_at,
                (preserved or {}).get("created_at") or now_text,
                now_text,
            ),
        )
    conn.commit()
    conn.close()
    return portal_get_collection_event(team_id, collection_event_id), "updated"


def portal_delete_collection_event(team_id, collection_event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM portal_collection_events WHERE team_id=? AND id=?", (team_id, collection_event_id))
    if not c.fetchone():
        conn.close()
        return False
    c.execute("DELETE FROM portal_collection_event_members WHERE collection_event_id=?", (collection_event_id,))
    c.execute("DELETE FROM portal_collection_events WHERE team_id=? AND id=?", (team_id, collection_event_id))
    conn.commit()
    conn.close()
    return True


def portal_duplicate_collection_event(team_id, collection_event_id):
    source_event = portal_get_collection_event(team_id, collection_event_id)
    if not source_event:
        return None, "not_found"

    member_rows = portal_get_collection_event_members(team_id, collection_event_id)
    target_member_ids = [
        row.get("member_id")
        for row in member_rows
        if _coerce_positive_int(row.get("member_id")) is not None
    ]
    if not target_member_ids:
        return None, "members_required"

    duplicated_event, status = portal_create_collection_event(
        team_id,
        source_event.get("title") or "",
        source_event.get("collection_date") or "",
        int(source_event.get("amount") or 0),
        source_event.get("note") or "",
        target_member_ids=target_member_ids,
        target_mode=source_event.get("target_mode") or "manual",
        attendance_event_id=source_event.get("attendance_event_id"),
    )
    return duplicated_event, status


def portal_update_collection_member_status(team_id, collection_event_id, member_id, status):
    normalized_status = normalize_collection_status(status)
    if not normalized_status:
        return None, "invalid_status"

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT cem.id
        FROM portal_collection_event_members cem
        INNER JOIN portal_collection_events ce
            ON ce.id = cem.collection_event_id
        WHERE ce.team_id=? AND ce.id=? AND cem.member_id=?
        """,
        (team_id, collection_event_id, member_id),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return None, "not_found"

    now_text = portal_now_text()
    collected_at = now_text if normalized_status == COLLECTION_STATUS_COLLECTED else None
    c.execute(
        """
        UPDATE portal_collection_event_members
        SET status=?, collected_at=?, updated_at=?
        WHERE id=?
        """,
        (normalized_status, collected_at, now_text, row["id"]),
    )
    conn.commit()
    conn.close()

    member_rows = portal_get_collection_event_members(team_id, collection_event_id)
    for member_row in member_rows:
        if int(member_row.get("member_id") or 0) == int(member_id):
            return member_row, "updated"
    return None, "not_found"


def portal_update_event(team_id, event_id, date, start_time, end_time, opponent, place):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE portal_events
        SET date=?, start_time=?, end_time=?, opponent=?, place=?
        WHERE team_id=? AND id=?
        """,
        (date, start_time, end_time, opponent, place, team_id, event_id),
    )
    conn.commit()
    c.execute(
        """
        SELECT id, team_id, date, start_time, end_time, opponent, place, created_at
        FROM portal_events
        WHERE team_id=? AND id=?
        """,
        (team_id, event_id),
    )
    event = row_to_dict(c.fetchone())
    conn.close()
    return event


def portal_delete_event(team_id, event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM portal_attendance WHERE team_id=? AND event_id=?",
        (team_id, event_id),
    )
    c.execute(
        "DELETE FROM portal_transport_assignments WHERE team_id=? AND event_id=?",
        (team_id, event_id),
    )
    c.execute(
        "DELETE FROM portal_transport_responses WHERE team_id=? AND event_id=?",
        (team_id, event_id),
    )
    c.execute(
        "DELETE FROM portal_events WHERE team_id=? AND id=?",
        (team_id, event_id),
    )
    conn.commit()
    conn.close()


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
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO portal_attendance (team_id, event_id, member_name, status, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(team_id, event_id, member_name)
        DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at
        """,
        (team_id, event_id, member_name, status, portal_now_text()),
    )
    conn.commit()
    conn.close()
    portal_touch_admin_last_attendance_updated_by_team(team_id)


def portal_get_attendance(team_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, team_id, event_id, member_name, status, updated_at
        FROM portal_attendance
        WHERE team_id=?
        ORDER BY
            CASE status
                WHEN '参加' THEN 0
                WHEN '未定' THEN 1
                WHEN '不参加' THEN 2
                ELSE 99
            END,
            member_name
        """,
        (team_id,),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_get_attendance_for_event(team_id, event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, team_id, event_id, member_name, status, updated_at
        FROM portal_attendance
        WHERE team_id=? AND event_id=?
        ORDER BY member_name
        """,
        (team_id, event_id),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_get_transport_responses(team_id, event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            pm.id AS member_id,
            pm.name AS member_name,
            pm.display_order,
            ptr.transport_role,
            ptr.seats_available,
            ptr.note,
            ptr.updated_at
        FROM portal_members pm
        LEFT JOIN portal_transport_responses ptr
            ON ptr.team_id = pm.team_id
           AND ptr.event_id = ?
           AND ptr.member_name = pm.name
        WHERE pm.team_id=? AND pm.is_active=1
        ORDER BY pm.display_order ASC, pm.id ASC
        """,
        (event_id, team_id),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_get_all_transport_responses_for_event(team_id, event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
            ptr.id,
            ptr.team_id,
            ptr.event_id,
            ptr.member_name,
            ptr.transport_role,
            ptr.seats_available,
            ptr.note,
            ptr.updated_at,
            pm.id AS member_id,
            pm.display_order,
            pm.is_active
        FROM portal_transport_responses ptr
        LEFT JOIN portal_members pm
            ON pm.team_id = ptr.team_id AND pm.name = ptr.member_name
        WHERE ptr.team_id=? AND ptr.event_id=?
        ORDER BY
            CASE WHEN pm.display_order IS NULL THEN 1 ELSE 0 END,
            pm.display_order ASC,
            ptr.member_name ASC
        """,
        (team_id, event_id),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_replace_transport_responses(team_id, event_id, response_rows):
    now_text = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM portal_transport_assignments WHERE team_id=? AND event_id=?",
        (team_id, event_id),
    )
    c.execute(
        "DELETE FROM portal_transport_responses WHERE team_id=? AND event_id=?",
        (team_id, event_id),
    )
    for row in response_rows:
        member_name = (row.get("member_name") or "").strip()
        if not member_name:
            continue
        transport_role = normalize_transport_role(row.get("transport_role")) or TRANSPORT_ROLE_NONE
        seats_available = _coerce_positive_int(row.get("seats_available")) or 0
        if transport_role != TRANSPORT_ROLE_DRIVER:
            seats_available = 0
        c.execute(
            """
            INSERT INTO portal_transport_responses (
                team_id,
                event_id,
                member_name,
                transport_role,
                seats_available,
                note,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                team_id,
                event_id,
                member_name,
                transport_role,
                seats_available,
                (row.get("note") or "").strip(),
                now_text,
            ),
        )
    conn.commit()
    conn.close()


def portal_replace_transport_responses_for_attendees(team_id, event_id, attendee_names, response_rows):
    allowed_names = set(_normalize_name_list(attendee_names))
    existing_rows = portal_get_all_transport_responses_for_event(team_id, event_id)
    preserved_rows = []
    seen_names = set()
    for row in response_rows:
        member_name = (row.get("member_name") or "").strip()
        if not member_name or member_name not in allowed_names or member_name in seen_names:
            continue
        preserved_rows.append(row)
        seen_names.add(member_name)
    for row in existing_rows:
        member_name = (row.get("member_name") or "").strip()
        if not member_name or member_name in allowed_names or member_name in seen_names:
            continue
        preserved_rows.append(
            {
                "member_name": member_name,
                "transport_role": row.get("transport_role"),
                "seats_available": row.get("seats_available"),
                "note": row.get("note"),
            }
        )
        seen_names.add(member_name)
    portal_replace_transport_responses(team_id, event_id, preserved_rows)


def portal_get_transport_assignments(team_id, event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, team_id, event_id, driver_name, passenger_name, display_order, created_at, updated_at
        FROM portal_transport_assignments
        WHERE team_id=? AND event_id=?
        ORDER BY display_order ASC, id ASC
        """,
        (team_id, event_id),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def portal_prune_transport_assignments(team_id, event_id, valid_member_names):
    valid_names = set(_normalize_name_list(valid_member_names))
    if not valid_names:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "DELETE FROM portal_transport_assignments WHERE team_id=? AND event_id=?",
            (team_id, event_id),
        )
        conn.commit()
        conn.close()
        return

    conn = get_db_connection()
    c = conn.cursor()
    assignment_rows = portal_get_transport_assignments(team_id, event_id)
    retained_rows = []
    for row in assignment_rows:
        passenger_name = (row.get("passenger_name") or "").strip()
        driver_name = (row.get("driver_name") or "").strip()
        if passenger_name in valid_names and driver_name in valid_names:
            retained_rows.append({"passenger_name": passenger_name, "driver_name": driver_name})
    c.execute(
        "DELETE FROM portal_transport_assignments WHERE team_id=? AND event_id=?",
        (team_id, event_id),
    )
    now_text = portal_now_text()
    for index, row in enumerate(retained_rows, start=1):
        c.execute(
            """
            INSERT INTO portal_transport_assignments (
                team_id,
                event_id,
                driver_name,
                passenger_name,
                display_order,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (team_id, event_id, row["driver_name"], row["passenger_name"], index, now_text, now_text),
        )
    conn.commit()
    conn.close()


def portal_save_transport_assignments(team_id, event_id, requested_assignments):
    response_rows = portal_get_all_transport_responses_for_event(team_id, event_id)
    driver_capacity = {}
    passenger_names = set()
    for row in response_rows:
        member_name = (row.get("member_name") or "").strip()
        transport_role = normalize_transport_role(row.get("transport_role")) or TRANSPORT_ROLE_NONE
        if transport_role == TRANSPORT_ROLE_DRIVER:
            driver_capacity[member_name] = max(0, int(row.get("seats_available") or 0))
        elif transport_role == TRANSPORT_ROLE_PASSENGER:
            passenger_names.add(member_name)

    normalized_assignments = []
    assigned_passengers = set()
    seats_used = {}
    for raw_assignment in requested_assignments:
        passenger_name = (raw_assignment.get("passenger_name") or "").strip()
        driver_name = (raw_assignment.get("driver_name") or "").strip()
        if not passenger_name or not driver_name:
            continue
        if passenger_name in assigned_passengers:
            continue
        if passenger_name not in passenger_names:
            return False, "乗車希望ではないメンバーが含まれています。"
        if driver_name not in driver_capacity:
            return False, "運転者として登録されていないメンバーが含まれています。"
        if passenger_name == driver_name:
            return False, "自分自身を自分の車に割り当てることはできません。"
        seats_used[driver_name] = seats_used.get(driver_name, 0) + 1
        if seats_used[driver_name] > driver_capacity.get(driver_name, 0):
            return False, f"{driver_name} さんの同乗可能人数を超えています。"
        assigned_passengers.add(passenger_name)
        normalized_assignments.append({"passenger_name": passenger_name, "driver_name": driver_name})

    now_text = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM portal_transport_assignments WHERE team_id=? AND event_id=?",
        (team_id, event_id),
    )
    for index, assignment in enumerate(normalized_assignments, start=1):
        c.execute(
            """
            INSERT INTO portal_transport_assignments (
                team_id,
                event_id,
                driver_name,
                passenger_name,
                display_order,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                team_id,
                event_id,
                assignment["driver_name"],
                assignment["passenger_name"],
                index,
                now_text,
                now_text,
            ),
        )
    conn.commit()
    conn.close()
    return True, "saved"


def format_member_analytics_rate(numerator, denominator):
    if denominator <= 0:
        return "-"
    return f"{(numerator / denominator) * 100:.1f}%"


ADMIN_MEMBER_ANALYTICS_TABS = {
    "basic": {
        "label": "基本情報",
        "columns": [],
    },
    "attendance": {
        "label": "出欠情報",
        "columns": [
            ("attendance_count", "参加回数"),
            ("attendance_rate", "参加割合"),
            ("absence_count", "不参加回数"),
            ("absence_rate", "不参加割合"),
            ("unanswered_count", "未回答回数"),
            ("unanswered_rate", "未回答割合"),
        ],
    },
    "transport": {
        "label": "配車情報",
        "columns": [
            ("driver_count", "運転回数"),
            ("driver_rate", "運転割合"),
            ("passenger_count", "乗車回数"),
            ("passenger_rate", "乗車割合"),
            ("direct_count", "現地集合回数"),
            ("direct_rate", "現地集合割合"),
        ],
    },
    "collection": {
        "label": "集金情報",
        "columns": [
            ("collection_amount_label", "集金額合計"),
            ("collection_count", "回収回数"),
            ("pending_collection_count", "未回収回数"),
            ("pending_collection_amount_label", "未回収額"),
        ],
    },
    "all": {
        "label": "すべて",
        "columns": [
            ("attendance_count", "参加回数"),
            ("attendance_rate", "参加割合"),
            ("absence_count", "不参加回数"),
            ("absence_rate", "不参加割合"),
            ("unanswered_count", "未回答回数"),
            ("unanswered_rate", "未回答割合"),
            ("driver_count", "運転回数"),
            ("driver_rate", "運転割合"),
            ("passenger_count", "乗車回数"),
            ("passenger_rate", "乗車割合"),
            ("direct_count", "現地集合回数"),
            ("direct_rate", "現地集合割合"),
            ("collection_amount_label", "集金額合計"),
            ("collection_count", "回収回数"),
            ("pending_collection_count", "未回収回数"),
            ("pending_collection_amount_label", "未回収額"),
        ],
    },
}


def normalize_admin_member_analytics_tab(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_MEMBER_ANALYTICS_TABS else "basic"


def parse_iso_date_or_none(value):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def resolve_member_analytics_period(team_id, start_date=None, end_date=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT MIN(period_date) AS min_date, MAX(period_date) AS max_date
        FROM (
            SELECT date AS period_date
            FROM portal_events
            WHERE team_id=? AND date IS NOT NULL AND date <> ''
            UNION ALL
            SELECT collection_date AS period_date
            FROM portal_collection_events
            WHERE team_id=? AND collection_date IS NOT NULL AND collection_date <> ''
        ) period_source
        """,
        (team_id, team_id),
    )
    period_row = row_to_dict(c.fetchone()) or {}
    conn.close()

    available_start = parse_iso_date_or_none(period_row.get("min_date")) or date.today()
    available_end = parse_iso_date_or_none(period_row.get("max_date")) or available_start

    resolved_start = parse_iso_date_or_none(start_date) or available_start
    resolved_end = parse_iso_date_or_none(end_date) or available_end
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start

    return {
        "start_date": resolved_start,
        "end_date": resolved_end,
        "start_date_value": resolved_start.isoformat(),
        "end_date_value": resolved_end.isoformat(),
        "available_start_date": available_start,
        "available_end_date": available_end,
        "available_start_date_value": available_start.isoformat(),
        "available_end_date_value": available_end.isoformat(),
    }


def build_admin_member_analytics(team_id, period_start=None, period_end=None, include_inactive=False):
    members = portal_get_members_for_team(team_id, include_inactive=include_inactive)
    member_order = []
    member_stats = {}
    for member in members:
        member_name = (member.get("name") or "").strip()
        if not member_name:
            continue
        member_created_at = parse_portal_datetime(member.get("created_at"))
        member_start_date = member_created_at.date() if member_created_at else None
        member_order.append(member_name)
        member_stats[member_name] = {
            "member_id": member.get("id"),
            "member_name": member_name,
            "status_label": "有効" if member.get("is_active") else "無効",
            "is_active": bool(member.get("is_active")),
            "member_start_date": member_start_date,
            "attendance_count": 0,
            "attendance_rate": "-",
            "absence_count": 0,
            "absence_rate": "-",
            "unanswered_count": 0,
            "unanswered_rate": "-",
            "collection_count": 0,
            "collection_amount": 0,
            "collection_amount_label": format_currency_yen(0),
            "pending_collection_count": 0,
            "pending_collection_amount": 0,
            "pending_collection_amount_label": format_currency_yen(0),
            "driver_count": 0,
            "passenger_count": 0,
            "direct_count": 0,
            "driver_rate": "-",
            "passenger_rate": "-",
            "direct_rate": "-",
            "_attendance_denominator": 0,
            "_transport_denominator": 0,
        }

    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
        SELECT id, date
        FROM portal_events
        WHERE team_id=?
        ORDER BY date, start_time, id
        """,
        (team_id,),
    )
    event_rows = rows_to_dict(c.fetchall())
    event_dates = {
        row["id"]: parse_iso_date_or_none(row.get("date"))
        for row in event_rows
        if row.get("id") is not None
    }

    c.execute(
        """
        SELECT event_id, member_name, status
        FROM portal_attendance
        WHERE team_id=?
        """,
        (team_id,),
    )
    attendance_rows = rows_to_dict(c.fetchall())

    c.execute(
        """
        SELECT cem.member_name, cem.status, ce.amount, ce.collection_date
        FROM portal_collection_event_members cem
        INNER JOIN portal_collection_events ce
            ON ce.id = cem.collection_event_id
        WHERE ce.team_id=?
        """,
        (team_id,),
    )
    collection_rows = rows_to_dict(c.fetchall())

    c.execute(
        """
        SELECT event_id, member_name, transport_role
        FROM portal_transport_responses
        WHERE team_id=?
        """,
        (team_id,),
    )
    transport_rows = rows_to_dict(c.fetchall())
    conn.close()

    eligible_events_by_member = {
        member_name: 0
        for member_name in member_stats
    }
    for event_date in event_dates.values():
        if event_date is None:
            continue
        if period_start and event_date < period_start:
            continue
        if period_end and event_date > period_end:
            continue
        for member_name, stats in member_stats.items():
            member_start_date = stats["member_start_date"]
            if member_start_date and event_date < member_start_date:
                continue
            eligible_events_by_member[member_name] += 1

    for row in attendance_rows:
        member_name = (row.get("member_name") or "").strip()
        if member_name not in member_stats:
            continue
        event_id = row.get("event_id")
        event_date = event_dates.get(event_id)
        if event_date is None:
            continue
        if period_start and event_date < period_start:
            continue
        if period_end and event_date > period_end:
            continue
        member_start_date = member_stats[member_name]["member_start_date"]
        if member_start_date and event_date < member_start_date:
            continue
        status = normalize_status(row.get("status"))
        if status == "参加":
            member_stats[member_name]["attendance_count"] += 1
        elif status == "不参加":
            member_stats[member_name]["absence_count"] += 1

    for row in collection_rows:
        member_name = (row.get("member_name") or "").strip()
        if member_name not in member_stats:
            continue
        collection_date = parse_iso_date_or_none(row.get("collection_date"))
        if collection_date is None:
            continue
        if period_start and collection_date < period_start:
            continue
        if period_end and collection_date > period_end:
            continue
        member_start_date = member_stats[member_name]["member_start_date"]
        if member_start_date and collection_date < member_start_date:
            continue
        normalized_status = normalize_collection_status(row.get("status"))
        if normalized_status == COLLECTION_STATUS_COLLECTED:
            member_stats[member_name]["collection_count"] += 1
            member_stats[member_name]["collection_amount"] += int(row.get("amount") or 0)
        elif normalized_status == COLLECTION_STATUS_PENDING:
            member_stats[member_name]["pending_collection_count"] += 1
            member_stats[member_name]["pending_collection_amount"] += int(row.get("amount") or 0)

    for row in transport_rows:
        member_name = (row.get("member_name") or "").strip()
        if member_name not in member_stats:
            continue
        event_id = row.get("event_id")
        event_date = event_dates.get(event_id)
        if event_date is None:
            continue
        if period_start and event_date < period_start:
            continue
        if period_end and event_date > period_end:
            continue
        member_start_date = member_stats[member_name]["member_start_date"]
        if member_start_date and event_date < member_start_date:
            continue
        transport_role = normalize_transport_role(row.get("transport_role")) or TRANSPORT_ROLE_NONE
        if transport_role == TRANSPORT_ROLE_DRIVER:
            member_stats[member_name]["driver_count"] += 1
            member_stats[member_name]["_transport_denominator"] += 1
        elif transport_role == TRANSPORT_ROLE_PASSENGER:
            member_stats[member_name]["passenger_count"] += 1
            member_stats[member_name]["_transport_denominator"] += 1
        elif transport_role == TRANSPORT_ROLE_DIRECT:
            member_stats[member_name]["direct_count"] += 1
            member_stats[member_name]["_transport_denominator"] += 1

    analytics_rows = []
    for member_name in member_order:
        stats = member_stats[member_name]
        eligible_event_count = eligible_events_by_member.get(member_name, 0)
        stats["unanswered_count"] = max(
            0,
            eligible_event_count - stats["attendance_count"] - stats["absence_count"],
        )
        stats["attendance_rate"] = format_member_analytics_rate(stats["attendance_count"], eligible_event_count)
        stats["absence_rate"] = format_member_analytics_rate(stats["absence_count"], eligible_event_count)
        stats["unanswered_rate"] = format_member_analytics_rate(stats["unanswered_count"], eligible_event_count)
        stats["collection_amount_label"] = format_currency_yen(stats["collection_amount"])
        stats["pending_collection_amount_label"] = format_currency_yen(stats["pending_collection_amount"])
        transport_denominator = stats["_transport_denominator"]
        stats["driver_rate"] = format_member_analytics_rate(stats["driver_count"], transport_denominator)
        stats["passenger_rate"] = format_member_analytics_rate(stats["passenger_count"], transport_denominator)
        stats["direct_rate"] = format_member_analytics_rate(stats["direct_count"], transport_denominator)
        analytics_rows.append(stats)

    return {
        "rows": analytics_rows,
        "member_count": len(analytics_rows),
        "event_count": sum(1 for event_date in event_dates.values() if event_date and (not period_start or event_date >= period_start) and (not period_end or event_date <= period_end)),
    }


def build_admin_member_analytics_csv_response(team_id, active_tab, period_start=None, period_end=None):
    tab_key = normalize_admin_member_analytics_tab(active_tab)
    analytics = build_admin_member_analytics(
        team_id,
        period_start=period_start,
        period_end=period_end,
        include_inactive=True,
    )
    tab_definition = ADMIN_MEMBER_ANALYTICS_TABS[tab_key]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["表示タブ", tab_definition["label"]])
    writer.writerow(["開始期間", period_start.isoformat() if period_start else ""])
    writer.writerow(["終了期間", period_end.isoformat() if period_end else ""])
    writer.writerow([])

    header = ["メンバー名", "ステータス", *[label for _, label in tab_definition["columns"]]]
    writer.writerow(header)
    for row in analytics["rows"]:
        writer.writerow(
            [
                row.get("member_name") or "",
                row.get("status_label") or "",
                *[row.get(column_key, "") for column_key, _ in tab_definition["columns"]],
            ]
        )

    csv_text = "\ufeff" + output.getvalue()
    filename = f"member_analytics_{tab_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def build_portal_transport_overview(team_id, event_id, allowed_member_names=None):
    response_rows = portal_get_all_transport_responses_for_event(team_id, event_id)
    assignment_rows = portal_get_transport_assignments(team_id, event_id)
    attendance_rows = portal_get_attendance_for_event(team_id, event_id)
    attendance_map = {
        row.get("member_name"): normalize_status(row.get("status"))
        for row in attendance_rows
        if row.get("member_name")
    }
    allowed_name_set = set(_normalize_name_list(allowed_member_names or []))
    if allowed_name_set:
        response_rows = [
            row for row in response_rows
            if (row.get("member_name") or "").strip() in allowed_name_set
        ]

    driver_rows = []
    passenger_rows = []
    direct_rows = []
    none_rows = []
    driver_cards_by_name = {}
    passenger_name_set = set()
    for row in response_rows:
        member_name = (row.get("member_name") or "").strip()
        transport_role = normalize_transport_role(row.get("transport_role")) or TRANSPORT_ROLE_NONE
        enriched = {
            **row,
            "member_name": member_name,
            "attendance_status": attendance_map.get(member_name, ""),
            "transport_role": transport_role,
            "transport_role_label": TRANSPORT_ROLE_LABELS.get(transport_role, TRANSPORT_ROLE_LABELS[TRANSPORT_ROLE_NONE]),
            "seats_available": max(0, int(row.get("seats_available") or 0)),
            "note": row.get("note") or "",
        }
        if transport_role == TRANSPORT_ROLE_DRIVER:
            driver_rows.append(enriched)
            driver_cards_by_name[member_name] = {
                **enriched,
                "assigned_passengers": [],
                "assigned_count": 0,
                "remaining_seats": max(0, int(enriched["seats_available"])),
            }
        elif transport_role == TRANSPORT_ROLE_PASSENGER:
            passenger_rows.append(enriched)
            passenger_name_set.add(member_name)
        elif transport_role == TRANSPORT_ROLE_DIRECT:
            direct_rows.append(enriched)
        else:
            none_rows.append(enriched)

    assignment_map = {}
    for row in assignment_rows:
        passenger_name = (row.get("passenger_name") or "").strip()
        driver_name = (row.get("driver_name") or "").strip()
        if passenger_name not in passenger_name_set:
            continue
        driver_card = driver_cards_by_name.get(driver_name)
        if not driver_card:
            continue
        assignment_map[passenger_name] = driver_name
        driver_card["assigned_passengers"].append(passenger_name)

    for driver_card in driver_cards_by_name.values():
        driver_card["assigned_count"] = len(driver_card["assigned_passengers"])
        driver_card["remaining_seats"] = max(0, driver_card["seats_available"] - driver_card["assigned_count"])

    for row in passenger_rows:
        row["assigned_driver"] = assignment_map.get(row["member_name"], "")

    total_seats = sum(card["seats_available"] for card in driver_cards_by_name.values())
    assigned_count = len(assignment_map)
    passenger_count = len(passenger_rows)
    summary = {
        "driver_count": len(driver_rows),
        "passenger_count": passenger_count,
        "direct_count": len(direct_rows),
        "none_count": len(none_rows),
        "total_seats": total_seats,
        "assigned_count": assigned_count,
        "unassigned_count": max(0, passenger_count - assigned_count),
        "seat_surplus": total_seats - passenger_count,
    }
    return {
        "response_rows": response_rows,
        "driver_rows": driver_rows,
        "passenger_rows": passenger_rows,
        "direct_rows": direct_rows,
        "none_rows": none_rows,
        "driver_cards": list(driver_cards_by_name.values()),
        "summary": summary,
    }


def portal_delete_member_attendance_by_month(team_id, month, name):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        DELETE FROM portal_attendance
        WHERE team_id=?
          AND member_name=?
          AND event_id IN (
              SELECT id
              FROM portal_events
              WHERE team_id=? AND substr(date,1,7)=?
          )
        """,
        (team_id, name, team_id, month),
    )
    conn.commit()
    conn.close()


def portal_build_event_list_csv_response(team_id, month="all"):
    events = portal_get_events([team_id])
    if month and month != "all":
        events = [event for event in events if event.get("date", "").startswith(month)]

    target_event_ids = {event["id"] for event in events}
    attendance_rows = [
        row for row in portal_get_attendance(team_id) if row.get("event_id") in target_event_ids
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


def collection_status_to_symbol(status):
    normalized_status = normalize_collection_status(status)
    symbol_map = {
        COLLECTION_STATUS_COLLECTED: "○",
        COLLECTION_STATUS_PENDING: "×",
        COLLECTION_STATUS_EXEMPT: "ー",
    }
    return symbol_map.get(normalized_status, "-")


def portal_build_collection_list_csv_response(team_id, month="all", member_name=""):
    collection_events = portal_get_collection_events(team_id)
    if month and month != "all":
        collection_events = [
            event for event in collection_events if (event.get("collection_date") or "").startswith(month)
        ]

    active_members = portal_get_members_for_team(team_id, include_inactive=False)
    member_names = [member.get("name") for member in active_members if member.get("name")]
    target_member_names = [member_name] if member_name and member_name in member_names else member_names

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["日付", "集金名", "金額", "備考", "○", "×", "ー", *target_member_names])

    for collection_event in collection_events:
        member_rows = portal_get_collection_event_members(team_id, collection_event["id"])
        member_status_map = {
            (row.get("current_member_name") or row.get("member_name") or ""): normalize_collection_status(row.get("status"))
            for row in member_rows
        }
        summary = build_collection_event_summary(collection_event, member_rows)
        writer.writerow(
            [
                collection_event.get("collection_date") or "",
                collection_event.get("title") or "",
                int(collection_event.get("amount") or 0),
                collection_event.get("note") or "",
                summary["collected_count"],
                summary["pending_count"],
                summary["exempt_count"],
                *[collection_status_to_symbol(member_status_map.get(name, "")) for name in target_member_names],
            ]
        )

    csv_text = "\ufeff" + output.getvalue()
    filename_suffix = month if month and month != "all" else "all"
    filename = f"collection_list_export_{filename_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def build_member_legacy_index_context(team, active_month="", selected_member=""):
    owner_admin = get_team_owner_admin(team)
    can_use_paid_features = is_paid_plan_admin(owner_admin)
    events = portal_get_events([team["id"]])
    attendance_rows = portal_get_attendance(team["id"])
    attendance_rows.sort(key=lambda item: item["id"])
    active_members = portal_get_members_for_team(team["id"], include_inactive=False)
    active_member_names = [member.get("name") for member in active_members if member.get("name")]
    if selected_member and selected_member not in active_member_names:
        selected_member = ""

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
        members_by_month[month] = [selected_member] if selected_member else list(active_member_names)

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
        "member_options": active_member_names,
        "selected_member_filter": selected_member,
        "public_id": team["public_id"],
        "can_use_attendance_check": can_use_paid_features,
        "can_use_csv_export": can_use_paid_features,
        "plan_csv_message": get_plan_restriction_message(PLAN_FEATURE_CSV_EXPORT),
        "plan_attendance_check_message": get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK),
        "transport_role_labels": TRANSPORT_ROLE_LABELS,
    }


def portal_has_admins():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins LIMIT 1")
    exists = c.fetchone() is not None
    conn.close()
    return exists


def sync_postgres_id_sequence(cursor, table_name):
    if not USE_POSTGRES:
        return
    cursor.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table_name}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table_name}), 1),
            (SELECT COUNT(*) > 0 FROM {table_name})
        )
        """
    )


def migrate_portal_json_to_db():
    if not PORTAL_DATA_PATH.exists():
        return
    try:
        data = json.loads(PORTAL_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(1) AS cnt FROM admins")
    has_admin = (row_to_dict(c.fetchone()) or {}).get("cnt", 0) > 0
    c.execute("SELECT COUNT(1) AS cnt FROM teams")
    has_team = (row_to_dict(c.fetchone()) or {}).get("cnt", 0) > 0
    c.execute("SELECT COUNT(1) AS cnt FROM portal_events")
    has_event = (row_to_dict(c.fetchone()) or {}).get("cnt", 0) > 0
    if has_admin or has_team or has_event:
        conn.close()
        return

    for admin in data.get("admins", []):
        c.execute(
            """
            INSERT INTO admins (id, email, password_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email) DO NOTHING
            """,
            (
                admin.get("id"),
                admin.get("email"),
                admin.get("password_hash"),
                admin.get("created_at") or portal_now_text(),
                admin.get("expires_at")
                or build_admin_expiry_text(created_at=admin.get("created_at")),
            ),
        )

    for team in data.get("teams", []):
        c.execute(
            """
            INSERT INTO teams (id, admin_id, name, public_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(public_id) DO NOTHING
            """,
            (
                team.get("id"),
                team.get("admin_id"),
                team.get("name"),
                team.get("public_id") or generate_public_id(),
                team.get("created_at") or portal_now_text(),
            ),
        )

    for member in data.get("members", []):
        c.execute(
            """
            INSERT INTO portal_members (id, team_id, name, display_order, note, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id, name) DO NOTHING
            """,
            (
                member.get("id"),
                member.get("team_id"),
                member.get("name"),
                member.get("display_order") or member.get("id") or 0,
                member.get("note") or "",
                1 if member.get("is_active", True) else 0,
                member.get("created_at") or portal_now_text(),
                member.get("updated_at") or member.get("created_at") or portal_now_text(),
            ),
        )

    for event in data.get("events", []):
        c.execute(
            """
            INSERT INTO portal_events (id, team_id, date, start_time, end_time, opponent, place, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                event.get("id"),
                event.get("team_id"),
                event.get("date"),
                event.get("start_time"),
                event.get("end_time"),
                event.get("opponent"),
                event.get("place"),
                event.get("created_at") or portal_now_text(),
            ),
        )

    for attendance in data.get("attendance", []):
        raw_status = (attendance.get("status") or "").strip()
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
        c.execute(
            """
            INSERT INTO portal_attendance (id, team_id, event_id, member_name, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                attendance.get("id"),
                attendance.get("team_id"),
                attendance.get("event_id"),
                attendance.get("member_name"),
                status_map.get(raw_status, ""),
                attendance.get("updated_at") or portal_now_text(),
            ),
        )

    sync_postgres_id_sequence(c, "admins")
    sync_postgres_id_sequence(c, "teams")
    sync_postgres_id_sequence(c, "portal_members")
    sync_postgres_id_sequence(c, "portal_events")
    sync_postgres_id_sequence(c, "portal_attendance")

    conn.commit()
    conn.close()


def redirect_to_team_month(public_id, month=None):
    month_value = (month or "").strip()
    if month_value:
        return redirect(url_for("member_team_page", public_id=public_id, month=month_value))
    return redirect(url_for("member_team_page", public_id=public_id))


def get_db_connection():
    return build_shared_db_connection(
        use_postgres=USE_POSTGRES,
        database_url=DATABASE_URL,
        sqlite_db_path=SQLITE_DB_PATH,
        psycopg2_module=psycopg2,
        dict_cursor=DictCursor,
        psycopg_module=psycopg,
        dict_row=dict_row,
    )


def sqlite_table_exists(cursor, table_name):
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return bool(cursor.fetchone()[0])


def first_column_value(row, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        for value in row.values():
            return value
        return default
    try:
        return row[0]
    except (KeyError, IndexError, TypeError):
        pass
    for attr in ("values",):
        method = getattr(row, attr, None)
        if callable(method):
            values = list(method())
            if values:
                return values[0]
    return default


def sqlite_column_names(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def cleanup_legacy_paypay_schema_sqlite(conn, cursor):
    plan_request_columns = sqlite_column_names(cursor, "admin_plan_requests")
    has_paypay_payment_id = "paypay_payment_id" in plan_request_columns
    has_paypay_table = sqlite_table_exists(cursor, "admin_paypay_payments")
    if not has_paypay_payment_id and not has_paypay_table:
        return "not_present"

    linked_paypay_rows = 0
    if has_paypay_payment_id:
        cursor.execute("SELECT COUNT(*) FROM admin_plan_requests WHERE paypay_payment_id IS NOT NULL")
        linked_paypay_rows = int(cursor.fetchone()[0] or 0)

    legacy_pending_rows = 0
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM admin_plan_requests
        WHERE lower(coalesce(payment_method, ''))='paypay' AND status=?
        """,
        (ADMIN_PLAN_REQUEST_STATUS_PENDING,),
    )
    legacy_pending_rows = int(cursor.fetchone()[0] or 0)

    paypay_table_rows = 0
    if has_paypay_table:
        cursor.execute("SELECT COUNT(*) FROM admin_paypay_payments")
        paypay_table_rows = int(cursor.fetchone()[0] or 0)

    if linked_paypay_rows or legacy_pending_rows or paypay_table_rows:
        app.logger.warning(
            "Skipping legacy PayPay schema cleanup on SQLite because linked_rows=%s, pending_legacy_rows=%s, paypay_table_rows=%s",
            linked_paypay_rows,
            legacy_pending_rows,
            paypay_table_rows,
        )
        return "skipped_not_safe"

    for index_name in (
        "idx_admin_paypay_payments_admin_created",
        "idx_admin_paypay_payments_merchant_payment_id",
        "idx_admin_paypay_payments_status_created",
    ):
        cursor.execute(f"DROP INDEX IF EXISTS {index_name}")

    if has_paypay_table:
        cursor.execute("DROP TABLE IF EXISTS admin_paypay_payments")

    if has_paypay_payment_id:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("ALTER TABLE admin_plan_requests RENAME TO admin_plan_requests__legacy_paypay_cleanup")
        cursor.execute(
            """
            CREATE TABLE admin_plan_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                request_type TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                payment_amount INTEGER NOT NULL DEFAULT 0,
                payment_date TEXT NOT NULL,
                payment_reference TEXT,
                request_note TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                review_note TEXT,
                reviewed_by_admin_id INTEGER,
                reviewed_at TEXT,
                stripe_payment_id INTEGER,
                payment_verification_status TEXT NOT NULL DEFAULT 'pending',
                payment_verified_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(admin_id) REFERENCES admins(id),
                FOREIGN KEY(reviewed_by_admin_id) REFERENCES admins(id)
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO admin_plan_requests (
                id,
                admin_id,
                request_type,
                payment_method,
                payment_amount,
                payment_date,
                payment_reference,
                request_note,
                status,
                review_note,
                reviewed_by_admin_id,
                reviewed_at,
                stripe_payment_id,
                payment_verification_status,
                payment_verified_at,
                created_at,
                updated_at
            )
            SELECT
                id,
                admin_id,
                request_type,
                payment_method,
                payment_amount,
                payment_date,
                payment_reference,
                request_note,
                status,
                review_note,
                reviewed_by_admin_id,
                reviewed_at,
                stripe_payment_id,
                payment_verification_status,
                payment_verified_at,
                created_at,
                updated_at
            FROM admin_plan_requests__legacy_paypay_cleanup
            """
        )
        cursor.execute("DROP TABLE admin_plan_requests__legacy_paypay_cleanup")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA foreign_key_check")
        foreign_key_issues = cursor.fetchall()
        if foreign_key_issues:
            raise sqlite3.IntegrityError("Foreign key check failed after legacy PayPay cleanup.")

    return "cleaned"


def cleanup_legacy_paypay_schema_postgres(cursor):
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name='admin_plan_requests' AND column_name='paypay_payment_id'
        )
        """
    )
    has_paypay_payment_id = bool(first_column_value(cursor.fetchone(), False))
    cursor.execute("SELECT to_regclass('public.admin_paypay_payments')")
    has_paypay_table = bool(first_column_value(cursor.fetchone(), False))
    if not has_paypay_payment_id and not has_paypay_table:
        return "not_present"

    linked_paypay_rows = 0
    if has_paypay_payment_id:
        cursor.execute("SELECT COUNT(*) FROM admin_plan_requests WHERE paypay_payment_id IS NOT NULL")
        linked_paypay_rows = int(first_column_value(cursor.fetchone(), 0) or 0)

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM admin_plan_requests
        WHERE lower(coalesce(payment_method, ''))='paypay' AND status=%s
        """,
        (ADMIN_PLAN_REQUEST_STATUS_PENDING,),
    )
    legacy_pending_rows = int(first_column_value(cursor.fetchone(), 0) or 0)

    paypay_table_rows = 0
    if has_paypay_table:
        cursor.execute("SELECT COUNT(*) FROM admin_paypay_payments")
        paypay_table_rows = int(first_column_value(cursor.fetchone(), 0) or 0)

    if linked_paypay_rows or legacy_pending_rows or paypay_table_rows:
        app.logger.warning(
            "Skipping legacy PayPay schema cleanup on Postgres because linked_rows=%s, pending_legacy_rows=%s, paypay_table_rows=%s",
            linked_paypay_rows,
            legacy_pending_rows,
            paypay_table_rows,
        )
        return "skipped_not_safe"

    cursor.execute("DROP INDEX IF EXISTS idx_admin_paypay_payments_admin_created")
    cursor.execute("DROP INDEX IF EXISTS idx_admin_paypay_payments_merchant_payment_id")
    cursor.execute("DROP INDEX IF EXISTS idx_admin_paypay_payments_status_created")
    cursor.execute("DROP TABLE IF EXISTS admin_paypay_payments")
    cursor.execute("ALTER TABLE admin_plan_requests DROP COLUMN IF EXISTS paypay_payment_id")
    return "cleaned"


def init_db_sqlite():
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        c = conn.cursor()
    except sqlite3.Error:
        return

    # New admin/team foundation for role separation and fixed member URLs.
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        status TEXT NOT NULL DEFAULT 'free',
        plan_type TEXT NOT NULL DEFAULT 'paid',
        account_status TEXT NOT NULL DEFAULT 'active',
        billing_status TEXT NOT NULL DEFAULT 'unpaid',
        last_billed_at TEXT,
        total_billing_amount INTEGER NOT NULL DEFAULT 0,
        billing_count INTEGER NOT NULL DEFAULT 0,
        last_login_at TEXT,
        last_attendance_updated_at TEXT,
        admin_memo TEXT
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admin_billing_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        billing_status TEXT NOT NULL,
        billed_at TEXT,
        amount INTEGER NOT NULL DEFAULT 0,
        total_amount INTEGER NOT NULL DEFAULT 0,
        billing_count INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(admin_id) REFERENCES admins(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admin_plan_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        request_type TEXT NOT NULL,
        payment_method TEXT NOT NULL,
        payment_amount INTEGER NOT NULL DEFAULT 0,
        payment_date TEXT NOT NULL,
        payment_reference TEXT,
        request_note TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        review_note TEXT,
        reviewed_by_admin_id INTEGER,
        reviewed_at TEXT,
        stripe_payment_id INTEGER,
        payment_verification_status TEXT NOT NULL DEFAULT 'pending',
        payment_verified_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(admin_id) REFERENCES admins(id),
        FOREIGN KEY(reviewed_by_admin_id) REFERENCES admins(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admin_stripe_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        stripe_checkout_session_id TEXT NOT NULL UNIQUE,
        stripe_payment_intent_id TEXT,
        request_type TEXT NOT NULL,
        request_amount INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'JPY',
        checkout_url TEXT,
        status TEXT NOT NULL DEFAULT 'created',
        stripe_status TEXT,
        stripe_payment_status TEXT,
        payment_reference TEXT,
        stripe_paid_at TEXT,
        requested_at TEXT,
        returned_at TEXT,
        confirmed_at TEXT,
        last_checked_at TEXT,
        linked_plan_request_id INTEGER,
        applied_at TEXT,
        applied_billing_history_id INTEGER,
        last_error_code TEXT,
        last_error_message TEXT,
        raw_create_response TEXT,
        raw_payment_details TEXT,
        raw_last_webhook TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(admin_id) REFERENCES admins(id),
        FOREIGN KEY(linked_plan_request_id) REFERENCES admin_plan_requests(id),
        FOREIGN KEY(applied_billing_history_id) REFERENCES admin_billing_history(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admin_stripe_webhook_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        stripe_checkout_session_id TEXT,
        stripe_payment_intent_id TEXT,
        payload_json TEXT,
        processing_status TEXT NOT NULL DEFAULT 'received',
        error_message TEXT,
        processed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
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

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        display_order INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, name),
        FOREIGN KEY(team_id) REFERENCES teams(id)
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        date TEXT,
        start_time TEXT,
        end_time TEXT,
        opponent TEXT,
        place TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES teams(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_collection_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        collection_date TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        target_mode TEXT NOT NULL DEFAULT 'manual',
        attendance_event_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(attendance_event_id) REFERENCES portal_events(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_collection_event_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        collection_event_id INTEGER NOT NULL,
        member_id INTEGER,
        member_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        collected_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(collection_event_id, member_id),
        FOREIGN KEY(collection_event_id) REFERENCES portal_collection_events(id)
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        event_id INTEGER,
        member_name TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, event_id, member_name),
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(event_id) REFERENCES portal_events(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_actual_attendees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        event_id INTEGER NOT NULL,
        member_name TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'attendance',
        confirmed_at TEXT NOT NULL,
        UNIQUE(team_id, event_id, member_name),
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(event_id) REFERENCES portal_events(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_transport_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        event_id INTEGER NOT NULL,
        member_name TEXT NOT NULL,
        transport_role TEXT NOT NULL DEFAULT 'none',
        seats_available INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, event_id, member_name),
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(event_id) REFERENCES portal_events(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_transport_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        event_id INTEGER NOT NULL,
        driver_name TEXT NOT NULL,
        passenger_name TEXT NOT NULL,
        display_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, event_id, passenger_name),
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(event_id) REFERENCES portal_events(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_tool_shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        event_id INTEGER NOT NULL,
        tool_type TEXT NOT NULL,
        share_id TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(event_id) REFERENCES portal_events(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_tool_saved_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        event_id INTEGER NOT NULL,
        tool_type TEXT NOT NULL,
        title TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES teams(id),
        FOREIGN KEY(event_id) REFERENCES portal_events(id)
    )
    """
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_actual_attendees_event_team ON portal_actual_attendees(team_id, event_id)"
    )
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_tool_shares_share_id ON portal_tool_shares(share_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_tool_saved_results_event_team ON portal_tool_saved_results(team_id, event_id, tool_type)"
    )
    cleanup_result = cleanup_legacy_paypay_schema_sqlite(conn, c)
    if cleanup_result == "cleaned":
        app.logger.info("Removed legacy PayPay schema from SQLite.")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_plan_requests_admin_created ON admin_plan_requests(admin_id, created_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_plan_requests_status_created ON admin_plan_requests(status, created_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_billing_history_admin_created ON admin_billing_history(admin_id, created_at)"
    )
    c.execute("PRAGMA table_info(admins)")
    admin_columns = [row[1] for row in c.fetchall()]
    if "email" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN email TEXT")
    if "password_hash" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN password_hash TEXT")
    if "created_at" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN created_at TEXT")
    if "expires_at" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN expires_at TEXT")
    if "status" not in admin_columns:
        c.execute(f"ALTER TABLE admins ADD COLUMN status TEXT NOT NULL DEFAULT '{ADMIN_STATUS_FREE}'")
    if "plan_type" not in admin_columns:
        c.execute(f"ALTER TABLE admins ADD COLUMN plan_type TEXT NOT NULL DEFAULT '{ADMIN_PLAN_PAID}'")
    if "account_status" not in admin_columns:
        c.execute(
            f"ALTER TABLE admins ADD COLUMN account_status TEXT NOT NULL DEFAULT '{ADMIN_ACCOUNT_STATUS_ACTIVE}'"
        )
    if "billing_status" not in admin_columns:
        c.execute(
            f"ALTER TABLE admins ADD COLUMN billing_status TEXT NOT NULL DEFAULT '{ADMIN_BILLING_STATUS_UNPAID}'"
        )
    if "last_billed_at" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN last_billed_at TEXT")
    if "total_billing_amount" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN total_billing_amount INTEGER NOT NULL DEFAULT 0")
    if "billing_count" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN billing_count INTEGER NOT NULL DEFAULT 0")
    if "last_login_at" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN last_login_at TEXT")
    if "last_attendance_updated_at" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN last_attendance_updated_at TEXT")
    if "admin_memo" not in admin_columns:
        c.execute("ALTER TABLE admins ADD COLUMN admin_memo TEXT")
    c.execute("PRAGMA table_info(admin_plan_requests)")
    admin_plan_request_columns = [row[1] for row in c.fetchall()]
    if "admin_id" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN admin_id INTEGER")
    if "request_type" not in admin_plan_request_columns:
        c.execute(
            f"ALTER TABLE admin_plan_requests ADD COLUMN request_type TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS}'"
        )
    if "payment_method" not in admin_plan_request_columns:
        c.execute(
            f"ALTER TABLE admin_plan_requests ADD COLUMN payment_method TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE}'"
        )
    if "payment_amount" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN payment_amount INTEGER NOT NULL DEFAULT 0")
    if "payment_date" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN payment_date TEXT")
    if "payment_reference" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN payment_reference TEXT")
    if "request_note" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN request_note TEXT")
    if "status" not in admin_plan_request_columns:
        c.execute(
            f"ALTER TABLE admin_plan_requests ADD COLUMN status TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_STATUS_PENDING}'"
        )
    if "review_note" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN review_note TEXT")
    if "reviewed_by_admin_id" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN reviewed_by_admin_id INTEGER")
    if "reviewed_at" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN reviewed_at TEXT")
    if "created_at" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN created_at TEXT")
    if "updated_at" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN updated_at TEXT")
    if "stripe_payment_id" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN stripe_payment_id INTEGER")
    if "payment_verification_status" not in admin_plan_request_columns:
        c.execute(
            f"ALTER TABLE admin_plan_requests ADD COLUMN payment_verification_status TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_PENDING}'"
        )
    if "payment_verified_at" not in admin_plan_request_columns:
        c.execute("ALTER TABLE admin_plan_requests ADD COLUMN payment_verified_at TEXT")
    c.execute(
        """
        UPDATE admin_plan_requests
        SET request_type = COALESCE(NULLIF(request_type, ''), ?),
            payment_method = COALESCE(NULLIF(payment_method, ''), ?),
            payment_amount = COALESCE(payment_amount, 0),
            payment_date = COALESCE(NULLIF(payment_date, ''), created_at, ?),
            status = COALESCE(NULLIF(status, ''), ?),
            review_note = COALESCE(review_note, ''),
            payment_reference = COALESCE(payment_reference, ''),
            request_note = COALESCE(request_note, ''),
            payment_verification_status = COALESCE(NULLIF(payment_verification_status, ''), ?),
            created_at = COALESCE(NULLIF(created_at, ''), ?),
            updated_at = COALESCE(NULLIF(updated_at, ''), created_at, ?)
        """,
        (
            ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
            portal_now_text(),
            ADMIN_PLAN_REQUEST_STATUS_PENDING,
            ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_PENDING,
            portal_now_text(),
            portal_now_text(),
        ),
    )
    c.execute(
        """
        UPDATE admins
        SET status = COALESCE(NULLIF(status, ''), ?),
            plan_type = CASE
                WHEN COALESCE(NULLIF(plan_type, ''), '') != '' THEN plan_type
                WHEN status = ? THEN ?
                ELSE ?
            END,
            account_status = CASE
                WHEN COALESCE(NULLIF(account_status, ''), '') != '' THEN account_status
                WHEN status IN (?, ?) THEN status
                ELSE ?
            END,
            billing_status = COALESCE(NULLIF(billing_status, ''), ?),
            total_billing_amount = COALESCE(total_billing_amount, 0),
            billing_count = COALESCE(billing_count, 0)
        """,
        (
            ADMIN_STATUS_FREE,
            ADMIN_STATUS_FREE,
            ADMIN_PLAN_FREE,
            ADMIN_PLAN_PAID,
            ADMIN_STATUS_SUSPENDED,
            ADMIN_STATUS_EXPIRED,
            ADMIN_ACCOUNT_STATUS_ACTIVE,
            ADMIN_BILLING_STATUS_UNPAID,
        ),
    )

    c.execute("PRAGMA table_info(admin_stripe_payments)")
    admin_stripe_payment_columns = [row[1] for row in c.fetchall()]
    if "admin_id" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN admin_id INTEGER")
    if "stripe_checkout_session_id" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN stripe_checkout_session_id TEXT")
    if "stripe_payment_intent_id" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN stripe_payment_intent_id TEXT")
    if "request_type" not in admin_stripe_payment_columns:
        c.execute(
            f"ALTER TABLE admin_stripe_payments ADD COLUMN request_type TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS}'"
        )
    if "request_amount" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN request_amount INTEGER NOT NULL DEFAULT 0")
    if "currency" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN currency TEXT NOT NULL DEFAULT 'JPY'")
    if "checkout_url" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN checkout_url TEXT")
    if "status" not in admin_stripe_payment_columns:
        c.execute(
            f"ALTER TABLE admin_stripe_payments ADD COLUMN status TEXT NOT NULL DEFAULT '{ADMIN_STRIPE_STATUS_CREATED}'"
        )
    if "stripe_status" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN stripe_status TEXT")
    if "stripe_payment_status" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN stripe_payment_status TEXT")
    if "payment_reference" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN payment_reference TEXT")
    if "stripe_paid_at" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN stripe_paid_at TEXT")
    if "requested_at" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN requested_at TEXT")
    if "returned_at" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN returned_at TEXT")
    if "confirmed_at" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN confirmed_at TEXT")
    if "last_checked_at" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN last_checked_at TEXT")
    if "linked_plan_request_id" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN linked_plan_request_id INTEGER")
    if "applied_at" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN applied_at TEXT")
    if "applied_billing_history_id" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN applied_billing_history_id INTEGER")
    if "last_error_code" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN last_error_code TEXT")
    if "last_error_message" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN last_error_message TEXT")
    if "raw_create_response" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN raw_create_response TEXT")
    if "raw_payment_details" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN raw_payment_details TEXT")
    if "raw_last_webhook" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN raw_last_webhook TEXT")
    if "created_at" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN created_at TEXT")
    if "updated_at" not in admin_stripe_payment_columns:
        c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN updated_at TEXT")
    c.execute(
        """
        UPDATE admin_stripe_payments
        SET request_type = COALESCE(NULLIF(request_type, ''), ?),
            request_amount = COALESCE(request_amount, 0),
            currency = COALESCE(NULLIF(currency, ''), 'JPY'),
            status = COALESCE(NULLIF(status, ''), ?),
            payment_reference = COALESCE(payment_reference, stripe_checkout_session_id, ''),
            created_at = COALESCE(NULLIF(created_at, ''), requested_at, ?),
            updated_at = COALESCE(NULLIF(updated_at, ''), created_at, ?)
        """,
        (
            ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            ADMIN_STRIPE_STATUS_CREATED,
            portal_now_text(),
            portal_now_text(),
        ),
    )

    c.execute("PRAGMA table_info(teams)")
    team_columns = [row[1] for row in c.fetchall()]
    if "admin_id" not in team_columns:
        c.execute("ALTER TABLE teams ADD COLUMN admin_id INTEGER")
    if "public_id" not in team_columns:
        c.execute("ALTER TABLE teams ADD COLUMN public_id TEXT")
    if "created_at" not in team_columns:
        c.execute("ALTER TABLE teams ADD COLUMN created_at TEXT")

    c.execute("PRAGMA table_info(portal_members)")
    portal_member_columns = [row[1] for row in c.fetchall()]
    if "display_order" not in portal_member_columns:
        c.execute("ALTER TABLE portal_members ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0")
    if "note" not in portal_member_columns:
        c.execute("ALTER TABLE portal_members ADD COLUMN note TEXT")
    if "is_active" not in portal_member_columns:
        c.execute("ALTER TABLE portal_members ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "updated_at" not in portal_member_columns:
        c.execute("ALTER TABLE portal_members ADD COLUMN updated_at TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_portal_members_team_id ON portal_members(team_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_members_team_display_order ON portal_members(team_id, display_order)"
    )
    c.execute(
        """
        UPDATE portal_members
        SET is_active = CASE WHEN is_active IS NULL THEN 1 ELSE is_active END,
            updated_at = CASE
                WHEN updated_at IS NULL OR updated_at = '' THEN COALESCE(created_at, ?)
                ELSE updated_at
            END
        """,
        (portal_now_text(),),
    )
    c.execute("SELECT id FROM teams ORDER BY id")
    team_rows = c.fetchall()
    for team_row in team_rows:
        team_id = team_row[0]
        c.execute(
            """
            SELECT id
            FROM portal_members
            WHERE team_id=?
            ORDER BY display_order ASC, id ASC
            """,
            (team_id,),
        )
        ordered_member_ids = [row[0] for row in c.fetchall()]
        for index, member_id in enumerate(ordered_member_ids, start=1):
            c.execute(
                "UPDATE portal_members SET display_order=? WHERE id=?",
                (index, member_id),
            )

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
    CREATE TABLE IF NOT EXISTS attendance_actual_attendees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'attendance',
        confirmed_at TEXT NOT NULL,
        UNIQUE(user_id, match_id, name),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(match_id) REFERENCES matches(id)
    )
    """
    )

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS attendance_tool_shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        tool_type TEXT NOT NULL,
        share_id TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(match_id) REFERENCES matches(id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS attendance_tool_saved_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        match_id INTEGER NOT NULL,
        tool_type TEXT NOT NULL,
        title TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(match_id) REFERENCES matches(id)
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_attendance_actual_attendees_match_user ON attendance_actual_attendees(user_id, match_id)"
    )
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_tool_shares_share_id ON attendance_tool_shares(share_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_attendance_tool_saved_results_match_user ON attendance_tool_saved_results(user_id, match_id, tool_type)"
    )

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

    # Ensure all admins have an expiry value.
    c.execute("SELECT id, created_at, expires_at FROM admins")
    existing_admins = c.fetchall()
    for admin_id, created_at, expires_at in existing_admins:
        if not expires_at:
            c.execute(
                "UPDATE admins SET expires_at=? WHERE id=?",
                (build_admin_expiry_text(created_at=created_at), admin_id),
            )

    try:
        conn.commit()
    except sqlite3.Error:
        pass
    conn.close()


def init_db_postgres():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admins (
        id SERIAL PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        status TEXT NOT NULL DEFAULT 'free',
        plan_type TEXT NOT NULL DEFAULT 'paid',
        account_status TEXT NOT NULL DEFAULT 'active',
        billing_status TEXT NOT NULL DEFAULT 'unpaid',
        last_billed_at TEXT,
        total_billing_amount INTEGER NOT NULL DEFAULT 0,
        billing_count INTEGER NOT NULL DEFAULT 0,
        last_login_at TEXT,
        last_attendance_updated_at TEXT,
        admin_memo TEXT
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admin_billing_history (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL REFERENCES admins(id),
        billing_status TEXT NOT NULL,
        billed_at TEXT,
        amount INTEGER NOT NULL DEFAULT 0,
        total_amount INTEGER NOT NULL DEFAULT 0,
        billing_count INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        created_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admin_plan_requests (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL REFERENCES admins(id),
        request_type TEXT NOT NULL,
        payment_method TEXT NOT NULL,
        payment_amount INTEGER NOT NULL DEFAULT 0,
        payment_date TEXT NOT NULL,
        payment_reference TEXT,
        request_note TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        review_note TEXT,
        reviewed_by_admin_id INTEGER REFERENCES admins(id),
        reviewed_at TEXT,
        stripe_payment_id INTEGER,
        payment_verification_status TEXT NOT NULL DEFAULT 'pending',
        payment_verified_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admin_stripe_payments (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER NOT NULL REFERENCES admins(id),
        stripe_checkout_session_id TEXT NOT NULL UNIQUE,
        stripe_payment_intent_id TEXT,
        request_type TEXT NOT NULL,
        request_amount INTEGER NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'JPY',
        checkout_url TEXT,
        status TEXT NOT NULL DEFAULT 'created',
        stripe_status TEXT,
        stripe_payment_status TEXT,
        payment_reference TEXT,
        stripe_paid_at TEXT,
        requested_at TEXT,
        returned_at TEXT,
        confirmed_at TEXT,
        last_checked_at TEXT,
        linked_plan_request_id INTEGER REFERENCES admin_plan_requests(id),
        applied_at TEXT,
        applied_billing_history_id INTEGER REFERENCES admin_billing_history(id),
        last_error_code TEXT,
        last_error_message TEXT,
        raw_create_response TEXT,
        raw_payment_details TEXT,
        raw_last_webhook TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS admin_stripe_webhook_events (
        id SERIAL PRIMARY KEY,
        event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        stripe_checkout_session_id TEXT,
        stripe_payment_intent_id TEXT,
        payload_json TEXT,
        processing_status TEXT NOT NULL DEFAULT 'received',
        error_message TEXT,
        processed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        email TEXT
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS teams (
        id SERIAL PRIMARY KEY,
        admin_id INTEGER REFERENCES admins(id),
        name TEXT NOT NULL,
        public_id TEXT,
        created_at TEXT
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS team_members (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(team_id, name)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS team_attendance (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        member_name TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, member_name)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_members (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        name TEXT NOT NULL,
        display_order INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, name)
    )
    """
    )
    c.execute("ALTER TABLE portal_members ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 0")
    c.execute("ALTER TABLE portal_members ADD COLUMN IF NOT EXISTS note TEXT")
    c.execute("ALTER TABLE portal_members ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1")
    c.execute("ALTER TABLE portal_members ADD COLUMN IF NOT EXISTS updated_at TEXT")
    c.execute("CREATE INDEX IF NOT EXISTS idx_portal_members_team_id ON portal_members(team_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_members_team_display_order ON portal_members(team_id, display_order)"
    )
    c.execute(
        """
        UPDATE portal_members
        SET is_active = COALESCE(is_active, 1),
            updated_at = CASE
                WHEN updated_at IS NULL OR updated_at = '' THEN COALESCE(created_at, %s)
                ELSE updated_at
            END
        """,
        (portal_now_text(),),
    )
    c.execute("SELECT id FROM teams ORDER BY id")
    team_rows = c.fetchall()
    for team_row in team_rows:
        team_id = team_row["id"] if isinstance(team_row, dict) or hasattr(team_row, "keys") else team_row[0]
        c.execute(
            """
            SELECT id
            FROM portal_members
            WHERE team_id=%s
            ORDER BY display_order ASC, id ASC
            """,
            (team_id,),
        )
        ordered_member_ids = [row["id"] if isinstance(row, dict) or hasattr(row, "keys") else row[0] for row in c.fetchall()]
        for index, member_id in enumerate(ordered_member_ids, start=1):
            c.execute(
                "UPDATE portal_members SET display_order=%s WHERE id=%s",
                (index, member_id),
            )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_events (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        date TEXT,
        start_time TEXT,
        end_time TEXT,
        opponent TEXT,
        place TEXT,
        created_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_collection_events (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        title TEXT NOT NULL,
        collection_date TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        target_mode TEXT NOT NULL DEFAULT 'manual',
        attendance_event_id INTEGER REFERENCES portal_events(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_collection_event_members (
        id SERIAL PRIMARY KEY,
        collection_event_id INTEGER NOT NULL REFERENCES portal_collection_events(id),
        member_id INTEGER,
        member_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        collected_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(collection_event_id, member_id)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_attendance (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        event_id INTEGER REFERENCES portal_events(id),
        member_name TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, event_id, member_name)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_actual_attendees (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        event_id INTEGER NOT NULL REFERENCES portal_events(id),
        member_name TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'attendance',
        confirmed_at TEXT NOT NULL,
        UNIQUE(team_id, event_id, member_name)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_transport_responses (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        event_id INTEGER NOT NULL REFERENCES portal_events(id),
        member_name TEXT NOT NULL,
        transport_role TEXT NOT NULL DEFAULT 'none',
        seats_available INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, event_id, member_name)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_transport_assignments (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        event_id INTEGER NOT NULL REFERENCES portal_events(id),
        driver_name TEXT NOT NULL,
        passenger_name TEXT NOT NULL,
        display_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(team_id, event_id, passenger_name)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_tool_shares (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        event_id INTEGER NOT NULL REFERENCES portal_events(id),
        tool_type TEXT NOT NULL,
        share_id TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS portal_tool_saved_results (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        event_id INTEGER NOT NULL REFERENCES portal_events(id),
        tool_type TEXT NOT NULL,
        title TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_actual_attendees_event_team ON portal_actual_attendees(team_id, event_id)"
    )
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_tool_shares_share_id ON portal_tool_shares(share_id)")
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS matches (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL DEFAULT 0 REFERENCES users(id),
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
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL DEFAULT 0 REFERENCES users(id),
        match_id INTEGER,
        name TEXT,
        status TEXT,
        UNIQUE(match_id, name)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS attendance_actual_attendees (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        match_id INTEGER NOT NULL REFERENCES matches(id),
        name TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'attendance',
        confirmed_at TEXT NOT NULL,
        UNIQUE(user_id, match_id, name)
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS attendance_tool_shares (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        match_id INTEGER NOT NULL REFERENCES matches(id),
        tool_type TEXT NOT NULL,
        share_id TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS attendance_tool_saved_results (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        match_id INTEGER NOT NULL REFERENCES matches(id),
        tool_type TEXT NOT NULL,
        title TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
    )
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS payments (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        plan_name TEXT NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """
    )

    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS email TEXT")
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS password_hash TEXT")
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS created_at TEXT")
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS expires_at TEXT")
    c.execute(f"ALTER TABLE admins ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT '{ADMIN_STATUS_FREE}'")
    c.execute(f"ALTER TABLE admins ADD COLUMN IF NOT EXISTS plan_type TEXT NOT NULL DEFAULT '{ADMIN_PLAN_PAID}'")
    c.execute(
        f"ALTER TABLE admins ADD COLUMN IF NOT EXISTS account_status TEXT NOT NULL DEFAULT '{ADMIN_ACCOUNT_STATUS_ACTIVE}'"
    )
    c.execute(
        f"ALTER TABLE admins ADD COLUMN IF NOT EXISTS billing_status TEXT NOT NULL DEFAULT '{ADMIN_BILLING_STATUS_UNPAID}'"
    )
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS last_billed_at TEXT")
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS total_billing_amount INTEGER NOT NULL DEFAULT 0")
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS billing_count INTEGER NOT NULL DEFAULT 0")
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS last_login_at TEXT")
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS last_attendance_updated_at TEXT")
    c.execute("ALTER TABLE admins ADD COLUMN IF NOT EXISTS admin_memo TEXT")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS admin_id INTEGER")
    c.execute(
        f"ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS request_type TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS}'"
    )
    c.execute(
        f"ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS payment_method TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE}'"
    )
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS payment_amount INTEGER NOT NULL DEFAULT 0")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS payment_date TEXT")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS payment_reference TEXT")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS request_note TEXT")
    c.execute(
        f"ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_STATUS_PENDING}'"
    )
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS review_note TEXT")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS reviewed_by_admin_id INTEGER")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS reviewed_at TEXT")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS created_at TEXT")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS updated_at TEXT")
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS stripe_payment_id INTEGER")
    c.execute(
        f"ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS payment_verification_status TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_PENDING}'"
    )
    c.execute("ALTER TABLE admin_plan_requests ADD COLUMN IF NOT EXISTS payment_verified_at TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS admin_id INTEGER")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS stripe_checkout_session_id TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT")
    c.execute(
        f"ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS request_type TEXT NOT NULL DEFAULT '{ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS}'"
    )
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS request_amount INTEGER NOT NULL DEFAULT 0")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS currency TEXT NOT NULL DEFAULT 'JPY'")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS checkout_url TEXT")
    c.execute(
        f"ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT '{ADMIN_STRIPE_STATUS_CREATED}'"
    )
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS stripe_status TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS stripe_payment_status TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS payment_reference TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS stripe_paid_at TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS requested_at TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS returned_at TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS confirmed_at TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS last_checked_at TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS linked_plan_request_id INTEGER")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS applied_at TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS applied_billing_history_id INTEGER")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS last_error_code TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS last_error_message TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS raw_create_response TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS raw_payment_details TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS raw_last_webhook TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS created_at TEXT")
    c.execute("ALTER TABLE admin_stripe_payments ADD COLUMN IF NOT EXISTS updated_at TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS event_id TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS event_type TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS stripe_checkout_session_id TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS payload_json TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS processing_status TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS error_message TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS processed_at TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS created_at TEXT")
    c.execute("ALTER TABLE admin_stripe_webhook_events ADD COLUMN IF NOT EXISTS updated_at TEXT")
    c.execute(
        """
        UPDATE admin_plan_requests
        SET request_type = COALESCE(NULLIF(request_type, ''), %s),
            payment_method = COALESCE(NULLIF(payment_method, ''), %s),
            payment_amount = COALESCE(payment_amount, 0),
            payment_date = COALESCE(NULLIF(payment_date, ''), created_at, %s),
            status = COALESCE(NULLIF(status, ''), %s),
            review_note = COALESCE(review_note, ''),
            payment_reference = COALESCE(payment_reference, ''),
            request_note = COALESCE(request_note, ''),
            payment_verification_status = COALESCE(NULLIF(payment_verification_status, ''), %s),
            created_at = COALESCE(NULLIF(created_at, ''), %s),
            updated_at = COALESCE(NULLIF(updated_at, ''), created_at, %s)
        """,
        (
            ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
            portal_now_text(),
            ADMIN_PLAN_REQUEST_STATUS_PENDING,
            ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_PENDING,
            portal_now_text(),
            portal_now_text(),
        ),
    )
    c.execute(
        """
        UPDATE admin_stripe_payments
        SET request_type = COALESCE(NULLIF(request_type, ''), %s),
            request_amount = COALESCE(request_amount, 0),
            currency = COALESCE(NULLIF(currency, ''), 'JPY'),
            status = COALESCE(NULLIF(status, ''), %s),
            payment_reference = COALESCE(NULLIF(payment_reference, ''), stripe_checkout_session_id),
            created_at = COALESCE(NULLIF(created_at, ''), %s),
            updated_at = COALESCE(NULLIF(updated_at, ''), created_at)
        """,
        (
            ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            ADMIN_STRIPE_STATUS_CREATED,
            portal_now_text(),
        ),
    )
    c.execute(
        """
        UPDATE admins
        SET status = COALESCE(NULLIF(status, ''), %s),
            plan_type = CASE
                WHEN COALESCE(NULLIF(plan_type, ''), '') != '' THEN plan_type
                WHEN status = %s THEN %s
                ELSE %s
            END,
            account_status = CASE
                WHEN COALESCE(NULLIF(account_status, ''), '') != '' THEN account_status
                WHEN status IN (%s, %s) THEN status
                ELSE %s
            END,
            billing_status = COALESCE(NULLIF(billing_status, ''), %s),
            total_billing_amount = COALESCE(total_billing_amount, 0),
            billing_count = COALESCE(billing_count, 0)
        """,
        (
            ADMIN_STATUS_FREE,
            ADMIN_STATUS_FREE,
            ADMIN_PLAN_FREE,
            ADMIN_PLAN_PAID,
            ADMIN_STATUS_SUSPENDED,
            ADMIN_STATUS_EXPIRED,
            ADMIN_ACCOUNT_STATUS_ACTIVE,
            ADMIN_BILLING_STATUS_UNPAID,
        ),
    )
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
    c.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS admin_id INTEGER")
    c.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS public_id TEXT")
    c.execute("ALTER TABLE teams ADD COLUMN IF NOT EXISTS created_at TEXT")
    c.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 0")
    c.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 0")
    c.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 0")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_billing_history_admin_created ON admin_billing_history(admin_id, created_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_plan_requests_admin_created ON admin_plan_requests(admin_id, created_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_plan_requests_status_created ON admin_plan_requests(status, created_at)"
    )
    c.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_stripe_payments_checkout_session_id ON admin_stripe_payments(stripe_checkout_session_id)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_stripe_payments_admin_created ON admin_stripe_payments(admin_id, created_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_stripe_payments_status_created ON admin_stripe_payments(status, created_at)"
    )
    c.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_stripe_webhook_events_event_id ON admin_stripe_webhook_events(event_id)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_stripe_webhook_events_processed ON admin_stripe_webhook_events(processing_status, created_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_attendance_actual_attendees_match_user ON attendance_actual_attendees(user_id, match_id)"
    )
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_tool_shares_share_id ON attendance_tool_shares(share_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_attendance_tool_saved_results_match_user ON attendance_tool_saved_results(user_id, match_id, tool_type)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_tool_saved_results_event_team ON portal_tool_saved_results(team_id, event_id, tool_type)"
    )
    cleanup_result = cleanup_legacy_paypay_schema_postgres(c)
    if cleanup_result == "cleaned":
        app.logger.info("Removed legacy PayPay schema from Postgres.")

    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_public_id_unique ON teams(public_id)")
    c.execute(
        """
        UPDATE attendance a
        SET user_id = m.user_id
        FROM matches m
        WHERE a.match_id = m.id
          AND a.user_id = 0
        """
    )

    c.execute("SELECT id, public_id, created_at FROM teams")
    existing_teams = c.fetchall()
    for row in existing_teams:
        team_id = row["id"]
        public_id = row["public_id"]
        created_at = row["created_at"]
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

    c.execute("SELECT id, created_at, expires_at FROM admins")
    existing_admins = c.fetchall()
    for row in existing_admins:
        admin_id = row["id"]
        created_at = row["created_at"]
        expires_at = row["expires_at"]
        if not expires_at:
            c.execute(
                "UPDATE admins SET expires_at=? WHERE id=?",
                (build_admin_expiry_text(created_at=created_at), admin_id),
            )

    conn.commit()
    conn.close()


def init_db():
    if USE_POSTGRES:
        init_db_postgres()
    else:
        init_db_sqlite()


def bootstrap_admin_from_env():
    email = os.environ.get("ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "")
    reset_password = os.environ.get("ADMIN_BOOTSTRAP_RESET_PASSWORD", "").strip() == "1"

    if not email and not password:
        return
    if not email or not password:
        app.logger.warning("Admin bootstrap skipped: both ADMIN_BOOTSTRAP_EMAIL and ADMIN_BOOTSTRAP_PASSWORD are required.")
        return
    if len(password) < 8:
        app.logger.warning("Admin bootstrap skipped: ADMIN_BOOTSTRAP_PASSWORD must be at least 8 characters.")
        return

    existing_admin = portal_get_admin_by_email(email)
    if existing_admin:
        if reset_password:
            existing_admin["password_hash"] = generate_password_hash(password)
            portal_save_admin(existing_admin)
            app.logger.info("Admin bootstrap updated password for existing admin: %s", email)
        else:
            app.logger.info("Admin bootstrap found existing admin: %s", email)
        return

    created = portal_create_admin(email, password)
    if created:
        app.logger.info("Admin bootstrap created admin: %s", email)
    else:
        app.logger.warning("Admin bootstrap could not create admin: %s", email)


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


def admin_api_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return {"error": "forbidden"}, 403
        return func(*args, **kwargs)

    return wrapper


def is_site_admin_email(email):
    return (email or "").strip().lower() in SITE_ADMIN_EMAILS


def site_admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("admin_login_entry", next=request.path))

        admin_email = session.get("admin_email", "")
        if not is_site_admin_email(admin_email):
            return redirect(
                url_for(
                    "admin_dashboard",
                    error_message="サイト運営者ページにはアクセスできません。",
                )
            )
        return func(*args, **kwargs)

    return wrapper


def get_owned_team_or_error(team_id, admin_id):
    target_team = portal_get_team(team_id)
    if not target_team:
        return None, "not_found"
    if target_team.get("admin_id") != admin_id:
        return None, "forbidden"
    return target_team, None


def parse_boolean_input(value):
    normalized = (str(value) if value is not None else "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def format_start_date(created_at):
    raw = (created_at or "").strip()
    if not raw:
        return "-"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw[:10]


def format_usage_days(created_at):
    parsed = parse_portal_datetime(created_at)
    if not parsed:
        return "-"
    usage_days = max(0, (datetime.now().date() - parsed.date()).days)
    return f"{usage_days}日"


def sync_admin_plan_by_expiry(admin_row):
    if not admin_row:
        return admin_row

    plan_type = normalize_admin_plan_type(admin_row.get("plan_type")) or (
        ADMIN_PLAN_FREE if normalize_admin_status(admin_row.get("status")) == ADMIN_STATUS_FREE else ADMIN_PLAN_PAID
    )
    account_status = normalize_admin_account_status(admin_row.get("account_status")) or ADMIN_ACCOUNT_STATUS_ACTIVE
    effective_expiry = resolve_admin_expiry_datetime(admin_row.get("created_at"), admin_row.get("expires_at"))
    today = datetime.now().date()

    updates = {}
    should_record_history = False
    history_note = ""

    if account_status == ADMIN_ACCOUNT_STATUS_EXPIRED:
        account_status = ADMIN_ACCOUNT_STATUS_ACTIVE
        updates["account_status"] = account_status

    if plan_type == ADMIN_PLAN_PAID and effective_expiry and effective_expiry.date() < today:
        plan_type = ADMIN_PLAN_FREE
        updates["plan_type"] = plan_type
        if account_status == ADMIN_ACCOUNT_STATUS_EXPIRED:
            account_status = ADMIN_ACCOUNT_STATUS_ACTIVE
            updates["account_status"] = account_status
        should_record_history = True
        history_note = "利用期限切れにより無料プランへ自動切替"

    desired_status = ADMIN_STATUS_SUSPENDED if account_status == ADMIN_ACCOUNT_STATUS_SUSPENDED else (
        ADMIN_STATUS_PAID if plan_type == ADMIN_PLAN_PAID else ADMIN_STATUS_FREE
    )
    if normalize_admin_status(admin_row.get("status")) != desired_status:
        updates["status"] = desired_status

    if updates:
        portal_update_admin_profile_fields(admin_row["id"], **updates)
        admin_row.update(updates)
        if should_record_history:
            portal_record_admin_billing_history(
                admin_id=admin_row["id"],
                billing_status=normalize_admin_billing_status(admin_row.get("billing_status")) or ADMIN_BILLING_STATUS_UNPAID,
                billed_at=portal_now_text(),
                amount=0,
                total_amount=int(admin_row.get("total_billing_amount") or 0),
                billing_count=int(admin_row.get("billing_count") or 0),
                note=history_note,
            )

    admin_row["plan_type"] = plan_type
    admin_row["account_status"] = account_status
    admin_row["status"] = desired_status
    return admin_row


def resolve_admin_status(admin_row):
    stored_plan_type = (admin_row.get("plan_type") or "").strip().lower()
    stored_account_status = (admin_row.get("account_status") or "").strip().lower()
    legacy_status = (admin_row.get("status") or "").strip().lower()
    if stored_account_status == ADMIN_ACCOUNT_STATUS_SUSPENDED or legacy_status == ADMIN_STATUS_SUSPENDED:
        return ADMIN_STATUS_SUSPENDED
    if stored_plan_type == ADMIN_PLAN_PAID or legacy_status == ADMIN_STATUS_PAID:
        return ADMIN_STATUS_PAID
    return ADMIN_STATUS_FREE


def format_admin_status(admin_row):
    return ADMIN_STATUS_LABELS.get(resolve_admin_status(admin_row), "無料")


def format_admin_billing_status(value):
    normalized = (value or "").strip().lower()
    return ADMIN_BILLING_STATUS_LABELS.get(normalized, "未課金")


def normalize_admin_status(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_STATUS_LABELS else ""


def normalize_admin_plan_type(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_PLAN_LABELS else ""


def normalize_admin_account_status(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_ACCOUNT_STATUS_LABELS else ""


def get_admin_plan_type(admin_row):
    if not admin_row:
        return ADMIN_PLAN_PAID
    normalized = normalize_admin_plan_type(admin_row.get("plan_type"))
    if normalized:
        return normalized
    legacy_status = normalize_admin_status(admin_row.get("status"))
    if legacy_status == ADMIN_STATUS_FREE:
        return ADMIN_PLAN_FREE
    return ADMIN_PLAN_PAID


def is_paid_plan_admin(admin_row):
    return get_admin_plan_type(admin_row) == ADMIN_PLAN_PAID


def get_plan_restriction_message(feature_key):
    return PLAN_RESTRICTION_MESSAGES.get(feature_key, "この機能は有料プランで利用できます。")


def can_admin_create_team(admin_row, existing_team_count=0):
    if is_paid_plan_admin(admin_row):
        return True
    return existing_team_count < ADMIN_FREE_TEAM_LIMIT


def get_team_owner_admin(team):
    if not team:
        return None
    admin_id = team.get("admin_id")
    if not admin_id:
        return None
    return portal_get_admin(admin_id)


def can_team_use_paid_feature(team):
    return is_paid_plan_admin(get_team_owner_admin(team))


def build_member_page_notice_redirect(public_id, message, month="", name=""):
    params = {"public_id": public_id}
    if month:
        params["month"] = month
    if name:
        params["name"] = name
    if message:
        params["error_message"] = message
    return redirect(url_for("member_team_page", **params))


def normalize_admin_billing_status(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_BILLING_STATUS_LABELS else ""


def format_portal_date(value):
    parsed = parse_portal_datetime(value)
    if not parsed:
        return "-"
    return parsed.strftime("%Y-%m-%d")


def format_currency_yen(value):
    try:
        amount = int(value or 0)
    except (TypeError, ValueError):
        amount = 0
    return f"¥{amount:,}"


def format_billing_history_amount(value):
    try:
        amount = int(value or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount > 0:
        return f"+{format_currency_yen(amount)}"
    if amount < 0:
        return f"-{format_currency_yen(abs(amount))}"
    return format_currency_yen(0)


def normalize_admin_plan_request_status(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_PLAN_REQUEST_STATUS_LABELS else ""


def normalize_admin_plan_request_type(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_PLAN_REQUEST_TYPE_LABELS else ""


def normalize_admin_plan_request_payment_method(value):
    normalized = (value or "").strip().lower()
    return normalized if normalized in ADMIN_PLAN_REQUEST_PAYMENT_METHOD_LABELS else ""


def enrich_admin_stripe_payment_row(row):
    normalized_status = normalize_admin_stripe_status(row.get("status")) or ADMIN_STRIPE_STATUS_UNKNOWN
    normalized_request_type = normalize_admin_plan_request_type(row.get("request_type")) or ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS
    extension_days = ADMIN_PLAN_PAYMENT_AMOUNT_EXTENSION_DAYS.get(
        int(row.get("request_amount") or 0),
        ADMIN_PLAN_REQUEST_EXTENSION_DAYS.get(normalized_request_type, 30),
    )
    row["status"] = normalized_status
    row["status_text"] = ADMIN_STRIPE_STATUS_LABELS.get(normalized_status, "確認中")
    row["request_type"] = normalized_request_type
    row["request_type_text"] = ADMIN_PLAN_REQUEST_TYPE_LABELS.get(normalized_request_type, "有料プラン申請")
    row["request_amount_text"] = format_currency_yen(row.get("request_amount"))
    row["request_extension_text"] = f"+{extension_days}日"
    row["stripe_paid_at_text"] = format_portal_date(row.get("stripe_paid_at"))
    row["confirmed_at_text"] = format_portal_date(row.get("confirmed_at"))
    row["created_date"] = format_portal_date(row.get("created_at"))
    row["applied_at_text"] = format_portal_date(row.get("applied_at"))
    row["is_completed"] = normalized_status == ADMIN_STRIPE_STATUS_COMPLETED
    row["is_applied"] = bool(row.get("applied_at"))
    row["is_linked"] = bool(row.get("linked_plan_request_id"))
    if row["is_applied"]:
        row["application_status_text"] = "適用済み"
    elif row["is_completed"]:
        row["application_status_text"] = "支払い完了・適用待ち"
    elif normalized_status in {ADMIN_STRIPE_STATUS_OPEN, ADMIN_STRIPE_STATUS_RETURNED, ADMIN_STRIPE_STATUS_UNKNOWN}:
        row["application_status_text"] = "支払い確認中"
    elif normalized_status == ADMIN_STRIPE_STATUS_CANCELED:
        row["application_status_text"] = "キャンセル"
    elif normalized_status == ADMIN_STRIPE_STATUS_FAILED:
        row["application_status_text"] = "支払い失敗"
    elif normalized_status == ADMIN_STRIPE_STATUS_EXPIRED:
        row["application_status_text"] = "有効期限切れ"
    else:
        row["application_status_text"] = "未適用"
    row["payment_reference_text"] = stripe_extract_reference(row)
    return row


def enrich_admin_stripe_payment_rows(rows):
    return [enrich_admin_stripe_payment_row(row) for row in rows]


def build_admin_stripe_payment_expiry_change_map(admin, billing_history_rows):
    expiry_map = {}
    if is_unlimited_expiry(admin.get("expires_at")):
        for row in billing_history_rows:
            expiry_map[row["id"]] = {"before_text": "無期限", "after_text": "無期限"}
        return expiry_map

    current_expiry = resolve_admin_expiry_datetime(admin.get("created_at"), None)
    for row in billing_history_rows:
        amount = int(row.get("amount") or 0)
        if amount <= 0:
            continue
        billed_at_text = (row.get("billed_at") or row.get("created_at") or "").strip()
        billed_at_dt = parse_portal_datetime(billed_at_text) or datetime.now()
        before_dt = current_expiry
        extend_days = ADMIN_PLAN_PAYMENT_AMOUNT_EXTENSION_DAYS.get(amount, 0)
        base_dt = before_dt if (before_dt and before_dt > billed_at_dt) else billed_at_dt
        after_dt = base_dt + timedelta(days=extend_days)
        expiry_map[row["id"]] = {
            "before_text": format_expiry_date(before_dt.strftime("%Y-%m-%d %H:%M:%S") if before_dt else ""),
            "after_text": format_expiry_date(after_dt.strftime("%Y-%m-%d %H:%M:%S")),
        }
        current_expiry = after_dt
    return expiry_map


def attach_admin_stripe_payment_expiry_change(rows, admin):
    expiry_map = build_admin_stripe_payment_expiry_change_map(
        admin,
        portal_get_admin_billing_history_timeline(admin["id"]),
    )
    for row in rows:
        billing_history_id = row.get("applied_billing_history_id")
        expiry_change = expiry_map.get(billing_history_id)
        if expiry_change:
            row["expiry_before_text"] = expiry_change["before_text"]
            row["expiry_after_text"] = expiry_change["after_text"]
        elif row.get("is_applied"):
            row["expiry_before_text"] = "-"
            row["expiry_after_text"] = "-"
        else:
            row["expiry_before_text"] = "未適用のため未確定"
            row["expiry_after_text"] = "未適用のため未確定"
    return rows


def enrich_admin_plan_request_row(row):
    normalized_status = normalize_admin_plan_request_status(row.get("status")) or ADMIN_PLAN_REQUEST_STATUS_PENDING
    normalized_request_type = (
        normalize_admin_plan_request_type(row.get("request_type")) or ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS
    )
    normalized_payment_method = normalize_admin_plan_request_payment_method(row.get("payment_method")) or (
        (row.get("payment_method") or "").strip().lower()
    )
    row["status"] = normalized_status
    row["status_text"] = ADMIN_PLAN_REQUEST_STATUS_LABELS.get(normalized_status, "申請中")
    row["request_type"] = normalized_request_type
    row["request_type_text"] = ADMIN_PLAN_REQUEST_TYPE_LABELS.get(normalized_request_type, "有料プラン申請")
    row["payment_method"] = normalized_payment_method
    row["payment_method_text"] = ADMIN_PLAN_REQUEST_PAYMENT_METHOD_LABELS.get(normalized_payment_method, "不明")
    verification_status = (
        normalize_admin_plan_request_payment_verification_status(row.get("payment_verification_status"))
        or ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_PENDING
    )
    row["payment_verification_status"] = verification_status
    row["payment_verification_status_text"] = ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_LABELS.get(verification_status, "確認待ち")
    row["payment_amount_text"] = format_currency_yen(row.get("payment_amount"))
    row["payment_date_text"] = format_portal_date(row.get("payment_date"))
    row["created_date"] = format_portal_date(row.get("created_at"))
    row["reviewed_date"] = format_portal_date(row.get("reviewed_at"))
    row["payment_verified_date"] = format_portal_date(row.get("payment_verified_at"))
    row["is_legacy_payment_method"] = normalized_payment_method != ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE
    stripe_status = normalize_admin_stripe_status(row.get("stripe_order_status")) or map_stripe_status(
        {
            "status": row.get("stripe_remote_status"),
            "payment_status": row.get("stripe_remote_payment_status"),
        }
    )
    row["stripe_status_text"] = ADMIN_STRIPE_STATUS_LABELS.get(stripe_status, "-")
    row["stripe_checkout_session_id"] = (row.get("stripe_checkout_session_id") or "").strip()
    return row


def enrich_admin_plan_request_rows(rows):
    return [enrich_admin_plan_request_row(row) for row in rows]


def build_admin_plan_request_page_context(admin):
    pending_plan_request_raw = portal_get_pending_admin_plan_request_by_admin(admin["id"])
    pending_plan_request = enrich_admin_plan_request_row(pending_plan_request_raw) if pending_plan_request_raw else None
    plan_request_history = enrich_admin_plan_request_rows(portal_get_admin_plan_request_history(admin["id"], limit=20))
    completed_stripe_payment_raw = portal_get_latest_unlinked_completed_admin_stripe_payment(admin["id"])
    completed_stripe_payment = (
        enrich_admin_stripe_payment_row(completed_stripe_payment_raw) if completed_stripe_payment_raw else None
    )
    recent_stripe_payments = attach_admin_stripe_payment_expiry_change(
        enrich_admin_stripe_payment_rows(portal_get_admin_stripe_payments_for_admin(admin["id"], limit=10)),
        admin,
    )
    effective_expiry = resolve_admin_expiry_datetime(admin.get("created_at"), admin.get("expires_at"))
    effective_expiry_text = (
        ADMIN_EXPIRY_UNLIMITED
        if is_unlimited_expiry(admin.get("expires_at"))
        else (effective_expiry.strftime("%Y-%m-%d %H:%M:%S") if effective_expiry else "")
    )
    return {
        "admin": admin,
        "admin_email": admin["email"],
        "current_plan_type": get_admin_plan_type(admin),
        "current_plan_label": ADMIN_PLAN_LABELS.get(get_admin_plan_type(admin), "有料"),
        "current_expiry_date": format_expiry_date(effective_expiry_text),
        "current_remaining_days": format_remaining_days(effective_expiry_text),
        "pending_plan_request": pending_plan_request,
        "plan_request_history": plan_request_history,
        "completed_stripe_payment": completed_stripe_payment,
        "recent_stripe_payments": recent_stripe_payments,
        "plan_request_type_options": ADMIN_PLAN_REQUEST_TYPE_LABELS,
        "payment_amount_options": ADMIN_PLAN_REQUEST_PAYMENT_AMOUNT_OPTIONS,
        "stripe_is_configured": stripe_is_configured(),
        "stripe_checkout_is_configured": stripe_checkout_is_configured(),
        "stripe_webhook_is_configured": stripe_webhook_is_configured(),
        "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
    }


def local_payment_preview_allowed():
    host = ((request.host or "").split(":", 1)[0] or "").strip().lower()
    remote_addr = (request.remote_addr or "").strip().lower()
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    return (
        app.debug
        or os.environ.get("ENABLE_LOCAL_PAYMENT_PREVIEW", "").strip() == "1"
        or host in local_hosts
        or remote_addr in local_hosts
    )


def build_local_preview_admin_plan_request_context(scenario="paid_unlinked"):
    scenario_value = (scenario or "").strip().lower() or "paid_unlinked"
    valid_scenarios = {
        "empty": {
            "label": "empty",
            "title": "管理者プレビュー: まだ決済なし",
            "summary": "決済前の初期状態です。申請フォームはまだ出ず、Stripe決済一覧には未完了の支払いだけが並びます。",
            "checks": [
                "決済完了の確認前は申請フォームが出ないこと",
                "success URL に戻っただけでは申請完了扱いにならない案内が見えること",
                "プレビューではボタンが無効化され、理由も表示されること",
            ],
        },
        "paid_unlinked": {
            "label": "paid_unlinked",
            "title": "管理者プレビュー: Stripe決済完了、未申請",
            "summary": "Stripe API で完了確認できた決済があり、まだ有料化反映はされていない状態です。次の操作は申請送信です。",
            "checks": [
                "完了済みStripe決済の内容が申請フォームに反映されること",
                "決済完了と有料化反映が分離されている説明が見えること",
                "送信ボタンは preview_mode 限定で無効化されていること",
            ],
        },
        "pending_review": {
            "label": "pending_review",
            "title": "管理者プレビュー: 申請済み、承認待ち",
            "summary": "Stripe決済は完了済みで申請送信も済んでいます。申請中のため、新しい決済や新規申請はできない状態です。",
            "checks": [
                "申請中のため新規決済と新規申請が止まること",
                "支払確認済み・最終確認日の情報が履歴から追えること",
                "有料化反映前であることが分かること",
            ],
        },
        "approved_with_history": {
            "label": "approved_with_history",
            "title": "管理者プレビュー: 承認済み、履歴あり",
            "summary": "サイト運営者承認まで完了した後の見え方です。旧 PayPay 履歴は文字列履歴として残しつつ、新規導線は Stripe 専用のままです。",
            "checks": [
                "承認済み履歴と legacy PayPay 履歴が同居しても読めること",
                "Stripe 新規導線が継続して見えること",
                "旧決済方式の新規利用終了案内が残ること",
            ],
        },
    }
    scenario_meta = valid_scenarios.get(scenario_value) or valid_scenarios["paid_unlinked"]
    scenario_value = scenario_meta["label"]
    expiry_text = "2026-05-01 00:00:00"

    history_rows = [
        {
            "id": 91,
            "admin_id": 1,
            "request_type": ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            "payment_method": ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
            "payment_amount": 1000,
            "payment_date": "2026-03-18 18:40:00",
            "payment_reference": "cs_test_approved_preview / pi:pi_test_approved_preview",
            "status": ADMIN_PLAN_REQUEST_STATUS_APPROVED,
            "review_note": "表示確認用の承認済みサンプル",
            "reviewed_at": "2026-03-18 19:00:00",
            "payment_verification_status": ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED,
            "payment_verified_at": "2026-03-18 18:45:00",
            "stripe_order_status": ADMIN_STRIPE_STATUS_COMPLETED,
            "stripe_remote_status": "complete",
            "stripe_remote_payment_status": "paid",
            "stripe_checkout_session_id": "cs_test_approved_preview",
            "created_at": "2026-03-18 18:41:00",
            "updated_at": "2026-03-18 19:00:00",
        },
        {
            "id": 90,
            "admin_id": 1,
            "request_type": ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            "payment_method": "paypay",
            "payment_amount": 500,
            "payment_date": "2026-03-10 12:00:00",
            "payment_reference": "legacy-paypay-history-preview",
            "status": ADMIN_PLAN_REQUEST_STATUS_REJECTED,
            "review_note": "旧履歴表示サンプル",
            "reviewed_at": "2026-03-10 13:00:00",
            "payment_verification_status": ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_UNVERIFIED,
            "payment_verified_at": "",
            "created_at": "2026-03-10 12:05:00",
            "updated_at": "2026-03-10 13:00:00",
        },
    ]
    stripe_payments = [
        {
            "id": 201,
            "admin_id": 1,
            "stripe_checkout_session_id": "cs_test_completed_preview",
            "stripe_payment_intent_id": "pi_test_completed_preview",
            "request_type": ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            "request_amount": 1000,
            "status": ADMIN_STRIPE_STATUS_COMPLETED,
            "stripe_paid_at": "2026-03-22 10:30:00",
            "confirmed_at": "2026-03-22 10:31:00",
            "created_at": "2026-03-22 10:20:00",
            "linked_plan_request_id": None,
        },
        {
            "id": 202,
            "admin_id": 1,
            "stripe_checkout_session_id": "cs_test_open_preview",
            "stripe_payment_intent_id": "pi_test_open_preview",
            "request_type": ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            "request_amount": 500,
            "status": ADMIN_STRIPE_STATUS_OPEN,
            "stripe_paid_at": "",
            "confirmed_at": "",
            "created_at": "2026-03-22 09:10:00",
            "linked_plan_request_id": None,
        },
    ]
    pending_plan_request = None
    completed_stripe_payment = None

    if scenario_value == "empty":
        stripe_payments = [stripe_payments[1]]
        history_rows = []
    elif scenario_value == "paid_unlinked":
        completed_stripe_payment = stripe_payments[0]
    elif scenario_value == "pending_review":
        pending_plan_request = {
            "id": 101,
            "admin_id": 1,
            "request_type": ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            "payment_method": ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
            "payment_amount": 1000,
            "payment_date": "2026-03-22 10:30:00",
            "payment_reference": "cs_test_pending_preview / pi:pi_test_pending_preview",
            "status": ADMIN_PLAN_REQUEST_STATUS_PENDING,
            "review_note": "",
            "reviewed_at": "",
            "payment_verification_status": ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED,
            "payment_verified_at": "2026-03-22 10:31:00",
            "stripe_order_status": ADMIN_STRIPE_STATUS_COMPLETED,
            "stripe_remote_status": "complete",
            "stripe_remote_payment_status": "paid",
            "stripe_checkout_session_id": "cs_test_pending_preview",
            "created_at": "2026-03-22 10:32:00",
            "updated_at": "2026-03-22 10:32:00",
        }
        stripe_payments[0]["linked_plan_request_id"] = 101
        history_rows = [pending_plan_request, history_rows[0], history_rows[1]]
    elif scenario_value == "approved_with_history":
        stripe_payments = [stripe_payments[0]]
        history_rows = history_rows
    else:
        completed_stripe_payment = stripe_payments[0]

    scenario_links = [
        {
            "key": key,
            "label": meta["label"],
            "title": meta["title"],
            "url": url_for("dev_stripe_preview_admin_plan_requests", scenario=key),
            "active": key == scenario_value,
        }
        for key, meta in valid_scenarios.items()
    ]

    return {
        "admin_email": "preview-admin@example.com",
        "current_plan_label": ADMIN_PLAN_LABELS.get(ADMIN_PLAN_PAID, "有料"),
        "current_expiry_date": format_expiry_date(expiry_text),
        "current_remaining_days": format_remaining_days(expiry_text),
        "pending_plan_request": enrich_admin_plan_request_row(pending_plan_request) if pending_plan_request else None,
        "plan_request_history": enrich_admin_plan_request_rows(history_rows),
        "completed_stripe_payment": enrich_admin_stripe_payment_row(completed_stripe_payment) if completed_stripe_payment else None,
        "recent_stripe_payments": enrich_admin_stripe_payment_rows(stripe_payments),
        "plan_request_type_options": ADMIN_PLAN_REQUEST_TYPE_LABELS,
        "payment_amount_options": ADMIN_PLAN_REQUEST_PAYMENT_AMOUNT_OPTIONS,
        "stripe_is_configured": True,
        "stripe_checkout_is_configured": True,
        "stripe_webhook_is_configured": True,
        "stripe_publishable_key": "pk_test_preview",
        "error_message": "",
        "success_message": "ローカルプレビュー表示です。実決済や申請送信は実行されません。",
        "preview_mode": True,
        "preview_scenario": scenario_value,
        "preview_page_role": "admin",
        "preview_title": scenario_meta["title"],
        "preview_summary": scenario_meta["summary"],
        "preview_checks": scenario_meta["checks"],
        "preview_hub_url": url_for("dev_stripe_preview_index"),
        "preview_actions_disabled_reason": "preview_mode のため、Stripe checkout・申請送信・手動再確認はすべて無効化しています。",
        "preview_scenario_links": scenario_links,
    }


def build_local_preview_site_admin_plan_requests_context(scenario="stripe_pending"):
    scenario_value = (scenario or "").strip().lower() or "stripe_pending"
    valid_scenarios = {
        "stripe_pending": {
            "label": "stripe_pending",
            "title": "サイト運営者プレビュー: 承認可能な Stripe pending",
            "summary": "Stripe 決済完了を確認済みで、fail-closed の承認対象として表示される状態です。",
            "checks": [
                "承認・却下ボタンが Stripe pending にだけ出ること",
                "支払確認・最終確認日・決済状態が読めること",
                "preview_mode では承認操作そのものは無効化されること",
            ],
        },
        "legacy_paypay_pending": {
            "label": "legacy_paypay_pending",
            "title": "サイト運営者プレビュー: 承認不可な legacy PayPay pending",
            "summary": "旧決済方式の pending 履歴です。却下は可能だが承認はできない、という運用確認用です。",
            "checks": [
                "legacy PayPay に承認ボタンが出ないこと",
                "旧決済方式の案内が明示されること",
                "旧履歴文字列がそのまま読めること",
            ],
        },
        "approved_history": {
            "label": "approved_history",
            "title": "サイト運営者プレビュー: 承認済み Stripe 履歴",
            "summary": "承認完了後の見え方を確認するための履歴サンプルです。対応済み表示に切り替わります。",
            "checks": [
                "承認済みでは操作欄が対応済み表示になること",
                "確認済みステータスと最終確認日が残ること",
                "Stripe の決済状態が履歴から追えること",
            ],
        },
    }
    scenario_meta = valid_scenarios.get(scenario_value) or valid_scenarios["stripe_pending"]
    scenario_value = scenario_meta["label"]

    scenario_rows = {
        "stripe_pending": [
            {
                "id": 301,
                "admin_id": 7,
                "admin_email": "team-alpha@example.com",
                "request_type": ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
                "payment_method": ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
                "payment_amount": 1000,
                "payment_date": "2026-03-22 10:30:00",
                "payment_reference": "cs_test_site_pending / pi:pi_test_site_pending",
                "status": ADMIN_PLAN_REQUEST_STATUS_PENDING,
                "review_note": "",
                "reviewed_at": "",
                "payment_verification_status": ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED,
                "payment_verified_at": "2026-03-22 10:32:00",
                "stripe_order_status": ADMIN_STRIPE_STATUS_COMPLETED,
                "stripe_remote_status": "complete",
                "stripe_remote_payment_status": "paid",
                "stripe_checkout_session_id": "cs_test_site_pending",
                "created_at": "2026-03-22 10:33:00",
                "updated_at": "2026-03-22 10:33:00",
            }
        ],
        "legacy_paypay_pending": [
            {
                "id": 303,
                "admin_id": 9,
                "admin_email": "legacy-admin@example.com",
                "request_type": ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
                "payment_method": "paypay",
                "payment_amount": 500,
                "payment_date": "2026-03-20 08:00:00",
                "payment_reference": "legacy-paypay-preview",
                "status": ADMIN_PLAN_REQUEST_STATUS_PENDING,
                "review_note": "",
                "reviewed_at": "",
                "payment_verification_status": ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_UNVERIFIED,
                "payment_verified_at": "",
                "created_at": "2026-03-20 08:05:00",
                "updated_at": "2026-03-20 08:05:00",
            }
        ],
        "approved_history": [
            {
                "id": 302,
                "admin_id": 8,
                "admin_email": "team-beta@example.com",
                "request_type": ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
                "payment_method": ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
                "payment_amount": 500,
                "payment_date": "2026-03-21 09:00:00",
                "payment_reference": "cs_test_site_approved / pi:pi_test_site_approved",
                "status": ADMIN_PLAN_REQUEST_STATUS_APPROVED,
                "review_note": "確認済み",
                "reviewed_at": "2026-03-21 09:20:00",
                "payment_verification_status": ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED,
                "payment_verified_at": "2026-03-21 09:05:00",
                "stripe_order_status": ADMIN_STRIPE_STATUS_COMPLETED,
                "stripe_remote_status": "complete",
                "stripe_remote_payment_status": "paid",
                "stripe_checkout_session_id": "cs_test_site_approved",
                "created_at": "2026-03-21 09:01:00",
                "updated_at": "2026-03-21 09:20:00",
            }
        ],
    }
    request_rows = scenario_rows[scenario_value]
    pending_count = len([row for row in request_rows if row.get("status") == ADMIN_PLAN_REQUEST_STATUS_PENDING])
    scenario_links = [
        {
            "key": key,
            "label": meta["label"],
            "title": meta["title"],
            "url": url_for("dev_stripe_preview_site_admin_plan_requests", scenario=key),
            "active": key == scenario_value,
        }
        for key, meta in valid_scenarios.items()
    ]
    return {
        "request_rows": enrich_admin_plan_request_rows(request_rows),
        "pending_count": pending_count,
        "error_message": "",
        "success_message": "ローカルプレビュー表示です。実承認や Stripe 再確認は実行されません。",
        "preview_mode": True,
        "preview_scenario": scenario_value,
        "preview_page_role": "site_admin",
        "preview_title": scenario_meta["title"],
        "preview_summary": scenario_meta["summary"],
        "preview_checks": scenario_meta["checks"],
        "preview_hub_url": url_for("dev_stripe_preview_index"),
        "preview_actions_disabled_reason": "preview_mode のため、承認・却下・Stripe 再確認は表示確認専用で無効化しています。",
        "preview_scenario_links": scenario_links,
    }


def build_public_team_url(team):
    public_id = (team.get("public_id") or "").strip()
    if not public_id:
        return ""
    return url_for("member_team_page", public_id=public_id)


def enrich_team_detail_row(team):
    team["registered_date"] = format_start_date(team.get("created_at"))
    team["last_attendance_updated_date"] = format_portal_date(team.get("last_attendance_updated_at"))
    team["public_url"] = build_public_team_url(team)
    return team


def enrich_site_admin_row(row, team_details=None):
    row["start_date"] = format_start_date(row.get("created_at"))
    if is_unlimited_expiry(row.get("expires_at")):
        row["effective_expiry"] = ADMIN_EXPIRY_UNLIMITED
    else:
        effective_expiry = resolve_admin_expiry_datetime(row.get("created_at"), row.get("expires_at"))
        row["effective_expiry"] = effective_expiry.strftime("%Y-%m-%d %H:%M:%S") if effective_expiry else ""
    row["expiry_date"] = format_expiry_date(row.get("effective_expiry"))
    row["remaining_days_text"] = format_remaining_days(row.get("effective_expiry"))
    row["plan_type"] = normalize_admin_plan_type(row.get("plan_type")) or (
        ADMIN_PLAN_FREE if (row.get("status") or "").strip().lower() == ADMIN_STATUS_FREE else ADMIN_PLAN_PAID
    )
    row["account_status"] = normalize_admin_account_status(row.get("account_status")) or (
        (row.get("status") or "").strip().lower()
        if (row.get("status") or "").strip().lower() in {ADMIN_STATUS_SUSPENDED, ADMIN_STATUS_EXPIRED}
        else ADMIN_ACCOUNT_STATUS_ACTIVE
    )
    row["plan_type_text"] = ADMIN_PLAN_LABELS.get(row["plan_type"], "有料")
    row["account_status_text"] = ADMIN_ACCOUNT_STATUS_LABELS.get(row["account_status"], "利用中")
    row["status_code"] = resolve_admin_status(row)
    row["status_text"] = ADMIN_STATUS_LABELS.get(row["status_code"], "無料")
    row["billing_status_text"] = format_admin_billing_status(row.get("billing_status"))
    row["last_login_date"] = format_portal_date(row.get("last_login_at"))
    row["last_billed_date"] = format_portal_date(row.get("last_billed_at"))
    row["last_billed_input"] = row["last_billed_date"] if row["last_billed_date"] != "-" else ""
    row["total_billing_amount_text"] = format_currency_yen(row.get("total_billing_amount"))
    if team_details is not None:
        row["team_details"] = [enrich_team_detail_row(team) for team in team_details]
        row["team_count"] = len(row["team_details"])
    return row


def enrich_admin_billing_history_rows(rows):
    enriched_rows = []
    for row in rows:
        row["billing_status_text"] = format_admin_billing_status(row.get("billing_status"))
        row["billed_date"] = format_portal_date(row.get("billed_at"))
        row["created_date"] = format_portal_date(row.get("created_at"))
        row["amount_text"] = format_billing_history_amount(row.get("amount"))
        row["total_amount_text"] = format_currency_yen(row.get("total_amount"))
        enriched_rows.append(row)
    return enriched_rows


def format_expiry_date(expires_at):
    if is_unlimited_expiry(expires_at):
        return "無期限"
    parsed = parse_portal_datetime(expires_at)
    if not parsed:
        return "-"
    return parsed.strftime("%Y-%m-%d")


def format_remaining_days(expires_at):
    if is_unlimited_expiry(expires_at):
        return "無期限"
    parsed = parse_portal_datetime(expires_at)
    if not parsed:
        return "-"
    remaining_days = (parsed.date() - datetime.now().date()).days
    if remaining_days >= 0:
        return f"{remaining_days}日"
    return f"期限切れ（{abs(remaining_days)}日経過）"


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


def _normalize_name_list(values):
    normalized = []
    seen = set()
    for value in values or []:
        name = (value or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def _coerce_team_count(value, default=2, minimum=2, maximum=9):
    try:
        team_count = int(value)
    except (TypeError, ValueError):
        team_count = default
    return max(minimum, min(maximum, team_count))


class TeamAllocator:
    def allocate(self, members, team_count):
        raise NotImplementedError


class RandomTeamAllocator(TeamAllocator):
    def allocate(self, members, team_count):
        shuffled = list(members)
        random.shuffle(shuffled)
        teams = [{"name": f"Team {index + 1}", "members": []} for index in range(team_count)]
        for index, member_name in enumerate(shuffled):
            teams[index % team_count]["members"].append(member_name)
        return teams


def build_team_allocator(strategy="random"):
    # Strategy hook for future extension (level/position balanced allocation).
    if strategy == "random":
        return RandomTeamAllocator()
    return RandomTeamAllocator()


def serialize_team_result(teams):
    return [{"name": team.get("name", ""), "members": _normalize_name_list(team.get("members", []))} for team in teams]


def parse_team_state_from_form(raw_value):
    if not raw_value:
        return []
    try:
        loaded = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    teams = []
    for index, raw_team in enumerate(loaded, start=1):
        if not isinstance(raw_team, dict):
            continue
        team_name = (raw_team.get("name") or f"Team {index}").strip() or f"Team {index}"
        teams.append({"name": team_name, "members": _normalize_name_list(raw_team.get("members", []))})
    return teams


def build_admin_plan_request_expiry(admin_row, request_type, approved_at_text, payment_amount=None):
    if is_unlimited_expiry(admin_row.get("expires_at")):
        return ADMIN_EXPIRY_UNLIMITED
    extend_days = ADMIN_PLAN_PAYMENT_AMOUNT_EXTENSION_DAYS.get(
        int(payment_amount or 0),
        ADMIN_PLAN_REQUEST_EXTENSION_DAYS.get(request_type, 30),
    )
    approved_at_dt = parse_portal_datetime(approved_at_text) or datetime.now()
    effective_expiry = resolve_admin_expiry_datetime(admin_row.get("created_at"), admin_row.get("expires_at"))
    base_dt = effective_expiry if (effective_expiry and effective_expiry > approved_at_dt) else approved_at_dt
    return (base_dt + timedelta(days=extend_days)).strftime("%Y-%m-%d %H:%M:%S")


def build_admin_plan_request_billing_note(request_row):
    parts = [f"有料プラン申請承認 #{request_row['id']}"]
    payment_reference = (request_row.get("payment_reference") or "").strip()
    if payment_reference:
        parts.append(f"識別情報: {payment_reference}")
    request_note = (request_row.get("request_note") or "").strip()
    if request_note:
        parts.append(f"申請メモ: {request_note}")
    return " / ".join(parts)


def build_admin_plan_request_auto_review_note(payment_row, applied_via=""):
    parts = ["Stripe APIで支払い完了を確認後に自動反映"]
    payment_reference = stripe_extract_reference(payment_row)
    if payment_reference:
        parts.append(f"識別情報: {payment_reference}")
    if applied_via:
        applied_via_labels = {
            "success": "success戻り",
            "manual_refresh": "手動再確認",
            "webhook": "webhook受信後API確認",
        }
        parts.append(f"反映経路: {applied_via_labels.get(applied_via, applied_via)}")
    return " / ".join(parts)


def portal_auto_apply_completed_admin_stripe_payment(stripe_payment_id, applied_via=""):
    if not stripe_payment_id:
        return False, "stripe_payment_not_found", None
    applied_at_text = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT
                id,
                admin_id,
                stripe_checkout_session_id,
                stripe_payment_intent_id,
                request_type,
                request_amount,
                currency,
                checkout_url,
                status,
                stripe_status,
                stripe_payment_status,
                payment_reference,
                stripe_paid_at,
                requested_at,
                returned_at,
                confirmed_at,
                last_checked_at,
                linked_plan_request_id,
                applied_at,
                applied_billing_history_id,
                last_error_code,
                last_error_message,
                raw_create_response,
                raw_payment_details,
                raw_last_webhook,
                created_at,
                updated_at
            FROM admin_stripe_payments
            WHERE id=?
            LIMIT 1
            """,
            (stripe_payment_id,),
        )
        payment_row = row_to_dict(c.fetchone())
        if not payment_row:
            conn.close()
            return False, "stripe_payment_not_found", None
        if payment_row.get("status") != ADMIN_STRIPE_STATUS_COMPLETED:
            conn.close()
            return False, "stripe_payment_not_completed", payment_row

        linked_request_row = None
        linked_request_id = payment_row.get("linked_plan_request_id")
        if linked_request_id:
            c.execute(
                """
                SELECT
                    id,
                    admin_id,
                    request_type,
                    payment_method,
                    payment_amount,
                    payment_date,
                    payment_reference,
                    request_note,
                    status,
                    review_note,
                    reviewed_by_admin_id,
                    reviewed_at,
                    stripe_payment_id,
                    payment_verification_status,
                    payment_verified_at,
                    created_at,
                    updated_at
                FROM admin_plan_requests
                WHERE id=?
                LIMIT 1
                """,
                (linked_request_id,),
            )
            linked_request_row = row_to_dict(c.fetchone())
            if linked_request_row and linked_request_row.get("status") == ADMIN_PLAN_REQUEST_STATUS_APPROVED:
                if not payment_row.get("applied_at"):
                    c.execute(
                        """
                        UPDATE admin_stripe_payments
                        SET applied_at=COALESCE(applied_at, ?),
                            updated_at=?
                        WHERE id=?
                        """,
                        (linked_request_row.get("reviewed_at") or applied_at_text, applied_at_text, stripe_payment_id),
                    )
                    conn.commit()
                else:
                    conn.close()
                return True, "already_applied", portal_get_admin_stripe_payment(stripe_payment_id)
            if linked_request_row and linked_request_row.get("status") == ADMIN_PLAN_REQUEST_STATUS_REJECTED:
                conn.close()
                return False, "linked_plan_request_rejected", payment_row

        c.execute(
            """
            UPDATE admin_stripe_payments
            SET applied_at=?,
                updated_at=?
            WHERE id=? AND applied_at IS NULL
            """,
            (applied_at_text, applied_at_text, stripe_payment_id),
        )
        if c.rowcount <= 0:
            conn.rollback()
            conn.close()
            latest_payment = portal_get_admin_stripe_payment(stripe_payment_id)
            if latest_payment and latest_payment.get("applied_at"):
                return True, "already_applied", latest_payment
            return False, "apply_claim_failed", latest_payment

        c.execute(f"SELECT {ADMIN_SELECT_COLUMNS} FROM admins WHERE id=?", (payment_row["admin_id"],))
        admin_row = row_to_dict(c.fetchone())
        if not admin_row:
            conn.rollback()
            conn.close()
            return False, "admin_not_found", payment_row

        payment_amount = int(payment_row.get("request_amount") or 0)
        payment_date = payment_row.get("stripe_paid_at") or applied_at_text
        payment_reference = payment_row.get("payment_reference") or stripe_extract_reference(payment_row)
        request_type = payment_row.get("request_type") or ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS
        auto_review_note = build_admin_plan_request_auto_review_note(payment_row, applied_via=applied_via)
        request_note = linked_request_row.get("request_note") if linked_request_row else ""

        if linked_request_row:
            request_id = linked_request_row["id"]
            c.execute(
                """
                UPDATE admin_plan_requests
                SET request_type=?,
                    payment_method=?,
                    payment_amount=?,
                    payment_date=?,
                    payment_reference=?,
                    status=?,
                    review_note=?,
                    reviewed_by_admin_id=NULL,
                    reviewed_at=?,
                    stripe_payment_id=?,
                    payment_verification_status=?,
                    payment_verified_at=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    request_type,
                    ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
                    payment_amount,
                    payment_date,
                    payment_reference,
                    ADMIN_PLAN_REQUEST_STATUS_APPROVED,
                    auto_review_note,
                    applied_at_text,
                    stripe_payment_id,
                    ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED,
                    applied_at_text,
                    applied_at_text,
                    request_id,
                ),
            )
        else:
            c.execute(
                """
                INSERT INTO admin_plan_requests (
                    admin_id,
                    request_type,
                    payment_method,
                    payment_amount,
                    payment_date,
                    payment_reference,
                    request_note,
                    status,
                    review_note,
                    reviewed_by_admin_id,
                    reviewed_at,
                    stripe_payment_id,
                    payment_verification_status,
                    payment_verified_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payment_row["admin_id"],
                    request_type,
                    ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
                    payment_amount,
                    payment_date,
                    payment_reference,
                    request_note or "",
                    ADMIN_PLAN_REQUEST_STATUS_APPROVED,
                    auto_review_note,
                    None,
                    applied_at_text,
                    stripe_payment_id,
                    ADMIN_PLAN_REQUEST_PAYMENT_VERIFICATION_VERIFIED,
                    applied_at_text,
                    applied_at_text,
                    applied_at_text,
                ),
            )
            request_id = c.lastrowid if not USE_POSTGRES else None
            if USE_POSTGRES and not request_id:
                c.execute("SELECT currval(pg_get_serial_sequence('admin_plan_requests', 'id')) AS id")
                latest_row = c.fetchone()
                request_id = (
                    latest_row["id"] if isinstance(latest_row, dict) or hasattr(latest_row, "keys") else latest_row[0]
                )

        total_billing_amount = int(admin_row.get("total_billing_amount") or 0) + payment_amount
        billing_count = int(admin_row.get("billing_count") or 0) + 1
        expires_at = build_admin_plan_request_expiry(
            admin_row,
            request_type,
            payment_date,
            payment_amount=payment_amount,
        )
        current_account_status = normalize_admin_account_status(admin_row.get("account_status")) or ADMIN_ACCOUNT_STATUS_ACTIVE
        account_status = (
            ADMIN_ACCOUNT_STATUS_SUSPENDED
            if current_account_status == ADMIN_ACCOUNT_STATUS_SUSPENDED
            else ADMIN_ACCOUNT_STATUS_ACTIVE
        )
        legacy_status = ADMIN_STATUS_SUSPENDED if account_status == ADMIN_ACCOUNT_STATUS_SUSPENDED else ADMIN_STATUS_PAID

        c.execute(
            """
            UPDATE admins
            SET plan_type=?,
                billing_status=?,
                total_billing_amount=?,
                billing_count=?,
                last_billed_at=?,
                expires_at=?,
                account_status=?,
                status=?
            WHERE id=?
            """,
            (
                ADMIN_PLAN_PAID,
                ADMIN_BILLING_STATUS_PAID,
                total_billing_amount,
                billing_count,
                payment_date,
                expires_at,
                account_status,
                legacy_status,
                payment_row["admin_id"],
            ),
        )
        c.execute(
            """
            INSERT INTO admin_billing_history (
                admin_id,
                billing_status,
                billed_at,
                amount,
                total_amount,
                billing_count,
                note,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payment_row["admin_id"],
                ADMIN_BILLING_STATUS_PAID,
                payment_date,
                payment_amount,
                total_billing_amount,
                billing_count,
                build_admin_plan_request_billing_note(
                    {
                        "id": request_id,
                        "payment_reference": payment_reference,
                        "request_note": request_note or "",
                    }
                ),
                applied_at_text,
            ),
        )
        billing_history_id = c.lastrowid if not USE_POSTGRES else None
        if USE_POSTGRES and not billing_history_id:
            c.execute("SELECT currval(pg_get_serial_sequence('admin_billing_history', 'id')) AS id")
            latest_row = c.fetchone()
            billing_history_id = (
                latest_row["id"] if isinstance(latest_row, dict) or hasattr(latest_row, "keys") else latest_row[0]
            )
        c.execute(
            """
            UPDATE admin_stripe_payments
            SET linked_plan_request_id=?,
                applied_billing_history_id=?,
                updated_at=?
            WHERE id=?
            """,
            (request_id, billing_history_id, applied_at_text, stripe_payment_id),
        )
        conn.commit()
    except DatabaseError:
        conn.rollback()
        conn.close()
        return False, "database_error", None

    conn.close()
    return True, "applied", portal_get_admin_stripe_payment(stripe_payment_id)


def sync_admin_stripe_payment_with_stripe(checkout_session_id, mark_returned=False, applied_via=""):
    payment_details = stripe_get_checkout_session(checkout_session_id)
    error_object = (payment_details.get("json", {}) or {}).get("error") or {}
    updated_payment = portal_update_admin_stripe_payment_from_remote(
        checkout_session_id,
        payment_details=payment_details if payment_details.get("json") else None,
        mark_returned=mark_returned,
        error_code=error_object.get("code") or payment_details.get("error") or "",
        error_message=error_object.get("message") or "",
    )
    auto_apply_result = {"ok": False, "status": "not_attempted"}
    if updated_payment and updated_payment.get("status") == ADMIN_STRIPE_STATUS_COMPLETED:
        applied_ok, apply_status, latest_payment = portal_auto_apply_completed_admin_stripe_payment(
            updated_payment.get("id"),
            applied_via=applied_via,
        )
        updated_payment = latest_payment or updated_payment
        auto_apply_result = {"ok": applied_ok, "status": apply_status}
    if updated_payment and updated_payment.get("linked_plan_request_id"):
        portal_sync_plan_request_verification_with_payment(
            updated_payment.get("linked_plan_request_id"),
            ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
            updated_payment.get("status"),
            payment_date=updated_payment.get("stripe_paid_at") or "",
            payment_reference=updated_payment.get("payment_reference") or stripe_extract_reference(updated_payment),
        )
    return updated_payment, payment_details, auto_apply_result


def verify_admin_plan_request_payment_before_approval(request_row):
    payment_method = normalize_admin_plan_request_payment_method(request_row.get("payment_method"))
    if payment_method != ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE:
        return False, "legacy_payment_method_not_supported"
    if not request_row.get("stripe_payment_id"):
        return False, "stripe_payment_not_found"
    payment_row = portal_get_admin_stripe_payment(request_row.get("stripe_payment_id"))
    if not payment_row:
        return False, "stripe_payment_not_found"
    updated_payment, _payment_details, _auto_apply_result = sync_admin_stripe_payment_with_stripe(
        payment_row.get("stripe_checkout_session_id") or ""
    )
    if not updated_payment:
        return False, "stripe_payment_refresh_failed"
    if updated_payment.get("status") != ADMIN_STRIPE_STATUS_COMPLETED:
        return False, "stripe_payment_not_completed"
    return True, "verified"


def portal_review_admin_plan_request(request_id, reviewer_admin_id, decision, review_note=""):
    if decision not in {ADMIN_PLAN_REQUEST_STATUS_APPROVED, ADMIN_PLAN_REQUEST_STATUS_REJECTED}:
        return False, "invalid_decision"
    if decision == ADMIN_PLAN_REQUEST_STATUS_APPROVED:
        verified, verify_status = verify_admin_plan_request_payment_before_approval(request_row=portal_get_admin_plan_request(request_id))
        if not verified:
            return False, verify_status

    review_timestamp = portal_now_text()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT
                id,
                admin_id,
                request_type,
                payment_method,
                payment_amount,
                payment_date,
                payment_reference,
                request_note,
                status,
                review_note,
                reviewed_by_admin_id,
                reviewed_at,
                stripe_payment_id,
                payment_verification_status,
                payment_verified_at,
                created_at,
                updated_at
            FROM admin_plan_requests
            WHERE id=?
            """,
            (request_id,),
        )
        request_row = row_to_dict(c.fetchone())
        if not request_row:
            conn.close()
            return False, "not_found"
        if request_row.get("status") != ADMIN_PLAN_REQUEST_STATUS_PENDING:
            conn.close()
            return False, "already_reviewed"
        if decision == ADMIN_PLAN_REQUEST_STATUS_APPROVED:
            refreshed_request_row = portal_get_admin_plan_request(request_id)
            if refreshed_request_row:
                request_row = refreshed_request_row

        c.execute(
            """
            UPDATE admin_plan_requests
            SET status=?, review_note=?, reviewed_by_admin_id=?, reviewed_at=?, updated_at=?
            WHERE id=? AND status=?
            """,
            (
                decision,
                review_note,
                reviewer_admin_id,
                review_timestamp,
                review_timestamp,
                request_id,
                ADMIN_PLAN_REQUEST_STATUS_PENDING,
            ),
        )
        if c.rowcount <= 0:
            conn.rollback()
            conn.close()
            return False, "already_reviewed"

        if decision == ADMIN_PLAN_REQUEST_STATUS_REJECTED and request_row.get("stripe_payment_id"):
            c.execute(
                """
                UPDATE admin_stripe_payments
                SET linked_plan_request_id=NULL, updated_at=?
                WHERE id=? AND linked_plan_request_id=?
                """,
                (review_timestamp, request_row.get("stripe_payment_id"), request_id),
            )

        if decision == ADMIN_PLAN_REQUEST_STATUS_APPROVED:
            c.execute(f"SELECT {ADMIN_SELECT_COLUMNS} FROM admins WHERE id=?", (request_row["admin_id"],))
            admin_row = row_to_dict(c.fetchone())
            if not admin_row:
                conn.rollback()
                conn.close()
                return False, "admin_not_found"

            payment_amount = int(request_row.get("payment_amount") or 0)
            total_billing_amount = int(admin_row.get("total_billing_amount") or 0) + payment_amount
            billing_count = int(admin_row.get("billing_count") or 0) + 1
            expires_at = build_admin_plan_request_expiry(
                admin_row,
                request_row.get("request_type"),
                review_timestamp,
                payment_amount=payment_amount,
            )
            current_account_status = normalize_admin_account_status(admin_row.get("account_status")) or ADMIN_ACCOUNT_STATUS_ACTIVE
            account_status = (
                ADMIN_ACCOUNT_STATUS_SUSPENDED
                if current_account_status == ADMIN_ACCOUNT_STATUS_SUSPENDED
                else ADMIN_ACCOUNT_STATUS_ACTIVE
            )
            legacy_status = (
                ADMIN_STATUS_SUSPENDED if account_status == ADMIN_ACCOUNT_STATUS_SUSPENDED else ADMIN_STATUS_PAID
            )

            c.execute(
                """
                UPDATE admins
                SET plan_type=?,
                    billing_status=?,
                    total_billing_amount=?,
                    billing_count=?,
                    last_billed_at=?,
                    expires_at=?,
                    account_status=?,
                    status=?
                WHERE id=?
                """,
                (
                    ADMIN_PLAN_PAID,
                    ADMIN_BILLING_STATUS_PAID,
                    total_billing_amount,
                    billing_count,
                    request_row.get("payment_date"),
                    expires_at,
                    account_status,
                    legacy_status,
                    request_row["admin_id"],
                ),
            )
            c.execute(
                """
                INSERT INTO admin_billing_history (
                    admin_id,
                    billing_status,
                    billed_at,
                    amount,
                    total_amount,
                    billing_count,
                    note,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_row["admin_id"],
                    ADMIN_BILLING_STATUS_PAID,
                    request_row.get("payment_date"),
                    payment_amount,
                    total_billing_amount,
                    billing_count,
                    build_admin_plan_request_billing_note(request_row),
                    review_timestamp,
                ),
            )

        conn.commit()
    except DatabaseError:
        conn.rollback()
        conn.close()
        return False, "database_error"

    conn.close()
    return True, decision


def parse_random_pick_names(raw_value="", single_value=""):
    names = []
    if raw_value:
        try:
            loaded = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            loaded = []
        if isinstance(loaded, list):
            names = _normalize_name_list(loaded)
    if not names and single_value:
        single_name = single_value.strip()
        if single_name:
            names = [single_name]
    return names


def swap_members_in_teams(teams, src_team_idx, src_member_idx, dst_team_idx, dst_member_idx):
    if not teams:
        return teams, "empty"
    if src_team_idx < 0 or src_team_idx >= len(teams) or dst_team_idx < 0 or dst_team_idx >= len(teams):
        return teams, "invalid_team"
    src_members = teams[src_team_idx].get("members", [])
    dst_members = teams[dst_team_idx].get("members", [])
    if src_member_idx < 0 or src_member_idx >= len(src_members) or dst_member_idx < 0 or dst_member_idx >= len(dst_members):
        return teams, "invalid_member"
    src_members[src_member_idx], dst_members[dst_member_idx] = dst_members[dst_member_idx], src_members[src_member_idx]
    return teams, "swapped"


def build_role_slots(form):
    role_fields = [
        ("キャプテン", "role_captain_count"),
        ("審判", "role_referee_count"),
        ("タイムキーパー", "role_timekeeper_count"),
        ("用具係", "role_equipment_count"),
    ]
    slots = []
    for role_name, field_name in role_fields:
        count = _coerce_positive_int(form.get(field_name))
        if count:
            slots.extend([role_name] * count)

    custom_text = (form.get("custom_roles") or "").strip()
    if custom_text:
        for line in custom_text.replace("\r", "").split("\n"):
            row = line.strip()
            if not row:
                continue
            if ":" in row:
                name, count_text = row.split(":", 1)
                role_name = name.strip()
                role_count = _coerce_positive_int(count_text.strip()) or 0
            else:
                role_name = row
                role_count = 1
            if role_name and role_count > 0:
                slots.extend([role_name] * role_count)
    return slots


def assign_roles(members, role_slots):
    shuffled_members = list(members)
    random.shuffle(shuffled_members)
    assignments = []
    for index, role_name in enumerate(role_slots):
        if index >= len(shuffled_members):
            break
        assignments.append({"role": role_name, "member": shuffled_members[index]})
    unassigned_roles = role_slots[len(assignments) :]
    remaining_members = shuffled_members[len(assignments) :]
    return assignments, unassigned_roles, remaining_members


def create_attendance_tool_share(user_id, match_id, tool_type, payload):
    share_id = secrets.token_urlsafe(10)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO attendance_tool_shares (user_id, match_id, tool_type, share_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            match_id,
            tool_type,
            share_id,
            json.dumps(payload, ensure_ascii=False),
            portal_now_text(),
        ),
    )
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    if deleted:
        portal_touch_admin_last_attendance_updated_by_team(team_id)
    return share_id


def get_attendance_tool_share(share_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, user_id, match_id, tool_type, share_id, payload_json, created_at
        FROM attendance_tool_shares
        WHERE share_id=?
        """,
        (share_id,),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    if not row:
        return None
    try:
        row["payload"] = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        row["payload"] = {}
    return row


def create_attendance_tool_saved_result(user_id, match_id, tool_type, title, payload):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO attendance_tool_saved_results (user_id, match_id, tool_type, title, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            match_id,
            tool_type,
            title,
            json.dumps(payload, ensure_ascii=False),
            portal_now_text(),
        ),
    )
    saved_id = c.lastrowid if not USE_POSTGRES else None
    conn.commit()
    if USE_POSTGRES and not saved_id:
        c.execute(
            """
            SELECT id
            FROM attendance_tool_saved_results
            WHERE user_id=? AND match_id=? AND tool_type=? AND title=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, match_id, tool_type, title),
        )
        row = row_to_dict(c.fetchone())
        saved_id = row.get("id") if row else None
    conn.close()
    return saved_id


def get_attendance_tool_saved_results(user_id, match_id, tool_type=None, limit=20):
    conn = get_db_connection()
    c = conn.cursor()
    params = [user_id, match_id]
    where_clause = "WHERE user_id=? AND match_id=?"
    if tool_type:
        where_clause += " AND tool_type=?"
        params.append(tool_type)
    params.append(limit)
    c.execute(
        f"""
        SELECT id, user_id, match_id, tool_type, title, payload_json, created_at
        FROM attendance_tool_saved_results
        {where_clause}
        ORDER BY id DESC
        LIMIT ?
        """,
        params,
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    for row in rows:
        try:
            row["payload"] = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            row["payload"] = {}
    return rows


def get_attendance_tool_saved_result(user_id, match_id, saved_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, user_id, match_id, tool_type, title, payload_json, created_at
        FROM attendance_tool_saved_results
        WHERE user_id=? AND match_id=? AND id=?
        """,
        (user_id, match_id, saved_id),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    if not row:
        return None
    try:
        row["payload"] = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        row["payload"] = {}
    return row


def get_match_join_members(user_id, match_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT name, status
        FROM attendance
        WHERE match_id=? AND user_id=?
        ORDER BY id
        """,
        (match_id, user_id),
    )
    join_members = []
    for row in c.fetchall():
        if normalize_status(row["status"]) == "参加":
            join_members.append(row["name"])
    conn.close()
    return _normalize_name_list(join_members)


def get_confirmed_attendees(user_id, match_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT name, source_type
        FROM attendance_actual_attendees
        WHERE user_id=? AND match_id=?
        ORDER BY id ASC
        """,
        (user_id, match_id),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def save_confirmed_attendees(user_id, match_id, selected_names, walkin_names=None):
    selected = _normalize_name_list(selected_names)
    walkins = _normalize_name_list(walkin_names or [])
    join_names = set(get_match_join_members(user_id, match_id))
    names_to_keep = _normalize_name_list(selected + walkins)

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "DELETE FROM attendance_actual_attendees WHERE user_id=? AND match_id=?",
        (user_id, match_id),
    )
    for name in names_to_keep:
        if name in walkins:
            source_type = "walkin" if name in selected else "walkin_pending"
        else:
            source_type = "attendance" if name in join_names else "walkin"
        c.execute(
            """
            INSERT INTO attendance_actual_attendees (user_id, match_id, name, source_type, confirmed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, match_id, name, source_type, portal_now_text()),
    )
    conn.commit()
    conn.close()
    return names_to_keep


def add_walkin_attendee(user_id, match_id, name):
    target_name = (name or "").strip()
    if not target_name:
        return False
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO attendance_actual_attendees (user_id, match_id, name, source_type, confirmed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, match_id, name)
        DO UPDATE SET source_type=excluded.source_type, confirmed_at=excluded.confirmed_at
        """,
        (user_id, match_id, target_name, "walkin", portal_now_text()),
    )
    conn.commit()
    conn.close()
    return True


def remove_walkin_attendee(user_id, match_id, name):
    target_name = (name or "").strip()
    if not target_name:
        return False
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        DELETE FROM attendance_actual_attendees
        WHERE user_id=? AND match_id=? AND name=? AND source_type IN ('walkin', 'walkin_pending')
        """,
        (user_id, match_id, target_name),
    )
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_effective_attendees(user_id, match_id):
    confirmed_rows = get_confirmed_attendees(user_id, match_id)
    if confirmed_rows:
        return _normalize_name_list([row.get("name") for row in confirmed_rows if row.get("source_type") != "walkin_pending"])
    return get_match_join_members(user_id, match_id)


def create_portal_tool_share(team_id, event_id, tool_type, payload):
    share_id = secrets.token_urlsafe(10)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO portal_tool_shares (team_id, event_id, tool_type, share_id, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            team_id,
            event_id,
            tool_type,
            share_id,
            json.dumps(payload, ensure_ascii=False),
            portal_now_text(),
        ),
    )
    conn.commit()
    conn.close()
    return share_id


def get_portal_tool_share(share_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, team_id, event_id, tool_type, share_id, payload_json, created_at
        FROM portal_tool_shares
        WHERE share_id=?
        """,
        (share_id,),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    if not row:
        return None
    try:
        row["payload"] = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        row["payload"] = {}
    return row


def create_portal_tool_saved_result(team_id, event_id, tool_type, title, payload):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO portal_tool_saved_results (team_id, event_id, tool_type, title, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            team_id,
            event_id,
            tool_type,
            title,
            json.dumps(payload, ensure_ascii=False),
            portal_now_text(),
        ),
    )
    saved_id = c.lastrowid if not USE_POSTGRES else None
    conn.commit()
    if USE_POSTGRES and not saved_id:
        c.execute(
            """
            SELECT id
            FROM portal_tool_saved_results
            WHERE team_id=? AND event_id=? AND tool_type=? AND title=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (team_id, event_id, tool_type, title),
        )
        row = row_to_dict(c.fetchone())
        saved_id = row.get("id") if row else None
    conn.close()
    return saved_id


def get_portal_tool_saved_results(team_id, event_id, tool_type=None, limit=20):
    conn = get_db_connection()
    c = conn.cursor()
    params = [team_id, event_id]
    where_clause = "WHERE team_id=? AND event_id=?"
    if tool_type:
        where_clause += " AND tool_type=?"
        params.append(tool_type)
    params.append(limit)
    c.execute(
        f"""
        SELECT id, team_id, event_id, tool_type, title, payload_json, created_at
        FROM portal_tool_saved_results
        {where_clause}
        ORDER BY id DESC
        LIMIT ?
        """,
        params,
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    for row in rows:
        try:
            row["payload"] = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            row["payload"] = {}
    return rows


def get_portal_tool_saved_result(team_id, event_id, saved_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, team_id, event_id, tool_type, title, payload_json, created_at
        FROM portal_tool_saved_results
        WHERE team_id=? AND event_id=? AND id=?
        """,
        (team_id, event_id, saved_id),
    )
    row = row_to_dict(c.fetchone())
    conn.close()
    if not row:
        return None
    try:
        row["payload"] = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        row["payload"] = {}
    return row


def get_portal_event_join_members(team_id, event_id):
    rows = portal_get_attendance_for_event(team_id, event_id)
    join_members = []
    for row in rows:
        if normalize_status(row["status"]) == "参加":
            join_members.append(row["member_name"])
    return _normalize_name_list(join_members)


def get_portal_confirmed_attendees(team_id, event_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT member_name, source_type
        FROM portal_actual_attendees
        WHERE team_id=? AND event_id=?
        ORDER BY id ASC
        """,
        (team_id, event_id),
    )
    rows = rows_to_dict(c.fetchall())
    conn.close()
    return rows


def save_portal_confirmed_attendees(team_id, event_id, selected_names, walkin_names=None):
    selected = _normalize_name_list(selected_names)
    walkins = _normalize_name_list(walkin_names or [])
    join_names = set(get_portal_event_join_members(team_id, event_id))
    names_to_keep = _normalize_name_list(selected + walkins)

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM portal_actual_attendees WHERE team_id=? AND event_id=?", (team_id, event_id))
    for member_name in names_to_keep:
        if member_name in walkins:
            # Walk-in attendees are treated as confirmed immediately after being added.
            source_type = "walkin"
        else:
            source_type = "attendance" if member_name in join_names else "walkin"
        c.execute(
            """
            INSERT INTO portal_actual_attendees (team_id, event_id, member_name, source_type, confirmed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (team_id, event_id, member_name, source_type, portal_now_text()),
        )
    conn.commit()
    conn.close()
    portal_touch_admin_last_attendance_updated_by_team(team_id)
    return names_to_keep


def add_portal_walkin_attendee(team_id, event_id, member_name):
    target_name = (member_name or "").strip()
    if not target_name:
        return False
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO portal_actual_attendees (team_id, event_id, member_name, source_type, confirmed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(team_id, event_id, member_name)
        DO UPDATE SET source_type=excluded.source_type, confirmed_at=excluded.confirmed_at
        """,
        (team_id, event_id, target_name, "walkin", portal_now_text()),
    )
    c.execute(
        """
        INSERT INTO portal_transport_responses (
            team_id,
            event_id,
            member_name,
            transport_role,
            seats_available,
            note,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(team_id, event_id, member_name)
        DO UPDATE SET
            transport_role=excluded.transport_role,
            seats_available=excluded.seats_available,
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (team_id, event_id, target_name, TRANSPORT_ROLE_DIRECT, 0, "", portal_now_text()),
    )
    conn.commit()
    conn.close()
    portal_touch_admin_last_attendance_updated_by_team(team_id)
    return True


def remove_portal_walkin_attendee(team_id, event_id, member_name):
    target_name = (member_name or "").strip()
    if not target_name:
        return False
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        DELETE FROM portal_actual_attendees
        WHERE team_id=? AND event_id=? AND member_name=? AND source_type IN ('walkin', 'walkin_pending')
        """,
        (team_id, event_id, target_name),
    )
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    if deleted:
        portal_touch_admin_last_attendance_updated_by_team(team_id)
    return deleted


def get_portal_effective_attendees(team_id, event_id):
    confirmed_rows = get_portal_confirmed_attendees(team_id, event_id)
    if confirmed_rows:
        return _normalize_name_list([row.get("member_name") for row in confirmed_rows if row.get("source_type") != "walkin_pending"])
    return get_portal_event_join_members(team_id, event_id)


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


def get_team_members(team_id, include_inactive=False):
    return portal_get_members_for_team(team_id, include_inactive=include_inactive)


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


register_attendance_portal_routes(
    app,
    build_event_list_csv_response=build_event_list_csv_response,
    datetime=datetime,
    get_db_connection=get_db_connection,
    login_required=login_required,
)
register_admin_core_routes(
    app,
    ADMIN_FREE_TEAM_LIMIT=ADMIN_FREE_TEAM_LIMIT,
    ADMIN_PLAN_REQUESTS_ENABLED=ADMIN_PLAN_REQUESTS_ENABLED,
    PLAN_FEATURE_TEAM_CREATE=PLAN_FEATURE_TEAM_CREATE,
    admin_login_required=admin_login_required,
    build_admin_dashboard_team_guides=build_admin_dashboard_team_guides,
    can_admin_create_team=can_admin_create_team,
    get_admin_plan_type=get_admin_plan_type,
    get_plan_restriction_message=get_plan_restriction_message,
    get_teams_for_admin=get_teams_for_admin,
    is_site_admin_email=is_site_admin_email,
    portal_authenticate_admin=portal_authenticate_admin,
    portal_create_admin=portal_create_admin,
    portal_create_team=portal_create_team,
    portal_get_admin=portal_get_admin,
    portal_get_admin_by_email=portal_get_admin_by_email,
    portal_touch_admin_last_login=portal_touch_admin_last_login,
    portal_update_admin_credentials=portal_update_admin_credentials,
)
register_site_admin_routes(
    app,
    ADMIN_ACCOUNT_STATUS_ACTIVE=ADMIN_ACCOUNT_STATUS_ACTIVE,
    ADMIN_ACCOUNT_STATUS_EXPIRED=ADMIN_ACCOUNT_STATUS_EXPIRED,
    ADMIN_ACCOUNT_STATUS_SUSPENDED=ADMIN_ACCOUNT_STATUS_SUSPENDED,
    ADMIN_EXPIRY_UNLIMITED=ADMIN_EXPIRY_UNLIMITED,
    ADMIN_FREE_TEAM_LIMIT=ADMIN_FREE_TEAM_LIMIT,
    ADMIN_PLAN_FREE=ADMIN_PLAN_FREE,
    ADMIN_PLAN_PAID=ADMIN_PLAN_PAID,
    ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE=ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
    ADMIN_PLAN_REQUEST_STATUS_APPROVED=ADMIN_PLAN_REQUEST_STATUS_APPROVED,
    ADMIN_PLAN_REQUEST_STATUS_PENDING=ADMIN_PLAN_REQUEST_STATUS_PENDING,
    ADMIN_PLAN_REQUEST_STATUS_REJECTED=ADMIN_PLAN_REQUEST_STATUS_REJECTED,
    SITE_ADMIN_EMAILS=SITE_ADMIN_EMAILS,
    append_query_params=append_query_params,
    enrich_admin_billing_history_rows=enrich_admin_billing_history_rows,
    enrich_admin_plan_request_rows=enrich_admin_plan_request_rows,
    enrich_site_admin_row=enrich_site_admin_row,
    normalize_admin_account_status=normalize_admin_account_status,
    normalize_admin_plan_request_payment_method=normalize_admin_plan_request_payment_method,
    normalize_admin_plan_request_status=normalize_admin_plan_request_status,
    normalize_admin_plan_type=normalize_admin_plan_type,
    portal_force_delete_admin=portal_force_delete_admin,
    portal_get_admin=portal_get_admin,
    portal_get_admin_billing_history=portal_get_admin_billing_history,
    portal_get_admin_plan_request=portal_get_admin_plan_request,
    portal_get_admin_plan_requests=portal_get_admin_plan_requests,
    portal_get_admin_summaries=portal_get_admin_summaries,
    portal_get_team_details_for_admin=portal_get_team_details_for_admin,
    portal_review_admin_plan_request=portal_review_admin_plan_request,
    portal_set_admin_expiry=portal_set_admin_expiry,
    portal_update_admin_profile_fields=portal_update_admin_profile_fields,
    resolve_admin_expiry_datetime=resolve_admin_expiry_datetime,
    site_admin_required=site_admin_required,
)


@app.route("/dev/stripe-preview")
def dev_stripe_preview_index():
    if not local_payment_preview_allowed():
        return Response("not found", status=404, content_type="text/plain; charset=utf-8")
    return render_template(
        "dev_stripe_preview_hub.html",
        admin_preview_links=build_local_preview_admin_plan_request_context()["preview_scenario_links"],
        site_admin_preview_links=build_local_preview_site_admin_plan_requests_context()["preview_scenario_links"],
    )


@app.route("/dev/stripe-preview/admin-plan-requests")
def dev_stripe_preview_admin_plan_requests():
    if not local_payment_preview_allowed():
        return Response("not found", status=404, content_type="text/plain; charset=utf-8")
    scenario = request.args.get("scenario", "paid_unlinked")
    context = build_local_preview_admin_plan_request_context(scenario=scenario)
    return render_template("admin_plan_requests.html", **context)


@app.route("/dev/stripe-preview/site-admin-plan-requests")
def dev_stripe_preview_site_admin_plan_requests():
    if not local_payment_preview_allowed():
        return Response("not found", status=404, content_type="text/plain; charset=utf-8")
    scenario = request.args.get("scenario", "stripe_pending")
    context = build_local_preview_site_admin_plan_requests_context(scenario=scenario)
    return render_template("site_admin_plan_requests.html", **context)


@app.route("/admin/stripe/checkout", methods=["POST"])
@admin_login_required
def admin_stripe_checkout():
    admin = portal_get_admin(session["admin_id"])
    if not admin:
        session.pop("admin_id", None)
        session.pop("admin_email", None)
        session.pop("is_site_admin", None)
        return redirect(url_for("admin_login_entry"))
    if not stripe_checkout_is_configured():
        return redirect(url_for("admin_create_plan_request", error_message="Stripe設定が未完了のため決済を開始できません。"))

    request_type = normalize_admin_plan_request_type(request.form.get("request_type"))
    if not request_type:
        return redirect(url_for("admin_create_plan_request", error_message="申請種別を選択してください。"))
    try:
        payment_amount = int((request.form.get("payment_amount") or "").strip() or "0")
    except ValueError:
        return redirect(url_for("admin_create_plan_request", error_message="支払金額は整数で入力してください。"))
    if payment_amount not in ADMIN_PLAN_REQUEST_PAYMENT_AMOUNT_OPTIONS:
        return redirect(url_for("admin_create_plan_request", error_message="支払金額の選択肢が不正です。"))

    payload, create_response = stripe_create_checkout_session(admin, request_type, payment_amount)
    if create_response.get("json", {}).get("id"):
        portal_create_admin_stripe_payment(
            admin_id=admin["id"],
            request_type=request_type,
            request_amount=payment_amount,
            create_response=create_response,
        )
    redirect_url = (create_response.get("json", {}).get("url") or "").strip()
    if create_response.get("ok") and redirect_url:
        return redirect(redirect_url)
    error_object = (create_response.get("json", {}) or {}).get("error") or {}
    error_message = error_object.get("message") or "Stripe決済の開始に失敗しました。時間をおいて再度お試しください。"
    if not payload.get("success_url"):
        error_message = "Stripeの戻り先URLを生成できませんでした。STRIPE_REDIRECT_BASE_URLを確認してください。"
    return redirect(url_for("admin_create_plan_request", error_message=error_message))


@app.route("/admin/stripe/success", methods=["GET"])
def admin_stripe_success():
    checkout_session_id = request.args.get("session_id", "").strip()
    if not checkout_session_id:
        return redirect(url_for("admin_create_plan_request", error_message="Stripe決済の識別情報が不足しています。"))
    payment_row = portal_get_admin_stripe_payment_by_checkout_session_id(checkout_session_id)
    if not payment_row:
        payment_details = stripe_get_checkout_session(checkout_session_id)
        payment_row = portal_ensure_admin_stripe_payment_from_remote(checkout_session_id, payment_details=payment_details)
    if not payment_row:
        return redirect(url_for("admin_create_plan_request", error_message="Stripe決済情報が見つかりません。"))

    updated_payment, payment_details, auto_apply_result = sync_admin_stripe_payment_with_stripe(
        checkout_session_id,
        mark_returned=True,
        applied_via="success",
    )
    if "admin_id" not in session or int(session.get("admin_id") or 0) != int(payment_row.get("admin_id") or 0):
        return redirect(url_for("admin_login_entry", next=url_for("admin_create_plan_request")))

    status = (updated_payment or {}).get("status") or ""
    if status == ADMIN_STRIPE_STATUS_COMPLETED:
        if not auto_apply_result.get("ok"):
            error_message = "Stripe決済の完了は確認できましたが、有料プラン反映に失敗しました。時間をおいて再確認してください。"
            if auto_apply_result.get("status") == "linked_plan_request_rejected":
                error_message = "紐付いた旧申請が却下済みのため、自動反映できませんでした。"
            return redirect(url_for("admin_create_plan_request", error_message=error_message))
        return redirect(
            url_for(
                "admin_create_plan_request",
                success_message="Stripe決済を確認し、有料プランへ反映しました。",
            )
        )
    error_object = (payment_details.get("json", {}) or {}).get("error") or {}
    error_message = error_object.get("message") or "Stripe決済の完了を確認できませんでした。時間をおいて再確認してください。"
    if status == ADMIN_STRIPE_STATUS_CANCELED:
        error_message = "Stripe決済はキャンセルされました。"
    elif status == ADMIN_STRIPE_STATUS_FAILED:
        error_message = "Stripe決済は失敗しました。"
    elif status == ADMIN_STRIPE_STATUS_EXPIRED:
        error_message = "Stripe決済の有効期限が切れました。"
    elif status in {ADMIN_STRIPE_STATUS_RETURNED, ADMIN_STRIPE_STATUS_UNKNOWN, ADMIN_STRIPE_STATUS_OPEN}:
        error_message = "Stripe決済は確認中です。必要に応じて再確認してください。"
    return redirect(url_for("admin_create_plan_request", error_message=error_message))


@app.route("/admin/stripe/payments/<checkout_session_id>/refresh", methods=["POST"])
@admin_login_required
def admin_refresh_stripe_payment(checkout_session_id):
    redirect_target = request.referrer or url_for("admin_create_plan_request")
    payment_row = portal_get_admin_stripe_payment_by_checkout_session_id(checkout_session_id)
    if not payment_row:
        return redirect(append_query_params(redirect_target, error_message="対象のStripe決済が見つかりません。"))
    is_owner = int(payment_row.get("admin_id") or 0) == int(session.get("admin_id") or 0)
    if not is_owner and not session.get("is_site_admin"):
        return redirect(append_query_params(redirect_target, error_message="他の管理者のStripe決済は確認できません。"))

    updated_payment, _payment_details, auto_apply_result = sync_admin_stripe_payment_with_stripe(
        checkout_session_id,
        applied_via="manual_refresh",
    )
    if updated_payment:
        success_message = "Stripe決済状態を更新しました。"
        if (updated_payment.get("status") == ADMIN_STRIPE_STATUS_COMPLETED) and auto_apply_result.get("ok"):
            success_message = "Stripe決済状態を更新し、有料プラン反映まで完了しました。"
        elif (updated_payment.get("status") == ADMIN_STRIPE_STATUS_COMPLETED) and not auto_apply_result.get("ok"):
            return redirect(
                append_query_params(
                    redirect_target,
                    error_message="Stripe決済完了は確認できましたが、有料プラン反映に失敗しました。",
                )
            )
        return redirect(append_query_params(redirect_target, success_message=success_message))
    return redirect(append_query_params(redirect_target, error_message="Stripe決済状態を更新できませんでした。"))


@app.route("/stripe/webhooks", methods=["POST"])
def stripe_webhook():
    payload_text = request.get_data(cache=False, as_text=True) or ""
    if not stripe_verify_webhook_signature(payload_text, request.headers.get("Stripe-Signature", "")):
        return Response("forbidden", status=403, content_type="text/plain; charset=utf-8")
    try:
        payload = json.loads(payload_text) if payload_text else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        return Response("ok", status=200, content_type="text/plain; charset=utf-8")
    event_id = (payload.get("id") or "").strip()
    event_type = (payload.get("type") or "").strip()
    event_object = ((payload.get("data") or {}).get("object") or {})
    if not isinstance(event_object, dict):
        event_object = {}
    checkout_session_id = (event_object.get("id") or "").strip() if event_type.startswith("checkout.session.") else ""
    payment_intent_id = ""
    if event_type.startswith("payment_intent."):
        payment_intent_id = (event_object.get("id") or "").strip()
    elif event_type.startswith("checkout.session."):
        payment_intent_value = event_object.get("payment_intent")
        if isinstance(payment_intent_value, dict):
            payment_intent_id = (payment_intent_value.get("id") or "").strip()
        else:
            payment_intent_id = (payment_intent_value or "").strip()
    if event_id:
        existing_event = portal_get_stripe_webhook_event(event_id)
        if existing_event and existing_event.get("processing_status") in {"processed", "ignored", "duplicate"}:
            return Response("ok", status=200, content_type="text/plain; charset=utf-8")
        if not existing_event:
            try:
                portal_create_stripe_webhook_event(
                    event_id,
                    event_type or "unknown",
                    checkout_session_id=checkout_session_id,
                    payment_intent_id=payment_intent_id,
                    payload_text=payload_text,
                )
            except DatabaseError:
                existing_event = portal_get_stripe_webhook_event(event_id)
                if existing_event:
                    return Response("ok", status=200, content_type="text/plain; charset=utf-8")
    if not event_type.startswith("checkout.session.") and not event_type.startswith("payment_intent."):
        if event_id:
            portal_update_stripe_webhook_event(
                event_id,
                "ignored",
                checkout_session_id=checkout_session_id,
                payment_intent_id=payment_intent_id,
            )
        return Response("ok", status=200, content_type="text/plain; charset=utf-8")
    payment_row = None
    if checkout_session_id:
        payment_row = portal_get_admin_stripe_payment_by_checkout_session_id(checkout_session_id)
    if not payment_row and payment_intent_id:
        payment_row = portal_get_admin_stripe_payment_by_payment_intent_id(payment_intent_id)
        if payment_row:
            checkout_session_id = (payment_row.get("stripe_checkout_session_id") or "").strip()
    if not payment_row:
        payment_details = stripe_get_checkout_session(checkout_session_id) if checkout_session_id else {}
        payment_row = portal_ensure_admin_stripe_payment_from_remote(checkout_session_id, payment_details=payment_details)
    if not payment_row:
        if event_id:
            portal_update_stripe_webhook_event(
                event_id,
                "ignored",
                error_message="payment_not_found",
                checkout_session_id=checkout_session_id,
                payment_intent_id=payment_intent_id,
            )
        return Response("ok", status=200, content_type="text/plain; charset=utf-8")

    payment_details = stripe_get_checkout_session(checkout_session_id)
    error_object = (payment_details.get("json", {}) or {}).get("error") or {}
    updated_payment = portal_update_admin_stripe_payment_from_remote(
        checkout_session_id,
        payment_details=payment_details if payment_details.get("json") else None,
        webhook_payload=payload,
        error_code=error_object.get("code") or payment_details.get("error") or "",
        error_message=error_object.get("message") or "",
    )
    auto_apply_ok = True
    auto_apply_status = "not_attempted"
    if updated_payment and updated_payment.get("status") == ADMIN_STRIPE_STATUS_COMPLETED:
        auto_apply_ok, auto_apply_status, updated_payment = portal_auto_apply_completed_admin_stripe_payment(
            updated_payment.get("id"),
            applied_via="webhook",
        )
    if updated_payment and updated_payment.get("linked_plan_request_id"):
        portal_sync_plan_request_verification_with_payment(
            updated_payment.get("linked_plan_request_id"),
            ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
            updated_payment.get("status"),
            payment_date=updated_payment.get("stripe_paid_at") or "",
            payment_reference=updated_payment.get("payment_reference") or stripe_extract_reference(updated_payment),
        )
    if updated_payment and updated_payment.get("status") == ADMIN_STRIPE_STATUS_COMPLETED and not auto_apply_ok:
        if event_id:
            portal_update_stripe_webhook_event(
                event_id,
                "failed",
                error_message=auto_apply_status,
                checkout_session_id=checkout_session_id,
                payment_intent_id=payment_intent_id,
            )
        return Response("retry", status=500, content_type="text/plain; charset=utf-8")
    if event_id:
        portal_update_stripe_webhook_event(
            event_id,
            "processed",
            error_message=error_object.get("message") or "",
            checkout_session_id=checkout_session_id,
            payment_intent_id=payment_intent_id,
        )
    return Response("ok", status=200, content_type="text/plain; charset=utf-8")


@app.route("/admin/plan-requests", methods=["GET", "POST"])
@admin_login_required
def admin_create_plan_request():
    admin = portal_get_admin(session["admin_id"])
    if not admin:
        session.pop("admin_id", None)
        session.pop("admin_email", None)
        return redirect(url_for("admin_login_entry"))

    if not ADMIN_PLAN_REQUESTS_ENABLED:
        return redirect(url_for("admin_dashboard", error_message="有料プラン申請は現在準備中です。"))

    if request.method == "GET":
        context = build_admin_plan_request_page_context(admin)
        context["error_message"] = request.args.get("error_message", "").strip()
        context["success_message"] = request.args.get("success_message", "").strip()
        return render_template("admin_plan_requests.html", **context)
    return redirect(
        url_for(
            "admin_create_plan_request",
            error_message="申請送信フローは廃止されました。Stripe APIで支払い完了を確認できた決済は自動で有料プランへ反映されます。",
        )
    )


@app.route("/admin/account/delete", methods=["POST"])
@admin_login_required
def admin_delete_account():
    current_password = request.form.get("current_password", "")
    deleted, status = portal_delete_admin(session["admin_id"], current_password)

    if deleted:
        session.pop("admin_id", None)
        session.pop("admin_email", None)
        session.pop("is_site_admin", None)
        return redirect(url_for("admin_login_entry"))

    if status == "invalid_password":
        return redirect(
            url_for(
                "admin_account_settings",
                error_message="現在のパスワードが正しくありません。",
            )
        )
    return redirect(
        url_for(
            "admin_account_settings",
            error_message="管理者アカウントを削除できませんでした。",
        )
    )


@app.route("/admin/teams/<int:team_id>/delete", methods=["POST"])
@admin_login_required
def admin_delete_team(team_id):
    if portal_delete_team(session["admin_id"], team_id):
        return redirect(url_for("admin_dashboard", success_message="チームを削除しました。"))
    return redirect(url_for("admin_dashboard", error_message="チームを削除できませんでした。"))


def serialize_member_for_api(member):
    if not member:
        return None
    return {
        "id": member.get("id"),
        "team_id": member.get("team_id"),
        "display_name": member.get("name"),
        "name": member.get("name"),
        "display_order": member.get("display_order"),
        "note": member.get("note") or "",
        "is_active": bool(member.get("is_active")),
        "created_at": member.get("created_at"),
        "updated_at": member.get("updated_at"),
    }


def serialize_collection_member_for_api(member_row):
    if not member_row:
        return None
    status = normalize_collection_status(member_row.get("status")) or COLLECTION_STATUS_PENDING
    display_name = member_row.get("current_member_name") or member_row.get("member_name") or ""
    return {
        "member_id": member_row.get("member_id"),
        "member_name": display_name,
        "member_name_snapshot": member_row.get("member_name") or "",
        "status": status,
        "status_label": COLLECTION_STATUS_LABELS.get(status, COLLECTION_STATUS_LABELS[COLLECTION_STATUS_PENDING]),
        "collected_at": member_row.get("collected_at") or "",
        "collected_at_label": format_collection_collected_at(member_row.get("collected_at")),
        "is_active": bool(member_row.get("current_member_is_active")) if member_row.get("current_member_is_active") is not None else True,
    }


def serialize_collection_event_for_list(collection_event, member_rows):
    summary = build_collection_event_summary(collection_event, member_rows)
    return {
        "id": collection_event.get("id"),
        "team_id": collection_event.get("team_id"),
        "title": collection_event.get("title") or "",
        "collection_date": collection_event.get("collection_date") or "",
        "collection_date_label": format_date_mmdd_with_weekday(collection_event.get("collection_date") or ""),
        "amount": int(collection_event.get("amount") or 0),
        "amount_label": format_currency_yen(collection_event.get("amount") or 0),
        "note": collection_event.get("note") or "",
        "target_mode": collection_event.get("target_mode") or "manual",
        "summary": summary,
        "summary_labels": {
            "target_count": summary["target_count"],
            "collected_count": summary["collected_count"],
            "pending_count": summary["pending_count"],
            "exempt_count": summary["exempt_count"],
            "collected_total": format_currency_yen(summary["collected_total"]),
            "pending_total": format_currency_yen(summary["pending_total"]),
        },
    }


register_admin_team_member_routes(
    app,
    ADMIN_MEMBER_ANALYTICS_TABS=ADMIN_MEMBER_ANALYTICS_TABS,
    _coerce_positive_int=_coerce_positive_int,
    admin_api_required=admin_api_required,
    admin_login_required=admin_login_required,
    build_admin_member_analytics=build_admin_member_analytics,
    build_admin_member_analytics_csv_response=build_admin_member_analytics_csv_response,
    get_owned_team_or_error=get_owned_team_or_error,
    normalize_admin_member_analytics_tab=normalize_admin_member_analytics_tab,
    parse_boolean_input=parse_boolean_input,
    portal_add_member=portal_add_member,
    portal_delete_member_by_id=portal_delete_member_by_id,
    portal_get_member=portal_get_member,
    portal_get_members_for_team=portal_get_members_for_team,
    portal_reorder_members=portal_reorder_members,
    portal_update_member=portal_update_member,
    resolve_member_analytics_period=resolve_member_analytics_period,
    serialize_member_for_api=serialize_member_for_api,
)
register_admin_team_event_routes(
    app,
    _coerce_positive_int=_coerce_positive_int,
    admin_login_required=admin_login_required,
    build_time_from_form=build_time_from_form,
    format_date_mmdd_with_weekday=format_date_mmdd_with_weekday,
    get_owned_team_or_error=get_owned_team_or_error,
    is_valid_10min_time=is_valid_10min_time,
    portal_create_event=portal_create_event,
    portal_delete_event=portal_delete_event,
    portal_duplicate_event=portal_duplicate_event,
    portal_get_event=portal_get_event,
    portal_get_events=portal_get_events,
    portal_update_event=portal_update_event,
)
register_admin_team_collection_routes(
    app,
    _coerce_positive_int=_coerce_positive_int,
    admin_api_required=admin_api_required,
    admin_login_required=admin_login_required,
    build_collection_event_summary=build_collection_event_summary,
    format_currency_yen=format_currency_yen,
    get_owned_team_or_error=get_owned_team_or_error,
    normalize_collection_status=normalize_collection_status,
    portal_build_collection_list_csv_response=portal_build_collection_list_csv_response,
    portal_create_collection_event=portal_create_collection_event,
    portal_delete_collection_event=portal_delete_collection_event,
    portal_duplicate_collection_event=portal_duplicate_collection_event,
    portal_get_collection_event=portal_get_collection_event,
    portal_get_collection_event_members=portal_get_collection_event_members,
    portal_get_collection_events=portal_get_collection_events,
    portal_get_members_for_team=portal_get_members_for_team,
    portal_update_collection_event=portal_update_collection_event,
    portal_update_collection_member_status=portal_update_collection_member_status,
    serialize_collection_event_for_list=serialize_collection_event_for_list,
    serialize_collection_member_for_api=serialize_collection_member_for_api,
)
register_public_team_core_routes(
    app,
    PLAN_FEATURE_ATTENDANCE_CHECK=PLAN_FEATURE_ATTENDANCE_CHECK,
    PLAN_FEATURE_CSV_EXPORT=PLAN_FEATURE_CSV_EXPORT,
    _normalize_name_list=_normalize_name_list,
    build_member_legacy_index_context=build_member_legacy_index_context,
    build_member_page_notice_redirect=build_member_page_notice_redirect,
    can_team_use_paid_feature=can_team_use_paid_feature,
    get_plan_restriction_message=get_plan_restriction_message,
    get_team_by_public_id=get_team_by_public_id,
    normalize_status=normalize_status,
    portal_build_event_list_csv_response=portal_build_event_list_csv_response,
    portal_get_event=portal_get_event,
    portal_get_attendance=portal_get_attendance,
    portal_get_events=portal_get_events,
    portal_get_members_for_team=portal_get_members_for_team,
    portal_upsert_attendance=portal_upsert_attendance,
    redirect_to_team_month=redirect_to_team_month,
)
register_public_attendance_tool_routes(
    app,
    PLAN_FEATURE_ATTENDANCE_CHECK=PLAN_FEATURE_ATTENDANCE_CHECK,
    PLAN_FEATURE_RANDOM_PICK=PLAN_FEATURE_RANDOM_PICK,
    PLAN_FEATURE_TEAM_SPLIT=PLAN_FEATURE_TEAM_SPLIT,
    TRANSPORT_ROLE_DIRECT=TRANSPORT_ROLE_DIRECT,
    TRANSPORT_ROLE_DRIVER=TRANSPORT_ROLE_DRIVER,
    TRANSPORT_ROLE_LABELS=TRANSPORT_ROLE_LABELS,
    TRANSPORT_ROLE_NONE=TRANSPORT_ROLE_NONE,
    TRANSPORT_ROLE_PASSENGER=TRANSPORT_ROLE_PASSENGER,
    _coerce_positive_int=_coerce_positive_int,
    _coerce_team_count=_coerce_team_count,
    _normalize_name_list=_normalize_name_list,
    add_portal_walkin_attendee=add_portal_walkin_attendee,
    build_member_page_notice_redirect=build_member_page_notice_redirect,
    build_portal_transport_overview=build_portal_transport_overview,
    build_team_allocator=build_team_allocator,
    can_team_use_paid_feature=can_team_use_paid_feature,
    create_portal_tool_saved_result=create_portal_tool_saved_result,
    create_portal_tool_share=create_portal_tool_share,
    format_date_mmdd_with_weekday=format_date_mmdd_with_weekday,
    get_plan_restriction_message=get_plan_restriction_message,
    get_portal_confirmed_attendees=get_portal_confirmed_attendees,
    get_portal_effective_attendees=get_portal_effective_attendees,
    get_portal_tool_saved_result=get_portal_tool_saved_result,
    get_portal_tool_saved_results=get_portal_tool_saved_results,
    get_portal_tool_share=get_portal_tool_share,
    get_team_by_public_id=get_team_by_public_id,
    normalize_status=normalize_status,
    normalize_transport_role=normalize_transport_role,
    parse_random_pick_names=parse_random_pick_names,
    parse_team_state_from_form=parse_team_state_from_form,
    portal_get_all_transport_responses_for_event=portal_get_all_transport_responses_for_event,
    portal_get_attendance_for_event=portal_get_attendance_for_event,
    portal_get_event=portal_get_event,
    portal_get_members_for_team=portal_get_members_for_team,
    portal_prune_transport_assignments=portal_prune_transport_assignments,
    portal_replace_transport_responses=portal_replace_transport_responses,
    portal_replace_transport_responses_for_attendees=portal_replace_transport_responses_for_attendees,
    portal_save_transport_assignments=portal_save_transport_assignments,
    remove_portal_walkin_attendee=remove_portal_walkin_attendee,
    save_portal_confirmed_attendees=save_portal_confirmed_attendees,
    serialize_team_result=serialize_team_result,
    swap_members_in_teams=swap_members_in_teams,
)
register_legacy_attendance_routes(
    app,
    _coerce_positive_int=_coerce_positive_int,
    _coerce_team_count=_coerce_team_count,
    _normalize_name_list=_normalize_name_list,
    add_walkin_attendee=add_walkin_attendee,
    build_team_allocator=build_team_allocator,
    build_time_from_form=build_time_from_form,
    create_attendance_tool_saved_result=create_attendance_tool_saved_result,
    create_attendance_tool_share=create_attendance_tool_share,
    format_date_mmdd_with_weekday=format_date_mmdd_with_weekday,
    get_attendance_tool_saved_result=get_attendance_tool_saved_result,
    get_attendance_tool_saved_results=get_attendance_tool_saved_results,
    get_confirmed_attendees=get_confirmed_attendees,
    get_db_connection=get_db_connection,
    get_effective_attendees=get_effective_attendees,
    is_valid_10min_time=is_valid_10min_time,
    login_required=login_required,
    normalize_status=normalize_status,
    parse_random_pick_names=parse_random_pick_names,
    parse_team_state_from_form=parse_team_state_from_form,
    redirect_to_app_with_month=redirect_to_app_with_month,
    remove_walkin_attendee=remove_walkin_attendee,
    save_confirmed_attendees=save_confirmed_attendees,
    serialize_team_result=serialize_team_result,
    swap_members_in_teams=swap_members_in_teams,
)


@app.route("/")
def home():
    return redirect(url_for("admin_login_entry"))


@app.route("/apps/attendance/app/description")
def attendance_description():
    return render_template("landing.html")


def ensure_app_initialized():
    global _APP_INITIALIZED
    if _APP_INITIALIZED:
        return app

    try:
        init_db()
        if PORTAL_JSON_MIGRATION_ENABLED:
            migrate_portal_json_to_db()
        bootstrap_admin_from_env()
    except DatabaseError:
        app.logger.exception("Database initialization failed.")
        if RENDER_ENV:
            raise

    _APP_INITIALIZED = True
    return app


def create_app():
    return ensure_app_initialized()


ensure_app_initialized()


if __name__ == "__main__":
    app.run(debug=True)
