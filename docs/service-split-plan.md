# Mossan Store Service Split Plan

## Current structure summary

- Current entry point: `app.py`
- Current templates directory: `templates/`
- Current static directory: `static/`
- Current deploy setting: `render.yaml` runs a single Flask app with `gunicorn app:app`
- Current DB handling lives in `app.py`
  - environment loading and app bootstrapping
  - SQLite / PostgreSQL switching
  - schema creation / migration helpers
  - attendance and portal data access

## Current responsibilities in the single app

### Store-web side routes

These routes are already close to the future `store-web` responsibility.

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

### Attendance-app side routes

These routes should stay with the future `attendance-app` service.

- `/admin/*`
- `/site-admin/*`
- `/team/<public_id>/*`
- `/apps/attendance/app/*`
- `/apps/attendance/share/<share_id>`

### Current template grouping

Store-web oriented templates:

- `templates/home.html`
- `templates/apps.html`
- `templates/landing.html`
- `templates/blog.html`
- `templates/blog_*.html`
- `templates/base.html`
- marketing-oriented images under `static/images/`

Attendance-app oriented templates:

- `templates/admin_*.html`
- `templates/site_admin_*.html`
- `templates/attendance*.html`
- `templates/public_*.html`
- `templates/member_*.html`
- `templates/login.html`
- `templates/register.html`
- `templates/payment.html`
- `templates/add.html`
- `templates/edit.html`

Mixed or needs later judgment:

- `templates/base.html`
- `static/css/style.css`
- `static/favicon.ico`
- `static/attendance-board-favicon.svg`

## Proposed service ownership

### `services/store-web`

Owns:

- top page
- contact page handling
- blog pages
- app summary / app guide pages
- app directory pages
- SEO files such as sitemap and robots

Should avoid:

- direct attendance DB reads
- admin login flows
- team/member operational pages

### `services/attendance-app`

Owns:

- admin portal
- site admin screens
- attendance board main app
- member/public attendance pages
- attendance check tools
- payment/login flows tied to the app
- attendance and team operational data

### `shared`

Good early candidates only after real duplication appears:

- environment variable loading
- settings access
- DB connection adapter
- date/time formatting helpers
- generic query / row conversion helpers
- generic URL/query helpers
- generic validation helpers

Keep out of `shared` for now:

- attendance-specific business rules
- admin portal behavior
- member/team page logic
- plan restriction wording tied only to attendance-app

## Safe migration steps

### Step 1: create the destination structure first

Goal:

- add `services/store-web/`
- add `services/attendance-app/`
- add `shared/`
- document what will move later

Why this is safe:

- no route behavior changes
- current deploy stays intact
- easy to compare before/after

### Step 2: split code by module before changing deployment

Goal:

- move store-web routes into a dedicated module or blueprint
- move attendance-app routes into a dedicated module or blueprint
- keep a single runtime entry point temporarily

Why this is safe:

- Render still runs one service during the refactor
- route behavior can be checked locally without service separation yet

### Step 3: separate template/static ownership gradually

Goal:

- copy or move store-web templates into `services/store-web/templates/`
- copy or move attendance templates into `services/attendance-app/templates/`
- only extract shared assets after duplication is confirmed

Local checks:

- home page
- blog pages
- admin login
- admin dashboard
- public team page
- attendance month / check flows

### Step 4: prepare separate runtime entry points

Goal:

- create service-local `app.py`
- create service-local `requirements.txt`
- choose what each service imports from `shared/`

Why this is safe:

- can be done after blueprint/module split is stable
- each service can be smoke-tested independently

### Step 5: switch Render to multi-service deployment

Goal:

- keep `store-web` and `attendance-app` as separate Render web services
- connect PostgreSQL primarily to `attendance-app`
- keep `store-web` DB usage minimal or none

Recommendation:

- do not replace the current `render.yaml` yet
- use `render.multiservice.example.yaml` as the future target

## What was implemented in this step

- added `services/` scaffolding
- added service ownership notes under each future service
- added `shared/` placeholder guidance
- added a separate Render multi-service example file
- added service-local `app.py` entry points that safely wrap the root Flask app
- added service-local `requirements.txt` files that reuse the root dependency list
- extracted `store-web` route registration from `app.py` into `service_modules/store_web_routes.py`
- extracted `attendance-app` route registration into dedicated `service_modules/*` files
- added service-local template/static override loading in `shared/service_host.py`
- copied the first representative templates into each service folder as a safe intermediate move
- copied the first representative base templates, images, and favicons into service-local `templates/` and `static/`
- copied additional `store-web` blog/guide templates and `attendance-app` admin/site-admin templates into service-local folders
- copied additional `attendance-app` public/member/legacy app templates into service-local folders
- copied the remaining root-only templates into service-local folders, leaving only non-runtime static mockup assets at the root
- added `create_app()` entry points for the root app and both service apps as an intermediate step toward real app factories
- moved shared env-loading and DB wrapper helpers into `shared/` as the first safe common runtime extraction
- moved low-risk runtime settings (`SECRET_KEY`, DB URL flags, SQLite default path, Render flags) behind a shared runtime settings helper
- moved the remaining legacy `/apps/attendance/app/*` attendance routes into `service_modules/legacy_attendance_routes.py`, reducing direct route ownership inside the root `app.py`
- changed the attendance app introduction page so `attendance-app` is the primary home, while `store-web` can redirect there when `ATTENDANCE_APP_BASE_URL` is configured

This keeps the current app runnable while making the intended split explicit.

## Current local run options

At this stage, there are now three safe ways to run the project locally:

- root app: `python app.py`
- store-web view: `python services/store-web/app.py`
- attendance-app view: `python services/attendance-app/app.py`

Important note:

- the service-local entry points still depend on the root `app.py`
- they currently restrict exposed paths instead of fully splitting implementation code
- this is an intermediate step before moving route code into separate modules

## Current progress toward the final goal

Completed:

- service destination folders exist
- service-local entry points exist
- `store-web` routes are no longer defined inline inside the root `app.py`

Not completed yet:

- some `attendance-app` routes still remain inside the root `app.py`
- many templates and static files still fall back to the root folders
- service-local static assets now work for the first copied files, but most assets still fall back to the root folders
- many major pages now have service-local template copies, but template fallback to the root folders is still in use for the rest
- all current runtime templates now have service-local copies, while fallback remains available and root-only leftovers are now mostly mockup/static reference files
- service entry points now support `create_app()` style startup, but still build from the shared root implementation underneath
- root app still holds most business logic, but low-risk runtime setup is beginning to move into `shared/`
- root app still holds most business logic, but shared runtime setup now covers env loading, settings resolution, and DB wrappers
- service-local apps still import the root app during startup
- Render is still using the single-service live configuration

Recommended next implementation step:

- continue moving templates and static files in small service-based groups while keeping root fallback
