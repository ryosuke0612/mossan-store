# Stripe Acceptance DB Queries

## 使い方
- Stripe 受け入れ確認の各段で `schedule.db` を読むときの確認用クエリ集
- 事前に [`STRIPE_ACCEPTANCE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_CHECKLIST.md) を読む
- まとめて確認したい場合は [`scripts/run_stripe_acceptance_snapshot.ps1`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/run_stripe_acceptance_snapshot.ps1) を使う

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_stripe_acceptance_snapshot.ps1 `
  -DbPath schedule.db `
  -AdminEmail admin@example.com `
  -AdminId 1 `
  -StripePaymentId 10 `
  -PlanRequestId 20
```

置換用プレースホルダ:
- `TARGET_ADMIN_EMAIL`
- `TARGET_ADMIN_ID`
- `TARGET_STRIPE_PAYMENT_ID`
- `TARGET_PLAN_REQUEST_ID`

## 1. 事前の管理者状態
```sql
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
WHERE email = 'TARGET_ADMIN_EMAIL';
```

## 2. 決済開始直後に Stripe 決済行ができているか
```sql
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
    requested_at,
    returned_at,
    confirmed_at,
    last_checked_at,
    linked_plan_request_id,
    applied_at,
    applied_billing_history_id,
    created_at,
    updated_at
FROM admin_stripe_payments
WHERE admin_id = TARGET_ADMIN_ID
ORDER BY id DESC
LIMIT 10;
```

確認ポイント:
- 決済行が作られている
- `applied_at` はまだ `NULL`
- `admins` と `admin_billing_history` はまだ未更新

## 3. success / 再確認 / webhook 後に API 再確認されたか
```sql
SELECT
    id,
    status,
    stripe_status,
    stripe_payment_status,
    stripe_paid_at,
    returned_at,
    confirmed_at,
    last_checked_at,
    linked_plan_request_id,
    applied_at,
    applied_billing_history_id,
    last_error_code,
    last_error_message
FROM admin_stripe_payments
WHERE id = TARGET_STRIPE_PAYMENT_ID;
```

確認ポイント:
- `status='completed'` になっている
- `stripe_payment_status='paid'` を確認できる
- `applied_at` が埋まっていれば自動反映済み

## 4. 監査用 plan request が自動作成または更新されたか
```sql
SELECT
    apr.id,
    apr.admin_id,
    apr.request_type,
    apr.payment_method,
    apr.payment_amount,
    apr.payment_date,
    apr.payment_reference,
    apr.status,
    apr.review_note,
    apr.reviewed_by_admin_id,
    apr.reviewed_at,
    apr.stripe_payment_id,
    apr.payment_verification_status,
    apr.payment_verified_at,
    apr.created_at,
    apr.updated_at,
    asp.status AS stripe_row_status,
    asp.stripe_payment_status,
    asp.last_checked_at,
    asp.linked_plan_request_id,
    asp.applied_at,
    asp.applied_billing_history_id
FROM admin_plan_requests apr
LEFT JOIN admin_stripe_payments asp ON asp.id = apr.stripe_payment_id
WHERE apr.admin_id = TARGET_ADMIN_ID
ORDER BY apr.id DESC
LIMIT 10;
```

確認ポイント:
- `payment_method='stripe'`
- `status='approved'`
- `payment_verification_status='verified'`
- `admin_stripe_payments.linked_plan_request_id` と一致する

## 5. 自動反映後の admins 更新
```sql
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
WHERE id = TARGET_ADMIN_ID;
```

確認ポイント:
- `plan_type='paid'`
- `billing_status='paid'`
- `billing_count` が 1 回だけ増えている
- `expires_at` が 30 日延長されている

## 6. billing history が 1 回だけ記録されたか
```sql
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
WHERE admin_id = TARGET_ADMIN_ID
ORDER BY id DESC
LIMIT 10;
```

確認ポイント:
- 新しい 1 行だけ追加されている
- `amount` が決済金額と一致する
- `billing_count` が `admins.billing_count` と整合する

## 7. 同じ決済で二重反映されていないか
```sql
SELECT
    asp.id,
    asp.linked_plan_request_id,
    asp.applied_at,
    asp.applied_billing_history_id,
    COUNT(abh.id) AS billing_rows_for_same_payment
FROM admin_stripe_payments asp
LEFT JOIN admin_plan_requests apr ON apr.id = asp.linked_plan_request_id
LEFT JOIN admin_billing_history abh
    ON abh.admin_id = asp.admin_id
   AND abh.billed_at = asp.stripe_paid_at
   AND abh.amount = asp.request_amount
WHERE asp.id = TARGET_STRIPE_PAYMENT_ID
GROUP BY asp.id, asp.linked_plan_request_id, asp.applied_at, asp.applied_billing_history_id;
```

確認ポイント:
- `applied_at` が 1 つだけ入っている
- `billing_rows_for_same_payment` が 1

## 8. 旧 PayPay 履歴が読めるか
```sql
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
```

確認ポイント:
- 旧履歴が読める
- `pending` が残っていない

## 9. まとめ確認
```sql
SELECT
    (SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, '')) = 'paypay') AS legacy_paypay_rows,
    (SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, '')) = 'paypay' AND status = 'pending') AS pending_legacy_paypay_rows,
    (SELECT COUNT(*) FROM admin_stripe_payments WHERE admin_id = TARGET_ADMIN_ID) AS stripe_payment_rows,
    (SELECT COUNT(*) FROM admin_plan_requests WHERE admin_id = TARGET_ADMIN_ID AND payment_method = 'stripe') AS stripe_plan_request_rows,
    (SELECT COUNT(*) FROM admin_billing_history WHERE admin_id = TARGET_ADMIN_ID) AS billing_history_rows;
```
