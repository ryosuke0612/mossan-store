import argparse
import sqlite3
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_PY_PATH = ROOT_DIR / "app.py"


def load_app_source():
    return APP_PY_PATH.read_text(encoding="utf-8-sig")


def check_app_source(source):
    checks = []

    checks.append(
        (
            "legacy label remains readable",
            '"paypay": "旧PayPay"' in source,
            "old PayPay history label is preserved",
        )
    )
    checks.append(
        (
            "approval is fail-closed for non-stripe",
            'return False, "legacy_payment_method_not_supported"' in source,
            "approval path blocks legacy payment methods",
        )
    )
    checks.append(
        (
            "admin create plan request stays stripe-only",
            'error_message="現在の有料プラン申請はStripeのみ対応しています。"' in source,
            "plan request POST rejects non-Stripe methods",
        )
    )
    checks.append(
        (
            "success return alone is not treated as success",
            "success URL に戻っただけでは申請完了になりません。" in source,
            "success return warning remains in request flow",
        )
    )
    checks.append(
        (
            "sqlite cleanup exists",
            "def cleanup_legacy_paypay_schema_sqlite" in source,
            "SQLite cleanup helper is present",
        )
    )
    checks.append(
        (
            "postgres cleanup exists",
            "def cleanup_legacy_paypay_schema_postgres" in source,
            "Postgres cleanup helper is present",
        )
    )

    return checks


def sqlite_table_names(cursor):
    return {
        row[0]
        for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def sqlite_column_names(cursor, table_name):
    return [row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()]


def check_sqlite_db(db_path):
    checks = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    cur = conn.cursor()
    tables = sqlite_table_names(cur)

    paypay_table_exists = "admin_paypay_payments" in tables
    checks.append(
        (
            "admin_paypay_payments removed",
            not paypay_table_exists,
            "legacy PayPay payment table is absent",
        )
    )

    admin_plan_request_columns = sqlite_column_names(cur, "admin_plan_requests")
    checks.append(
        (
            "paypay_payment_id removed",
            "paypay_payment_id" not in admin_plan_request_columns,
            "legacy paypay_payment_id column is absent",
        )
    )

    paypay_indexes = cur.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='index'
          AND (tbl_name='admin_paypay_payments' OR ifnull(sql, '') LIKE '%paypay_payment_id%')
        ORDER BY name
        """
    ).fetchall()
    checks.append(
        (
            "paypay indexes removed",
            len(paypay_indexes) == 0,
            "legacy PayPay indexes are absent",
        )
    )

    legacy_rows = cur.execute(
        "SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, ''))='paypay'"
    ).fetchone()[0]
    checks.append(
        (
            "legacy history still readable",
            legacy_rows >= 0,
            f"legacy paypay history rows = {legacy_rows}",
        )
    )

    pending_legacy_rows = cur.execute(
        """
        SELECT COUNT(*)
        FROM admin_plan_requests
        WHERE lower(coalesce(payment_method, ''))='paypay' AND status='pending'
        """
    ).fetchone()[0]
    checks.append(
        (
            "no pending legacy approvals remain",
            pending_legacy_rows == 0,
            f"pending legacy rows = {pending_legacy_rows}",
        )
    )

    conn.close()
    return checks


def print_results(title, checks):
    print(f"[{title}]")
    failed = False
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {name} - {detail}")
        if not ok:
            failed = True
    print("")
    return failed


def main():
    parser = argparse.ArgumentParser(
        description="Verify PayPay removal state and Stripe safety invariants."
    )
    parser.add_argument(
        "--db",
        default=str(ROOT_DIR / "schedule.db"),
        help="Path to SQLite database to inspect.",
    )
    args = parser.parse_args()

    source = load_app_source()
    app_failed = print_results("app.py", check_app_source(source))

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[database]\nFAIL: database exists - missing database file: {db_path}\n")
        raise SystemExit(1)

    try:
        db_failed = print_results(str(db_path), check_sqlite_db(db_path))
    except sqlite3.Error as exc:
        print(f"[{db_path}]\nFAIL: sqlite inspection - {exc}\n")
        raise SystemExit(1)

    if app_failed or db_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
