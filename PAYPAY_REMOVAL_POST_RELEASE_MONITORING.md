# PayPay Removal Post Release Monitoring

## 目的

- PayPay 完全撤去リリース直後に異常が出ていないかを確認する
- Stripe の安全設計が本番でも維持されているかを短時間で確認する
- 問題発生時に最初に見る場所を固定する

## リリース直後に確認すること

### 1. DB 残骸再確認

実行:

```powershell
python scripts\verify_paypay_removal_state.py
```

見る点:

- PayPay テーブル・列・インデックスが再出現していない
- 旧 PayPay 履歴は読める
- legacy pending が 0 のまま

### 2. 管理者画面の新規導線確認

見る点:

- 有料プラン申請画面が Stripe 専用のまま
- 旧決済方式の新規利用案内が適切
- Stripe 決済完了前は申請フォームが出ない

### 3. サイト運営者画面の確認

見る点:

- 旧決済方式は承認不可
- Stripe 行では支払確認、最終確認日、決済状態が見える
- `Stripe再確認` ボタンが使える

## 最初の 1 件で見ること

### 1. Stripe 決済開始

見る点:

- `admin_stripe_payments` に行が作られる
- まだ `admins` と `admin_billing_history` は変わらない

### 2. success 戻り

見る点:

- `success URL` 戻りだけでは完了扱いにならない
- completed な決済だけが申請に使われる

### 3. 申請送信

見る点:

- `admin_plan_requests.payment_method='stripe'`
- `stripe_payment_id` が紐づく
- `linked_plan_request_id` が一致する

### 4. 承認

見る点:

- 承認前に再確認が走る
- completed でなければ承認されない
- 承認時だけ `admins` と `admin_billing_history` が更新される

## 問題があったときの最初の確認先

- コード
  - [`app.py`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/app.py)
- 画面
  - [`templates/admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/admin_plan_requests.html)
  - [`templates/site_admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/site_admin_plan_requests.html)
- 手順
  - [`PAYPAY_REMOVAL_RELEASE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/PAYPAY_REMOVAL_RELEASE_CHECKLIST.md)
  - [`STRIPE_ACCEPTANCE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_CHECKLIST.md)
- DB
  - [`STRIPE_ACCEPTANCE_DB_QUERIES.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_DB_QUERIES.md)
  - [`scripts/run_stripe_acceptance_snapshot.ps1`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/run_stripe_acceptance_snapshot.ps1)

## 要注意サイン

- `payment_method='paypay'` の新規行が増える
- 旧決済方式の pending が増える
- `admin_stripe_payments` は増えているのに `admin_plan_requests` が作られない
- 承認前に `admins.billing_count` や `total_billing_amount` が増える
- `admin_billing_history` が承認前に増える
- `Stripe再確認` が失敗し続ける
- `status='completed'` なのに承認できない

## 安定確認の完了条件

- リリース直後確認が問題なし
- 最初の 1 件が安全設計どおり完了
- 旧 PayPay 履歴だけが残り、新規 PayPay データが増えていない
