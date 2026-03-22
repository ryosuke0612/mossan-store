# PayPay Removal Release Checklist

## 目的

- PayPay 完全撤去を本番反映してよい状態かを最終確認する
- Stripe の安全設計を壊していないことを短時間で確認する
- 実行順と参照資料を 1 つにまとめる

## 参照資料

- 残骸確認スクリプト: [`scripts/verify_paypay_removal_state.py`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/verify_paypay_removal_state.py)
- Stripe 受け入れ確認: [`STRIPE_ACCEPTANCE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_CHECKLIST.md)
- DB クエリ集: [`STRIPE_ACCEPTANCE_DB_QUERIES.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_DB_QUERIES.md)
- 一括 SQL: [`scripts/stripe_acceptance_snapshot.sql`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/stripe_acceptance_snapshot.sql)
- PowerShell 一括確認: [`scripts/run_stripe_acceptance_snapshot.ps1`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/run_stripe_acceptance_snapshot.ps1)
- 撤去方針と手動 SQL: [`PAYPAY_REMOVAL_PLAN.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/PAYPAY_REMOVAL_PLAN.md)

## 実行順

### 1. DB 残骸確認

実行:

```powershell
python scripts\verify_paypay_removal_state.py
```

合格条件:

- `admin_paypay_payments removed` が `PASS`
- `paypay_payment_id removed` が `PASS`
- `paypay indexes removed` が `PASS`
- `legacy history still readable` が `PASS`
- `no pending legacy approvals remain` が `PASS`

### 2. 対象管理者の事前スナップショット取得

実行例:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_stripe_acceptance_snapshot.ps1 `
  -DbPath schedule.db `
  -AdminEmail admin@example.com `
  -AdminId 1
```

見る点:

- `admins` の `billing_count` と `total_billing_amount`
- `admin_billing_history` の最新行
- `admin_stripe_payments` の最新状態
- 旧 PayPay 履歴が残っていること

### 3. Stripe 通し確認

実施内容:

- [`STRIPE_ACCEPTANCE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_CHECKLIST.md) の 1 から 8 を順番に実施する

特に落としてはいけない条件:

- `success URL` 戻りだけでは成功扱いしない
- webhook 単独に依存しない
- 手動再確認が効く
- 承認前に fail-closed 再確認される
- 承認時だけ `admins` と `admin_billing_history` が更新される

### 4. 事後スナップショット取得

実行例:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_stripe_acceptance_snapshot.ps1 `
  -DbPath schedule.db `
  -AdminEmail admin@example.com `
  -AdminId 1 `
  -StripePaymentId 10 `
  -PlanRequestId 20
```

見る点:

- `admin_plan_requests.payment_method='stripe'`
- `admin_plan_requests.stripe_payment_id` が入っている
- `admin_stripe_payments.linked_plan_request_id` が申請 ID と一致する
- 承認後にだけ `admins.billing_count` と `admins.total_billing_amount` が増えている
- 承認後にだけ `admin_billing_history` が 1 行増えている

### 5. 問題があった場合

- 個別確認は [`STRIPE_ACCEPTANCE_DB_QUERIES.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_DB_QUERIES.md) を使う
- PayPay 残骸が再出現した場合や DB cleanup を手動でやる場合は [`PAYPAY_REMOVAL_PLAN.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/PAYPAY_REMOVAL_PLAN.md) の SQL を使う

## リリース判断

以下をすべて満たしたら PayPay 完全撤去はリリース可:

- PayPay テーブル・列・インデックスが存在しない
- 旧 PayPay 履歴は読める
- 旧決済方式は承認不可のまま
- Stripe success / 手動再確認 / 承認前確認が機能する
- 承認前に有料化されない
- 承認時だけ `admins` と `admin_billing_history` が更新される

## この環境での既知事項

- `schedule.db` の現観測では PayPay テーブル・列・インデックスは除去済み
- 旧 PayPay 履歴は 2 件残っている
- `sqlite3.OperationalError: disk I/O error` が出る環境があったため、本番反映前に安定環境での再確認は必須
- 外部 Stripe API を叩く通し確認はこの環境では未実施
