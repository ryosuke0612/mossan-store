# Render Stripe Deploy Checklist

## 目的
- Render 本番環境で Stripe 自動反映フローを安全に公開する
- `success URL` 単独成功禁止、手動再確認、webhook 併用の API 再確認を維持したままデプロイする
- completed / paid を確認できた決済だけ、金額に応じて延長される状態で公開する

## デプロイ前
1. Render の環境変数を確認する
- `SECRET_KEY`
- `DATABASE_URL`
- `RENDER=true`
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_REDIRECT_BASE_URL`
- `SITE_ADMIN_EMAILS`

2. Stripe 関連の値を確認する
- `STRIPE_REDIRECT_BASE_URL` は Render の公開 `https://...` URL と一致している
- Stripe Dashboard の webhook 送信先が本番 URL の webhook endpoint を向いている

3. DB 残骸確認を行う
- 必要なら [`scripts/verify_paypay_removal_state.py`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/verify_paypay_removal_state.py) を先に実行する

## デプロイ直後
1. アプリが正常起動していることを確認する
- Render の deploy log にエラーがない
- `/admin/plan-requests` が開く

2. プレビューではなく本番導線を見ていることを確認する
- `/dev/stripe-preview/...` は表示確認専用
- 実確認は `/admin/plan-requests` と `/site-admin/plan-requests` で行う

## 本番確認
### 1. 決済開始
- `/admin/plan-requests` で決済を開始する

期待結果:
- Stripe Checkout へ遷移する
- この時点では `admins` と `admin_billing_history` は未更新

### 2. success 戻り確認
- Stripe Checkout から戻る

期待結果:
- `success URL` に戻っただけでは成功扱いにならない
- Stripe API 確認後だけ completed / paid を自動反映対象として扱う
- completed / paid を確認できれば、そのまま有料化まで完了する

### 3. 手動再確認
- 管理者画面か site_admin 画面の `Stripe再確認` を押す

期待結果:
- webhook 未着でも API ベースで更新できる
- 反映済み決済では二重加算されない

### 4. site_admin 監査確認
- `/site-admin/plan-requests` を開く

期待結果:
- Stripe 承認ボタンは出ない
- 監査表示と `Stripe再確認` だけが残る
- legacy PayPay は読み取りできる

## トラブルシュート
- 決済導線が出ない: `STRIPE_*` 環境変数と `STRIPE_REDIRECT_BASE_URL` を確認する
- success 後に未反映: `admin_stripe_payments.status`, `stripe_payment_status`, `applied_at` を確認する
- 二重加算が心配: `admin_billing_history` と `admins.billing_count` が 1 回だけ増えているか確認する
- site_admin 画面が旧承認 UI のまま: 最新デプロイが反映されているか確認する

## 関連資料
- [`STRIPE_ACCEPTANCE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_CHECKLIST.md)
- [`STRIPE_ACCEPTANCE_DB_QUERIES.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_DB_QUERIES.md)
- [`PAYPAY_REMOVAL_RELEASE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/PAYPAY_REMOVAL_RELEASE_CHECKLIST.md)
