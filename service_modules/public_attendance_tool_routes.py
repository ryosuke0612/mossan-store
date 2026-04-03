import json
import random
from datetime import datetime

from flask import redirect, render_template, request, url_for


def register_public_attendance_tool_routes(
    app,
    *,
    PLAN_FEATURE_ATTENDANCE_CHECK,
    PLAN_FEATURE_RANDOM_PICK,
    PLAN_FEATURE_TEAM_SPLIT,
    TRANSPORT_ROLE_DIRECT,
    TRANSPORT_ROLE_DRIVER,
    TRANSPORT_ROLE_LABELS,
    TRANSPORT_ROLE_NONE,
    TRANSPORT_ROLE_PASSENGER,
    _coerce_positive_int,
    _coerce_team_count,
    _normalize_name_list,
    add_portal_walkin_attendee,
    build_member_page_notice_redirect,
    build_portal_transport_overview,
    build_team_allocator,
    can_team_use_paid_feature,
    create_portal_tool_saved_result,
    create_portal_tool_share,
    format_date_mmdd_with_weekday,
    get_plan_restriction_message,
    get_portal_confirmed_attendees,
    get_portal_effective_attendees,
    get_portal_tool_saved_result,
    get_portal_tool_saved_results,
    get_portal_tool_share,
    get_team_by_public_id,
    normalize_status,
    normalize_transport_role,
    parse_random_pick_names,
    parse_team_state_from_form,
    portal_get_all_transport_responses_for_event,
    portal_get_attendance_for_event,
    portal_get_event,
    portal_get_members_for_team,
    portal_prune_transport_assignments,
    portal_replace_transport_responses,
    portal_replace_transport_responses_for_attendees,
    portal_save_transport_assignments,
    remove_portal_walkin_attendee,
    save_portal_confirmed_attendees,
    serialize_team_result,
    swap_members_in_teams,
):
    def public_attendance_check(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK))

        match = portal_get_event(team["id"], match_id)
        if not match:
            return redirect(url_for("member_team_page", public_id=public_id))

        rows = portal_get_attendance_for_event(team["id"], match_id)
        grouped_members = {"参加": [], "不参加": [], "未定": []}
        for row in rows:
            status = normalize_status(row["status"])
            if status in grouped_members:
                grouped_members[status].append(row["member_name"])

        match_data = dict(match)
        match_data["date_label"] = format_date_mmdd_with_weekday(match["date"])
        confirmed_rows = get_portal_confirmed_attendees(team["id"], match_id)
        confirmed_names = [
            row.get("member_name")
            for row in confirmed_rows
            if row.get("member_name") and row.get("source_type") != "walkin_pending"
        ]
        walkin_names = [
            row.get("member_name")
            for row in confirmed_rows
            if row.get("member_name") and row.get("source_type") in ("walkin", "walkin_pending")
        ]
        has_confirmed_today = bool(confirmed_names)
        candidate_names = _normalize_name_list(grouped_members["参加"] + walkin_names)
        effective_attendees = get_portal_effective_attendees(team["id"], match_id)
        transport_response_map = {}
        for row in portal_get_all_transport_responses_for_event(team["id"], match_id):
            member_name = (row.get("member_name") or "").strip()
            if not member_name or member_name not in candidate_names:
                continue
            transport_response_map[member_name] = {
                "transport_role": normalize_transport_role(row.get("transport_role")) or "",
                "seats_available": max(0, int(row.get("seats_available") or 0)),
                "note": row.get("note") or "",
            }

        tool_message = request.args.get("tool_message", "").strip()
        return render_template(
            "public_attendance_check.html",
            public_id=public_id,
            match=match_data,
            join_members=grouped_members["参加"],
            absent_members=grouped_members["不参加"],
            undecided_members=grouped_members["未定"],
            candidate_names=candidate_names,
            confirmed_names=confirmed_names,
            walkin_names=walkin_names,
            has_confirmed_today=has_confirmed_today,
            effective_attendees=effective_attendees,
            transport_response_map=transport_response_map,
            transport_role_labels=TRANSPORT_ROLE_LABELS,
            tool_message=tool_message,
            tools_url=url_for("public_attendance_tools", public_id=public_id, match_id=match_id),
            transport_assign_url=url_for("public_attendance_transport_assignments", public_id=public_id, match_id=match_id),
        )

    def public_attendance_tools(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_TEAM_SPLIT))
        match = portal_get_event(team["id"], match_id)
        if not match:
            return redirect(url_for("member_team_page", public_id=public_id))

        match_data = dict(match)
        match_data["date_label"] = format_date_mmdd_with_weekday(match["date"])
        effective_attendees = get_portal_effective_attendees(team["id"], match_id)
        team_result = []
        random_pick = []
        team_share_url = ""
        team_share_text = ""
        team_qr_url = ""
        selected_team_count = _coerce_team_count(request.args.get("team_count"), default=2)
        selected_pick_count = _coerce_team_count(
            request.args.get("pick_count"),
            default=1,
            minimum=1,
            maximum=max(1, len(effective_attendees)),
        )
        tool_message = request.args.get("tool_message", "").strip()
        if request.args.get("tool_type") == "team_split":
            team_result = parse_team_state_from_form(request.args.get("team_state", ""))
        if request.args.get("tool_type") == "random_pick":
            random_pick = parse_random_pick_names(request.args.get("picked_names", ""), request.args.get("picked_name", ""))
        if team_result:
            share_id = request.args.get("share_id", "").strip()
            if share_id:
                team_share_url = url_for("public_attendance_tool_share_view", public_id=public_id, share_id=share_id, _external=True)
                lines = ["【チーム分け結果】"]
                for team_data in team_result:
                    lines.append(f"{team_data['name']}: " + ", ".join(team_data["members"]))
                team_share_text = "\n".join(lines)
                team_qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=240x240&data={team_share_url}"
        saved_tool_results = get_portal_tool_saved_results(team["id"], match_id, limit=30)
        return render_template(
            "public_attendance_tools.html",
            public_id=public_id,
            match=match_data,
            effective_attendees=effective_attendees,
            tool_message=tool_message,
            team_result=team_result,
            random_pick=random_pick,
            team_state_json=json.dumps(serialize_team_result(team_result), ensure_ascii=False) if team_result else "[]",
            team_share_url=team_share_url,
            team_share_text=team_share_text,
            team_qr_url=team_qr_url,
            saved_tool_results=saved_tool_results,
            selected_team_count=selected_team_count,
            selected_pick_count=selected_pick_count,
        )

    def public_attendance_transport_assignments(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK))
        match = portal_get_event(team["id"], match_id)
        if not match:
            return redirect(url_for("member_team_page", public_id=public_id))

        match_data = dict(match)
        match_data["date_label"] = format_date_mmdd_with_weekday(match["date"])
        effective_attendees = get_portal_effective_attendees(team["id"], match_id)
        transport_overview = build_portal_transport_overview(team["id"], match_id, allowed_member_names=effective_attendees)
        tool_message = request.args.get("tool_message", "").strip()
        return render_template(
            "public_attendance_transport_assign.html",
            public_id=public_id,
            match=match_data,
            tool_message=tool_message,
            transport_summary=transport_overview["summary"],
            transport_driver_cards=transport_overview["driver_cards"],
            transport_passenger_rows=transport_overview["passenger_rows"],
            transport_driver_options=[row for row in transport_overview["driver_rows"] if int(row.get("seats_available") or 0) > 0],
        )

    def public_attendance_check_confirm_attendees(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK))
        selected_names = request.form.getlist("confirmed_names")
        walkin_names = request.form.getlist("walkin_names")
        confirmed_names = save_portal_confirmed_attendees(team["id"], match_id, selected_names, walkin_names)
        submitted_transport_map = {}
        for member_name, transport_role, seats_available, note in zip(
            request.form.getlist("transport_member_name"),
            request.form.getlist("transport_role"),
            request.form.getlist("seats_available"),
            request.form.getlist("transport_note"),
        ):
            normalized_member_name = (member_name or "").strip()
            if not normalized_member_name:
                continue
            submitted_transport_map[normalized_member_name] = {
                "transport_role": normalize_transport_role(transport_role) or TRANSPORT_ROLE_NONE,
                "seats_available": _coerce_positive_int(seats_available) or 0,
                "note": note or "",
            }
        transport_rows = []
        for member_name in confirmed_names:
            submitted = submitted_transport_map.get(member_name, {})
            transport_role = submitted.get("transport_role") or TRANSPORT_ROLE_DIRECT
            seats_available = submitted.get("seats_available") or 0
            if transport_role == TRANSPORT_ROLE_DRIVER and seats_available <= 0:
                seats_available = 1
            if transport_role != TRANSPORT_ROLE_DRIVER:
                seats_available = 0
            transport_rows.append(
                {
                    "member_name": member_name,
                    "transport_role": transport_role,
                    "seats_available": seats_available,
                    "note": submitted.get("note", ""),
                }
            )
        portal_replace_transport_responses_for_attendees(team["id"], match_id, confirmed_names, transport_rows)
        portal_prune_transport_assignments(team["id"], match_id, confirmed_names)
        save_mode = (request.form.get("save_mode") or "").strip().lower()
        success_message = "値を更新しました。" if save_mode == "autosave" else "当日参加者を確定しました。"
        return redirect(url_for("public_attendance_check", public_id=public_id, match_id=match_id, tool_message=success_message))

    def public_attendance_check_add_walkin(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK))
        walkin_name = request.form.get("walkin_name", "")
        added = add_portal_walkin_attendee(team["id"], match_id, walkin_name)
        message = "飛び入り参加者を追加しました。" if added else "飛び入り参加者名を入力してください。"
        return redirect(url_for("public_attendance_check", public_id=public_id, match_id=match_id, tool_message=message))

    def public_attendance_check_delete_walkin(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK))
        member_name = request.form.get("member_name", "")
        deleted = remove_portal_walkin_attendee(team["id"], match_id, member_name)
        message = "飛び入り参加者を削除しました。" if deleted else "削除対象の飛び入り参加者が見つかりませんでした。"
        return redirect(url_for("public_attendance_check", public_id=public_id, match_id=match_id, tool_message=message))

    def public_attendance_check_delete_selected_walkins(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK))
        selected_names = set(_normalize_name_list(request.form.getlist("confirmed_names")))
        walkin_names = _normalize_name_list(request.form.getlist("walkin_names"))
        target_names = [name for name in walkin_names if name in selected_names]
        deleted_count = 0
        for member_name in target_names:
            if remove_portal_walkin_attendee(team["id"], match_id, member_name):
                deleted_count += 1
        if deleted_count:
            message = f"飛び入り参加者を削除しました（{deleted_count}人）。"
        else:
            message = "削除できる飛び入り参加者が選択されていません。"
        return redirect(url_for("public_attendance_check", public_id=public_id, match_id=match_id, tool_message=message))

    def public_transport(public_id, event_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))

        event = portal_get_event(team["id"], event_id)
        if not event:
            return redirect(url_for("member_team_page", public_id=public_id))

        active_members = portal_get_members_for_team(team["id"], include_inactive=False)
        attendance_map = {
            row.get("member_name"): normalize_status(row.get("status"))
            for row in portal_get_attendance_for_event(team["id"], event_id)
        }
        transport_target_members = [
            member for member in active_members if attendance_map.get(member.get("name") or "", "") != "不参加"
        ]
        if request.method == "POST":
            action = (request.form.get("action") or "save_responses").strip()
            if action == "save_assignments":
                assignments = [
                    {"passenger_name": passenger_name, "driver_name": driver_name}
                    for passenger_name, driver_name in zip(
                        request.form.getlist("passenger_name"),
                        request.form.getlist("driver_name"),
                    )
                ]
                saved, status = portal_save_transport_assignments(team["id"], event_id, assignments)
                if not saved:
                    return redirect(url_for("public_transport", public_id=public_id, event_id=event_id, error_message=status))
                return redirect(url_for("public_transport", public_id=public_id, event_id=event_id, success_message="配車割当を保存しました。"))
            response_rows = []
            for member in transport_target_members:
                member_id = member.get("id")
                member_name = member.get("name") or ""
                transport_role = normalize_transport_role(request.form.get(f"transport_role_{member_id}")) or TRANSPORT_ROLE_NONE
                seats_available = _coerce_positive_int(request.form.get(f"seats_available_{member_id}")) or 0
                if transport_role == TRANSPORT_ROLE_DRIVER and seats_available <= 0:
                    seats_available = 1
                if transport_role != TRANSPORT_ROLE_DRIVER:
                    seats_available = 0
                response_rows.append(
                    {
                        "member_name": member_name,
                        "transport_role": transport_role,
                        "seats_available": seats_available,
                        "note": request.form.get(f"transport_note_{member_id}", ""),
                    }
                )
            portal_replace_transport_responses(team["id"], event_id, response_rows)
            return redirect(url_for("public_transport", public_id=public_id, event_id=event_id, success_message="配車回答を保存しました。"))

        event_data = dict(event)
        event_data["date_label"] = format_date_mmdd_with_weekday(event_data.get("date", ""))
        overview = build_portal_transport_overview(team["id"], event_id)
        transport_target_names = {member.get("name") or "" for member in transport_target_members if member.get("name")}
        member_rows = [row for row in overview["response_rows"] if (row.get("member_name") or "") in transport_target_names]
        for row in member_rows:
            attendance_status = attendance_map.get(row.get("member_name"), "")
            transport_role = normalize_transport_role(row.get("transport_role")) or ""
            if not transport_role:
                transport_role = TRANSPORT_ROLE_PASSENGER if attendance_status == "参加" else TRANSPORT_ROLE_NONE
            row["attendance_status"] = attendance_status
            row["transport_role"] = transport_role
            row["seats_available"] = max(0, int(row.get("seats_available") or 0))
            row["note"] = row.get("note") or ""

        return render_template(
            "public_transport_manage.html",
            public_id=public_id,
            team=team,
            event=event_data,
            member_rows=member_rows,
            driver_cards=overview["driver_cards"],
            passenger_rows=overview["passenger_rows"],
            direct_rows=overview["direct_rows"],
            none_rows=overview["none_rows"],
            summary=overview["summary"],
            driver_options=[row for row in overview["driver_rows"] if int(row.get("seats_available") or 0) > 0],
            transport_role_labels=TRANSPORT_ROLE_LABELS,
            error_message=request.args.get("error_message", "").strip(),
            success_message=request.args.get("success_message", "").strip(),
        )

    def public_attendance_check_team_split(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_TEAM_SPLIT))
        attendees = get_portal_effective_attendees(team["id"], match_id)
        if len(attendees) < 2:
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="チーム分けには2名以上必要です。"))
        team_count = _coerce_team_count(request.form.get("team_count"), default=2)
        teams = build_team_allocator("random").allocate(attendees, team_count)
        return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_type="team_split", team_state=json.dumps(serialize_team_result(teams), ensure_ascii=False), team_count=team_count, tool_message=f"{team_count}チームにランダム分けしました。"))

    def public_attendance_check_team_rerun(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_TEAM_SPLIT))
        attendees = get_portal_effective_attendees(team["id"], match_id)
        team_count = _coerce_team_count(request.form.get("team_count"), default=2)
        if len(attendees) < 2:
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="参加者が不足しているため再実行できません。"))
        teams = build_team_allocator("random").allocate(attendees, team_count)
        return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_type="team_split", team_state=json.dumps(serialize_team_result(teams), ensure_ascii=False), team_count=team_count, tool_message="チーム分けを再実行しました。"))

    def public_attendance_check_team_swap(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_TEAM_SPLIT))
        teams = parse_team_state_from_form(request.form.get("team_state_json", ""))
        src_team_idx = _coerce_positive_int(request.form.get("src_team_idx"))
        src_member_idx = _coerce_positive_int(request.form.get("src_member_idx"))
        dst_team_idx = _coerce_positive_int(request.form.get("dst_team_idx"))
        dst_member_idx = _coerce_positive_int(request.form.get("dst_member_idx"))
        if None in {src_team_idx, src_member_idx, dst_team_idx, dst_member_idx}:
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_type="team_split", team_state=json.dumps(serialize_team_result(teams), ensure_ascii=False), team_count=len(teams), tool_message="入れ替え対象を選択してください。"))
        updated_teams, swap_status = swap_members_in_teams(teams, src_team_idx - 1, src_member_idx - 1, dst_team_idx - 1, dst_member_idx - 1)
        message = "メンバーを入れ替えました。" if swap_status == "swapped" else "入れ替えに失敗しました。"
        return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_type="team_split", team_state=json.dumps(serialize_team_result(updated_teams), ensure_ascii=False), team_count=len(updated_teams), tool_message=message))

    def public_attendance_check_team_share(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_TEAM_SPLIT))
        teams = parse_team_state_from_form(request.form.get("team_state_json", ""))
        if not teams:
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="共有するチーム分け結果がありません。"))
        payload = {"teams": serialize_team_result(teams)}
        share_id = create_portal_tool_share(team["id"], match_id, "team_split", payload)
        return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_type="team_split", team_state=json.dumps(payload["teams"], ensure_ascii=False), team_count=len(payload["teams"]), share_id=share_id, tool_message="共有URLを作成しました。"))

    def public_attendance_check_role_assign(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_RANDOM_PICK))
        return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="役割決め機能は廃止しました。"))

    def public_attendance_check_random_pick(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_RANDOM_PICK))
        attendees = get_portal_effective_attendees(team["id"], match_id)
        if not attendees:
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="当日参加者を先に確定してください。"))
        pick_count = _coerce_team_count(request.form.get("pick_count"), default=1, minimum=1, maximum=max(1, len(attendees)))
        picked_names = random.sample(attendees, k=pick_count)
        picked_label = f"{len(picked_names)}人" if len(picked_names) > 1 else "1人"
        return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_type="random_pick", picked_names=json.dumps(picked_names, ensure_ascii=False), pick_count=pick_count, tool_message=f"ランダムで{picked_label}を代表者に選出しました。"))

    def public_attendance_tools_save_transport_assignments(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_ATTENDANCE_CHECK))
        effective_attendees = get_portal_effective_attendees(team["id"], match_id)
        assignments = [
            {"passenger_name": passenger_name, "driver_name": driver_name}
            for passenger_name, driver_name in zip(request.form.getlist("passenger_name"), request.form.getlist("driver_name"))
            if (passenger_name or "").strip() in effective_attendees
        ]
        saved, status = portal_save_transport_assignments(team["id"], match_id, assignments)
        redirect_kwargs = {"public_id": public_id, "match_id": match_id}
        if not saved and status:
            redirect_kwargs["tool_message"] = status
        return redirect(url_for("public_attendance_transport_assignments", **redirect_kwargs))

    def public_attendance_check_save_tool_result(public_id, match_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_TEAM_SPLIT))

        tool_type = (request.form.get("tool_type") or "").strip()
        title = (request.form.get("title") or "").strip()
        payload = None

        if tool_type == "team_split":
            teams = parse_team_state_from_form(request.form.get("team_state_json", ""))
            if teams:
                payload = {"teams": serialize_team_result(teams)}
            if not title:
                title = f"チーム分け {datetime.now().strftime('%m/%d %H:%M')}"
        elif tool_type == "role_assign":
            try:
                role_state = json.loads(request.form.get("role_state_json", "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                role_state = {}
            if isinstance(role_state, dict) and role_state:
                payload = role_state
            if not title:
                title = f"役割決め {datetime.now().strftime('%m/%d %H:%M')}"
        elif tool_type == "random_pick":
            picked_names = parse_random_pick_names(request.form.get("picked_names_json", ""), request.form.get("picked_name", ""))
            if picked_names:
                payload = {"picked_names": picked_names}
            if not title:
                title = f"代表者選出 {datetime.now().strftime('%m/%d %H:%M')}"
        else:
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="保存対象の種類が不正です。"))

        if not payload:
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="保存対象の結果がありません。"))

        create_portal_tool_saved_result(team["id"], match_id, tool_type, title, payload)
        return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="結果を保存しました。"))

    def public_attendance_check_load_tool_result(public_id, match_id, saved_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        if not can_team_use_paid_feature(team):
            return build_member_page_notice_redirect(public_id, get_plan_restriction_message(PLAN_FEATURE_TEAM_SPLIT))
        saved = get_portal_tool_saved_result(team["id"], match_id, saved_id)
        if not saved:
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="保存結果が見つかりません。"))

        tool_type = saved.get("tool_type")
        payload = saved.get("payload") or {}
        title = saved.get("title") or "保存結果"
        if tool_type == "team_split":
            teams = payload.get("teams") if isinstance(payload, dict) else []
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_type="team_split", team_state=json.dumps(teams, ensure_ascii=False), team_count=len(teams), tool_message=f"{title} を再利用しました。"))
        if tool_type == "role_assign":
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message=f"{title} は役割決め機能のため再利用できません。"))
        if tool_type == "random_pick":
            picked_names = []
            if isinstance(payload, dict):
                picked_names = parse_random_pick_names(json.dumps(payload.get("picked_names", []), ensure_ascii=False), payload.get("picked_name", ""))
            return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_type="random_pick", picked_names=json.dumps(picked_names, ensure_ascii=False), pick_count=max(1, len(picked_names)), tool_message=f"{title} を再利用しました。"))
        return redirect(url_for("public_attendance_tools", public_id=public_id, match_id=match_id, tool_message="この保存結果は再利用できません。"))

    def public_attendance_tool_share_view(public_id, share_id):
        team = get_team_by_public_id(public_id)
        if not team:
            return redirect(url_for("attendance_description"))
        share_data = get_portal_tool_share(share_id)
        if not share_data or share_data.get("team_id") != team["id"]:
            return "Share data not found.", 404
        payload = share_data.get("payload") or {}
        teams = payload.get("teams") if isinstance(payload, dict) else []
        if not isinstance(teams, list):
            teams = []
        return render_template(
            "attendance_team_share.html",
            share_id=share_id,
            teams=parse_team_state_from_form(json.dumps(teams, ensure_ascii=False)),
            created_at=share_data.get("created_at"),
        )

    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>", endpoint="public_attendance_check", view_func=public_attendance_check)
    app.add_url_rule("/team/<public_id>/attendance/tools/<int:match_id>", endpoint="public_attendance_tools", view_func=public_attendance_tools)
    app.add_url_rule("/team/<public_id>/attendance/tools/<int:match_id>/transport", endpoint="public_attendance_transport_assignments", view_func=public_attendance_transport_assignments)
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/confirm", endpoint="public_attendance_check_confirm_attendees", view_func=public_attendance_check_confirm_attendees, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/walkin", endpoint="public_attendance_check_add_walkin", view_func=public_attendance_check_add_walkin, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/walkin/delete", endpoint="public_attendance_check_delete_walkin", view_func=public_attendance_check_delete_walkin, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/walkin/delete-selected", endpoint="public_attendance_check_delete_selected_walkins", view_func=public_attendance_check_delete_selected_walkins, methods=["POST"])
    app.add_url_rule("/team/<public_id>/transport/<int:event_id>", endpoint="public_transport", view_func=public_transport, methods=["GET", "POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/team-split", endpoint="public_attendance_check_team_split", view_func=public_attendance_check_team_split, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/team-rerun", endpoint="public_attendance_check_team_rerun", view_func=public_attendance_check_team_rerun, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/team-swap", endpoint="public_attendance_check_team_swap", view_func=public_attendance_check_team_swap, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/team-share", endpoint="public_attendance_check_team_share", view_func=public_attendance_check_team_share, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/role-assign", endpoint="public_attendance_check_role_assign", view_func=public_attendance_check_role_assign, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/random-pick", endpoint="public_attendance_check_random_pick", view_func=public_attendance_check_random_pick, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/transport-assign", endpoint="public_attendance_tools_save_transport_assignments", view_func=public_attendance_tools_save_transport_assignments, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/save", endpoint="public_attendance_check_save_tool_result", view_func=public_attendance_check_save_tool_result, methods=["POST"])
    app.add_url_rule("/team/<public_id>/attendance/check/<int:match_id>/tools/load/<int:saved_id>", endpoint="public_attendance_check_load_tool_result", view_func=public_attendance_check_load_tool_result, methods=["POST"])
    app.add_url_rule("/team/<public_id>/share/<share_id>", endpoint="public_attendance_tool_share_view", view_func=public_attendance_tool_share_view)
