from flask import Response, redirect, render_template, request, url_for


def register_store_web_routes(
    app,
    *,
    attendance_app_base_url,
    build_contact_page_context,
    is_contact_email_configured,
    is_valid_email,
    send_contact_form_email,
):
    def home():
        status = request.args.get("contact_status", "").strip().lower()
        if status not in {"sent"}:
            status = ""
        return render_template("home.html", **build_contact_page_context(status=status))

    def contact_submit():
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        prefill = {
            "name": name,
            "email": email,
            "subject": subject,
            "message": message,
        }

        if not name:
            error_message = "お名前を入力してください。"
        elif not is_valid_email(email):
            error_message = "返信先のメールアドレスを正しく入力してください。"
        elif not subject:
            error_message = "件名を入力してください。"
        elif len(subject) > 120:
            error_message = "件名は120文字以内で入力してください。"
        elif not message:
            error_message = "ご相談内容を入力してください。"
        elif len(message) > 3000:
            error_message = "ご相談内容は3000文字以内で入力してください。"
        elif not is_contact_email_configured():
            error_message = "問い合わせメール設定がまだ完了していません。"
        else:
            error_message = ""

        if error_message:
            return (
                render_template(
                    "home.html",
                    **build_contact_page_context(
                        error_message=error_message,
                        prefill=prefill,
                    ),
                ),
                400,
            )

        try:
            send_contact_form_email(
                name=name,
                email=email,
                subject=subject,
                message=message,
                remote_addr=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
                user_agent=request.headers.get("User-Agent", ""),
            )
        except Exception:
            return (
                render_template(
                    "home.html",
                    **build_contact_page_context(
                        error_message="送信に失敗しました。時間をおいて再度お試しください。",
                        prefill=prefill,
                    ),
                ),
                502,
            )

        return redirect(url_for("home", contact_status="sent"))

    def attendance_description():
        configured_base_url = (attendance_app_base_url or "").strip().rstrip("/")
        current_root = request.url_root.rstrip("/")
        if configured_base_url and current_root != configured_base_url:
            return redirect(f"{configured_base_url}{request.path}")
        return render_template("landing.html")

    def apps_list():
        return render_template("apps.html")

    def shift_app():
        return render_template("shift.html")

    def qrcode_app():
        return render_template("qrcode.html")

    def noticeboard_app():
        return render_template("noticeboard.html")

    def blog_index():
        return render_template("blog.html")

    def blog_sports_attendance():
        return render_template("blog_sports_attendance.html")

    def blog_pta_attendance():
        return render_template("blog_pta_attendance.html")

    def blog_attendance_management_app():
        return render_template("blog_attendance_management_app.html")

    def sitemap():
        sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://mossan-store.com/</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/apps</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/blog</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/blog/sports-attendance</loc>
  </url>
  <url>
    <loc>https://mossan-store.com/blog/pta-attendance</loc>
  </url>
</urlset>"""
        return Response(sitemap_xml, content_type="application/xml; charset=utf-8")

    def robots():
        robots_txt = """User-agent: *
Allow: /
Sitemap: https://mossan-store.com/sitemap.xml"""
        return Response(robots_txt, content_type="text/plain; charset=utf-8")

    app.add_url_rule("/", endpoint="home", view_func=home)
    app.add_url_rule("/contact", endpoint="contact_submit", view_func=contact_submit, methods=["POST"])
    app.add_url_rule(
        "/apps/attendance/app/description",
        endpoint="attendance_description",
        view_func=attendance_description,
    )
    app.add_url_rule("/apps", endpoint="apps_list", view_func=apps_list)
    app.add_url_rule("/apps/shift", endpoint="shift_app", view_func=shift_app)
    app.add_url_rule("/apps/qrcode", endpoint="qrcode_app", view_func=qrcode_app)
    app.add_url_rule("/apps/noticeboard", endpoint="noticeboard_app", view_func=noticeboard_app)
    app.add_url_rule("/blog", endpoint="blog_index", view_func=blog_index)
    app.add_url_rule(
        "/blog/sports-attendance",
        endpoint="blog_sports_attendance",
        view_func=blog_sports_attendance,
    )
    app.add_url_rule("/blog/pta-attendance", endpoint="blog_pta_attendance", view_func=blog_pta_attendance)
    app.add_url_rule(
        "/blog/attendance-management-app",
        endpoint="blog_attendance_management_app",
        view_func=blog_attendance_management_app,
    )
    app.add_url_rule("/sitemap.xml", endpoint="sitemap", view_func=sitemap)
    app.add_url_rule("/robots.txt", endpoint="robots", view_func=robots)
