param(
    [string]$DbPath = "schedule.db",
    [string]$AdminEmail = "",
    [Nullable[int]]$AdminId = $null,
    [Nullable[int]]$StripePaymentId = $null,
    [Nullable[int]]$PlanRequestId = $null
)

$pythonScript = @'
import sqlite3
import sys
from pathlib import Path


def print_section(title, columns, rows):
    print(f"=== {title} ===")
    print("\t".join(columns))
    if not rows:
        print("(no rows)")
        print("")
        return
    for row in rows:
        print("\t".join("" if value is None else str(value) for value in row))
    print("")


args = list(sys.argv[1:])
while len(args) < 5:
    args.append("")

db_path = Path(args[0])
admin_email = args[1]
admin_id = int(args[2]) if args[2] else None
stripe_payment_id = int(args[3]) if args[3] else None
plan_request_id = int(args[4]) if args[4] else None

conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
cur = conn.cursor()

if admin_email or admin_id is not None:
    if admin_email and admin_id is not None:
        rows = cur.execute(
            """
            SELECT id, email, plan_type, account_status, billing_status, expires_at,
                   total_billing_amount, billing_count, last_billed_at
            FROM admins
            WHERE email = ? OR id = ?
            ORDER BY id
            """,
            (admin_email, admin_id),
        ).fetchall()
    elif admin_email:
        rows = cur.execute(
            """
            SELECT id, email, plan_type, account_status, billing_status, expires_at,
                   total_billing_amount, billing_count, last_billed_at
            FROM admins
            WHERE email = ?
            ORDER BY id
            """,
            (admin_email,),
        ).fetchall()
    else:
        rows = cur.execute(
            """
            SELECT id, email, plan_type, account_status, billing_status, expires_at,
                   total_billing_amount, billing_count, last_billed_at
            FROM admins
            WHERE id = ?
            ORDER BY id
            """,
            (admin_id,),
        ).fetchall()
else:
    rows = []

print_section(
    "Admin Lookup",
    [
        "id",
        "email",
        "plan_type",
        "account_status",
        "billing_status",
        "expires_at",
        "total_billing_amount",
        "billing_count",
        "last_billed_at",
    ],
    rows,
)

if admin_id is not None:
    rows = cur.execute(
        """
        SELECT id, admin_id, stripe_checkout_session_id, stripe_payment_intent_id, request_type,
               request_amount, status, stripe_status, stripe_payment_status, payment_reference,
               stripe_paid_at, requested_at, returned_at, confirmed_at, last_checked_at,
               linked_plan_request_id, last_error_code, last_error_message, created_at, updated_at
        FROM admin_stripe_payments
        WHERE admin_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (admin_id,),
    ).fetchall()
else:
    rows = []

print_section(
    "Stripe Payments",
    [
        "id",
        "admin_id",
        "stripe_checkout_session_id",
        "stripe_payment_intent_id",
        "request_type",
        "request_amount",
        "status",
        "stripe_status",
        "stripe_payment_status",
        "payment_reference",
        "stripe_paid_at",
        "requested_at",
        "returned_at",
        "confirmed_at",
        "last_checked_at",
        "linked_plan_request_id",
        "last_error_code",
        "last_error_message",
        "created_at",
        "updated_at",
    ],
    rows,
)

if stripe_payment_id is not None:
    rows = cur.execute(
        """
        SELECT id, admin_id, status, stripe_status, stripe_payment_status, payment_reference,
               stripe_paid_at, requested_at, returned_at, confirmed_at, last_checked_at,
               linked_plan_request_id, last_error_code, last_error_message, created_at, updated_at
        FROM admin_stripe_payments
        WHERE id = ?
        """,
        (stripe_payment_id,),
    ).fetchall()
else:
    rows = []

print_section(
    "Target Stripe Payment",
    [
        "id",
        "admin_id",
        "status",
        "stripe_status",
        "stripe_payment_status",
        "payment_reference",
        "stripe_paid_at",
        "requested_at",
        "returned_at",
        "confirmed_at",
        "last_checked_at",
        "linked_plan_request_id",
        "last_error_code",
        "last_error_message",
        "created_at",
        "updated_at",
    ],
    rows,
)

if admin_id is not None:
    rows = cur.execute(
        """
        SELECT apr.id, apr.admin_id, apr.request_type, apr.payment_method, apr.payment_amount,
               apr.payment_date, apr.payment_reference, apr.status, apr.reviewed_by_admin_id,
               apr.reviewed_at, apr.stripe_payment_id, apr.payment_verification_status,
               apr.payment_verified_at, apr.created_at, apr.updated_at,
               asp.status AS stripe_row_status, asp.last_checked_at, asp.linked_plan_request_id
        FROM admin_plan_requests apr
        LEFT JOIN admin_stripe_payments asp ON asp.id = apr.stripe_payment_id
        WHERE apr.admin_id = ?
        ORDER BY apr.id DESC
        LIMIT 20
        """,
        (admin_id,),
    ).fetchall()
else:
    rows = []

print_section(
    "Plan Requests",
    [
        "id",
        "admin_id",
        "request_type",
        "payment_method",
        "payment_amount",
        "payment_date",
        "payment_reference",
        "status",
        "reviewed_by_admin_id",
        "reviewed_at",
        "stripe_payment_id",
        "payment_verification_status",
        "payment_verified_at",
        "created_at",
        "updated_at",
        "stripe_row_status",
        "last_checked_at",
        "linked_plan_request_id",
    ],
    rows,
)

if plan_request_id is not None:
    rows = cur.execute(
        """
        SELECT apr.id, apr.admin_id, apr.request_type, apr.payment_method, apr.payment_amount,
               apr.payment_date, apr.payment_reference, apr.status, apr.reviewed_by_admin_id,
               apr.reviewed_at, apr.stripe_payment_id, apr.payment_verification_status,
               apr.payment_verified_at, apr.created_at, apr.updated_at,
               asp.status AS stripe_row_status, asp.stripe_status, asp.stripe_payment_status,
               asp.last_checked_at, asp.linked_plan_request_id
        FROM admin_plan_requests apr
        LEFT JOIN admin_stripe_payments asp ON asp.id = apr.stripe_payment_id
        WHERE apr.id = ?
        """,
        (plan_request_id,),
    ).fetchall()
else:
    rows = []

print_section(
    "Target Plan Request",
    [
        "id",
        "admin_id",
        "request_type",
        "payment_method",
        "payment_amount",
        "payment_date",
        "payment_reference",
        "status",
        "reviewed_by_admin_id",
        "reviewed_at",
        "stripe_payment_id",
        "payment_verification_status",
        "payment_verified_at",
        "created_at",
        "updated_at",
        "stripe_row_status",
        "stripe_status",
        "stripe_payment_status",
        "last_checked_at",
        "linked_plan_request_id",
    ],
    rows,
)

if admin_id is not None:
    rows = cur.execute(
        """
        SELECT id, admin_id, billing_status, billed_at, amount, total_amount,
               billing_count, note, created_at
        FROM admin_billing_history
        WHERE admin_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (admin_id,),
    ).fetchall()
else:
    rows = []

print_section(
    "Billing History",
    [
        "id",
        "admin_id",
        "billing_status",
        "billed_at",
        "amount",
        "total_amount",
        "billing_count",
        "note",
        "created_at",
    ],
    rows,
)

rows = cur.execute(
    """
    SELECT id, admin_id, payment_method, status, payment_amount, payment_date,
           payment_reference, created_at
    FROM admin_plan_requests
    WHERE lower(coalesce(payment_method, '')) = 'paypay'
    ORDER BY id DESC
    """
).fetchall()

print_section(
    "Legacy PayPay History",
    [
        "id",
        "admin_id",
        "payment_method",
        "status",
        "payment_amount",
        "payment_date",
        "payment_reference",
        "created_at",
    ],
    rows,
)

summary = cur.execute(
    """
    SELECT
        (SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, '')) = 'paypay'),
        (SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, '')) = 'paypay' AND status = 'pending'),
        (SELECT COUNT(*) FROM admin_stripe_payments WHERE ? IS NOT NULL AND admin_id = ?),
        (SELECT COUNT(*) FROM admin_plan_requests WHERE ? IS NOT NULL AND admin_id = ? AND payment_method = 'stripe'),
        (SELECT COUNT(*) FROM admin_billing_history WHERE ? IS NOT NULL AND admin_id = ?)
    """,
    (admin_id, admin_id, admin_id, admin_id, admin_id, admin_id),
).fetchall()

print_section(
    "Summary Counts",
    [
        "legacy_paypay_rows",
        "pending_legacy_paypay_rows",
        "stripe_payment_rows",
        "stripe_plan_request_rows",
        "billing_history_rows",
    ],
    summary,
)

conn.close()
'@

$adminIdArg = if ($null -eq $AdminId) { "" } else { [string]$AdminId.Value }
$stripePaymentIdArg = if ($null -eq $StripePaymentId) { "" } else { [string]$StripePaymentId.Value }
$planRequestIdArg = if ($null -eq $PlanRequestId) { "" } else { [string]$PlanRequestId.Value }

$pythonScript | python - $DbPath $AdminEmail $adminIdArg $stripePaymentIdArg $planRequestIdArg
