import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def patch_sqlite_connect():
    real_connect = sqlite3.connect

    def patched_connect(database, *args, **kwargs):
        if isinstance(database, str) and database.startswith("file:"):
            kwargs.setdefault("uri", True)
        return real_connect(database, *args, **kwargs)

    sqlite3.connect = patched_connect


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r} actual={actual!r}")


def main():
    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))
    patch_sqlite_connect()
    os.environ["SQLITE_DB_PATH"] = "file:codex_memdb_auto_apply?mode=memory&cache=shared"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    keeper = sqlite3.connect(os.environ["SQLITE_DB_PATH"])
    import app  # noqa: PLC0415

    cur = keeper.cursor()
    now = datetime.now().replace(microsecond=0)
    created_at = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    initial_expiry = (now + timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    expected_expiry = (now + timedelta(days=70)).strftime("%Y-%m-%d %H:%M:%S")
    paid_at = now.strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        INSERT INTO admins (
            id, email, password_hash, created_at, expires_at,
            status, plan_type, account_status, billing_status,
            total_billing_amount, billing_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "admin@example.com",
            "",
            created_at,
            initial_expiry,
            app.ADMIN_STATUS_FREE,
            app.ADMIN_PLAN_FREE,
            app.ADMIN_ACCOUNT_STATUS_ACTIVE,
            app.ADMIN_BILLING_STATUS_UNPAID,
            0,
            0,
        ),
    )
    cur.execute(
        """
        INSERT INTO admin_stripe_payments (
            id, admin_id, stripe_checkout_session_id, stripe_payment_intent_id,
            request_type, request_amount, currency, checkout_url,
            status, stripe_status, stripe_payment_status,
            payment_reference, stripe_paid_at, requested_at, confirmed_at,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            1,
            "cs_test_auto",
            "pi_test_auto",
            app.ADMIN_PLAN_REQUEST_TYPE_PAID_30_DAYS,
            1000,
            "JPY",
            "",
            app.ADMIN_STRIPE_STATUS_COMPLETED,
            "complete",
            "paid",
            "cs_test_auto / pi:pi_test_auto",
            paid_at,
            paid_at,
            paid_at,
            paid_at,
            paid_at,
        ),
    )
    keeper.commit()

    first_ok, first_status, _first_payment = app.portal_auto_apply_completed_admin_stripe_payment(
        1,
        applied_via="success",
    )
    second_ok, second_status, _second_payment = app.portal_auto_apply_completed_admin_stripe_payment(
        1,
        applied_via="manual_refresh",
    )

    admin_row = app.portal_get_admin(1)
    billing_rows = app.portal_get_admin_billing_history(1, limit=10)
    plan_requests = app.portal_get_admin_plan_request_history(1, limit=10)
    payment_row = app.portal_get_admin_stripe_payment(1)

    assert_equal(first_ok, True, "first apply ok")
    assert_equal(first_status, "applied", "first apply status")
    assert_equal(second_ok, True, "second apply ok")
    assert_equal(second_status, "already_applied", "second apply status")
    assert_equal(admin_row.get("plan_type"), app.ADMIN_PLAN_PAID, "admin plan_type")
    assert_equal(admin_row.get("billing_status"), app.ADMIN_BILLING_STATUS_PAID, "admin billing_status")
    assert_equal(int(admin_row.get("billing_count") or 0), 1, "admin billing_count")
    assert_equal(int(admin_row.get("total_billing_amount") or 0), 1000, "admin total_billing_amount")
    assert_equal(admin_row.get("expires_at"), expected_expiry, "admin expires_at")
    assert_equal(len(billing_rows), 1, "billing history rows")
    assert_equal(len(plan_requests), 1, "plan request rows")
    assert_equal(plan_requests[0].get("status"), app.ADMIN_PLAN_REQUEST_STATUS_APPROVED, "plan request status")
    assert_equal(bool(payment_row.get("applied_at")), True, "payment applied_at present")
    assert_equal(int(payment_row.get("applied_billing_history_id") or 0), 1, "payment applied billing history id")

    print("PASS: stripe auto-apply flow")
    print(f"PASS: first apply status = {first_status}")
    print(f"PASS: second apply status = {second_status}")
    print(f"PASS: expires_at = {admin_row.get('expires_at')}")
    print(f"PASS: billing_count = {admin_row.get('billing_count')}")
    print(f"PASS: billing_rows = {len(billing_rows)}")
    print(f"PASS: plan_request_rows = {len(plan_requests)}")

    keeper.close()


if __name__ == "__main__":
    main()
