import os

from flask import Flask, redirect


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    @app.get("/")
    def root_index():
        attendance_url = (os.environ.get("ATTENDANCE_APP_BASE_URL") or "").strip().rstrip("/")
        store_url = (os.environ.get("STORE_WEB_BASE_URL") or "").strip().rstrip("/")

        store_link = store_url or "/"
        attendance_link = attendance_url or "/attendance"

        return f"""
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mossan Store Workspace</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #111827;
      color: #f9fafb;
    }}
    main {{
      max-width: 760px;
      margin: 72px auto;
      padding: 0 24px;
    }}
    .card {{
      background: #1f2937;
      border: 1px solid #374151;
      border-radius: 18px;
      padding: 24px;
      margin-top: 18px;
    }}
    a {{
      color: #93c5fd;
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
    code {{
      background: #0f172a;
      padding: 2px 6px;
      border-radius: 6px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Mossan Store Workspace</h1>
    <p>root の <code>app.py</code> は互換用の軽量入口です。サービス本体は各サービス配下に分離されています。</p>
    <div class="card">
      <h2>Active Services</h2>
      <p><a href="{store_link}">store-web</a></p>
      <p><a href="{attendance_link}">attendance-app</a></p>
    </div>
    <div class="card">
      <h2>Legacy App</h2>
      <p>旧モノリス本体は <code>legacy/root_monolith_app.py</code> に退避しています。</p>
    </div>
  </main>
</body>
</html>
"""

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "mode": "workspace-root"}

    @app.get("/attendance")
    def attendance_redirect():
        attendance_url = (os.environ.get("ATTENDANCE_APP_BASE_URL") or "").strip().rstrip("/")
        if attendance_url:
            return redirect(f"{attendance_url}/admin/login")
        return redirect("/")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
