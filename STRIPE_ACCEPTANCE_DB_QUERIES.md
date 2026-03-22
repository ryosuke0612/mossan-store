# Stripe Acceptance DB Queries

## 使い方

- Stripe 受け入れ確認の各段で `schedule.db` を読むときの確認用クエリ集
- 管理者メールアドレスまたは `admin_id` を対象にして使う
- 事前に [`STRIPE_ACCEPTANCE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_CHECKLIST.md) を読む
- まとめて確認したい場合は [`scripts/stripe_acceptance_snapshot.sql`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/stripe_acceptance_snapshot.sql) を使う
- PowerShell からまとめて確認したい場合は [`scripts/run_stripe_acceptance_snapshot.ps1`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/run_stripe_acceptance_snapshot.ps1) を使う

実行例:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_stripe_acceptance_snapshot.ps1 `
  -DbPath schedule.db `
  -AdminEmail admin@example.com `
  -AdminId 1 `
  -StripePaymentId 10 `
  -PlanRequestId 20
```

## 置換する値

- `TARGET_ADMIN_EMAIL`
- `TARGET_ADMIN_ID`
- `TARGET_STRIPE_PAYMENT_ID`
- `TARGET_PLAN_REQUEST_ID`

## 1. 対象管理者を特定する

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

## 2. 決済開始直後に Stripe 決済行ができているか確認する

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
    created_at,
    updated_at
FROM admin_stripe_payments
WHERE admin_id = TARGET_ADMIN_ID
ORDER BY id DESC
LIMIT 10;
```

見る点:

- 行が作られている
- `linked_plan_request_id` はまだ `NULL`
- この時点では `admins` と `admin_billing_history` は未更新

## 3. success 後に API 再確認されたか確認する

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
    last_error_code,
    last_error_message,
    linked_plan_request_id
FROM admin_stripe_payments
WHERE id = TARGET_STRIPE_PAYMENT_ID;
```

見る点:

- `status='completed'` なら completed 扱い
- `returned_at` または `last_checked_at` が更新されている
- まだ `linked_plan_request_id` がない段階なら、申請送信前

## 4. 申請送信後に plan request と Stripe 決済が紐づいたか確認する

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
    apr.stripe_payment_id,
    apr.payment_verification_status,
    apr.payment_verified_at,
    apr.created_at,
    apr.updated_at,
    asp.status AS stripe_payment_status_code,
    asp.linked_plan_request_id,
    asp.last_checked_at
FROM admin_plan_requests apr
LEFT JOIN admin_stripe_payments asp ON asp.id = apr.stripe_payment_id
WHERE apr.admin_id = TARGET_ADMIN_ID
ORDER BY apr.id DESC
LIMIT 10;
```

見る点:

- `payment_method='stripe'`
- `stripe_payment_id` が入っている
- `admin_stripe_payments.linked_plan_request_id` が申請 ID と一致する
- まだ `status='pending'` の段階では有料化反映なし

## 5. サイト運営者画面の支払確認表示に対応する値を確認する

```sql
SELECT
    apr.id,
    apr.status,
    apr.payment_verification_status,
    apr.payment_verified_at,
    asp.status AS stripe_status_code,
    asp.last_checked_at,
    asp.stripe_paid_at,
    asp.payment_reference
FROM admin_plan_requests apr
LEFT JOIN admin_stripe_payments asp ON asp.id = apr.stripe_payment_id
WHERE apr.id = TARGET_PLAN_REQUEST_ID;
```

見る点:

- `payment_verification_status`
- `payment_verified_at`
- `asp.status`
- `asp.last_checked_at`

## 6. 承認前は admins と billing history が変わっていないことを確認する

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

見る点:

- 承認前は `billing_count` と `total_billing_amount` が増えていない
- 承認前は新しい `admin_billing_history` 行が追加されていない

## 7. 承認後にだけ admins と billing history が更新されたか確認する

```sql
SELECT
    apr.id,
    apr.status,
    apr.reviewed_by_admin_id,
    apr.reviewed_at,
    apr.payment_verification_status,
    apr.payment_verified_at
FROM admin_plan_requests apr
WHERE apr.id = TARGET_PLAN_REQUEST_ID;
```

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

見る点:

- `admin_plan_requests.status='approved'`
- `reviewed_at` が入っている
- `admins.billing_count` と `admins.total_billing_amount` が更新される
- `admin_billing_history` に新しい 1 行が追加される

## 8. 旧 PayPay 履歴が残っているか確認する

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

見る点:

- 旧履歴が読める
- `pending` が残っていない

## 9. 一括確認

```sql
SELECT
    (SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, '')) = 'paypay') AS legacy_paypay_rows,
    (SELECT COUNT(*) FROM admin_plan_requests WHERE lower(coalesce(payment_method, '')) = 'paypay' AND status = 'pending') AS pending_legacy_paypay_rows,
    (SELECT COUNT(*) FROM admin_plan_requests WHERE payment_method = 'stripe' AND admin_id = TARGET_ADMIN_ID) AS stripe_plan_request_rows,
    (SELECT COUNT(*) FROM admin_stripe_payments WHERE admin_id = TARGET_ADMIN_ID) AS stripe_payment_rows,
    (SELECT COUNT(*) FROM admin_billing_history WHERE admin_id = TARGET_ADMIN_ID) AS billing_history_rows;
```
