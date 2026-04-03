from flask import redirect, render_template, request, session, url_for


def register_admin_team_event_routes(
    app,
    *,
    _coerce_positive_int,
    admin_login_required,
    build_time_from_form,
    format_date_mmdd_with_weekday,
    get_owned_team_or_error,
    is_valid_10min_time,
    portal_create_event,
    portal_delete_event,
    portal_duplicate_event,
    portal_get_event,
    portal_get_events,
    portal_update_event,
):
    def admin_team_events(team_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return redirect(url_for("admin_dashboard", error_message="対象チームが見つかりません。"))
        if team_error == "forbidden":
            return redirect(url_for("admin_dashboard", error_message="他チームは操作できません。"))

        error_message = request.args.get("error_message", "").strip()
        success_message = request.args.get("success_message", "").strip()
        selected_month = request.args.get("month", "").strip()
        editing_event_id = _coerce_positive_int(request.args.get("editing_event_id"))

        def _redirect_events(month_value="", success="", error="", editing_id=None):
            params = {"team_id": team_id}
            if month_value:
                params["month"] = month_value
            if success:
                params["success_message"] = success
            if error:
                params["error_message"] = error
            if editing_id:
                params["editing_event_id"] = editing_id
            return redirect(url_for("admin_team_events", **params))

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            selected_month = request.form.get("month", "").strip() or selected_month
            selected_event_ids_raw = request.form.get("selected_event_ids", "").strip()
            selected_event_ids = []
            if selected_event_ids_raw:
                seen_event_ids = set()
                for raw_id in selected_event_ids_raw.split(","):
                    event_id = _coerce_positive_int(raw_id.strip())
                    if event_id is None or event_id in seen_event_ids:
                        continue
                    seen_event_ids.add(event_id)
                    selected_event_ids.append(event_id)
            editing_event_id = _coerce_positive_int(request.form.get("editing_event_id")) or editing_event_id

            if action in {"add_event", "update_event"}:
                event_date = request.form.get("date", "").strip()
                start_time = build_time_from_form("start_time")
                end_time = build_time_from_form("end_time")
                opponent = request.form.get("opponent", "").strip()
                place = request.form.get("place", "").strip()
                if not event_date or not opponent or not place:
                    error_message = "日付・内容・場所は必須です。"
                elif not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
                    error_message = "開始/終了時刻は10分単位で入力してください。"
                elif action == "add_event":
                    portal_create_event(team["id"], event_date, start_time, end_time, opponent, place)
                    return _redirect_events(month_value=event_date[:7], success="イベントを登録しました。")
                else:
                    if editing_event_id is None:
                        error_message = "編集対象のイベントを選択してください。"
                    elif not portal_get_event(team["id"], editing_event_id):
                        error_message = "編集対象のイベントが見つかりません。"
                    else:
                        portal_update_event(team["id"], editing_event_id, event_date, start_time, end_time, opponent, place)
                        return _redirect_events(month_value=event_date[:7], success="イベントを更新しました。")
            elif action == "start_edit":
                if len(selected_event_ids) != 1:
                    return _redirect_events(month_value=selected_month, error="編集するイベントを1件選択してください。")
                selected_event_id = selected_event_ids[0]
                target_event = portal_get_event(team["id"], selected_event_id)
                if not target_event:
                    return _redirect_events(month_value=selected_month, error="対象イベントが見つかりません。")
                return _redirect_events(month_value=(target_event.get("date") or "")[:7], editing_id=selected_event_id)
            elif action == "duplicate_event":
                if not selected_event_ids:
                    return _redirect_events(month_value=selected_month, error="複製するイベントを選択してください。")
                copied_count = 0
                last_month = selected_month
                for selected_event_id in selected_event_ids:
                    target_event = portal_get_event(team["id"], selected_event_id)
                    if not target_event:
                        continue
                    portal_duplicate_event(team["id"], selected_event_id)
                    copied_count += 1
                    event_month = (target_event.get("date") or "")[:7]
                    if event_month:
                        last_month = event_month
                if copied_count == 0:
                    return _redirect_events(month_value=selected_month, error="対象イベントが見つかりません。")
                return _redirect_events(month_value=last_month, success=f"イベントを複製しました（{copied_count}件）。")
            elif action == "delete_event":
                if not selected_event_ids:
                    return _redirect_events(month_value=selected_month, error="削除するイベントを選択してください。")
                deleted_count = 0
                last_month = selected_month
                for selected_event_id in selected_event_ids:
                    target_event = portal_get_event(team["id"], selected_event_id)
                    if not target_event:
                        continue
                    event_month = (target_event.get("date") or "")[:7]
                    if event_month:
                        last_month = event_month
                    portal_delete_event(team["id"], selected_event_id)
                    deleted_count += 1
                if deleted_count == 0:
                    return _redirect_events(month_value=selected_month, error="対象イベントが見つかりません。")
                return _redirect_events(month_value=last_month, success=f"イベントを削除しました（{deleted_count}件）。")
            else:
                error_message = "不正な操作です。"

        all_events = portal_get_events([team["id"]])
        months = sorted({event["date"][:7] for event in all_events if event.get("date")})
        if not selected_month and months:
            selected_month = months[0]
        if selected_month and selected_month not in months:
            selected_month = months[0] if months else ""

        editing_event = None
        if editing_event_id is not None:
            candidate = portal_get_event(team["id"], editing_event_id)
            if candidate:
                editing_event = dict(candidate)
                edit_month = (editing_event.get("date") or "")[:7]
                if edit_month:
                    selected_month = edit_month
            else:
                editing_event_id = None

        events_with_labels = []
        for event in all_events:
            event_data = dict(event)
            event_data["date_label"] = format_date_mmdd_with_weekday(event_data.get("date", ""))
            events_with_labels.append(event_data)
        month_data = {
            month: [event for event in events_with_labels if (event.get("date") or "").startswith(month)]
            for month in months
        }

        return render_template(
            "admin_team_events.html",
            team=team,
            months=months,
            selected_month=selected_month,
            month_data=month_data,
            editing_event=editing_event,
            editing_event_id=editing_event_id,
            error_message=error_message,
            success_message=success_message,
        )

    app.add_url_rule(
        "/admin/teams/<int:team_id>/events",
        endpoint="admin_team_events",
        view_func=admin_login_required(admin_team_events),
        methods=["GET", "POST"],
    )
