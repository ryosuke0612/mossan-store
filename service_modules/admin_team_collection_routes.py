from datetime import date

from flask import redirect, render_template, request, session, url_for


def register_admin_team_collection_routes(
    app,
    *,
    _coerce_positive_int,
    admin_api_required,
    admin_login_required,
    build_collection_event_summary,
    format_currency_yen,
    get_owned_team_or_error,
    normalize_collection_status,
    portal_build_collection_list_csv_response,
    portal_create_collection_event,
    portal_delete_collection_event,
    portal_duplicate_collection_event,
    portal_get_collection_event,
    portal_get_collection_event_members,
    portal_get_collection_events,
    portal_get_members_for_team,
    portal_update_collection_event,
    portal_update_collection_member_status,
    serialize_collection_event_for_list,
    serialize_collection_member_for_api,
):
    def admin_team_collections(team_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return redirect(url_for("admin_dashboard", error_message="対象チームが見つかりません。"))
        if team_error == "forbidden":
            return redirect(url_for("admin_dashboard", error_message="他チームは操作できません。"))

        error_message = request.args.get("error_message", "").strip()
        success_message = request.args.get("success_message", "").strip()
        page = _coerce_positive_int(request.args.get("page")) or 1
        scroll_y = request.args.get("scroll_y", "").strip()
        editing_collection_id = _coerce_positive_int(request.args.get("editing_collection_id"))

        def _redirect_collections(page_value=None, success="", error="", editing_id=None, scroll_value=""):
            params = {"team_id": team_id}
            if page_value and page_value > 1:
                params["page"] = page_value
            if success:
                params["success_message"] = success
            if error:
                params["error_message"] = error
            if editing_id:
                params["editing_collection_id"] = editing_id
            if scroll_value:
                params["scroll_y"] = scroll_value
            return redirect(url_for("admin_team_collections", **params))

        active_members = portal_get_members_for_team(team["id"], include_inactive=False)

        if request.method == "POST":
            action = request.form.get("action", "").strip()
            page = _coerce_positive_int(request.form.get("page")) or page
            scroll_y = request.form.get("scroll_y", "").strip() or scroll_y
            editing_collection_id = _coerce_positive_int(request.form.get("editing_collection_id")) or editing_collection_id
            selected_collection_ids_raw = request.form.get("selected_collection_ids", "").strip()
            selected_collection_ids = []
            if selected_collection_ids_raw:
                seen_collection_ids = set()
                for raw_id in selected_collection_ids_raw.split(","):
                    collection_id = _coerce_positive_int(raw_id.strip())
                    if collection_id is None or collection_id in seen_collection_ids:
                        continue
                    seen_collection_ids.add(collection_id)
                    selected_collection_ids.append(collection_id)
            title = request.form.get("title", "").strip()
            collection_date = request.form.get("collection_date", "").strip()
            if not collection_date:
                if editing_collection_id:
                    editing_event = portal_get_collection_event(team["id"], editing_collection_id)
                    collection_date = (editing_event or {}).get("collection_date", "").strip()
                if not collection_date:
                    collection_date = date.today().isoformat()
            note = request.form.get("note", "").strip()
            target_mode_input = (request.form.get("target_mode") or "all_active").strip()
            target_mode = "all_active" if target_mode_input == "all_active" else "manual"
            target_member_ids = request.form.getlist("target_member_ids")
            amount_raw = request.form.get("amount", "").strip()

            if action in {"create_collection", "update_collection"}:
                try:
                    amount = int(amount_raw)
                except ValueError:
                    amount = -1
                if not title:
                    error_message = "集金イベント名を入力してください。"
                elif amount < 0:
                    error_message = "金額は0円以上の整数で入力してください。"
                else:
                    if action == "create_collection":
                        created_event, status = portal_create_collection_event(
                            team["id"],
                            title,
                            collection_date,
                            amount,
                            note,
                            target_member_ids=target_member_ids,
                            target_mode=target_mode,
                        )
                        if created_event:
                            return _redirect_collections(page_value=1, success="集金イベントを作成しました。", scroll_value=scroll_y)
                        if status == "members_required":
                            error_message = "対象メンバーを1名以上選択してください。"
                        else:
                            error_message = "集金イベントを作成できませんでした。"
                    else:
                        updated_event, status = portal_update_collection_event(
                            team["id"],
                            editing_collection_id,
                            title,
                            collection_date,
                            amount,
                            note,
                            target_member_ids=target_member_ids,
                            target_mode=target_mode,
                        )
                        if updated_event:
                            return _redirect_collections(page_value=page, success="集金イベントを更新しました。", scroll_value=scroll_y)
                        if status == "not_found":
                            error_message = "編集対象の集金イベントが見つかりません。"
                        elif status == "members_required":
                            error_message = "対象メンバーを1名以上選択してください。"
                        else:
                            error_message = "集金イベントを更新できませんでした。"
            elif action == "start_edit":
                if len(selected_collection_ids) != 1:
                    return _redirect_collections(page_value=page, error="編集する集金イベントを1件選択してください。", scroll_value=scroll_y)
                target_id = selected_collection_ids[0]
                target_event = portal_get_collection_event(team["id"], target_id)
                if not target_event:
                    return _redirect_collections(page_value=page, error="対象の集金イベントが見つかりません。", scroll_value=scroll_y)
                return _redirect_collections(page_value=page, editing_id=target_id, scroll_value=scroll_y)
            elif action == "open_detail":
                if len(selected_collection_ids) != 1:
                    return _redirect_collections(page_value=page, error="詳細確認する集金イベントを1件選択してください。", scroll_value=scroll_y)
                target_id = selected_collection_ids[0]
                if not portal_get_collection_event(team["id"], target_id):
                    return _redirect_collections(page_value=page, error="対象の集金イベントが見つかりません。", scroll_value=scroll_y)
                return redirect(url_for("admin_team_collection_run", team_id=team["id"], collection_event_id=target_id, page=page, scroll_y=scroll_y))
            elif action == "duplicate_collection":
                if not selected_collection_ids:
                    return _redirect_collections(page_value=page, error="複製する集金イベントを選択してください。", scroll_value=scroll_y)
                copied_count = 0
                for target_id in selected_collection_ids:
                    target_event = portal_get_collection_event(team["id"], target_id)
                    if not target_event:
                        continue
                    duplicated_event, _status = portal_duplicate_collection_event(team["id"], target_id)
                    if not duplicated_event:
                        continue
                    copied_count += 1
                if copied_count == 0:
                    return _redirect_collections(page_value=page, error="対象の集金イベントが見つかりません。", scroll_value=scroll_y)
                return _redirect_collections(page_value=page, success=f"集金イベントを複製しました（{copied_count}件）。", scroll_value=scroll_y)
            elif action == "delete_collection":
                if not selected_collection_ids:
                    return _redirect_collections(page_value=page, error="削除する集金イベントを選択してください。", scroll_value=scroll_y)
                deleted_count = 0
                for target_id in selected_collection_ids:
                    target_event = portal_get_collection_event(team["id"], target_id)
                    if not target_event:
                        continue
                    if portal_delete_collection_event(team["id"], target_id):
                        deleted_count += 1
                if deleted_count == 0:
                    return _redirect_collections(page_value=page, error="対象の集金イベントが見つかりません。", scroll_value=scroll_y)
                return _redirect_collections(page_value=page, success=f"集金イベントを削除しました（{deleted_count}件）。", scroll_value=scroll_y)
            else:
                error_message = "不正な操作です。"

        collection_events = portal_get_collection_events(team["id"])
        editing_collection = None
        editing_member_ids = set()
        if editing_collection_id is not None:
            editing_collection = portal_get_collection_event(team["id"], editing_collection_id)
            if editing_collection:
                editing_member_ids = {
                    int(row.get("member_id"))
                    for row in portal_get_collection_event_members(team["id"], editing_collection_id)
                    if _coerce_positive_int(row.get("member_id")) is not None
                }
            else:
                editing_collection_id = None

        collection_rows = []
        for collection_event in collection_events:
            member_rows = portal_get_collection_event_members(team["id"], collection_event["id"])
            collection_rows.append(serialize_collection_event_for_list(collection_event, member_rows))
        per_page = 10
        total_count = len(collection_rows)
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        visible_rows = collection_rows[start_index:end_index]

        return render_template(
            "admin_team_collections_table.html",
            team=team,
            active_members=active_members,
            collection_rows=visible_rows,
            page=page,
            per_page=per_page,
            total_count=total_count,
            total_pages=total_pages,
            editing_collection=editing_collection,
            editing_collection_id=editing_collection_id,
            editing_member_ids=editing_member_ids,
            error_message=error_message,
            success_message=success_message,
            scroll_y=scroll_y,
        )

    def admin_team_collection_run(team_id, collection_event_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return redirect(url_for("admin_dashboard", error_message="対象チームが見つかりません。"))
        if team_error == "forbidden":
            return redirect(url_for("admin_dashboard", error_message="他チームは操作できません。"))

        collection_event = portal_get_collection_event(team["id"], collection_event_id)
        if not collection_event:
            return redirect(url_for("admin_team_collections", team_id=team["id"], error_message="集金イベントが見つかりません。"))

        member_rows = portal_get_collection_event_members(team["id"], collection_event_id)
        summary = build_collection_event_summary(collection_event, member_rows)
        serialized_members = [serialize_collection_member_for_api(member_row) for member_row in member_rows]
        page = _coerce_positive_int(request.args.get("page")) or 1
        scroll_y = request.args.get("scroll_y", "").strip()

        return render_template(
            "admin_collection_run.html",
            team=team,
            collection_event=collection_event,
            collection_event_view=serialize_collection_event_for_list(collection_event, member_rows),
            member_rows=serialized_members,
            summary=summary,
            summary_labels={
                "target_count": summary["target_count"],
                "collected_count": summary["collected_count"],
                "pending_count": summary["pending_count"],
                "exempt_count": summary["exempt_count"],
                "collected_total": format_currency_yen(summary["collected_total"]),
                "pending_total": format_currency_yen(summary["pending_total"]),
            },
            page=page,
            scroll_y=scroll_y,
        )

    def admin_export_collection_csv(team_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return redirect(url_for("admin_dashboard", error_message="対象チームが見つかりません。"))
        if team_error == "forbidden":
            return redirect(url_for("admin_dashboard", error_message="他チームは操作できません。"))

        month = request.args.get("month", "all").strip() or "all"
        name = (request.args.get("name") or "").strip()
        return portal_build_collection_list_csv_response(team["id"], month=month, member_name=name)

    def api_update_collection_member_status(team_id, collection_event_id, member_id):
        team, team_error = get_owned_team_or_error(team_id, session["admin_id"])
        if team_error == "not_found":
            return {"error": "not_found"}, 404
        if team_error == "forbidden":
            return {"error": "forbidden"}, 403

        payload = request.get_json(silent=True) or request.form
        next_status = normalize_collection_status(payload.get("status"))
        if not next_status:
            return {"error": "invalid_status"}, 400

        updated_row, status = portal_update_collection_member_status(team["id"], collection_event_id, member_id, next_status)
        if not updated_row and status == "not_found":
            return {"error": "member_not_found"}, 404
        if not updated_row:
            return {"error": "update_failed"}, 400

        collection_event = portal_get_collection_event(team["id"], collection_event_id)
        member_rows = portal_get_collection_event_members(team["id"], collection_event_id)
        summary = build_collection_event_summary(collection_event, member_rows)
        return {
            "status": "updated",
            "member": serialize_collection_member_for_api(updated_row),
            "summary": summary,
            "summary_labels": {
                "target_count": summary["target_count"],
                "collected_count": summary["collected_count"],
                "pending_count": summary["pending_count"],
                "exempt_count": summary["exempt_count"],
                "collected_total": format_currency_yen(summary["collected_total"]),
                "pending_total": format_currency_yen(summary["pending_total"]),
            },
        }

    app.add_url_rule("/admin/teams/<int:team_id>/collections", endpoint="admin_team_collections", view_func=admin_login_required(admin_team_collections), methods=["GET", "POST"])
    app.add_url_rule("/admin/teams/<int:team_id>/collections/<int:collection_event_id>", endpoint="admin_team_collection_run", view_func=admin_login_required(admin_team_collection_run))
    app.add_url_rule("/admin/teams/<int:team_id>/collections/csv", endpoint="admin_export_collection_csv", view_func=admin_login_required(admin_export_collection_csv))
    app.add_url_rule("/admin/api/teams/<int:team_id>/collections/<int:collection_event_id>/members/<int:member_id>", endpoint="api_update_collection_member_status", view_func=admin_api_required(api_update_collection_member_status), methods=["PATCH"])
