from flask import redirect, render_template, request, url_for


def register_public_team_core_routes(
    app,
    *,
    PLAN_FEATURE_ATTENDANCE_CHECK,
    PLAN_FEATURE_CSV_EXPORT,
    _normalize_name_list,
    build_member_legacy_index_context,
    build_member_page_notice_redirect,
    can_team_use_paid_feature,
    get_plan_restriction_message,
    get_team_by_public_id,
    normalize_status,
    portal_build_event_list_csv_response,
    portal_get_event,
    portal_get_attendance,
    portal_get_events,
    portal_get_members_for_team,
    portal_upsert_attendance,
    redirect_to_team_month,
):
    def member_team_page(public_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return render_template(
                "public_index_v2.html",
                team_name="Guest",
                months=[],
                can_use_attendance_check=True,
                can_use_csv_export=True,
                plan_attendance_check_message=get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK),
                plan_csv_message=get_plan_restriction_message(PLAN_FEATURE_CSV_EXPORT),
                error_message="",
            ), 404

        active_members = portal_get_members_for_team(team["id"], include_inactive=False)
        active_member_names = [member.get("name") for member in active_members if member.get("name")]
        if request.method == "POST":
            month = request.form.get("month", "").strip()
            filter_name = request.form.get("filter_name", "").strip()
            member_name = request.form.get("member_name", "").strip()
            status = normalize_status(request.form.get("status", ""))
            try:
                match_id = int(request.form.get("match_id", "0"))
            except (TypeError, ValueError):
                return redirect(url_for("member_team_page", public_id=public_id, month=month, name=filter_name or ""))

            if filter_name and filter_name not in active_member_names:
                filter_name = ""
            if member_name in active_member_names and status:
                match = portal_get_event(team["id"], match_id)
                if match:
                    portal_upsert_attendance(team["id"], match_id, member_name, status)

            return redirect(url_for("member_team_page", public_id=public_id, month=month, name=filter_name or ""))

        active_month = request.args.get("month", "").strip()
        selected_member = request.args.get("name", "").strip()
        context = build_member_legacy_index_context(team, active_month, selected_member)
        context["error_message"] = request.args.get("error_message", "").strip()
        return render_template("public_index_v2.html", **context)

    def public_add_match(public_id):
        return redirect(url_for("member_team_page", public_id=public_id))

    def public_delete_match(public_id, id):
        return redirect(url_for("member_team_page", public_id=public_id))

    def public_duplicate_match(public_id, id):
        return redirect(url_for("member_team_page", public_id=public_id))

    def public_bulk_match_action(public_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))

        action = request.form.get("action", "")
        current_month = request.form.get("current_month", "").strip()
        selected_ids_raw = request.form.getlist("selected_ids")
        if not selected_ids_raw:
            return redirect_to_team_month(public_id, current_month)

        try:
            selected_ids = [int(match_id) for match_id in selected_ids_raw]
        except ValueError:
            return redirect_to_team_month(public_id, current_month)

        events = portal_get_events([team["id"]])
        target_ids = [event["id"] for event in events if event["id"] in selected_ids]
        if not target_ids:
            return redirect_to_team_month(public_id, current_month)

        if action == "edit":
            return redirect_to_team_month(public_id, current_month)
        if action == "attendance_check":
            if not can_team_use_paid_feature(team):
                return build_member_page_notice_redirect(
                    public_id,
                    get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK),
                    month=current_month,
                )
            return redirect(url_for("public_attendance_check", public_id=public_id, match_id=target_ids[0], month=current_month))
        if action in {"duplicate", "delete"}:
            return redirect_to_team_month(public_id, current_month)

        return redirect_to_team_month(public_id, current_month)

    def public_edit_match(public_id, id):
        current_month = request.args.get("month", "").strip()
        return redirect_to_team_month(public_id, current_month)

    def public_attendance_month(public_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))

        member_options = portal_get_members_for_team(team["id"], include_inactive=False)
        member_names = [member.get("name") for member in member_options if member.get("name")]
        events = portal_get_events([team["id"]])
        months = sorted({event["date"][:7] for event in events if event.get("date")})
        selected_month = request.args.get("month")
        name = (request.args.get("name") or "").strip()
        if name and name not in member_names:
            name = ""
        error_message = ""

        if not selected_month and months:
            selected_month = months[0]

        if request.method == "POST":
            selected_month = request.form.get("month", "").strip() or selected_month
            name = (request.form.get("name") or "").strip()
            if name and name not in member_names:
                error_message = "対象メンバーが見つかりません。"
            elif not selected_month:
                error_message = "対象月を選択してください。"
            else:
                for raw_key, raw_value in request.form.items():
                    if not raw_key.startswith("status_"):
                        continue
                    parts = raw_key.split("_", 2)
                    if len(parts) != 3:
                        continue
                    try:
                        match_id = int(parts[1])
                    except ValueError:
                        continue
                    member_name = parts[2]
                    if member_name not in member_names:
                        continue
                    status = normalize_status(raw_value)
                    if status:
                        portal_upsert_attendance(team["id"], match_id, member_name, status)
                return redirect(url_for("public_attendance_month", public_id=public_id, month=selected_month or "", name=name or ""))

        attendance_dict = {}
        month_events = [event for event in events if not selected_month or (event.get("date") or "").startswith(selected_month)]
        if selected_month:
            for row in portal_get_attendance(team["id"]):
                event_id = row.get("event_id")
                member_name = row.get("member_name")
                if event_id and member_name:
                    attendance_dict[(event_id, member_name)] = normalize_status(row["status"])
        return render_template(
            "public_attendance_month.html",
            team=team,
            months=months,
            selected_month=selected_month,
            events=month_events,
            name=name,
            member_options=member_options,
            attendance_dict=attendance_dict,
            error_message=error_message,
        )

    def public_delete_member_attendance_by_month(public_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        return redirect(url_for("public_attendance_month", public_id=public_id, month=request.args.get("month", "").strip(), name=request.args.get("name", "").strip()))

    def public_export_attendance_csv(public_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_CSV_EXPORT))
        month = request.args.get("month", "all").strip() or "all"
        return portal_build_event_list_csv_response(team["id"], month)

    app.add_url_rule("/team/<public_id>", endpoint="member_team_page", view_func=member_team_page, methods=["GET", "POST"])
    app.add_url_rule("/team/<public_id>/add", endpoint="public_add_match", view_func=public_add_match, methods=["GET", "POST"])
    app.add_url_rule("/team/<public_id>/delete/<int:id>", endpoint="public_delete_match", view_func=public_delete_match)
    app.add_url_rule("/team/<public_id>/duplicate/<int:id>", endpoint="public_duplicate_match", view_func=public_duplicate_match)
    app.add_url_rule("/team/<public_id>/matches/action", endpoint="public_bulk_match_action", view_func=public_bulk_match_action, methods=["POST"])
    app.add_url_rule("/team/<public_id>/edit/<int:id>", endpoint="public_edit_match", view_func=public_edit_match, methods=["GET", "POST"])
    app.add_url_rule("/team/<public_id>/attendance/month", endpoint="public_attendance_month", view_func=public_attendance_month, methods=["GET", "POST"])
    app.add_url_rule("/team/<public_id>/attendance/member/delete", endpoint="public_delete_member_attendance_by_month", view_func=public_delete_member_attendance_by_month, methods=["POST"])
    app.add_url_rule("/team/<public_id>/csv", endpoint="public_export_attendance_csv", view_func=public_export_attendance_csv)
