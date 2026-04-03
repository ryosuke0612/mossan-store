from flask import redirect, render_template, request, session, url_for


def register_attendance_portal_routes(
    app,
    *,
    build_event_list_csv_response,
    datetime,
    get_db_connection,
    login_required,
):
    def register():
        return redirect(url_for("admin_login_entry"))

    def login():
        return redirect(url_for("admin_login_entry"))

    def logout():
        session.clear()
        return redirect(url_for("admin_login_entry"))

    def payment():
        plan_prices = {
            "ベーシックプラン": 980,
            "スタンダードプラン": 1980,
            "プレミアムプラン": 2980,
        }

        error_message = ""
        success_message = ""

        if request.method == "POST":
            plan_name = request.form.get("plan_name", "").strip()

            if plan_name not in plan_prices:
                error_message = "プランを選択してください。"
            else:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute(
                    """
                    INSERT INTO payments (user_id, plan_name, amount, status, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        session["user_id"],
                        plan_name,
                        plan_prices[plan_name],
                        "PAID",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
                conn.close()
                success_message = f"{plan_name} の決済が完了しました。"

        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            """
            SELECT plan_name, amount, status, created_at
            FROM payments
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 10
            """,
            (session["user_id"],),
        )
        recent_payments = c.fetchall()
        conn.close()

        return render_template(
            "payment.html",
            plan_prices=plan_prices,
            error_message=error_message,
            success_message=success_message,
            recent_payments=recent_payments,
            team_name=session.get("team_name") or session.get("username", ""),
        )

    def index():
        return redirect(url_for("admin_dashboard"))

    def export_attendance_csv():
        month = request.args.get("month", "all").strip() or "all"
        return build_event_list_csv_response(session["user_id"], month)

    app.add_url_rule(
        "/apps/attendance/app/register",
        endpoint="register",
        view_func=register,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/login",
        endpoint="login",
        view_func=login,
        methods=["GET", "POST"],
    )
    app.add_url_rule("/apps/attendance/app/logout", endpoint="logout", view_func=logout)
    app.add_url_rule(
        "/apps/attendance/app/payment",
        endpoint="payment",
        view_func=login_required(payment),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app",
        endpoint="index",
        view_func=login_required(index),
    )
    app.add_url_rule(
        "/apps/attendance/app/csv",
        endpoint="export_attendance_csv",
        view_func=login_required(export_attendance_csv),
    )
