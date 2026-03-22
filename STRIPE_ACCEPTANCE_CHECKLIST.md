# Stripe Acceptance Checklist

## 目的
- PayPay 完全撤去後も Stripe の安全設計が維持されていることを確認する
- `success URL` に戻っただけでは成功扱いしないことを確認する
- webhook 単独に依存せず、`success` / 手動再確認 / webhook で Stripe API 再確認が走ることを確認する
- Stripe API で `completed / paid` を確認できた決済だけが自動反映されることを確認する
- 1 決済 1 回だけ `admins` と `admin_billing_history` が更新されることを確認する

## 事前確認
1. DB 残骸確認を実行する

```powershell
python scripts\verify_paypay_removal_state.py
```

期待結果:
- `admin_paypay_payments removed` が `PASS`
- `paypay_payment_id removed` が `PASS`
- `stripe auto-apply columns exist` が `PASS`
- `legacy history still readable` が `PASS`
- `no pending legacy approvals remain` が `PASS`

2. Stripe 設定が入っていることを確認する
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_REDIRECT_BASE_URL`
- Render 本番 URL と `STRIPE_REDIRECT_BASE_URL` が一致していること
- `STRIPE_REDIRECT_BASE_URL` は `https://` の公開 URL であること

3. 本番導線とプレビュー導線を混同しないことを確認する
- 本番確認 URL: `/admin/plan-requests`
- 表示確認専用プレビュー: `/dev/stripe-preview/...`
- プレビューでは実決済確認を行わない

4. コード上の自動反映ロジックを先に回帰確認したい場合

```powershell
python scripts\verify_stripe_auto_apply_flow.py
```

期待結果:
- `PASS: stripe auto-apply flow`
- `PASS: second apply status = already_applied`

## 受け入れ確認
### 1. 管理者が Stripe 決済を開始する
操作:
- 管理者でログインする
- [`admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/admin_plan_requests.html) から Stripe 決済を開始する

期待結果:
- Stripe Checkout へ遷移する
- 決済開始直後に有料化は反映されない
- `admin_stripe_payments` に決済行が作られる
- この時点では `applied_at` と `applied_billing_history_id` は未設定

### 2. success URL に戻っただけでは成功扱いにならないことを確認する
操作:
- Stripe Checkout から未完了状態で戻る、または未完了のまま再訪する

期待結果:
- 有料プランは反映されない
- `admin_billing_history` は増えない
- 管理者画面で再確認を促すメッセージが表示される

### 3. Stripe 支払い完了後、success で API 再確認され自動反映されることを確認する
操作:
- テスト決済を完了する
- `/admin/stripe/success` 経由で管理者画面へ戻る

期待結果:
- Stripe API 再確認後にだけ成功メッセージが出る
- `admin_stripe_payments.status='completed'`
- `admin_stripe_payments.applied_at` が埋まる
- `admins.plan_type='paid'`
- 既存有効期限が未来ならそこから 30 日延長、期限切れまたは空なら現在時刻基準で 30 日延長
- `admin_billing_history` に新しい 1 行だけ追加される

### 4. 手動再確認でも自動反映できることを確認する
操作:
- 管理者画面または site_admin 画面の `Stripe再確認` を押す

期待結果:
- `admin_refresh_stripe_payment` が API ベースで状態確認する
- webhook が未着でも completed / paid を確認できれば自動反映される
- 反映済み決済では再加算されない

### 5. 1 決済 1 回だけ反映されることを確認する
操作:
- 同じ Stripe 決済に対して `success` 再訪、`Stripe再確認`、webhook 再送を行う

期待結果:
- `admins.billing_count` は 1 回しか増えない
- `admins.total_billing_amount` は 1 回しか増えない
- `admin_billing_history` は 1 行しか増えない
- `admin_stripe_payments.applied_at` は維持される

### 6. site_admin 画面が承認画面ではなく監査画面になっていることを確認する
操作:
- [`site_admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/site_admin_plan_requests.html) を開く

期待結果:
- Stripe の承認ボタンが出ない
- Stripe の `Stripe再確認` 導線と監査表示だけが残る
- legacy PayPay 行は読み取りできる
- legacy pending があれば却下だけ可能なまま

## 失敗時の確認ポイント
- [`app.py`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/app.py)
- [`templates/admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/admin_plan_requests.html)
- [`templates/site_admin_plan_requests.html`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/templates/site_admin_plan_requests.html)
- `admin_stripe_payments`
- `admin_plan_requests`
- `admin_billing_history`
- `admins`

## 完了条件
- DB 残骸確認スクリプトが `PASS`
- Stripe の `success` / 手動再確認 / webhook で安全設計が崩れていない
- `success URL` 単独では成功扱いにならない
- completed / paid を確認できた決済だけ自動で 30 日追加される
- 1 決済 1 回だけ billing history が記録される
- 旧 PayPay 履歴が読める

## 関連資料
- [`RENDER_STRIPE_DEPLOY_CHECKLIST.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/RENDER_STRIPE_DEPLOY_CHECKLIST.md)
- [`STRIPE_ACCEPTANCE_DB_QUERIES.md`](C:/Users/ponnt/OneDrive/Desktop/python/soccer-app/STRIPE_ACCEPTANCE_DB_QUERIES.md)
