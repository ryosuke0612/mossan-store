# PayPay Removal Plan

## 目的

- Stripe 専用運用へ完全移行する
- Stripe の安全設計は壊さない
- `success` へ戻っただけでは成功扱いしない
- webhook だけに依存しない
- callback / success / 手動再確認 / 承認前確認で Stripe API による状態確認を継続する
- 決済完了と有料化反映を分離したままにする
- サイト運営者承認時だけ `admins` と `admin_billing_history` を更新する
- 旧 PayPay 履歴は `admin_plan_requests.payment_method='paypay'` として最低限読める状態を維持する

## 2026-03-22 時点の整理

### すでに削除済み

- PayPay の新規決済 UI
- PayPay からの新規申請送信 UI
- PayPay checkout / callback / refresh / webhook ルート
- `app.py` 内の PayPay 実行系関数・参照
- `admin_create_plan_request` の PayPay 受付
- サイト運営者画面の PayPay 専用サマリー
- サイト運営者画面の PayPay 専用履歴確認 UI
- `init_db_sqlite` / `init_db_postgres` の新規スキーマ定義からの PayPay 生成

### まだ残してよいもの

- `admin_plan_requests.payment_method='paypay'` の旧履歴文字列
- 旧履歴を読めるための表示ラベル
- Stripe 側の決済確認 UI、最終確認日、決済状態表示
- Stripe 承認前の API 再確認と fail-closed 動作

### 今回の最終段対象

- `admin_paypay_payments` テーブル
- `admin_plan_requests.paypay_payment_id` 列
- `idx_admin_paypay_payments_*` 系インデックス

## 実 DB の確認結果

`schedule.db` を読み取り専用で確認した結果:

- `admin_paypay_payments` は存在するが 0 件
- `admin_plan_requests.paypay_payment_id` は列として残っている
- `admin_plan_requests.payment_method='paypay'` は 2 件
- `payment_method='paypay' AND status='pending'` は 0 件
- `idx_admin_paypay_payments_admin_created`
- `idx_admin_paypay_payments_merchant_payment_id`
- `idx_admin_paypay_payments_status_created`

この状態なら、旧履歴の表示を `payment_method='paypay'` にのみ依存させたまま、PayPay 専用テーブル・列・インデックスを削除してよい。

## 今回実装した方針

### 1. コード依存を先に断つ

- `app.py` から `admin_paypay_payments` / `paypay_payment_id` への実行時参照を残さない
- 旧履歴表示は `payment_method='paypay'` の文字列だけで成立させる
- ラベルは `旧PayPay` として表示し、新規利用は終了済みであることを UI 上で明確にする

### 2. DB 削除は fail-closed にする

`app.py` の初期化処理に、以下の条件を満たしたときだけ旧 PayPay スキーマを削除する安全ガード付き cleanup を追加した。

- `admin_plan_requests.paypay_payment_id IS NOT NULL` が 0 件
- `admin_plan_requests.payment_method='paypay' AND status='pending'` が 0 件
- `admin_paypay_payments` が存在しても 0 件

条件を 1 つでも満たさない場合は削除をスキップし、アプリは旧スキーマを壊さず継続する。

### 3. cleanup 実装

- SQLite:
  - PayPay インデックス削除
  - `admin_paypay_payments` 削除
  - `admin_plan_requests` を現行 Stripe スキーマで再作成して `paypay_payment_id` を除外
  - データ再投入後に `PRAGMA foreign_key_check`
- Postgres:
  - PayPay インデックス削除
  - `admin_paypay_payments` 削除
  - `ALTER TABLE admin_plan_requests DROP COLUMN IF EXISTS paypay_payment_id`

## 手動実行が必要な場合の SQL

この環境では `schedule.db` に対する import ベース初期化時に `sqlite3.OperationalError: disk I/O error` が出るため、実 DB 更新が自動で最後まで走らない可能性がある。必要なら以下を保守手順として使う。

簡易再確認は次のスクリプトでも実行できる。

```powershell
python scripts\verify_paypay_removal_state.py
```

### SQLite (`schedule.db`)

事前確認:

```sql
SELECT COUNT(*) AS paypay_rows FROM admin_paypay_payments;
SELECT COUNT(*) AS linked_rows FROM admin_plan_requests WHERE paypay_payment_id IS NOT NULL;
SELECT COUNT(*) AS pending_legacy_rows
FROM admin_plan_requests
WHERE lower(coalesce(payment_method, '')) = 'paypay'
  AND status = 'pending';
```

3 件とも 0 のときだけ実行:

```sql
BEGIN TRANSACTION;

DROP INDEX IF EXISTS idx_admin_paypay_payments_admin_created;
DROP INDEX IF EXISTS idx_admin_paypay_payments_merchant_payment_id;
DROP INDEX IF EXISTS idx_admin_paypay_payments_status_created;
DROP TABLE IF EXISTS admin_paypay_payments;

ALTER TABLE admin_plan_requests RENAME TO admin_plan_requests__legacy_paypay_cleanup;

CREATE TABLE admin_plan_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    request_type TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    payment_amount INTEGER NOT NULL DEFAULT 0,
    payment_date TEXT NOT NULL,
    payment_reference TEXT,
    request_note TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    review_note TEXT,
    reviewed_by_admin_id INTEGER,
    reviewed_at TEXT,
    stripe_payment_id INTEGER,
    payment_verification_status TEXT NOT NULL DEFAULT 'pending',
    payment_verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(admin_id) REFERENCES admins(id),
    FOREIGN KEY(reviewed_by_admin_id) REFERENCES admins(id)
);

INSERT INTO admin_plan_requests (
    id,
    admin_id,
    request_type,
    payment_method,
    payment_amount,
    payment_date,
    payment_reference,
    request_note,
    status,
    review_note,
    reviewed_by_admin_id,
    reviewed_at,
    stripe_payment_id,
    payment_verification_status,
    payment_verified_at,
    created_at,
    updated_at
)
SELECT
    id,
    admin_id,
    request_type,
    payment_method,
    payment_amount,
    payment_date,
    payment_reference,
    request_note,
    status,
    review_note,
    reviewed_by_admin_id,
    reviewed_at,
    stripe_payment_id,
    payment_verification_status,
    payment_verified_at,
    created_at,
    updated_at
FROM admin_plan_requests__legacy_paypay_cleanup;

DROP TABLE admin_plan_requests__legacy_paypay_cleanup;

CREATE INDEX IF NOT EXISTS idx_admin_plan_requests_admin_created
ON admin_plan_requests(admin_id, created_at);

CREATE INDEX IF NOT EXISTS idx_admin_plan_requests_status_created
ON admin_plan_requests(status, created_at);

COMMIT;
```

事後確認:

```sql
PRAGMA table_info(admin_plan_requests);
SELECT name FROM sqlite_master WHERE type='table' AND name='admin_paypay_payments';
SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_admin_paypay_payments_%';
```

### Postgres

事前確認:

```sql
SELECT COUNT(*) AS paypay_rows FROM admin_paypay_payments;
SELECT COUNT(*) AS linked_rows FROM admin_plan_requests WHERE paypay_payment_id IS NOT NULL;
SELECT COUNT(*) AS pending_legacy_rows
FROM admin_plan_requests
WHERE lower(coalesce(payment_method, '')) = 'paypay'
  AND status = 'pending';
```

3 件とも 0 のときだけ実行:

```sql
BEGIN;
DROP INDEX IF EXISTS idx_admin_paypay_payments_admin_created;
DROP INDEX IF EXISTS idx_admin_paypay_payments_merchant_payment_id;
DROP INDEX IF EXISTS idx_admin_paypay_payments_status_created;
DROP TABLE IF EXISTS admin_paypay_payments;
ALTER TABLE admin_plan_requests DROP COLUMN IF EXISTS paypay_payment_id;
COMMIT;
```

## Stripe 安全設計で残すべき確認点

- `admin_create_plan_request` は Stripe 専用のまま
- `admin_stripe_success` は `session_id` を受けて Stripe API 再確認を実施する
- `admin_refresh_stripe_payment` から手動再確認できる
- webhook は補助入力であり、単独成功判定に使わない
- `verify_admin_plan_request_payment_before_approval` は Stripe 以外を `legacy_payment_method_not_supported` で fail-closed
- `portal_review_admin_plan_request` は承認直前に再確認し、承認時だけ `admins` と `admin_billing_history` を更新する

## 次段階の引き継ぎ

- `schedule.db` の `disk I/O error` が解消した環境で init 時 cleanup が実際に走るか確認する
- もし自動 cleanup を使わずに本番反映するなら、上記 SQL をメンテナンス手順として実行する
- 実施後は以下を確認する
  - `admin_paypay_payments` が消えている
  - `admin_plan_requests.paypay_payment_id` が消えている
  - 旧履歴 2 件が `旧PayPay` として読める
  - Stripe の success / refresh / webhook / 承認前再確認が従来通り動く
