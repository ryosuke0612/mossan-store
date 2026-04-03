# Render Deploy Checklist

## Target services

- `mossan-store-web`
  - domain target: `mossan-store.com`
  - root directory: `services/store-web`
  - start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
  - health check: `/`

- `mossan-attendance-app`
  - domain target: `attendance.mossan-store.com`
  - root directory: `services/attendance-app`
  - start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
  - health check: `/admin/login`
  - database: one existing Render PostgreSQL or one newly recreated PostgreSQL

## Required environment variables

### `mossan-store-web`

- `PYTHON_VERSION=3.12.8`
- `RENDER=true`
- `SECRET_KEY`
- `ATTENDANCE_APP_BASE_URL`
  - after the attendance domain is ready, set `https://attendance.mossan-store.com`

### `mossan-attendance-app`

- `PYTHON_VERSION=3.12.8`
- `RENDER=true`
- `SECRET_KEY`
- `DATABASE_URL`
- `ATTENDANCE_APP_BASE_URL`
  - set to the attendance app URL
- `STRIPE_REDIRECT_BASE_URL`
  - set to the attendance app URL
- `SITE_ADMIN_EMAILS`
- `ADMIN_BOOTSTRAP_EMAIL`
- `ADMIN_BOOTSTRAP_PASSWORD`
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CONNECT_TIMEOUT_SECONDS=10`
- `STRIPE_REQUEST_TIMEOUT_SECONDS=30`
- `STRIPE_WEBHOOK_TOLERANCE_SECONDS=300`

## Recommended deployment order

1. Decide which single PostgreSQL you will use
   - reuse the existing free-tier DB, or
   - delete the old DB and recreate one cleanly
2. Deploy `mossan-attendance-app`
3. Attach the chosen PostgreSQL to `DATABASE_URL`
4. Confirm `/admin/login` opens
5. Set custom domain `attendance.mossan-store.com`
6. Set `ATTENDANCE_APP_BASE_URL` and `STRIPE_REDIRECT_BASE_URL` to the final attendance domain
7. Deploy `mossan-store-web`
8. Set `ATTENDANCE_APP_BASE_URL` on `mossan-store-web` to the same attendance domain
9. Confirm `/apps/attendance/app/description` from `store-web` redirects to the attendance domain
10. Set custom domain `mossan-store.com`

## Post-deploy smoke checks

### `mossan-store-web`

- `/`
- `/apps`
- `/blog`
- `/apps/attendance/app/description`
  - should redirect to `attendance.mossan-store.com`

### `mossan-attendance-app`

- `/admin/login`
- `/admin`
- `/apps/attendance/app/description`
- `/apps/attendance/app/login`
- `/site-admin`

## Safe rollback

- keep [render.single-service.legacy.yaml](C:/Users/ponnt/OneDrive/Desktop/python/mossan-store/render.single-service.legacy.yaml) as the comparison copy of the old single-service setup
- do not delete the existing Render service until the new two-service deployment is confirmed
- switch DNS only after both new services are healthy

## Free-tier note

- the current [render.yaml](C:/Users/ponnt/OneDrive/Desktop/python/mossan-store/render.yaml) does not auto-create a database
- this is intentional so you can stay within the single PostgreSQL free-tier limit
- connect `DATABASE_URL` manually in Render to the one DB you choose for `attendance-app`
