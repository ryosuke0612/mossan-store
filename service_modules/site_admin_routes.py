from datetime import datetime, timedelta

from flask import redirect, render_template, request, session, url_for


def register_site_admin_routes(
    app,
    *,
    ADMIN_ACCOUNT_STATUS_ACTIVE,
    ADMIN_ACCOUNT_STATUS_EXPIRED,
    ADMIN_ACCOUNT_STATUS_SUSPENDED,
    ADMIN_EXPIRY_UNLIMITED,
    ADMIN_FREE_TEAM_LIMIT,
    ADMIN_PLAN_FREE,
    ADMIN_PLAN_PAID,
    ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE,
    ADMIN_PLAN_REQUEST_STATUS_APPROVED,
    ADMIN_PLAN_REQUEST_STATUS_PENDING,
    ADMIN_PLAN_REQUEST_STATUS_REJECTED,
    SITE_ADMIN_EMAILS,
    append_query_params,
    enrich_admin_billing_history_rows,
    enrich_admin_plan_request_rows,
    enrich_site_admin_row,
    normalize_admin_account_status,
    normalize_admin_plan_request_payment_method,
    normalize_admin_plan_request_status,
    normalize_admin_plan_type,
    portal_force_delete_admin,
    portal_get_admin,
    portal_get_admin_billing_history,
    portal_get_admin_plan_request,
    portal_get_admin_plan_requests,
    portal_get_admin_summaries,
    portal_get_team_details_for_admin,
    portal_review_admin_plan_request,
    portal_set_admin_expiry,
    portal_update_admin_profile_fields,
    resolve_admin_expiry_datetime,
    site_admin_required,
):
    def site_admin_dashboard():
        admin_rows = portal_get_admin_summaries()
        pending_plan_request_count = len(
            portal_get_admin_plan_requests(status=ADMIN_PLAN_REQUEST_STATUS_PENDING, limit=500)
        )
        error_message = request.args.get("error_message", "").strip()
        success_message = request.args.get("success_message", "").strip()
        for row in admin_rows:
            enrich_site_admin_row(row)

        return render_template(
            "site_admin_dashboard.html",
            admin_rows=admin_rows,
            error_message=error_message,
            success_message=success_message,
            site_admin_emails=sorted(SITE_ADMIN_EMAILS),
            pending_plan_request_count=pending_plan_request_count,
        )

    def site_admin_plan_requests():
        request_rows = enrich_admin_plan_request_rows(portal_get_admin_plan_requests(limit=300))
        pending_count = len(portal_get_admin_plan_requests(status=ADMIN_PLAN_REQUEST_STATUS_PENDING, limit=500))
        return render_template(
            "site_admin_plan_requests.html",
            request_rows=request_rows,
            pending_count=pending_count,
            error_message=request.args.get("error_message", "").strip(),
            success_message=request.args.get("success_message", "").strip(),
        )

    def site_admin_review_plan_request(request_id):
        request_row = portal_get_admin_plan_request(request_id)
        if not request_row:
            return redirect(url_for("site_admin_plan_requests", error_message="申請が見つかりません。"))
        payment_method = normalize_admin_plan_request_payment_method(request_row.get("payment_method"))
        if payment_method == ADMIN_PLAN_REQUEST_PAYMENT_METHOD_STRIPE:
            return redirect(
                url_for(
                    "site_admin_plan_requests",
                    error_message="Stripe決済の承認操作は廃止されました。Stripe再確認で自動反映状況を確認してください。",
                )
            )

        decision = normalize_admin_plan_request_status(request.form.get("decision"))
        if decision not in {ADMIN_PLAN_REQUEST_STATUS_APPROVED, ADMIN_PLAN_REQUEST_STATUS_REJECTED}:
            return redirect(url_for("site_admin_plan_requests", error_message="判定の値が不正です。"))

        review_note = request.form.get("review_note", "").strip()
        if len(review_note) > 1000:
            return redirect(url_for("site_admin_plan_requests", error_message="審査メモは1000文字以内で入力してください。"))

        reviewed, status = portal_review_admin_plan_request(request_id, session["admin_id"], decision, review_note)
        if reviewed:
            message = "申請を承認しました。" if decision == ADMIN_PLAN_REQUEST_STATUS_APPROVED else "申請を却下しました。"
            return redirect(url_for("site_admin_plan_requests", success_message=message))

        error_message = "申請を更新できませんでした。"
        if status == "already_reviewed":
            error_message = "この申請はすでに処理済みです。"
        elif status == "not_found":
            error_message = "申請が見つかりません。"
        elif status == "admin_not_found":
            error_message = "対象の管理者が見つかりません。"
        elif status == "legacy_payment_method_not_supported":
            error_message = "旧決済方式の申請は承認できません。必要な場合はStripeで再申請してください。"
        elif status == "stripe_payment_not_found":
            error_message = "紐付いたStripe決済が見つからないため承認できません。"
        elif status == "stripe_payment_refresh_failed":
            error_message = "Stripe決済の再確認に失敗したため承認できません。"
        elif status == "stripe_payment_not_completed":
            error_message = "Stripe決済の完了を再確認できなかったため承認できません。"
        return redirect(url_for("site_admin_plan_requests", error_message=error_message))

    def site_admin_admin_detail(admin_id):
        admin = portal_get_admin(admin_id)
        if not admin:
            return redirect(url_for("site_admin_dashboard", error_message="対象の管理者が見つかりません。"))

        team_details = portal_get_team_details_for_admin(admin_id)
        billing_history = enrich_admin_billing_history_rows(portal_get_admin_billing_history(admin_id, limit=20))
        enrich_site_admin_row(admin, team_details=team_details)
        return render_template(
            "site_admin_admin_detail.html",
            admin=admin,
            billing_history=billing_history,
            free_team_limit=ADMIN_FREE_TEAM_LIMIT,
            error_message=request.args.get("error_message", "").strip(),
            success_message=request.args.get("success_message", "").strip(),
        )

    def site_admin_update_admin_plan(admin_id):
        admin = portal_get_admin(admin_id)
        if not admin:
            return redirect(url_for("site_admin_dashboard", error_message="対象の管理者が見つかりません。"))

        plan_type = normalize_admin_plan_type(request.form.get("plan_type"))
        if not plan_type:
            return redirect(url_for("site_admin_admin_detail", admin_id=admin_id, error_message="プランの値が不正です。"))

        legacy_status = ADMIN_PLAN_PAID if plan_type == ADMIN_PLAN_PAID else ADMIN_PLAN_FREE
        current_account_status = normalize_admin_account_status(admin.get("account_status")) or ADMIN_ACCOUNT_STATUS_ACTIVE
        if current_account_status in {ADMIN_ACCOUNT_STATUS_SUSPENDED, ADMIN_ACCOUNT_STATUS_EXPIRED}:
            legacy_status = current_account_status
        if portal_update_admin_profile_fields(admin_id, plan_type=plan_type, status=legacy_status):
            return redirect(url_for("site_admin_admin_detail", admin_id=admin_id, success_message="プランを更新しました。"))
        return redirect(url_for("site_admin_admin_detail", admin_id=admin_id, error_message="プランを更新できませんでした。"))

    def site_admin_update_admin_account_status(admin_id):
        admin = portal_get_admin(admin_id)
        if not admin:
            return redirect(url_for("site_admin_dashboard", error_message="対象の管理者が見つかりません。"))

        next_url = request.form.get("next_url", "").strip()
        fallback_url = url_for("site_admin_admin_detail", admin_id=admin_id)
        redirect_target = next_url or fallback_url

        account_status = normalize_admin_account_status(request.form.get("account_status"))
        if not account_status or account_status == ADMIN_ACCOUNT_STATUS_EXPIRED:
            return redirect(append_query_params(redirect_target, error_message="利用状態の値が不正です。"))

        plan_type = normalize_admin_plan_type(admin.get("plan_type")) or ADMIN_PLAN_PAID
        legacy_status = account_status
        if account_status == ADMIN_ACCOUNT_STATUS_ACTIVE:
            legacy_status = ADMIN_PLAN_PAID if plan_type == ADMIN_PLAN_PAID else ADMIN_PLAN_FREE
        if portal_update_admin_profile_fields(admin_id, account_status=account_status, status=legacy_status):
            return redirect(append_query_params(redirect_target, success_message="利用状態を更新しました。"))
        return redirect(append_query_params(redirect_target, error_message="利用状態を更新できませんでした。"))

    def site_admin_update_admin_memo(admin_id):
        admin = portal_get_admin(admin_id)
        if not admin:
            return redirect(url_for("site_admin_dashboard", error_message="対象の管理者が見つかりません。"))

        admin_memo = request.form.get("admin_memo", "").strip()
        if len(admin_memo) > 5000:
            return redirect(url_for("site_admin_admin_detail", admin_id=admin_id, error_message="メモは5000文字以内で入力してください。"))

        if portal_update_admin_profile_fields(admin_id, admin_memo=admin_memo):
            return redirect(url_for("site_admin_admin_detail", admin_id=admin_id, success_message="メモを保存しました。"))
        return redirect(url_for("site_admin_admin_detail", admin_id=admin_id, error_message="メモを保存できませんでした。"))

    def site_admin_delete_admin_confirmed(admin_id):
        admin = portal_get_admin(admin_id)
        if not admin:
            return redirect(url_for("site_admin_dashboard", error_message="対象の管理者が見つかりません。"))

        confirm_email = request.form.get("confirm_email", "").strip().lower()
        if confirm_email != (admin.get("email") or "").strip().lower():
            return redirect(
                url_for(
                    "site_admin_admin_detail",
                    admin_id=admin_id,
                    error_message="削除確認のメールアドレスが一致しません。",
                )
            )

        deleted = portal_force_delete_admin(admin_id)
        if deleted:
            return redirect(url_for("site_admin_dashboard", success_message="管理者を削除しました。"))
        return redirect(url_for("site_admin_admin_detail", admin_id=admin_id, error_message="管理者を削除できませんでした。"))

    def site_admin_delete_admin(admin_id):
        deleted = portal_force_delete_admin(admin_id)
        if deleted:
            return redirect(url_for("site_admin_dashboard", success_message="管理者を削除しました。"))
        return redirect(url_for("site_admin_dashboard", error_message="管理者を削除できませんでした。"))

    def site_admin_extend_admin(admin_id):
        extend_days_raw = request.form.get("extend_days", "").strip()
        if extend_days_raw.lower() == "unlimited":
            extend_days = None
        else:
            try:
                extend_days = int(extend_days_raw)
            except ValueError:
                return redirect(url_for("site_admin_dashboard", error_message="延長日数が不正です。"))
            if extend_days <= 0:
                return redirect(url_for("site_admin_dashboard", error_message="延長日数は1日以上で指定してください。"))
            if extend_days > 3650:
                return redirect(url_for("site_admin_dashboard", error_message="延長日数が大きすぎます。"))

        admin = portal_get_admin(admin_id)
        if not admin:
            return redirect(url_for("site_admin_dashboard", error_message="対象の管理者が見つかりません。"))

        if extend_days is None:
            if portal_set_admin_expiry(admin_id, ADMIN_EXPIRY_UNLIMITED):
                return redirect(
                    url_for(
                        "site_admin_dashboard",
                        success_message=f"{admin.get('email', '管理者')}の利用期限を無期限にしました。",
                    )
                )
            return redirect(url_for("site_admin_dashboard", error_message="利用期限を更新できませんでした。"))

        now_dt = datetime.now()
        effective_expiry = resolve_admin_expiry_datetime(admin.get("created_at"), admin.get("expires_at"))
        base_dt = effective_expiry if (effective_expiry and effective_expiry > now_dt) else now_dt
        updated_expiry = (base_dt + timedelta(days=extend_days)).strftime("%Y-%m-%d %H:%M:%S")
        if portal_set_admin_expiry(admin_id, updated_expiry):
            return redirect(
                url_for(
                    "site_admin_dashboard",
                    success_message=f"{admin.get('email', '管理者')}の利用期限を{extend_days}日延長しました。",
                )
            )
        return redirect(url_for("site_admin_dashboard", error_message="利用期限を延長できませんでした。"))

    app.add_url_rule("/site-admin", endpoint="site_admin_dashboard_root", view_func=site_admin_required(site_admin_dashboard))
    app.add_url_rule("/site-admin/dashboard", endpoint="site_admin_dashboard", view_func=site_admin_required(site_admin_dashboard))
    app.add_url_rule("/site-admin/plan-requests", endpoint="site_admin_plan_requests", view_func=site_admin_required(site_admin_plan_requests))
    app.add_url_rule(
        "/site-admin/plan-requests/<int:request_id>/review",
        endpoint="site_admin_review_plan_request",
        view_func=site_admin_required(site_admin_review_plan_request),
        methods=["POST"],
    )
    app.add_url_rule("/site-admin/admins/<int:admin_id>", endpoint="site_admin_admin_detail", view_func=site_admin_required(site_admin_admin_detail))
    app.add_url_rule(
        "/site-admin/admins/<int:admin_id>/plan",
        endpoint="site_admin_update_admin_plan",
        view_func=site_admin_required(site_admin_update_admin_plan),
        methods=["POST"],
    )
    app.add_url_rule(
        "/site-admin/admins/<int:admin_id>/account-status",
        endpoint="site_admin_update_admin_account_status",
        view_func=site_admin_required(site_admin_update_admin_account_status),
        methods=["POST"],
    )
    app.add_url_rule(
        "/site-admin/admins/<int:admin_id>/memo",
        endpoint="site_admin_update_admin_memo",
        view_func=site_admin_required(site_admin_update_admin_memo),
        methods=["POST"],
    )
    app.add_url_rule(
        "/site-admin/admins/<int:admin_id>/delete-confirmed",
        endpoint="site_admin_delete_admin_confirmed",
        view_func=site_admin_required(site_admin_delete_admin_confirmed),
        methods=["POST"],
    )
    app.add_url_rule(
        "/site-admin/admins/<int:admin_id>/delete",
        endpoint="site_admin_delete_admin",
        view_func=site_admin_required(site_admin_delete_admin),
        methods=["POST"],
    )
    app.add_url_rule(
        "/site-admin/admins/<int:admin_id>/extend",
        endpoint="site_admin_extend_admin",
        view_func=site_admin_required(site_admin_extend_admin),
        methods=["POST"],
    )
