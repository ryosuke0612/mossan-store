# attendance-app

Future responsibility:

- attendance board main app
- admin portal
- site admin screens
- public/team attendance pages
- login, payment, and attendance tools

Current routes that should move here over time:

- `/admin/*`
- `/site-admin/*`
- `/team/<public_id>/*`
- `/apps/attendance/app/*`
- `/apps/attendance/share/<share_id>`

Notes:

- This service should keep the main DB responsibility.
- Attendance-specific logic should stay here unless real cross-service reuse appears.
- Current local entry point: `services/attendance-app/app.py`
- Current behavior: wraps the root Flask app and exposes only attendance-app routes
