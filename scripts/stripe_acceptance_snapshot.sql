-- Stripe acceptance snapshot for schedule.db
-- Usage example:
--   sqlite3 schedule.db ".read scripts/stripe_acceptance_snapshot.sql"
-- If your sqlite3 supports parameters, set them before reading:
--   sqlite3 schedule.db
--   .parameter init
--   .parameter set @admin_email "'admin@example.com'"
--   .parameter set @admin_id 1
--   .parameter set @stripe_payment_id 1
--   .parameter set @plan_request_id 1
--   .read scripts/stripe_acceptance_snapshot.sql

.headers on
.mode column

.print ====================
.print Admin Lookup
.print ====================
SELECT
    id,
    email,
    plan_type,
    account_status,
    billing_status,
    expires_at,
    total_billing_amount,
    billing_count,
    last_billed_at
FROM admins
WHERE (@admin_email IS NOT NULL AND email = @admin_email)
   OR (@admin_id IS NOT NULL AND id = @admin_id)
ORDER BY id;

.print
.print ====================
.print Stripe Payments
.print ====================
SELECT
    id,
    admin_id,
    stripe_checkout_session_id,
    stripe_payment_intent_id,
    request_type,
    request_amount,
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
    last_error_code,
    last_error_message,
    created_at,
    updated_at
FROM admin_stripe_payments
WHERE @admin_id IS NOT NULL AND admin_id = @admin_id
ORDER BY id DESC
LIMIT 20;

.print
.print ====================
.print Target Stripe Payment
.print ====================
SELECT
    id,
    admin_id,
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
    last_error_code,
    last_error_message,
    created_at,
    updated_at
FROM admin_stripe_payments
WHERE @stripe_payment_id IS NOT NULL AND id = @stripe_payment_id;

.print
.print ====================
.print Plan Requests
.print ====================
SELECT
    apr.id,
    apr.admin_id,
    apr.request_type,
    apr.payment_method,
    apr.payment_amount,
    apr.payment_date,
    apr.payment_reference,
    apr.status,
    apr.reviewed_by_admin_id,
    apr.reviewed_at,
    apr.stripe_payment_id,
    apr.payment_verification_status,
    apr.payment_verified_at,
    apr.created_at,
    apr.updated_at,
    asp.status AS stripe_row_status,
    asp.last_checked_at,
    asp.linked_plan_request_id
FROM admin_plan_requests apr
LEFT JOIN admin_stripe_payments asp ON asp.id = apr.stripe_payment_id
WHERE @admin_id IS NOT NULL AND apr.admin_id = @admin_id
ORDER BY apr.id DESC
LIMIT 20;

.print
.print ====================
.print Target Plan Request
.print ====================
SELECT
    apr.id,
    apr.admin_id,
    apr.request_type,
    apr.payment_method,
    apr.payment_amount,
    apr.payment_date,
    apr.payment_reference,
    apr.status,
    apr.reviewed_by_admin_id,
    apr.reviewed_at,
    apr.stripe_payment_id,
    apr.payment_verification_status,
    apr.payment_verified_at,
    apr.created_at,
    apr.updated_at,
    asp.status AS stripe_row_status,
    asp.stripe_status,
    asp.stripe_payment_status,
    asp.last_checked_at,
    asp.linked_plan_request_id
FROM admin_plan_requests apr
LEFT JOIN admin_stripe_payments asp ON asp.id = apr.stripe_payment_id
WHERE @plan_request_id IS NOT NULL AND apr.id = @plan_request_id;

.print
.print ====================
.print Billing History
.print ====================
SELECT
    id,
    admin_id,
    billing_status,
    billed_at,
    amount,
    total_amount,
    billing_count,
    note,
    created_at
FROM admin_billing_history
WHERE @admin_id IS NOT NULL AND admin_id = @admin_id
ORDER BY id DESC
LIMIT 20;

.print
.print ====================
.print Legacy PayPay History
.print ====================
SELECT
    id,
    admin_id,
    payment_method,
    status,
    payment_amount,
    payment_date,
    payment_reference,
    created_at
FROM admin_plan_requests
WHERE lower(coalesce(payment_method, '')) = 'paypay'
ORDER BY id DESC;

.print
.print ====================
.print Summary Counts
.print ====================
SELECT
    (SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, '')) = 'paypay') AS legacy_paypay_rows,
    (SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, '')) = 'paypay' AND status = 'pending') AS pending_legacy_paypay_rows,
    (SELECT COUNT(*) FROM admin_stripe_payments WHERE @admin_id IS NOT NULL AND admin_id = @admin_id) AS stripe_payment_rows,
    (SELECT COUNT(*) FROM admin_plan_requests WHERE @admin_id IS NOT NULL AND admin_id = @admin_id AND payment_method = 'stripe') AS stripe_plan_request_rows,
    (SELECT COUNT(*) FROM admin_billing_history WHERE @admin_id IS NOT NULL AND admin_id = @admin_id) AS billing_history_rows;
