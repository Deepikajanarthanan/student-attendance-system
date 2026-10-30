from datetime import date

import pandas as pd
import streamlit as st

from attendance import (
    add_or_update_holiday,
    attendance_exists,
    delete_attendance,
    get_absent_roll_nos,
    get_register_session,
    get_session_class_dates,
    get_session_status,
    get_students,
    holiday_for_date,
    save_attendance,
    save_register_session,
)
from database import init_db
from reports import calculate_attendance_marks, generate_register_excel

st.set_page_config(page_title="Attendance Register | Attendance", page_icon="📅", layout="wide")
init_db()

active_students = get_students(active_only=True)

register_tab, single_tab = st.tabs(["📋 Attendance Register Workflow", "📅 Single Date / Holiday"])

with register_tab:
    st.title("📋 Attendance Register Workflow")
    st.caption("Mark absent students date-by-date by Roll No from Start Date to End Date. Excel export with 5-mark attendance score unlocks after the last date is marked.")

    if not active_students:
        st.warning("⚠️ No active students found. Please add or upload students first on the **Students** page.")
        st.stop()

    session = get_register_session()

    # Session Configuration Expander
    with st.expander("⚙️ Configure Register Session Dates & Schedule", expanded=(session is None)):
        today_val = date.today()
        c1, c2 = st.columns(2)
        curr_start = session["start_date"] if session else today_val
        curr_end = session["end_date"] if session else today_val
        new_start = c1.date_input("Start Date", value=curr_start, format="DD-MM-YYYY", key="reg_start_input")
        new_end = c2.date_input("End Date", value=curr_end, format="DD-MM-YYYY", key="reg_end_input")

        weekday_map = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
        curr_weekdays = session["weekdays"] if session else [0, 3]
        new_weekdays = st.multiselect(
            "Class Days of Week",
            options=list(weekday_map.keys()),
            default=curr_weekdays,
            format_func=lambda k: weekday_map[k],
            help="Select which days classes occur (e.g., Monday and Thursday as in the register sheet)",
            key="reg_weekdays_input",
        )

        st.markdown("**Select the Period/Hour of the Day for each class day (e.g. 1st or 4th hour):**")
        curr_wp = session.get("weekday_periods", {}) if session else {0: 1, 3: 4}
        new_wp: dict[int, int] = {}
        if new_weekdays:
            cols = st.columns(min(len(new_weekdays), 4))
            hour_options = {1: "1st Hour (Period 1)", 2: "2nd Hour (Period 2)", 3: "3rd Hour (Period 3)",
                            4: "4th Hour (Period 4)", 5: "5th Hour (Period 5)", 6: "6th Hour (Period 6)",
                            7: "7th Hour (Period 7)", 8: "8th Hour (Period 8)"}
            for i, w_day in enumerate(sorted(new_weekdays)):
                col = cols[i % len(cols)]
                def_hr = curr_wp.get(w_day, 1 if w_day == 0 else 4 if w_day == 3 else 1)
                chosen_hr = col.selectbox(
                    f"{weekday_map[w_day]} Hour",
                    options=list(hour_options.keys()),
                    format_func=lambda h: hour_options[h],
                    index=list(hour_options.keys()).index(def_hr) if def_hr in hour_options else 0,
                    key=f"reg_wp_day_{w_day}",
                )
                new_wp[w_day] = chosen_hr

        st.caption("ℹ️ **Attendance Rule**: Each class date counts as exactly **1 hour** of attendance (e.g. 40 class days = 40 hours total).")

        if st.button("Save & Update Session Schedule", type="primary" if session is None else "secondary"):
            if new_end < new_start:
                st.error("End date cannot be earlier than start date.")
            elif not new_weekdays:
                st.error("Please select at least one class day of the week.")
            else:
                save_register_session(new_start, new_end, new_weekdays, periods_per_day=1, weekday_periods=new_wp)
                st.success("Attendance register schedule saved!")
                st.rerun()

    if not session:
        st.info("👆 Please configure your Start Date and End Date above to begin marking attendance.")
        st.stop()

    class_dates = get_session_class_dates(session["start_date"], session["end_date"], session["weekdays"])
    if not class_dates:
        st.warning(f"No class dates found between {session['start_date'].strftime('%d-%m-%Y')} and {session['end_date'].strftime('%d-%m-%Y')} for the selected weekdays.")
        st.stop()

    status = get_session_status(class_dates)
    total_dates = len(class_dates)
    marked_count = len(status["marked_dates"])
    remaining_count = len(status["unmarked_dates"])
    pct_done = (marked_count / total_dates) if total_dates else 0.0

    # Progress Summary
    st.subheader("Progress Overview")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Date Range", f"{session['start_date'].strftime('%d-%b')} to {session['end_date'].strftime('%d-%b')}")
    m2.metric("Total Class Dates", f"{total_dates} dates")
    m3.metric("Marked Dates", f"{marked_count} / {total_dates}")
    m4.metric("Remaining Dates", f"{remaining_count} left")

    st.progress(pct_done, text=f"Attendance progress: {marked_count} of {total_dates} dates marked ({pct_done*100:.1f}%)")

    st.divider()

    # Build data list for all scheduled dates
    table_rows = []
    for idx, d in enumerate(class_dates, start=1):
        d_iso = d.isoformat()
        is_hol = bool(holiday_for_date(d_iso))
        is_saved = attendance_exists(d_iso)
        curr_abs = get_absent_roll_nos(d_iso)
        curr_p = session.get("weekday_periods", {}).get(d.weekday(), 1)
        hr_str = f"{curr_p}{'st' if curr_p==1 else 'nd' if curr_p==2 else 'rd' if curr_p==3 else 'th'} Hr"
        date_label = f"#{idx}: {d.strftime('%d-%m-%Y (%A)')} — {hr_str}"

        if is_hol:
            init_val = "holiday"
            status_text = "🏖️ Holiday"
        elif is_saved:
            if curr_abs:
                init_val = ", ".join(curr_abs)
                status_text = f"✅ Marked ({len(curr_abs)} absent)"
            else:
                init_val = "P"
                status_text = "✅ All Present"
        else:
            init_val = ""
            status_text = "⏳ Pending"

        table_rows.append({
            "idx": idx,
            "date": d,
            "date_iso": d_iso,
            "date_label": date_label,
            "init_val": init_val,
            "status": status_text,
            "is_saved": is_saved,
            "is_hol": is_hol,
        })

    st.caption("ℹ️ **Instructions**: Enter absent roll numbers (e.g. `1, 4` or `01, 04`) for each date. Type `'holiday'` if it was a holiday. Type `'P'` or leave blank if all students were present.")

    # Action buttons at top
    b_col1, b_col2, b_col3 = st.columns([2, 2, 1])
    save_all_top = b_col1.button("💾 Save All Attendance", type="primary", use_container_width=True, key="reg_save_all_top")
    mark_unmarked_p = b_col2.button("✅ Mark All Remaining as All Present", use_container_width=True, key="reg_mark_all_p_top")
    if b_col3.button("🔄 Refresh", use_container_width=True, key="reg_refresh_top"):
        st.rerun()

    tab_editor, tab_form = st.tabs(["📊 Interactive Table View (Spreadsheet)", "📝 Two-Column Form View"])

    with tab_editor:
        df_display = pd.DataFrame([
            {
                "Date & Day": r["date_label"],
                "Absent Roll Numbers (or 'holiday' / 'P')": r["init_val"],
                "Status": r["status"],
            }
            for r in table_rows
        ])
        edited_grid = st.data_editor(
            df_display,
            column_config={
                "Date & Day": st.column_config.TextColumn("Date & Day", disabled=True, width="medium"),
                "Absent Roll Numbers (or 'holiday' / 'P')": st.column_config.TextColumn(
                    "Absent Roll Numbers (or 'holiday' / 'P')",
                    help="Enter roll numbers separated by comma (e.g. 02, 15), or type 'holiday', or 'P'",
                    width="large",
                ),
                "Status": st.column_config.TextColumn("Status", disabled=True, width="small"),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            key="reg_grid_editor",
        )

    with tab_form:
        header_col1, header_col2, header_col3 = st.columns([3, 4, 2])
        header_col1.markdown("**📅 Date & Day**")
        header_col2.markdown("**✍️ Absent Roll Numbers (or 'holiday' / 'P')**")
        header_col3.markdown("**📌 Status**")
        st.markdown("<hr style='margin-top: 0; margin-bottom: 10px;'>", unsafe_allow_html=True)

        form_inputs = {}
        for r in table_rows:
            fc1, fc2, fc3 = st.columns([3, 4, 2])
            fc1.write(f"**{r['date_label']}**")
            val = fc2.text_input(
                f"reg_absent_{r['date_iso']}",
                value=r["init_val"],
                placeholder="e.g. 1, 4 or 'holiday' or 'P'",
                label_visibility="collapsed",
                key=f"reg_form_roll_{r['date_iso']}",
            )
            fc3.caption(r["status"])
            form_inputs[r["date"]] = val

    save_all_bottom = st.button("💾 Save All Attendance", type="primary", use_container_width=True, key="reg_save_all_bottom")

    if save_all_top or save_all_bottom or mark_unmarked_p:
        errors = []
        saved_count = 0
        for i, r in enumerate(table_rows):
            d = r["date"]
            form_val = form_inputs.get(d, "").strip() if "form_inputs" in locals() and d in form_inputs else ""
            grid_val = str(edited_grid.iloc[i]["Absent Roll Numbers (or 'holiday' / 'P')"]).strip() if "edited_grid" in locals() and i < len(edited_grid) else ""

            if grid_val != r["init_val"]:
                raw_input = grid_val
            elif form_val != r["init_val"]:
                raw_input = form_val
            else:
                raw_input = grid_val or form_val or r["init_val"]
            raw_input = raw_input.strip()

            if mark_unmarked_p and not r["is_saved"] and not r["is_hol"] and not raw_input:
                raw_input = "P"

            if not raw_input:
                continue

            try:
                c_text = raw_input.casefold()
                if c_text in {"holiday", "h", "leave"}:
                    add_or_update_holiday(r["date_iso"], "Holiday", replace_attendance=True)
                    saved_count += 1
                elif c_text in {"p", "present", "all", "none", "nil", "0"}:
                    save_attendance(d, "", replace=True)
                    saved_count += 1
                else:
                    save_attendance(d, raw_input, replace=True)
                    saved_count += 1
            except ValueError as exc:
                errors.append(f"{d.strftime('%d-%m-%Y')}: {exc}")

        if errors:
            st.error("Some dates had errors:\n" + "\n".join(f"- {e}" for e in errors))
        else:
            st.success(f"✅ Attendance saved successfully for {saved_count} date(s)!")
            st.rerun()

    st.divider()

    # Excel Export Section - LOCKED until all dates through the last date are marked!
    st.subheader("📥 Export Official Register Excel")

    working_dates = [d for d in class_dates if not holiday_for_date(d.isoformat())]
    total_periods = len(working_dates)  # 1 hour per day -> 40 days = 40 hours!
    holidays_count = len(class_dates) - len(working_dates)

    if not status["is_complete"]:
        st.warning(
            f"🔒 **Excel Export is Locked**: Attendance has not yet been marked through the last date (**{class_dates[-1].strftime('%d-%m-%Y')}**).\n\n"
            f"**{remaining_count} date(s) remaining to mark:** "
            + ", ".join(d.strftime("%d-%m-%Y") for d in status["unmarked_dates"][:10])
            + ("..." if remaining_count > 10 else "")
        )
        st.button("📥 Download Excel Register (.xlsx)", disabled=True, help="Complete all attendance dates up to the end date to unlock export.")
    else:
        st.success(f"🎉 **All {total_dates} class dates through {class_dates[-1].strftime('%d-%m-%Y')} have been marked! ({len(working_dates)} Working Days / {total_periods} Hours + {holidays_count} Holidays)**")

        excel_bytes = generate_register_excel(
            session["start_date"],
            session["end_date"],
            class_dates=class_dates,
            periods_per_day=1,
        )
        file_name = f"attendance_register_{session['start_date'].strftime('%Y%m%d')}_{session['end_date'].strftime('%Y%m%d')}.xlsx"

        st.download_button(
            label="📥 Download Official Attendance Register (.xlsx)",
            data=excel_bytes,
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

        with st.expander("👁️ Preview Register Summary & 5-Mark Scores"):
            student_records = []
            for s in active_students:
                from database import connection
                with connection() as conn:
                    p_dates = [d.isoformat() for d in working_dates]
                    if p_dates:
                        placeholders = ",".join("?" for _ in p_dates)
                        cnt = conn.execute(
                            f"SELECT COUNT(*) FROM daily_attendance WHERE student_id=? AND status='P' AND attendance_date IN ({placeholders})",
                            (s["id"], *p_dates),
                        ).fetchone()[0]
                    else:
                        cnt = 0
                hrs_att = cnt * 1
                pct_att = (hrs_att / total_periods * 100.0) if total_periods else 0.0
                marks = calculate_attendance_marks(pct_att)
                student_records.append({
                    "Roll No": s["roll_no"],
                    "Reg No": s["reg_no"],
                    "Name": s["name"],
                    "HRS. ATT.": f"{hrs_att} / {total_periods}",
                    "% ATT.": f"{pct_att:.2f}%",
                    "Marks (Max 5)": marks,
                })
            st.dataframe(pd.DataFrame(student_records), use_container_width=True, hide_index=True)


with single_tab:
    st.title("📅 Single Date / Holiday Entry")
    st.caption("Quick entry for individual dates or holiday scheduling.")

    selected = st.date_input("Date", value=date.today(), format="DD-MM-YYYY", key="single_date_input")
    day = selected.isoformat()
    existing_attendance = attendance_exists(day)
    existing_holiday = holiday_for_date(day)
    day_type = st.radio("Day Type", ["Working Day", "Holiday"], horizontal=True, key="single_day_type")

    if existing_holiday and day_type == "Working Day":
        st.error("This date is already marked as a holiday. Please remove the holiday before recording attendance.")

    if day_type == "Working Day":
        if existing_attendance:
            st.warning("Attendance already exists for this date. Saving will replace it safely.")
        current = ", ".join(get_absent_roll_nos(day)) if existing_attendance else ""
        absent = st.text_area(
            "Absent Roll Numbers",
            value=current,
            placeholder="Example: 02, 15, 30",
            height=120,
            key="single_absent_input",
        )
        action = "Update Attendance" if existing_attendance else "Save Attendance"
        disabled = bool(existing_holiday)
        if st.button(action, type="primary", disabled=disabled, key="single_save_btn"):
            try:
                present, absent_count = save_attendance(selected, absent, replace=existing_attendance)
                st.success(f"Attendance saved: {present} present, {absent_count} absent.")
            except ValueError as exc:
                st.error(str(exc))
        if existing_attendance:
            st.divider()
            st.subheader("Delete attendance")
            confirm = st.checkbox(f"I am sure I want to delete attendance for {selected.strftime('%d-%m-%Y')}.", key="single_confirm_del")
            if st.button("Delete Attendance", disabled=not confirm, key="single_del_btn"):
                delete_attendance(selected)
                st.success("Attendance deleted.")
                st.rerun()
    else:
        if existing_attendance:
            st.warning("Attendance exists on this date. Saving the holiday will remove it.")
        description = st.text_input("Holiday Description", value=existing_holiday["description"] if existing_holiday else "", key="single_holiday_desc")
        replace = st.checkbox("Replace existing attendance with this holiday", disabled=not existing_attendance, key="single_replace_chk")
        if st.button("Save Holiday", type="primary", key="single_save_holiday_btn"):
            try:
                add_or_update_holiday(selected, description, replace_attendance=replace)
                st.success("Holiday saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

