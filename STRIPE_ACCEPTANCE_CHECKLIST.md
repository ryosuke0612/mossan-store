# Stripe Acceptance Checklist

## 目的

- PayPay 完全撤去後も Stripe の安全設計が維持されていることを確認する
- `success URL` 戻りだけでは成功扱いしないことを確認する
- webhook 単独に依存せず、success / 手動再確認 / 承認前確認で Stripe API 再確認が走ることを確認する
- 承認時だけ `admins` と `admin_billing_history` が更新されることを確認する

## 事前確認

1. DB 残骸確認を実行する

```powershell
python scripts\verify_paypay_removal_state.py
```

期待結果:

- `admin_paypay_payments removed` が `PASS`
- `paypay_payment_id removed` が `PASS`
- `paypay indexes removed` が `PASS`
- `legacy history still readable` が `PASS`
- `no pending legacy approvals remain` が `PASS`

2. Stripe 設定が入っていることを確認する

- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_REDIRECT_BASE_URL`
- Render 本番URLと `STRIPE_REDIRECT_BASE_URL` が一致していること
- `STRIPE_REDIRECT_BASE_URL` は `https://` の公開URLであること

3. テスト用の管理者アカウントとサイト運営者アカウントを用意する

4. 本番導線とプレビュー導線を混同しないことを確認する

- 本番確認URL: `/admin/plan-requests`
- 表示確認専用プレビュー: `/dev/stripe-preview/...`
- プレビューではボタンが無効化されるため、実決済確認には使わない

## 受け入れ確認

### 1. 管理者が Stripe 決済を開始する

操作:

- 管理者でログイン
- [`admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/admin_plan_requests.html) から Stripe 決済を開始する
- `/admin/plan-requests` に `クレジットカードで決済へ進む` ボタンが表示されることを確認する

期待結果:

- Stripe Checkout へ遷移する
- 決済開始直後に有料化は反映されない
- `admin_stripe_payments` に決済行が作られる

補足:

- ボタンが押せない場合は、まずプレビューURLではなく本番URLを開いているか確認する
- ボタンが出るが開始できない場合は `STRIPE_*` 環境変数と `STRIPE_REDIRECT_BASE_URL` を確認する

### 2. success URL に戻っただけでは申請完了にならないことを確認する

操作:

- Stripe Checkout から未完了状態で戻る、または未完了のまま再訪する

期待結果:

- 申請は送信されない
- 管理者画面で「必要に応じて再確認してください」と表示される
- 完了済みの Stripe 決済でない限り申請フォームは出ない

### 3. Stripe 支払い完了後、success で API 再確認されることを確認する

操作:

- テスト決済を完了する
- `/admin/stripe/success` 経由で管理者画面へ戻る

期待結果:

- Stripe API 再確認後にだけ「Stripe決済を確認しました」が出る
- 申請フォームには completed な Stripe 決済だけが使われる
- この時点ではまだ `admins` と `admin_billing_history` は更新されない

### 4. 手動再確認が機能することを確認する

操作:

- 管理者画面またはサイト運営者画面の `Stripe再確認` を押す

期待結果:

- `admin_refresh_stripe_payment` が成功メッセージを返す
- 最終確認日や決済状態表示が更新される
- webhook が未着でも API ベースで状態確認できる

### 5. 管理者が申請を送信する

操作:

- completed な Stripe 決済を使って申請送信する

期待結果:

- `admin_plan_requests.payment_method='stripe'`
- `admin_plan_requests.stripe_payment_id` に Stripe 決済が紐づく
- まだ有料化は反映されない

### 6. サイト運営者画面で確認できることを確認する

操作:

- [`site_admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/site_admin_plan_requests.html) を開く

期待結果:

- 支払確認
- 最終確認日
- 決済状態
- `Stripe再確認` ボタン

が表示される

### 7. 承認前に fail-closed 再確認されることを確認する

操作:

- サイト運営者が承認する

期待結果:

- `verify_admin_plan_request_payment_before_approval` が走る
- Stripe API 再確認に失敗したら承認されない
- Stripe completed でなければ承認されない
- 旧決済方式は承認不可のまま

### 8. 承認時だけ有料化が反映されることを確認する

操作:

- Stripe completed な申請を承認する

期待結果:

- ここで初めて `admins` が更新される
- ここで初めて `admin_billing_history` が追加される
- 承認前にはその更新が入っていない

## 失敗時の確認ポイント

- `app.py`
  - [`verify_admin_plan_request_payment_before_approval`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/app.py#L4795)
  - [`portal_review_admin_plan_request`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/app.py#L4814)
  - [`admin_stripe_success`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/app.py#L6154)
  - [`admin_refresh_stripe_payment`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/app.py#L6189)
  - [`admin_create_plan_request`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/app.py#L6304)
- テンプレート
  - [`admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/admin_plan_requests.html)
  - [`site_admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/site_admin_plan_requests.html)
- DB
  - `admin_stripe_payments`
  - `admin_plan_requests`
  - `admin_billing_history`
  - `admins`

## 完了条件

- DB 残骸確認スクリプトが `PASS`
- Stripe の success / 手動再確認 / webhook / 承認前確認のどれでも安全設計が崩れていない
- 承認時だけ有料化反映される
- 旧 PayPay 履歴 2 件が読める

## 関連資料

- [`RENDER_STRIPE_DEPLOY_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/RENDER_STRIPE_DEPLOY_CHECKLIST.md)
- [`STRIPE_ACCEPTANCE_DB_QUERIES.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_DB_QUERIES.md)
