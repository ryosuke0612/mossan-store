from flask import redirect, render_template, request, session, url_for


def register_admin_core_routes(
    app,
    *,
    ADMIN_FREE_TEAM_LIMIT,
    ADMIN_PLAN_REQUESTS_ENABLED,
    PLAN_FEATURE_TEAM_CREATE,
    admin_login_required,
    build_admin_dashboard_team_guides,
    can_admin_create_team,
    get_admin_plan_type,
    get_plan_restriction_message,
    get_teams_for_admin,
    is_site_admin_email,
    portal_authenticate_admin,
    portal_create_admin,
    portal_create_team,
    portal_get_admin,
    portal_get_admin_by_email,
    portal_touch_admin_last_login,
    portal_update_admin_credentials,
):
    def admin_login_entry():
        next_url = request.args.get("next") or request.form.get("next") or url_for("admin_dashboard")
        error_message = ""
        info_message = ""

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not email or "@" not in email:
                error_message = "メールアドレスを入力してください。"
            elif len(password) < 8:
                error_message = "パスワードは8文字以上で入力してください。"
            else:
                existing_admin = portal_get_admin_by_email(email)

                if existing_admin:
                    admin, auth_status = portal_authenticate_admin(email, password)
                    if admin:
                        portal_touch_admin_last_login(admin["id"])
                        session["admin_id"] = admin["id"]
                        session["admin_email"] = admin["email"]
                        session["is_site_admin"] = is_site_admin_email(admin["email"])
                        if auth_status == "password_initialized":
                            return redirect(
                                url_for(
                                    "admin_dashboard",
                                    success_message="管理者パスワードを設定しました。",
                                )
                            )
                        return redirect(next_url)
                    error_message = "メールアドレスまたはパスワードが正しくありません。"
                else:
                    admin = portal_create_admin(email, password)
                    if admin:
                        portal_touch_admin_last_login(admin["id"])
                        session["admin_id"] = admin["id"]
                        session["admin_email"] = admin["email"]
                        session["is_site_admin"] = is_site_admin_email(admin["email"])
                        return redirect(
                            url_for(
                                "admin_dashboard",
                                success_message="管理者アカウントを作成しました。",
                            )
                        )
                    error_message = "管理者アカウントを作成できませんでした。時間をおいて再度お試しください。"

        info_message = "メールアドレスが未登録の場合、自動的に新規アカウント登録になります。"

        return render_template(
            "admin_portal_login_v2.html",
            error_message=error_message,
            info_message=info_message,
            next_url=next_url,
        )

    def admin_dashboard():
        admin = portal_get_admin(session["admin_id"])
        if not admin:
            session.pop("admin_id", None)
            session.pop("admin_email", None)
            session.pop("is_site_admin", None)
            return redirect(url_for("admin_login_entry"))
        teams = get_teams_for_admin(session["admin_id"])
        error_message = request.args.get("error_message", "").strip()
        success_message = request.args.get("success_message", "").strip()
        can_create_team = can_admin_create_team(admin, len(teams))

        if request.method == "POST":
            team_name = request.form.get("team_name", "").strip()
            if not team_name:
                error_message = "チーム名を入力してください。"
            elif not can_admin_create_team(admin, len(teams)):
                error_message = get_plan_restriction_message(PLAN_FEATURE_TEAM_CREATE)
            else:
                portal_create_team(session["admin_id"], team_name)
                success_message = "チームを作成しました。"
                teams = get_teams_for_admin(session["admin_id"])
                can_create_team = can_admin_create_team(admin, len(teams))

        guided_teams = build_admin_dashboard_team_guides(teams)
        return render_template(
            "admin_dashboard_cards_v2.html",
            admin_email=session.get("admin_email", ""),
            teams=guided_teams,
            can_create_team=can_create_team,
            highlight_create_team=not guided_teams and can_create_team,
            admin_plan_requests_enabled=ADMIN_PLAN_REQUESTS_ENABLED,
            team_limit_message=get_plan_restriction_message(PLAN_FEATURE_TEAM_CREATE),
            free_team_limit=ADMIN_FREE_TEAM_LIMIT,
            current_plan_type=get_admin_plan_type(admin),
            error_message=error_message,
            success_message=success_message,
        )

    def admin_account_settings():
        error_message = request.args.get("error_message", "").strip()
        success_message = request.args.get("success_message", "").strip()

        admin = portal_get_admin(session["admin_id"])
        if not admin:
            session.pop("admin_id", None)
            session.pop("admin_email", None)
            return redirect(url_for("admin_login_entry"))

        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_email = request.form.get("email", "").strip().lower()
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if len(current_password) < 8:
                error_message = "現在のパスワードを入力してください。"
            elif new_password and len(new_password) < 8:
                error_message = "新しいパスワードは8文字以上で入力してください。"
            elif new_password != confirm_password:
                error_message = "新しいパスワードが確認用と一致しません。"
            else:
                updated_admin, status = portal_update_admin_credentials(
                    session["admin_id"],
                    current_password,
                    new_email,
                    new_password,
                )
                if updated_admin:
                    session["admin_email"] = updated_admin["email"]
                    session["is_site_admin"] = is_site_admin_email(updated_admin["email"])
                    admin = updated_admin
                    success_message = "管理者アカウント情報を更新しました。"
                elif status == "invalid_password":
                    error_message = "現在のパスワードが正しくありません。"
                elif status == "invalid_email":
                    error_message = "有効なメールアドレスを入力してください。"
                elif status == "email_taken":
                    error_message = "そのメールアドレスはすでに使用されています。"
                else:
                    error_message = "管理者情報を更新できませんでした。"

        return render_template(
            "admin_account_settings.html",
            admin_email=admin["email"],
            error_message=error_message,
            success_message=success_message,
        )

    def admin_logout():
        session.pop("admin_id", None)
        session.pop("admin_email", None)
        session.pop("is_site_admin", None)
        return redirect(url_for("admin_login_entry"))

    app.add_url_rule(
        "/admin/login",
        endpoint="admin_login_entry",
        view_func=admin_login_entry,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/admin",
        endpoint="admin_dashboard_root",
        view_func=admin_login_required(admin_dashboard),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/admin/dashboard",
        endpoint="admin_dashboard",
        view_func=admin_login_required(admin_dashboard),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/admin/account",
        endpoint="admin_account_settings",
        view_func=admin_login_required(admin_account_settings),
        methods=["GET", "POST"],
    )
    app.add_url_rule("/admin/logout", endpoint="admin_logout", view_func=admin_logout)
