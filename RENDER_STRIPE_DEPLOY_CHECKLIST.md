# Render Stripe Deploy Checklist

## 目的

- Render 本番環境で Stripe 導線を安全に公開する
- プレビュー導線と本番導線を混同せずに確認する
- success URL 単独成功禁止、手動再確認、承認前 fail-closed を維持したままデプロイする

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
- `STRIPE_REDIRECT_BASE_URL` に末尾スラッシュの有無差分があっても実URLがずれないことを確認する
- Stripe Dashboard の webhook 送信先が本番URLの webhook endpoint を向いている

3. DB 前提を確認する

- Render では PostgreSQL を使う
- `RENDER=true` の状態で `DATABASE_URL` が空だと起動失敗する実装になっている
- PayPay 残骸確認が必要なら [`scripts/verify_paypay_removal_state.py`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/scripts/verify_paypay_removal_state.py) を先に実行する

## デプロイ直後

1. アプリが正常起動していることを確認する

- Render の deploy log に起動エラーがない
- 500 エラーで落ちていない

2. 本番導線を確認する

- 管理者でログインする
- `/admin/plan-requests` を開く
- `クレジットカードで決済へ進む` ボタンが表示されることを確認する

3. プレビュー導線を本番確認に使っていないことを確認する

- `/dev/stripe-preview/...` は表示確認専用
- プレビューではボタンが無効化される
- 実決済確認は `/admin/plan-requests` だけで行う

## 決済導線確認

1. 管理者画面の決済開始

- `/admin/plan-requests` で金額と申請種別を選ぶ
- `クレジットカードで決済へ進む` を押す

期待結果:

- Stripe Checkout へリダイレクトする
- この時点では `admins` と `admin_billing_history` は更新されない

2. success 戻り確認

- Stripe Checkout から戻る

期待結果:

- success URL に戻っただけでは申請完了扱いにならない
- Stripe API 確認後だけ、申請送信可能な completed 決済として扱われる
- 申請フォームが出ても、まだ有料化反映はされていない

3. 手動再確認

- 管理者画面の `再確認` を押す

期待結果:

- webhook 未着でも API ベースで更新できる
- 決済状態と最終確認日が更新される

## 承認導線確認

1. 管理者が申請送信する

期待結果:

- `admin_plan_requests.payment_method='stripe'`
- `admin_plan_requests.stripe_payment_id` が入る
- まだ有料化反映されない

2. サイト運営者が確認する

- `/site-admin/plan-requests` を開く

期待結果:

- 支払確認
- 最終確認日
- 決済状態
- `Stripe再確認`

が見える

3. 承認前 fail-closed

- サイト運営者が承認する

期待結果:

- 承認前に Stripe API 再確認が走る
- completed を再確認できない場合は承認されない
- legacy PayPay pending は承認不可のまま

4. 承認時だけ反映

期待結果:

- 承認時にだけ `admins` が更新される
- 承認時にだけ `admin_billing_history` が追加される

## 問題が出たときの見方

- ボタンが押せない:
  - プレビューURLを見ていないか確認する
  - `STRIPE_*` 環境変数不足を確認する
- Checkout に進めない:
  - `STRIPE_REDIRECT_BASE_URL` を確認する
  - Render の公開URLと一致しているか確認する
- success 後に申請できない:
  - `admin_stripe_payments` の状態が completed か確認する
  - 管理者画面から `再確認` を試す
- 承認できない:
  - 承認前 API 再確認で fail-closed になっていないか確認する
  - legacy payment_method ではないか確認する

## 関連資料

- [`STRIPE_ACCEPTANCE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_CHECKLIST.md)
- [`STRIPE_ACCEPTANCE_DB_QUERIES.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_DB_QUERIES.md)
- [`PAYPAY_REMOVAL_RELEASE_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/PAYPAY_REMOVAL_RELEASE_CHECKLIST.md)
- [`app.py`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/app.py)
- [`templates/admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/admin_plan_requests.html)
- [`templates/site_admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/site_admin_plan_requests.html)
