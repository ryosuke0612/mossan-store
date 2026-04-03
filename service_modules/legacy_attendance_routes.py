import json
import random
from datetime import datetime

from flask import redirect, render_template, request, session, url_for


def register_legacy_attendance_routes(
    app,
    *,
    _coerce_positive_int,
    _coerce_team_count,
    _normalize_name_list,
    add_walkin_attendee,
    build_team_allocator,
    build_time_from_form,
    create_attendance_tool_saved_result,
    create_attendance_tool_share,
    format_date_mmdd_with_weekday,
    get_attendance_tool_saved_result,
    get_attendance_tool_saved_results,
    get_confirmed_attendees,
    get_db_connection,
    get_effective_attendees,
    is_valid_10min_time,
    login_required,
    normalize_status,
    parse_random_pick_names,
    parse_team_state_from_form,
    redirect_to_app_with_month,
    remove_walkin_attendee,
    save_confirmed_attendees,
    serialize_team_result,
    swap_members_in_teams,
):
    def add_match():
        current_month = request.args.get("month", "").strip()
        if request.method == "GET":
            return render_template("add.html", current_month=current_month)

        start_time = build_time_from_form("start_time")
        end_time = build_time_from_form("end_time")
        if not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
            return "start_time/end_time must be in 10-minute increments.", 400

        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            """
        INSERT INTO matches (user_id, date, start_time, end_time, opponent, place)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                session["user_id"],
                request.form["date"],
                start_time,
                end_time,
                request.form["opponent"],
                request.form["place"],
            ),
        )

        conn.commit()
        conn.close()
        return_month = request.form.get("return_month", "").strip() or current_month
        if not return_month:
            return_month = request.form.get("date", "")[:7]
        return redirect_to_app_with_month(return_month)

    def delete_match(id):
        conn = get_db_connection()
        c = conn.cursor()

        c.execute("DELETE FROM attendance WHERE match_id=? AND user_id=?", (id, session["user_id"]))
        c.execute("DELETE FROM matches WHERE id=? AND user_id=?", (id, session["user_id"]))

        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    def duplicate_match(id):
        conn = get_db_connection()
        c = conn.cursor()

        c.execute(
            """
        INSERT INTO matches (user_id, date, start_time, end_time, opponent, place)
        SELECT ?, date, start_time, end_time, opponent, place
        FROM matches
        WHERE id=? AND user_id=?
        """,
            (session["user_id"], id, session["user_id"]),
        )

        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    def bulk_match_action():
        action = request.form.get("action", "")
        current_month = request.form.get("current_month", "").strip()
        selected_ids_raw = request.form.getlist("selected_ids")

        if not selected_ids_raw:
            return redirect_to_app_with_month(current_month)

        try:
            selected_ids = [int(match_id) for match_id in selected_ids_raw]
        except ValueError:
            return redirect_to_app_with_month(current_month)

        placeholders = ",".join("?" for _ in selected_ids)
        conn = get_db_connection()
        c = conn.cursor()

        c.execute(
            f"""
            SELECT id, date, start_time, end_time, opponent, place
            FROM matches
            WHERE user_id=? AND id IN ({placeholders})
            ORDER BY date, start_time
            """,
            [session["user_id"], *selected_ids],
        )
        target_matches = c.fetchall()
        target_ids = [row["id"] for row in target_matches]

        if not target_ids:
            conn.close()
            return redirect_to_app_with_month(current_month)

        if action == "edit":
            conn.close()
            return redirect(url_for("edit_match", id=target_ids[0], month=current_month))
        if action == "attendance_check":
            conn.close()
            return redirect(url_for("attendance_check", match_id=target_ids[0], month=current_month))

        target_placeholders = ",".join("?" for _ in target_ids)

        if action == "duplicate":
            c.executemany(
                """
                INSERT INTO matches (user_id, date, start_time, end_time, opponent, place)
                SELECT ?, date, start_time, end_time, opponent, place
                FROM matches
                WHERE id=? AND user_id=?
                """,
                [(session["user_id"], match_id, session["user_id"]) for match_id in target_ids],
            )
        elif action == "delete":
            c.execute(
                f"DELETE FROM attendance WHERE user_id=? AND match_id IN ({target_placeholders})",
                [session["user_id"], *target_ids],
            )
            c.execute(
                f"DELETE FROM matches WHERE user_id=? AND id IN ({target_placeholders})",
                [session["user_id"], *target_ids],
            )
        else:
            conn.close()
            return redirect_to_app_with_month(current_month)

        conn.commit()
        conn.close()
        return redirect_to_app_with_month(current_month)

    def attendance_check(match_id):
        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT * FROM matches WHERE id=? AND user_id=?", (match_id, session["user_id"]))
        match = c.fetchone()
        if not match:
            conn.close()
            return redirect(url_for("index"))

        c.execute(
            """
            SELECT name, status
            FROM attendance
            WHERE match_id=? AND user_id=?
            ORDER BY id
            """,
            (match_id, session["user_id"]),
        )
        rows = c.fetchall()
        conn.close()

        grouped_members = {"参加": [], "不参加": [], "未定": []}
        for row in rows:
            status = normalize_status(row["status"])
            if status in grouped_members:
                grouped_members[status].append(row["name"])

        match_data = dict(match)
        match_data["date_label"] = format_date_mmdd_with_weekday(match["date"])
        confirmed_rows = get_confirmed_attendees(session["user_id"], match_id)
        confirmed_names = [
            row.get("name")
            for row in confirmed_rows
            if row.get("name") and row.get("source_type") != "walkin_pending"
        ]
        walkin_names = [
            row.get("name")
            for row in confirmed_rows
            if row.get("name") and row.get("source_type") in ("walkin", "walkin_pending")
        ]
        has_confirmed_today = bool(confirmed_names)
        candidate_names = _normalize_name_list(grouped_members["参加"] + walkin_names)
        effective_attendees = get_effective_attendees(session["user_id"], match_id)

        tool_message = request.args.get("tool_message", "").strip()

        return render_template(
            "attendance_check.html",
            match=match_data,
            join_members=grouped_members["参加"],
            absent_members=grouped_members["不参加"],
            undecided_members=grouped_members["未定"],
            candidate_names=candidate_names,
            confirmed_names=confirmed_names,
            walkin_names=walkin_names,
            has_confirmed_today=has_confirmed_today,
            effective_attendees=effective_attendees,
            tool_message=tool_message,
            tools_url=url_for("attendance_tools", match_id=match_id),
        )

    def attendance_tools(match_id):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM matches WHERE id=? AND user_id=?", (match_id, session["user_id"]))
        match = c.fetchone()
        conn.close()
        if not match:
            return redirect(url_for("index"))

        match_data = dict(match)
        match_data["date_label"] = format_date_mmdd_with_weekday(match["date"])
        effective_attendees = get_effective_attendees(session["user_id"], match_id)

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
            random_pick = parse_random_pick_names(
                request.args.get("picked_names", ""),
                request.args.get("picked_name", ""),
            )
        if team_result:
            share_id = request.args.get("share_id", "").strip()
            if share_id:
                team_share_url = url_for("attendance_tool_share_view", share_id=share_id, _external=True)
                lines = ["【チーム分け結果】"]
                for team_data in team_result:
                    lines.append(f"{team_data['name']}: " + ", ".join(team_data["members"]))
                team_share_text = "\n".join(lines)
                team_qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=240x240&data={team_share_url}"

        saved_tool_results = get_attendance_tool_saved_results(session["user_id"], match_id, limit=30)
        return render_template(
            "attendance_tools.html",
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

    def attendance_check_confirm_attendees(match_id):
        selected_names = request.form.getlist("confirmed_names")
        walkin_names = request.form.getlist("walkin_names")
        save_confirmed_attendees(session["user_id"], match_id, selected_names, walkin_names)
        return redirect(
            url_for(
                "attendance_check",
                match_id=match_id,
                tool_message="当日参加者を確定しました。",
            )
        )

    def attendance_check_add_walkin(match_id):
        walkin_name = request.form.get("walkin_name", "")
        added = add_walkin_attendee(session["user_id"], match_id, walkin_name)
        message = "飛び入り参加者を追加しました。" if added else "飛び入り参加者名を入力してください。"
        return redirect(url_for("attendance_check", match_id=match_id, tool_message=message))

    def attendance_check_delete_walkin(match_id):
        member_name = request.form.get("member_name", "")
        deleted = remove_walkin_attendee(session["user_id"], match_id, member_name)
        message = "飛び入り参加者を削除しました。" if deleted else "削除対象の飛び入り参加者が見つかりませんでした。"
        return redirect(url_for("attendance_check", match_id=match_id, tool_message=message))

    def attendance_check_team_split(match_id):
        attendees = get_effective_attendees(session["user_id"], match_id)
        if len(attendees) < 2:
            return redirect(url_for("attendance_tools", match_id=match_id, tool_message="チーム分けには2名以上必要です。"))

        team_count = _coerce_team_count(request.form.get("team_count"), default=2)
        allocator = build_team_allocator("random")
        teams = allocator.allocate(attendees, team_count)
        team_state = json.dumps(serialize_team_result(teams), ensure_ascii=False)

        return redirect(
            url_for(
                "attendance_tools",
                match_id=match_id,
                tool_type="team_split",
                team_state=team_state,
                team_count=team_count,
                tool_message=f"{team_count}チームにランダム分けしました。",
            )
        )

    def attendance_check_team_rerun(match_id):
        attendees = get_effective_attendees(session["user_id"], match_id)
        team_count = _coerce_team_count(request.form.get("team_count"), default=2)
        if len(attendees) < 2:
            return redirect(url_for("attendance_tools", match_id=match_id, tool_message="参加者が不足しているため再実行できません。"))
        teams = build_team_allocator("random").allocate(attendees, team_count)
        team_state = json.dumps(serialize_team_result(teams), ensure_ascii=False)
        return redirect(
            url_for(
                "attendance_tools",
                match_id=match_id,
                tool_type="team_split",
                team_state=team_state,
                team_count=team_count,
                tool_message="チーム分けを再実行しました。",
            )
        )

    def attendance_check_team_swap(match_id):
        teams = parse_team_state_from_form(request.form.get("team_state_json", ""))
        src_team_idx = _coerce_positive_int(request.form.get("src_team_idx"))
        src_member_idx = _coerce_positive_int(request.form.get("src_member_idx"))
        dst_team_idx = _coerce_positive_int(request.form.get("dst_team_idx"))
        dst_member_idx = _coerce_positive_int(request.form.get("dst_member_idx"))
        if None in {src_team_idx, src_member_idx, dst_team_idx, dst_member_idx}:
            team_state = json.dumps(serialize_team_result(teams), ensure_ascii=False)
            return redirect(
                url_for(
                    "attendance_tools",
                    match_id=match_id,
                    tool_type="team_split",
                    team_state=team_state,
                    team_count=len(teams),
                    tool_message="入れ替え対象を選択してください。",
                )
            )
        updated_teams, swap_status = swap_members_in_teams(
            teams,
            src_team_idx - 1,
            src_member_idx - 1,
            dst_team_idx - 1,
            dst_member_idx - 1,
        )
        message = "メンバーを入れ替えました。" if swap_status == "swapped" else "入れ替えに失敗しました。"
        team_state = json.dumps(serialize_team_result(updated_teams), ensure_ascii=False)
        return redirect(
            url_for(
                "attendance_tools",
                match_id=match_id,
                tool_type="team_split",
                team_state=team_state,
                team_count=len(updated_teams),
                tool_message=message,
            )
        )

    def attendance_check_team_share(match_id):
        teams = parse_team_state_from_form(request.form.get("team_state_json", ""))
        if not teams:
            return redirect(url_for("attendance_tools", match_id=match_id, tool_message="共有するチーム分け結果がありません。"))
        share_payload = {"teams": serialize_team_result(teams)}
        share_id = create_attendance_tool_share(session["user_id"], match_id, "team_split", share_payload)
        return redirect(
            url_for(
                "attendance_tools",
                match_id=match_id,
                tool_type="team_split",
                team_state=json.dumps(share_payload["teams"], ensure_ascii=False),
                team_count=len(share_payload["teams"]),
                share_id=share_id,
                tool_message="共有URLを作成しました。",
            )
        )

    def attendance_check_role_assign(match_id):
        return redirect(url_for("attendance_tools", match_id=match_id, tool_message="役割決め機能は廃止しました。"))

    def attendance_check_random_pick(match_id):
        attendees = get_effective_attendees(session["user_id"], match_id)
        if not attendees:
            return redirect(url_for("attendance_tools", match_id=match_id, tool_message="当日参加者を先に確定してください。"))
        pick_count = _coerce_team_count(
            request.form.get("pick_count"),
            default=1,
            minimum=1,
            maximum=max(1, len(attendees)),
        )
        picked_names = random.sample(attendees, k=pick_count)
        picked_label = f"{len(picked_names)}人" if len(picked_names) > 1 else "1人"
        return redirect(
            url_for(
                "attendance_tools",
                match_id=match_id,
                tool_type="random_pick",
                picked_names=json.dumps(picked_names, ensure_ascii=False),
                pick_count=pick_count,
                tool_message=f"ランダムで{picked_label}を代表者に選出しました。",
            )
        )

    def attendance_check_save_tool_result(match_id):
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
            picked_names = parse_random_pick_names(
                request.form.get("picked_names_json", ""),
                request.form.get("picked_name", ""),
            )
            if picked_names:
                payload = {"picked_names": picked_names}
            if not title:
                title = f"代表者選出 {datetime.now().strftime('%m/%d %H:%M')}"
        else:
            return redirect(url_for("attendance_tools", match_id=match_id, tool_message="保存対象の種類が不正です。"))

        if not payload:
            return redirect(url_for("attendance_tools", match_id=match_id, tool_message="保存対象の結果がありません。"))

        create_attendance_tool_saved_result(session["user_id"], match_id, tool_type, title, payload)
        return redirect(url_for("attendance_tools", match_id=match_id, tool_message="結果を保存しました。"))

    def attendance_check_load_tool_result(match_id, saved_id):
        saved = get_attendance_tool_saved_result(session["user_id"], match_id, saved_id)
        if not saved:
            return redirect(url_for("attendance_tools", match_id=match_id, tool_message="保存結果が見つかりません。"))

        tool_type = saved.get("tool_type")
        payload = saved.get("payload") or {}
        title = saved.get("title") or "保存結果"
        if tool_type == "team_split":
            teams = payload.get("teams") if isinstance(payload, dict) else []
            return redirect(
                url_for(
                    "attendance_tools",
                    match_id=match_id,
                    tool_type="team_split",
                    team_state=json.dumps(teams, ensure_ascii=False),
                    team_count=len(teams),
                    tool_message=f"{title} を再利用しました。",
                )
            )
        if tool_type == "role_assign":
            return redirect(
                url_for(
                    "attendance_tools",
                    match_id=match_id,
                    tool_message=f"{title} は役割決め機能のため再利用できません。",
                )
            )
        if tool_type == "random_pick":
            picked_names = []
            if isinstance(payload, dict):
                picked_names = parse_random_pick_names(
                    json.dumps(payload.get("picked_names", []), ensure_ascii=False),
                    payload.get("picked_name", ""),
                )
            return redirect(
                url_for(
                    "attendance_tools",
                    match_id=match_id,
                    tool_type="random_pick",
                    picked_names=json.dumps(picked_names, ensure_ascii=False),
                    pick_count=max(1, len(picked_names)),
                    tool_message=f"{title} を再利用しました。",
                )
            )
        return redirect(url_for("attendance_tools", match_id=match_id, tool_message="この保存結果は再利用できません。"))

    def attendance_tool_share_view(share_id):
        share_data = get_attendance_tool_share(share_id)
        if not share_data:
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

    def edit_match(id):
        current_month = request.args.get("month", "").strip()
        conn = get_db_connection()
        c = conn.cursor()

        if request.method == "POST":
            start_time = build_time_from_form("start_time")
            end_time = build_time_from_form("end_time")
            if not is_valid_10min_time(start_time) or not is_valid_10min_time(end_time):
                conn.close()
                return "start_time/end_time must be in 10-minute increments.", 400

            c.execute(
                """
            UPDATE matches
            SET date=?, start_time=?, end_time=?, opponent=?, place=?
            WHERE id=? AND user_id=?
            """,
                (
                    request.form["date"],
                    start_time,
                    end_time,
                    request.form["opponent"],
                    request.form["place"],
                    id,
                    session["user_id"],
                ),
            )
            conn.commit()
            conn.close()
            return_month = request.form.get("return_month", "").strip() or current_month
            if not return_month:
                return_month = request.form.get("date", "")[:7]
            return redirect_to_app_with_month(return_month)

        c.execute("SELECT * FROM matches WHERE id=? AND user_id=?", (id, session["user_id"]))
        match = c.fetchone()
        conn.close()

        if not match:
            return redirect_to_app_with_month(current_month)

        return render_template("edit.html", match=match, current_month=current_month)

    def attendance_month():
        conn = get_db_connection()
        c = conn.cursor()

        c.execute(
            """
            SELECT DISTINCT substr(date,1,7) as month
            FROM matches
            WHERE user_id=?
            ORDER BY month
            """,
            (session["user_id"],),
        )
        months = [row["month"] for row in c.fetchall()]
        c.execute(
            """
            SELECT
                a.name,
                MIN(a.id) AS first_attendance_id
            FROM attendance a
            JOIN matches m ON m.id = a.match_id
            WHERE m.user_id=?
            GROUP BY a.name
            ORDER BY first_attendance_id
            """,
            (session["user_id"],),
        )
        member_options = [row["name"] for row in c.fetchall() if row["name"]]

        selected_month = request.args.get("month")
        name = (request.args.get("name") or "").strip()
        if name and name not in member_options:
            name = ""
        error_message = ""

        if not selected_month and months:
            selected_month = months[0]

        if request.method == "POST":
            selected_month = request.form.get("month") or selected_month
            name = request.form.get("name", "").strip()
            filter_name = request.form.get("filter_name", "").strip()
            if filter_name and filter_name not in member_options:
                filter_name = ""
            match_id = request.form["match_id"]
            status = normalize_status(request.form["status"])

            if not name:
                error_message = "メンバーを選択してから出欠を登録してください。"
            elif name not in member_options:
                error_message = "選択したメンバーは登録されていません。"
            else:
                c.execute(
                    "SELECT id FROM matches WHERE id=? AND user_id=?",
                    (match_id, session["user_id"]),
                )
                match = c.fetchone()
                if not match:
                    conn.close()
                    return redirect_to_app_with_month(selected_month)

                c.execute(
                    """
                INSERT INTO attendance (user_id, match_id, name, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(match_id, name)
                DO UPDATE SET status=excluded.status, user_id=excluded.user_id
                """,
                    (session["user_id"], match_id, name, status),
                )

                conn.commit()
                conn.close()
                return redirect(
                    url_for(
                        "attendance_month",
                        month=selected_month or "",
                        name=filter_name or "",
                    )
                )

        matches = []
        attendance_dict = {}
        display_member_names = [name] if name else member_options

        if selected_month:
            c.execute(
                """
            SELECT * FROM matches
            WHERE user_id=? AND substr(date,1,7)=?
            ORDER BY date, start_time
            """,
                (session["user_id"], selected_month),
            )
            for row in c.fetchall():
                match_data = dict(row)
                match_data["date_label"] = format_date_mmdd_with_weekday(row["date"])
                matches.append(match_data)

            if display_member_names:
                placeholders = ",".join("?" for _ in display_member_names)
                c.execute(
                    f"""
                SELECT a.match_id, a.name, a.status
                FROM attendance a
                JOIN matches m ON m.id = a.match_id
                WHERE m.user_id=?
                  AND substr(m.date,1,7)=?
                  AND a.name IN ({placeholders})
                """,
                    [session["user_id"], selected_month, *display_member_names],
                )
                attendance_dict = {
                    (row["match_id"], row["name"]): normalize_status(row["status"]) for row in c.fetchall()
                }

        conn.close()

        return render_template(
            "attendance_month.html",
            months=months,
            selected_month=selected_month,
            matches=matches,
            name=name,
            member_options=member_options,
            display_member_names=display_member_names,
            attendance_dict=attendance_dict,
            error_message=error_message,
            edit_mode=bool(name),
        )

    def delete_member_attendance_by_month():
        month = request.args.get("month", "").strip()
        name = request.args.get("name", "").strip()

        if not month or not name:
            return redirect_to_app_with_month(month)

        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            """
            DELETE FROM attendance
            WHERE user_id=?
              AND name=?
              AND match_id IN (
                  SELECT id
                  FROM matches
                  WHERE user_id=? AND substr(date,1,7)=?
              )
            """,
            (session["user_id"], name, session["user_id"], month),
        )
        conn.commit()
        conn.close()

        return redirect_to_app_with_month(month)

    app.add_url_rule(
        "/apps/attendance/app/add",
        endpoint="add_match",
        view_func=login_required(add_match),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/delete/<int:id>",
        endpoint="delete_match",
        view_func=login_required(delete_match),
        methods=["GET"],
    )
    app.add_url_rule(
        "/apps/attendance/app/duplicate/<int:id>",
        endpoint="duplicate_match",
        view_func=login_required(duplicate_match),
        methods=["GET"],
    )
    app.add_url_rule(
        "/apps/attendance/app/matches/action",
        endpoint="bulk_match_action",
        view_func=login_required(bulk_match_action),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>",
        endpoint="attendance_check",
        view_func=login_required(attendance_check),
        methods=["GET"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/tools/<int:match_id>",
        endpoint="attendance_tools",
        view_func=login_required(attendance_tools),
        methods=["GET"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/confirm",
        endpoint="attendance_check_confirm_attendees",
        view_func=login_required(attendance_check_confirm_attendees),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/walkin",
        endpoint="attendance_check_add_walkin",
        view_func=login_required(attendance_check_add_walkin),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/walkin/delete",
        endpoint="attendance_check_delete_walkin",
        view_func=login_required(attendance_check_delete_walkin),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/tools/team-split",
        endpoint="attendance_check_team_split",
        view_func=login_required(attendance_check_team_split),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/tools/team-rerun",
        endpoint="attendance_check_team_rerun",
        view_func=login_required(attendance_check_team_rerun),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/tools/team-swap",
        endpoint="attendance_check_team_swap",
        view_func=login_required(attendance_check_team_swap),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/tools/team-share",
        endpoint="attendance_check_team_share",
        view_func=login_required(attendance_check_team_share),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/tools/role-assign",
        endpoint="attendance_check_role_assign",
        view_func=login_required(attendance_check_role_assign),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/tools/random-pick",
        endpoint="attendance_check_random_pick",
        view_func=login_required(attendance_check_random_pick),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/tools/save",
        endpoint="attendance_check_save_tool_result",
        view_func=login_required(attendance_check_save_tool_result),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/check/<int:match_id>/tools/load/<int:saved_id>",
        endpoint="attendance_check_load_tool_result",
        view_func=login_required(attendance_check_load_tool_result),
        methods=["POST"],
    )
    app.add_url_rule(
        "/apps/attendance/share/<share_id>",
        endpoint="attendance_tool_share_view",
        view_func=attendance_tool_share_view,
        methods=["GET"],
    )
    app.add_url_rule(
        "/apps/attendance/app/edit/<int:id>",
        endpoint="edit_match",
        view_func=login_required(edit_match),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/month",
        endpoint="attendance_month",
        view_func=login_required(attendance_month),
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/apps/attendance/app/attendance/member/delete",
        endpoint="delete_member_attendance_by_month",
        view_func=login_required(delete_member_attendance_by_month),
        methods=["POST"],
    )
