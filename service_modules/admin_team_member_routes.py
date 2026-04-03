from flask import redirect, render_template, request, session, url_for


def register_admin_team_member_routes(
    app,
    *,
    ADMIN_MEMBER_ANALYTICS_TABS,
    _coerce_positive_int,
    admin_api_required,
    admin_login_required,
    build_admin_member_analytics,
    build_admin_member_analytics_csv_response,
    get_owned_team_or_error,
    normalize_admin_member_analytics_tab,
    parse_boolean_input,
    portal_add_member,
    portal_delete_member_by_id,
    portal_get_member,
    portal_get_members_for_team,
    portal_reorder_members,
    portal_update_member,
    resolve_member_analytics_period,
    serialize_member_for_api,
):
    def admin_team_members(team_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return redirect(url_for("admin_dashboard", error_message="対象チームが見つかりません。"))
        if team_error == "forbidden":
            return redirect(url_for("admin_dashboard", error_message="他チームは操作できません。"))

        include_inactive = True
        error_message = request.args.get("error_message", "").strip()
        success_message = request.args.get("success_message", "").strip()
        selected_member_id = _coerce_positive_int(request.args.get("selected_member_id"))
        scroll_y = request.args.get("scroll_y", "").strip()
        active_tab = normalize_admin_member_analytics_tab(request.args.get("tab"))
        period_start_raw = request.args.get("start_date", "").strip()
        period_end_raw = request.args.get("end_date", "").strip()

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            selected_member_id = _coerce_positive_int(request.form.get("selected_member_id")) or selected_member_id
            scroll_y = request.form.get("scroll_y", "").strip()
            active_tab = normalize_admin_member_analytics_tab(request.form.get("active_tab") or active_tab)
            period_start_raw = (request.form.get("start_date") or period_start_raw).strip()
            period_end_raw = (request.form.get("end_date") or period_end_raw).strip()
            if action == "add_members":
                raw_names = request.form.get("member_names", "")
                lines = raw_names.replace("\r\n", "\n").split("\n")
                names = []
                seen = set()
                for line in lines:
                    name = line.strip()
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    names.append(name)

                if not names:
                    error_message = "追加するメンバー名を入力してください。"
                else:
                    added_count = 0
                    reactivated_count = 0
                    duplicate_names = []
                    failed_names = []
                    for name in names:
                        member, status = portal_add_member(team["id"], name)
                        if member and status == "created":
                            added_count += 1
                        elif member and status == "reactivated":
                            reactivated_count += 1
                        elif member and status == "exists":
                            duplicate_names.append(name)
                        else:
                            failed_names.append(name)

                    if failed_names:
                        error_message = f"メンバーを追加できませんでした: {', '.join(failed_names)}"
                    else:
                        summary_parts = []
                        if added_count:
                            summary_parts.append(f"{added_count}名を追加")
                        if reactivated_count:
                            summary_parts.append(f"{reactivated_count}名を再開")
                        if duplicate_names:
                            summary_parts.append(f"{len(duplicate_names)}名は既存")
                        success_message = "、".join(summary_parts) + "しました。"
            else:
                error_message = "不正な操作です。"

        members = portal_get_members_for_team(team["id"], include_inactive=include_inactive)
        total_members = len(members)
        active_members = len([member for member in members if member.get("is_active")])
        inactive_members = total_members - active_members
        analytics_period = resolve_member_analytics_period(
            team["id"],
            start_date=period_start_raw,
            end_date=period_end_raw,
        )
        analytics = build_admin_member_analytics(
            team["id"],
            period_start=analytics_period["start_date"],
            period_end=analytics_period["end_date"],
            include_inactive=include_inactive,
        )

        return render_template(
            "admin_team_members.html",
            team=team,
            members=members,
            analytics_rows=analytics["rows"],
            analytics_period=analytics_period,
            analytics_tabs=ADMIN_MEMBER_ANALYTICS_TABS,
            active_tab=active_tab,
            total_members=total_members,
            active_members=active_members,
            inactive_members=inactive_members,
            include_inactive=include_inactive,
            error_message=error_message,
            success_message=success_message,
            selected_member_id=selected_member_id,
            scroll_y=scroll_y,
        )

    def admin_export_member_analytics_csv(team_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return redirect(url_for("admin_dashboard", error_message="対象チームが見つかりません。"))
        if team_error == "forbidden":
            return redirect(url_for("admin_dashboard", error_message="他チームは操作できません。"))
        analytics_period = resolve_member_analytics_period(
            team["id"],
            start_date=request.args.get("start_date", "").strip(),
            end_date=request.args.get("end_date", "").strip(),
        )
        return build_admin_member_analytics_csv_response(
            team["id"],
            request.args.get("tab"),
            period_start=analytics_period["start_date"],
            period_end=analytics_period["end_date"],
        )

    def api_get_members(team_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return {"error": "not_found"}, 404
        if team_error == "forbidden":
            return {"error": "forbidden"}, 403
        include_inactive = request.args.get("include_inactive", "").strip() == "1"
        members = portal_get_members_for_team(team["id"], include_inactive=include_inactive)
        return {"members": [serialize_member_for_api(member) for member in members]}

    def api_create_member(team_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return {"error": "not_found"}, 404
        if team_error == "forbidden":
            return {"error": "forbidden"}, 403
        payload = request.get_json(silent=True) or request.form
        display_name = (payload.get("display_name") or payload.get("name") or "").strip()
        note = (payload.get("note") or "").strip()
        display_order = payload.get("display_order")
        if not display_name:
            return {"error": "display_name is required"}, 400
        if display_order is not None and str(display_order).strip() and _coerce_positive_int(display_order) is None:
            return {"error": "display_order must be a positive integer"}, 400
        member, status = portal_add_member(team["id"], display_name, note=note, display_order=display_order)
        if not member:
            return {"error": "member_create_failed"}, 400
        response_status = 200 if status in {"reactivated", "exists"} else 201
        return {"member": serialize_member_for_api(member), "status": status}, response_status

    def api_update_member(team_id, member_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return {"error": "not_found"}, 404
        if team_error == "forbidden":
            return {"error": "forbidden"}, 403
        if not portal_get_member(team["id"], member_id):
            return {"error": "member_not_found"}, 404
        payload = request.get_json(silent=True) or request.form
        display_name = payload.get("display_name")
        note = payload.get("note")
        if display_name is not None and not str(display_name).strip():
            return {"error": "display_name must not be empty"}, 400
        active_raw = payload.get("is_active")
        is_active = None
        if active_raw is not None:
            is_active = parse_boolean_input(active_raw)
            if is_active is None:
                return {"error": "is_active must be boolean"}, 400
        member, status = portal_update_member(team["id"], member_id, name=display_name, note=note, is_active=is_active)
        if not member and status == "not_found":
            return {"error": "member_not_found"}, 404
        if not member:
            return {"error": "member_update_failed"}, 400
        return {"member": serialize_member_for_api(member), "status": status}

    def api_delete_member(team_id, member_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return {"error": "not_found"}, 404
        if team_error == "forbidden":
            return {"error": "forbidden"}, 403
        if not portal_delete_member_by_id(team["id"], member_id):
            return {"error": "member_not_found"}, 404
        return {"status": "deleted"}

    def api_reorder_members(team_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return {"error": "not_found"}, 404
        if team_error == "forbidden":
            return {"error": "forbidden"}, 403
        payload = request.get_json(silent=True) or request.form
        member_ids = payload.get("member_ids")
        if isinstance(member_ids, str):
            member_ids = [value.strip() for value in member_ids.split(",") if value.strip()]
        if not isinstance(member_ids, list) or not member_ids:
            return {"error": "member_ids must be a non-empty list"}, 400
        reordered, status = portal_reorder_members(team["id"], member_ids)
        if not reordered and status == "not_found":
            return {"error": "member_not_found"}, 404
        if not reordered:
            return {"error": "invalid_order"}, 400
        members = portal_get_members_for_team(team["id"], include_inactive=True)
        return {"status": "updated", "members": [serialize_member_for_api(member) for member in members]}

    app.add_url_rule("/admin/teams/<int:team_id>/members", endpoint="admin_team_members", view_func=admin_login_required(admin_team_members), methods=["GET", "POST"])
    app.add_url_rule("/admin/teams/<int:team_id>/members/csv", endpoint="admin_export_member_analytics_csv", view_func=admin_login_required(admin_export_member_analytics_csv))
    app.add_url_rule("/admin/api/teams/<int:team_id>/members", endpoint="api_get_members", view_func=admin_api_required(api_get_members), methods=["GET"])
    app.add_url_rule("/admin/api/teams/<int:team_id>/members", endpoint="api_create_member", view_func=admin_api_required(api_create_member), methods=["POST"])
    app.add_url_rule("/admin/api/teams/<int:team_id>/members/<int:member_id>", endpoint="api_update_member", view_func=admin_api_required(api_update_member), methods=["PATCH", "PUT"])
    app.add_url_rule("/admin/api/teams/<int:team_id>/members/<int:member_id>", endpoint="api_delete_member", view_func=admin_api_required(api_delete_member), methods=["DELETE"])
    app.add_url_rule("/admin/api/teams/<int:team_id>/members/reorder", endpoint="api_reorder_members", view_func=admin_api_required(api_reorder_members), methods=["POST"])
