# store-web

Future responsibility:

- top page
- blog
- app summary pages
- marketing pages
- links to each app

Current routes that should move here over time:

- `/`
- `/contact`
- `/apps`
- `/apps/shift`
- `/apps/qrcode`
- `/apps/noticeboard`
- `/apps/attendance/app/description`
- `/blog`
- `/blog/sports-attendance`
- `/blog/pta-attendance`
- `/blog/attendance-management-app`
- `/sitemap.xml`
- `/robots.txt`

Notes:

- Keep DB dependence light.
- Avoid reading attendance operational tables directly where possible.
- During the first migration stages, code may still live in the root `app.py`.
- Current local entry point: `services/store-web/app.py`
- Current behavior: wraps the root Flask app and exposes only store-web routes
