# PostgreSQL Migration Checklist

## 1) Backup and Decommission Legacy Local Files
- Backup folder created: `backups/20260314_222526`
- Backed up files:
  - `portal_data.json`
  - `schedule.db`
  - `schedule.db-journal`

Note:
- In this environment, rename/move of the original files was blocked by filesystem permissions.
- Backup copies are complete. Originals can be deleted later when no process is locking them.

## 2) Prevent Render Misconfiguration
- App now fails fast on Render if `DATABASE_URL` is missing.
- Added runtime guard:
  - `RENDER=true` and no PostgreSQL URL -> raise `RuntimeError`

Also added:
- `PORTAL_JSON_MIGRATION_ENABLED=1` only when you explicitly want to import `portal_data.json`.
- Default is disabled to keep JSON out of normal runtime.

## 3) Core Flow Smoke Validation
- Ran automated flow smoke (temporary DB):
  - admin create/login
  - team create
  - event create
  - attendance upsert/read
  - CSV export
- Result: `flow smoke ok`
