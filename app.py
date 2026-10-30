"""Student Attendance Management System - Main Application Wizard."""
import importlib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import database
import attendance
import reports

# Ensure running Streamlit processes immediately pick up changes to helper modules
importlib.reload(database)
importlib.reload(attendance)
importlib.reload(reports)

from attendance import (
    add_or_update_holiday,
    attendance_exists,
    create_dataset,
    dataset_exists,
    delete_attendance,
    delete_dataset,
    delete_holiday,
    get_absent_roll_nos,
    get_active_dataset,
    get_course_details,
    get_dataset_info,
    get_holidays,
    get_register_session,
    get_session_class_dates,
    get_session_status,
    get_students,
    holiday_for_date,
    import_students,
    list_datasets,
    roll_sort_key,
    sanitize_dataset_name,
    save_attendance,
    save_course_details,
    save_register_session,
    set_active_dataset,
)
from database import connection, init_db
from reports import calculate_attendance_marks, generate_register_excel

st.set_page_config(page_title="Student Attendance", page_icon="🎓", layout="wide", initial_sidebar_state="collapsed")
init_db()

st.markdown("""
<style>
    /* Completely hide sidebar and page navigation */
    [data-testid="stSidebar"], [data-testid="stSidebarNav"], [data-testid="collapsedControl"] {
        display: none !important;
    }
    .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #dbeeff 0%, #eef7ff 100%);
        border: 1px solid #8fc5eb;
        border-radius: 12px;
        padding: 12px;
        box-shadow: 0 3px 8px rgba(30, 104, 156, 0.10);
    }
    [data-testid="stMetric"] label,
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #102a43 !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎓 Student Attendance Register Wizard")
st.caption("Upload student details, set your date range, mark absentees by Roll No date-by-date, and export the official register with attendance marks (max 5).")

# ----------------------------------------------------
# DATASET / CLASS SELECTOR & MANAGER BAR
# ----------------------------------------------------
all_datasets = list_datasets()
current_active_ds = get_active_dataset()

if "active_dataset" not in st.session_state or st.session_state["active_dataset"] not in all_datasets:
    st.session_state["active_dataset"] = current_active_ds

if get_active_dataset() != st.session_state["active_dataset"]:
    set_active_dataset(st.session_state["active_dataset"])

ds_infos = {name: get_dataset_info(name) for name in all_datasets}

with st.container():
    ds_c1, ds_c2, ds_c3 = st.columns([3, 1, 1])

    with ds_c1:
        def _ds_label(name: str) -> str:
            info = ds_infos.get(name, {})
            sc = info.get("student_count", 0)
            dc = info.get("marked_dates_count", 0)
            c_type = info.get("course_type", "classroom")
            type_tag = "🔬 Lab" if c_type == "lab" else "🏫 Classroom"
            return f"📂 {name}  [{type_tag}]  ({sc} student{'s' if sc != 1 else ''} • {dc} date{'s' if dc != 1 else ''} marked)"

        chosen_idx = all_datasets.index(st.session_state["active_dataset"]) if st.session_state["active_dataset"] in all_datasets else 0
        selected_ds = st.selectbox(
            "Selected Class / Dataset:",
            options=all_datasets,
            index=chosen_idx,
            format_func=_ds_label,
            help="Switch between different student classes or datasets.",
            key="global_selected_dataset_box",
        )
        if selected_ds != st.session_state["active_dataset"]:
            set_active_dataset(selected_ds)
            st.session_state["active_dataset"] = selected_ds
            st.rerun()

    with ds_c2:
        st.write("")
        st.write("")
        with st.popover("➕ New Dataset", use_container_width=True):
            st.markdown("#### ➕ Create New Dataset")
            st.caption("Create a separate dataset for another class, semester, or lab batch.")
            new_ds_name = st.text_input("Dataset / Class Name", placeholder="e.g. Class 2, Section B, Lab Batch 1", key="new_ds_input")
            new_ds_type = st.radio(
                "Course Type:",
                options=["classroom", "lab"],
                format_func=lambda x: "🏫 Classroom / Theory (1 hr/day)" if x == "classroom" else "🔬 Laboratory / Practical (3 hrs/day)",
                key="new_ds_type_radio",
            )
            if st.button("Create & Switch", type="primary", use_container_width=True, key="btn_create_new_ds"):
                clean_name = sanitize_dataset_name(new_ds_name.strip())
                if not new_ds_name.strip() or not clean_name:
                    st.error("Please provide a valid dataset name.")
                elif dataset_exists(clean_name):
                    st.error(f"⚠️ A dataset named '{clean_name}' already exists! Please choose a different name or switch to it from the dropdown.")
                else:
                    try:
                        created = create_dataset(clean_name)
                        save_course_details(
                            class_handled=created,
                            faculty_name="",
                            subject="",
                            total_hours=30 if new_ds_type == "lab" else 40,
                            course_type=new_ds_type,
                            dataset_name=created,
                        )
                        st.session_state["active_dataset"] = created
                        set_active_dataset(created)
                        st.success(f"Created and switched to '{created}' [{new_ds_type.title()}]!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error creating dataset: {exc}")

    with ds_c3:
        st.write("")
        st.write("")
        with st.popover("🗑️ Delete Dataset", use_container_width=True):
            st.markdown("#### 🗑️ Delete Dataset")
            
            target_del_idx = all_datasets.index(selected_ds) if selected_ds in all_datasets else 0
            ds_to_delete = st.selectbox(
                "Choose dataset to delete:",
                options=all_datasets,
                index=target_del_idx,
                key="ds_target_to_delete_box",
            )

            is_only_one = (len(all_datasets) == 1)
            if is_only_one:
                st.warning(f"⚠️ **'{ds_to_delete}' is your only dataset.**")
                st.caption("Deleting it will permanently clear all student details, schedule, and attendance records, resetting it to a clean empty dataset.")
                btn_delete_label = f"Yes, Delete & Reset '{ds_to_delete}'"
            else:
                st.warning(f"Are you sure you want to permanently delete **'{ds_to_delete}'**?")
                st.caption("⚠️ All student details, schedule, and attendance records for this class will be permanently removed.")
                btn_delete_label = f"Yes, Delete '{ds_to_delete}'"

            if st.button(btn_delete_label, type="primary", use_container_width=True, key="btn_confirm_delete_active_ds"):
                ok = delete_dataset(ds_to_delete)
                if ok:
                    remaining = list_datasets()
                    new_active = remaining[0] if (selected_ds == ds_to_delete or selected_ds not in remaining) else selected_ds
                    st.session_state["active_dataset"] = new_active
                    set_active_dataset(new_active)
                    if is_only_one:
                        st.success(f"Dataset '{ds_to_delete}' was deleted and reset to an empty dataset.")
                    else:
                        st.success(f"Deleted dataset '{ds_to_delete}'. Active dataset is now '{new_active}'.")
                    st.rerun()
                else:
                    st.error(f"Could not delete dataset '{ds_to_delete}'. The database file may be locked by another process. Please try again.")


students = get_students(active_only=True)
session = get_register_session()
course_details = get_course_details()

# ----------------------------------------------------
# STEP 1: Upload Student Details & Course Information
# ----------------------------------------------------
step1_expanded = (len(students) == 0)
with st.expander(f"📁 **Step 1: Upload Student Information & Course Details for '{selected_ds}'** {'✅ (' + str(len(students)) + ' students loaded)' if students else '⏳ (Action required)'}", expanded=step1_expanded):
    st.caption(f"Enter the class, faculty, subject, and total hours, and upload the student list for **{selected_ds}**.")

    st.markdown("##### 📌 Class & Faculty Information")
    curr_course_type = course_details.get("course_type", "classroom")
    inp_course_type = st.radio(
        "Course / Attendance Mode:",
        options=["classroom", "lab"],
        index=0 if curr_course_type == "classroom" else 1,
        format_func=lambda x: "🏫 Classroom / Theory (1 hr per class, 1 mark reduced per 3 absences)" if x == "classroom" else "🔬 Laboratory / Practical (3 hrs per day, 1 mark reduced per 1 absent day)",
        horizontal=True,
        key="meta_inp_course_type",
        help="Classroom calculates 1 hour per day and reduces 1 mark for every 3 classes absent. Laboratory calculates 3 hours per day and reduces 1 mark for every 1 day absent.",
    )

    m_c1, m_c2 = st.columns(2)
    with m_c1:
        inp_class = st.text_input("Class Handled", value=course_details.get("class_handled") or selected_ds, placeholder="e.g. III CSE - A", key="meta_inp_class")
        inp_subject = st.text_input("Subject", value=course_details.get("subject", ""), placeholder="e.g. Database Management Systems", key="meta_inp_subject")
    with m_c2:
        inp_faculty = st.text_input("Faculty Name", value=course_details.get("faculty_name", ""), placeholder="e.g. Dr. K. Sharma", key="meta_inp_faculty")
        default_hrs = int(course_details.get("total_hours", 30 if inp_course_type == "lab" else 40))
        inp_hours = st.number_input("Total Hours", min_value=1, max_value=200, value=default_hrs, step=1, key="meta_inp_hours")

    if students:
        if st.button("💾 Save / Update Course Details", key="btn_update_meta_only"):
            save_course_details(inp_class, inp_faculty, inp_subject, inp_hours, course_type=inp_course_type)
            st.success("Course and faculty details updated successfully!")
            st.rerun()

    st.markdown("---")
    st.markdown("##### 📄 Upload Student Details (CSV or Excel)")
    st.caption(f"Upload a CSV or Excel file containing columns: **Roll No** (or **SN**), **Reg No**, and **Name** for **{selected_ds}**.")
    uploaded_file = st.file_uploader(f"Upload Student Details for '{selected_ds}' (CSV or Excel)", type=["csv", "xlsx"], key="main_student_upload")
    
    if uploaded_file:
        try:
            frame = pd.read_csv(uploaded_file, dtype=str) if uploaded_file.name.lower().endswith(".csv") else pd.read_excel(uploaded_file, dtype=str)
            frame.columns = [str(c).strip() for c in frame.columns]

            def _norm(v: object) -> str:
                return "".join(c for c in str(v).upper() if c.isalnum())

            col_map = {}
            for col in frame.columns:
                c = _norm(col)
                if c in {"REGNO", "REGNUMBER", "REGISTRATIONNO", "REGISTRATIONNUMBER"}:
                    col_map[col] = "Reg No"
                elif c in {"ROLLNO", "ROLLNUMBER", "SN", "SNO", "SERIALNO", "SERIALNUMBER"}:
                    col_map[col] = "Roll No"
                elif c in {"NAME", "STUDENTNAME"}:
                    col_map[col] = "Name"
            frame = frame.rename(columns=col_map)
            
            needed = {"Reg No", "Roll No", "Name"}
            if not needed.issubset(frame.columns):
                st.error("Uploaded file must have columns for Roll No (or SN), Reg No, and Name.")
            else:
                preview = frame[["Roll No", "Reg No", "Name"]].fillna("")
                preview = preview.sort_values(by="Roll No", key=lambda col: [roll_sort_key(x) for x in col])
                st.write(f"**Found {len(preview)} student records in uploaded file (arranged roll-wise 1, 2, 3...):**")
                st.dataframe(preview, use_container_width=True, hide_index=True)

                st.markdown("##### ⚙️ Choose Attendance Mode for Uploaded Dataset:")
                upload_mode_choice = st.radio(
                    "Is this dataset for Classroom or Lab?",
                    options=["classroom", "lab"],
                    index=0 if inp_course_type == "classroom" else 1,
                    format_func=lambda x: "🏫 Classroom / Theory (1 hr per class, 1 mark reduced per 3 absences)" if x == "classroom" else "🔬 Laboratory / Practical (3 hrs per day, 1 mark reduced per 1 absent day)",
                    horizontal=True,
                    key="upload_mode_choice_radio",
                )

                btn_c1, btn_c2 = st.columns([1, 1])
                with btn_c1:
                    if st.button(f"📥 Save & Import to '{selected_ds}'", type="primary", use_container_width=True, key="btn_save_students"):
                        save_course_details(inp_class, inp_faculty, inp_subject, inp_hours, course_type=upload_mode_choice)
                        added, errors = import_students(preview.to_dict("records"))
                        st.success(f"Successfully loaded {added} student(s) and saved course details for '{selected_ds}' ({upload_mode_choice.title()})!")
                        if errors:
                            st.warning("Some rows were skipped:\n" + "\n".join(f"- {e}" for e in errors[:5]))
                        st.rerun()

                with btn_c2:
                    file_default_name = Path(uploaded_file.name).stem.replace("_", " ").title()
                    with st.popover("➕ Or Create as New Dataset & Import", use_container_width=True):
                        new_ds_from_file = st.text_input("New Dataset Name", value=file_default_name, key="input_ds_from_file")
                        popover_ds_type = st.radio(
                            "New Dataset Course Type:",
                            options=["classroom", "lab"],
                            index=0 if upload_mode_choice == "classroom" else 1,
                            format_func=lambda x: "🏫 Classroom / Theory (1 hr/day)" if x == "classroom" else "🔬 Laboratory / Practical (3 hrs/day)",
                            key="popover_ds_type_choice",
                        )
                        if st.button("Create & Import to New Dataset", type="primary", use_container_width=True, key="btn_create_and_import"):
                            new_name_clean = sanitize_dataset_name(new_ds_from_file.strip() or file_default_name)
                            if dataset_exists(new_name_clean):
                                 st.error(f"⚠️ A dataset named '{new_name_clean}' already exists! Please choose a different name.")
                            else:
                                try:
                                    created_name = create_dataset(new_name_clean)
                                    st.session_state["active_dataset"] = created_name
                                    set_active_dataset(created_name)
                                    save_course_details(inp_class or created_name, inp_faculty, inp_subject, inp_hours, course_type=popover_ds_type, dataset_name=created_name)
                                    added, errors = import_students(preview.to_dict("records"))
                                    st.success(f"Created '{created_name}' [{popover_ds_type.title()}], imported {added} student(s), and saved details!")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Error creating dataset: {exc}")
        except Exception as exc:
            st.error(f"Error reading file: {exc}")

    if students:
        c_badge = "🔬 Laboratory (3 hrs/day, 1 mark reduced per absent day)" if curr_course_type == "lab" else "🏫 Classroom / Theory (1 hr/day, 1 mark reduced per 3 absences)"
        st.info(
            f"Currently active students in '{selected_ds}': **{len(students)}** · "
            f"Mode: **{c_badge}** · "
            f"Class: **{inp_class}** · "
            f"Faculty: **{inp_faculty or '—'}** · "
            f"Subject: **{inp_subject or '—'}** · "
            f"Total Hours: **{inp_hours} hrs**."
        )

if not students:
    st.warning(f"👉 Please upload your student list for **'{selected_ds}'** in **Step 1** above to proceed.")
    st.stop()

# ----------------------------------------------------
# STEP 2: Configure Start Date & End Date
# ----------------------------------------------------
step2_expanded = (session is None)
with st.expander(f"📅 **Step 2: Course Dates & Class Schedule** {'✅ (Configured)' if session else '⏳ (Action required)'}", expanded=step2_expanded):
    today_val = date.today()
    c1, c2 = st.columns(2)
    curr_start = session["start_date"] if session else today_val
    curr_end = session["end_date"] if session else (today_val + timedelta(weeks=12))
    new_start = c1.date_input("Start Date", value=curr_start, format="DD-MM-YYYY", key=f"wizard_start_{selected_ds}")
    new_end = c2.date_input("End Date", value=curr_end, format="DD-MM-YYYY", key=f"wizard_end_{selected_ds}")

    is_lab = (course_details.get("course_type") == "lab")
    weekday_map = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
    curr_weekdays = session["weekdays"] if session else ([2] if is_lab else [0, 3])
    new_weekdays = st.multiselect(
        "Lab Days of Week" if is_lab else "Class Days of Week",
        options=list(weekday_map.keys()),
        default=curr_weekdays,
        format_func=lambda k: weekday_map[k],
        help="Select which day(s) the lab occurs (e.g. Wednesday for 3 hours per week)" if is_lab else "Select which days classes occur (e.g. Monday and Thursday as in your attendance register)",
        key=f"wizard_weekdays_{selected_ds}",
    )

    curr_wp = session.get("weekday_periods", {}) if session else {}
    new_wp: dict[int, str | int] = {}
    if is_lab:
        st.markdown("**Select Lab Timing / Period Block for each lab day (3 hours):**")
        lab_period_options = {
            "1-3": "Periods 1 to 3 (Morning, 3 hrs)",
            "4-6": "Periods 4 to 6 (Afternoon, 3 hrs)",
            "5-7": "Periods 5 to 7 (3 hrs)",
            "6-8": "Periods 6 to 8 (3 hrs)",
            "3": "3 Hours Block",
        }
        if new_weekdays:
            cols = st.columns(min(len(new_weekdays), 4))
            for i, w_day in enumerate(sorted(new_weekdays)):
                col = cols[i % len(cols)]
                def_opt = str(curr_wp.get(w_day, "1-3"))
                chosen_opt = col.selectbox(
                    f"{weekday_map[w_day]} Lab Timing",
                    options=list(lab_period_options.keys()),
                    format_func=lambda h: lab_period_options[h],
                    index=list(lab_period_options.keys()).index(def_opt) if def_opt in lab_period_options else 0,
                    key=f"wp_day_{selected_ds}_{w_day}",
                )
                new_wp[w_day] = chosen_opt
        periods_per_day = 3
        target_hours_val = course_details.get("total_hours", 30)
        st.caption(f"ℹ️ **Lab Attendance Rule**: Each lab date counts as **3 hours** of attendance. You mark attendance **once per day**, and it calculates for 3 hours. Target Course Hours: **{target_hours_val} hours**.")
    else:
        st.markdown("**Select the Period/Hour of the Day for each class day (e.g. 1st or 4th hour):**")
        if new_weekdays:
            cols = st.columns(min(len(new_weekdays), 4))
            hour_options = {1: "1st Hour (Period 1)", 2: "2nd Hour (Period 2)", 3: "3rd Hour (Period 3)",
                            4: "4th Hour (Period 4)", 5: "5th Hour (Period 5)", 6: "6th Hour (Period 6)",
                            7: "7th Hour (Period 7)", 8: "8th Hour (Period 8)"}
            for i, w_day in enumerate(sorted(new_weekdays)):
                col = cols[i % len(cols)]
                raw_hr = curr_wp.get(w_day, 1 if w_day == 0 else 4 if w_day == 3 else 1)
                def_hr = int(raw_hr) if str(raw_hr).isdigit() else (1 if w_day == 0 else 4 if w_day == 3 else 1)
                chosen_hr = col.selectbox(
                    f"{weekday_map[w_day]} Hour",
                    options=list(hour_options.keys()),
                    format_func=lambda h: hour_options[h],
                    index=list(hour_options.keys()).index(def_hr) if def_hr in hour_options else 0,
                    key=f"wp_day_{selected_ds}_{w_day}",
                )
                new_wp[w_day] = chosen_hr
        periods_per_day = 1
        target_hours_val = course_details.get("total_hours", 40)
        st.caption(f"ℹ️ **Classroom Attendance Rule**: Each class date counts as exactly **1 hour** of attendance. Target Course Hours: **{target_hours_val} hours**.")

    preview_dates = []
    if new_weekdays and new_end >= new_start:
        preview_dates = get_session_class_dates(new_start, new_end, new_weekdays, exclude_holidays=False)

    if preview_dates:
        hrs_text = f" ({len(preview_dates) * 3} hours total @ 3 hrs/day)" if is_lab else f" ({len(preview_dates)} hours total)"
        st.info(f"📅 **Schedule Preview**: Found **{len(preview_dates)} {'lab' if is_lab else 'class'} date(s)** between {new_start.strftime('%d-%m-%Y')} and {new_end.strftime('%d-%m-%Y')}{hrs_text}.")
    else:
        st.warning(f"⚠️ **0 matching dates found** between {new_start.strftime('%d-%m-%Y')} and {new_end.strftime('%d-%m-%Y')} for the selected day(s). Please extend the End Date to include your {'lab' if is_lab else 'class'} days.")

    btn_label = "Save Schedule & Proceed to Attendance Marking ➔" if session is None else "Update Course Schedule & Proceed ➔"
    if st.button(btn_label, type="primary", key=f"btn_save_schedule_{selected_ds}"):
        if new_end < new_start:
            st.error("End date cannot be earlier than start date.")
        elif not new_weekdays:
            st.error("Please select at least one class day of the week.")
        elif not preview_dates:
            day_names = ", ".join(weekday_map[w] for w in new_weekdays)
            st.error(f"⚠️ No matching dates found! The date range from {new_start.strftime('%d-%m-%Y')} to {new_end.strftime('%d-%m-%Y')} does not contain any {day_names}. Please extend the End Date.")
        else:
            save_register_session(new_start, new_end, new_weekdays, periods_per_day=periods_per_day, weekday_periods=new_wp)
            session = get_register_session()
            st.success("Course schedule saved successfully! Proceeding to Attendance Marking...")
            st.rerun()

if not session:
    st.info("👉 Please configure your Start Date and End Date in **Step 2** above to begin marking attendance.")
    st.stop()

is_lab = (course_details.get("course_type") == "lab")
class_dates = get_session_class_dates(session["start_date"], session["end_date"], session["weekdays"], exclude_holidays=False)
if not class_dates:
    c_warn1, c_warn2 = st.columns([3, 2])
    sel_day_names = ", ".join(weekday_map.get(w, str(w)) for w in session.get("weekdays", []))
    c_warn1.warning(f"⚠️ No dates found between **{session['start_date'].strftime('%d-%m-%Y')}** and **{session['end_date'].strftime('%d-%m-%Y')}** matching **{sel_day_names}**. Please expand your End Date.")
    if c_warn2.button("➕ Auto-Extend to 12 Weeks & Proceed", type="primary", key="btn_auto_extend_dates", use_container_width=True):
        extended_end = session["start_date"] + timedelta(weeks=12)
        save_register_session(session["start_date"], extended_end, session["weekdays"], periods_per_day=session["periods_per_day"], weekday_periods=session["weekday_periods"])
        st.success("Extended schedule! Loading dates...")
        st.rerun()
    st.stop()

status = get_session_status(class_dates)
total_dates = len(class_dates)
marked_count = len(status["marked_dates"])
remaining_count = len(status["unmarked_dates"])
pct_complete = (marked_count / total_dates) if total_dates else 0.0

# ----------------------------------------------------
# STEP 3: Mark Attendance by Roll Number
# ----------------------------------------------------
st.markdown("---")
st.subheader(f"📝 **Step 3: Mark Attendance by Roll Number ({'Laboratory' if is_lab else 'Classroom'})** ({marked_count} / {total_dates} dates marked)")

p1, p2, p3, p4 = st.columns(4)
p1.metric("Date Range", f"{session['start_date'].strftime('%d-%b')} to {session['end_date'].strftime('%d-%b')}")
p2.metric("Total Class Dates", f"{total_dates} dates")
p3.metric("Completed Dates", f"{marked_count} / {total_dates}")
p4.metric("Pending Dates", f"{remaining_count} remaining")

st.progress(pct_complete, text=f"Progress: {marked_count} of {total_dates} dates marked ({pct_complete*100:.1f}%)")

# Build data list for all scheduled dates
table_rows = []
for idx, d in enumerate(class_dates, start=1):
    d_iso = d.isoformat()
    is_hol = bool(holiday_for_date(d_iso))
    is_saved = attendance_exists(d_iso)
    curr_abs = get_absent_roll_nos(d_iso)
    if is_lab:
        curr_p = session.get("weekday_periods", {}).get(d.weekday(), "1-3")
        date_label = f"#{idx}: {d.strftime('%d-%m-%Y (%A)')} — Lab (3 Hrs, Periods {curr_p})"
    else:
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

if is_lab:
    st.caption("ℹ️ **Lab Instructions**: Mark attendance **once per day** (each day calculates as **3 hours**). Enter absent roll numbers (e.g. `1, 4` or `01, 04`). Type `'holiday'` if it was a holiday. Type `'P'` if all students were present.")
else:
    st.caption("ℹ️ **Classroom Instructions**: Enter absent roll numbers (e.g. `1, 4` or `01, 04`) for each date. Type `'holiday'` if it was a holiday. Type `'P'` if all students were present.")

# ----------------------------------------------------
# Quick Edit for a Single Date (Fastest & Most Reliable)
# ----------------------------------------------------
with st.expander("🎯 **Quick Edit Attendance for a Specific Date**", expanded=False):
    st.caption("Select any date below to instantly view or edit its absentees without scrolling through the full schedule.")
    q_col1, q_col2 = st.columns([2, 3])

    date_options = [r["date_iso"] for r in table_rows]
    def _format_q_date(iso_str: str) -> str:
        for r in table_rows:
            if r["date_iso"] == iso_str:
                return f"{r['date_label']}  [{r['status']}]"
        return iso_str

    selected_q_date = q_col1.selectbox(
        "Select Date to Edit:",
        options=date_options,
        format_func=_format_q_date,
        key="quick_edit_date_select",
    )

    current_q_row = next((r for r in table_rows if r["date_iso"] == selected_q_date), table_rows[0])
    q_col2.markdown(f"**Current Status:** {current_q_row['status']}")

    q_input_val = q_col2.text_input(
        "Absent Roll Number(s) (e.g. 10, 15) or 'P' / 'holiday':",
        value=current_q_row["init_val"],
        key=f"q_input_{selected_q_date}",
        help="Type roll numbers of absent students separated by commas (e.g. 2, 5 or 02, 05). Type 'P' for all present, or 'holiday'.",
    )

    qb_col1, qb_col2, qb_col3, qb_col4 = q_col2.columns([2, 2, 2, 2])
    btn_q_save = qb_col1.button("💾 Update Attendance", type="primary", use_container_width=True, key="btn_q_save")
    btn_q_present = qb_col2.button("✅ Mark All Present", use_container_width=True, key="btn_q_present")
    btn_q_holiday = qb_col3.button("🏖️ Mark as Holiday", use_container_width=True, key="btn_q_holiday")
    btn_q_remove_holiday = qb_col4.button("🔄 Remove Holiday", use_container_width=True, key="btn_q_remove_holiday", disabled=not current_q_row["is_hol"], help="Clear holiday status and reopen this date for attendance.")

    if btn_q_save or btn_q_present or btn_q_holiday or btn_q_remove_holiday:
        target_d = current_q_row["date"]
        target_iso = current_q_row["date_iso"]

        if btn_q_remove_holiday:
            delete_holiday(target_iso)
            delete_attendance(target_iso)
            st.success(f"✅ Holiday removed for {target_d.strftime('%d-%m-%Y')}! Date is now reopened for attendance.")
        elif btn_q_holiday:
            add_or_update_holiday(target_iso, "Holiday", replace_attendance=True)
            st.success(f"✅ {target_d.strftime('%d-%m-%Y')} marked as Holiday!")
        elif btn_q_present:
            delete_holiday(target_iso)
            save_attendance(target_d, "", replace=True)
            st.success(f"✅ {target_d.strftime('%d-%m-%Y')} marked as All Present!")
        else:
            raw_q = q_input_val.strip()
            c_raw = raw_q.casefold()
            if c_raw in {"holiday", "h", "leave"}:
                add_or_update_holiday(target_iso, "Holiday", replace_attendance=True)
                st.success(f"✅ {target_d.strftime('%d-%m-%Y')} marked as Holiday!")
            elif c_raw in {"clear", "remove", "delete", "unmark", "reopen"}:
                delete_holiday(target_iso)
                delete_attendance(target_iso)
                st.success(f"✅ Cleared attendance and holiday for {target_d.strftime('%d-%m-%Y')}!")
            elif c_raw in {"p", "present", "all", "none", "nil", "0", ""}:
                delete_holiday(target_iso)
                save_attendance(target_d, "", replace=True)
                st.success(f"✅ {target_d.strftime('%d-%m-%Y')} marked as All Present!")
            elif c_raw in {"a", "absent"}:
                st.error("⚠️ You entered 'A'. Please specify the absent student's Roll Number(s), e.g. `2, 5` or `02, 05`.")
                st.stop()
            else:
                try:
                    delete_holiday(target_iso)
                    p_cnt, a_cnt = save_attendance(target_d, raw_q, replace=True)
                    st.success(f"✅ {target_d.strftime('%d-%m-%Y')} updated: {a_cnt} absent (Roll No: {raw_q}), {p_cnt} present!")
                except ValueError as exc:
                    st.error(f"Error: {exc}")
                    st.stop()

        # Clear cached grid state so table refreshes cleanly
        if "wizard_grid_editor" in st.session_state:
            del st.session_state["wizard_grid_editor"]
        st.rerun()

# ----------------------------------------------------
# Manage Holidays Expander (View & Remove Any Holiday)
# ----------------------------------------------------
holidays_in_session = get_holidays(session["start_date"].isoformat(), session["end_date"].isoformat())
with st.expander(f"🏖️ **Manage Holidays ({len(holidays_in_session)} marked)**", expanded=False):
    st.caption("View or remove any holiday within your course schedule date range.")
    if holidays_in_session:
        st.markdown("**Marked Holidays:**")
        for h in holidays_in_session:
            h_d = date.fromisoformat(h["holiday_date"])
            hc1, hc2 = st.columns([3, 1])
            hc1.write(f"🏖️ **{h_d.strftime('%d-%m-%Y (%A)')}**: {h.get('description') or 'Holiday'}")
            if hc2.button("🗑️ Remove Holiday", key=f"btn_del_hol_{h['holiday_date']}", use_container_width=True):
                delete_holiday(h["holiday_date"])
                delete_attendance(h["holiday_date"])
                if "wizard_grid_editor" in st.session_state:
                    del st.session_state["wizard_grid_editor"]
                st.success(f"✅ Holiday removed for {h_d.strftime('%d-%m-%Y')}!")
                st.rerun()
    else:
        st.info("No holidays currently marked in this date range.")

# ----------------------------------------------------
# Bulk Schedule Editor (All Dates)
# ----------------------------------------------------
st.markdown("##### 📅 Full Schedule Attendance Sheet")

# Action buttons at top
b_col1, b_col2 = st.columns([1, 1])
save_all_top = b_col1.button("💾 Save All Attendance", type="primary", use_container_width=True, key="btn_save_all_top")
mark_unmarked_p = b_col2.button("✅ Mark All Remaining as All Present", use_container_width=True, key="btn_mark_all_p_top")

view_mode = st.radio(
    "Editor Style:",
    options=["📊 Spreadsheet Table View", "📝 List Form View"],
    horizontal=True,
    key="att_editor_style_choice",
)

if view_mode == "📊 Spreadsheet Table View":
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
                help="Enter roll numbers separated by comma (e.g. 02, 15), or type 'holiday', or 'P'. Press Enter after typing.",
                width="large",
            ),
            "Status": st.column_config.TextColumn("Status", disabled=True, width="small"),
        },
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key="wizard_grid_editor",
    )
else:
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
            f"absent_{r['date_iso']}",
            value=r["init_val"],
            placeholder="e.g. 1, 4 or 'holiday' or 'P'",
            label_visibility="collapsed",
            key=f"form_roll_{r['date_iso']}",
        )
        fc3.caption(r["status"])
        form_inputs[r["date"]] = val

save_all_bottom = st.button("💾 Save All Attendance", type="primary", use_container_width=True, key="btn_save_all_bottom")

# Processing save action
if save_all_top or save_all_bottom or mark_unmarked_p:
    errors = []
    saved_count = 0
    for i, r in enumerate(table_rows):
        d = r["date"]
        if view_mode == "📊 Spreadsheet Table View" and "edited_grid" in locals() and i < len(edited_grid):
            raw_input = str(edited_grid.iloc[i]["Absent Roll Numbers (or 'holiday' / 'P')"]).strip()
        elif view_mode == "📝 List Form View" and "form_inputs" in locals() and d in form_inputs:
            raw_input = str(form_inputs[d]).strip()
        else:
            raw_input = r["init_val"].strip()

        if mark_unmarked_p and not r["is_saved"] and not r["is_hol"] and not raw_input:
            raw_input = "P"

        c_text = raw_input.casefold() if raw_input else ""

        if r["is_hol"] and (not raw_input or c_text in {"clear", "remove", "delete", "unmark", "reopen"}):
            delete_holiday(r["date_iso"])
            delete_attendance(r["date_iso"])
            saved_count += 1
            continue

        if not raw_input:
            continue

        if c_text in {"a", "absent"}:
            errors.append(f"{d.strftime('%d-%m-%Y')}: You entered 'A'. Please specify the absent student's Roll Number (e.g. 2, 5 or 02, 05).")
            continue

        try:
            if c_text in {"holiday", "h", "leave"}:
                add_or_update_holiday(r["date_iso"], "Holiday", replace_attendance=True)
                saved_count += 1
            elif c_text in {"p", "present", "all", "none", "nil", "0"}:
                delete_holiday(r["date_iso"])
                save_attendance(d, "", replace=True)
                saved_count += 1
            else:
                delete_holiday(r["date_iso"])
                save_attendance(d, raw_input, replace=True)
                saved_count += 1
        except ValueError as exc:
            errors.append(f"{d.strftime('%d-%m-%Y')}: {exc}")

    if errors:
        st.error("Some dates had errors:\n" + "\n".join(f"- {e}" for e in errors))
    else:
        # Clear editor session state caches so fresh data from database is loaded
        if "wizard_grid_editor" in st.session_state:
            del st.session_state["wizard_grid_editor"]
        for r in table_rows:
            f_k = f"form_roll_{r['date_iso']}"
            if f_k in st.session_state:
                del st.session_state[f_k]

        st.success(f"✅ Attendance saved successfully for {saved_count} date(s)!")
        st.rerun()

# ----------------------------------------------------
# STEP 4: Export Sheet with Marks (Unlocked once complete)
# ----------------------------------------------------
st.markdown("---")
st.subheader("📥 **Step 4: Export Official Attendance Register**")

working_dates = [d for d in class_dates if not holiday_for_date(d.isoformat())]
is_lab = (course_details.get("course_type") == "lab")
effective_ppd = 3 if is_lab else 1
total_periods = len(working_dates) * effective_ppd
holidays_count = len(class_dates) - len(working_dates)

if not status["is_complete"]:
    st.warning(
        f"🔒 **Excel Export is Locked**: Attendance has not yet been marked through the last date (**{class_dates[-1].strftime('%d-%m-%Y')}**).\n\n"
        f"**{remaining_count} date(s) remaining:** "
        + ", ".join(d.strftime("%d-%m-%Y") for d in status["unmarked_dates"][:8])
        + ("..." if remaining_count > 8 else "")
    )
    st.button("📥 Download Official Register (.xlsx)", disabled=True, key="btn_export_disabled", help="Mark all dates through the last date to enable export.")
else:
    if is_lab:
        st.success(f"🎉 **All {total_dates} lab dates through the end date ({class_dates[-1].strftime('%d-%m-%Y')}): {len(working_dates)} Working Lab Days ({total_periods} Hours @ 3 hrs/day) + {holidays_count} Holidays.**")
    else:
        st.success(f"🎉 **All {total_dates} class dates through the end date ({class_dates[-1].strftime('%d-%m-%Y')}): {len(working_dates)} Working Days ({total_periods} Hours) + {holidays_count} Holidays.**")
    st.info("💡 **Need to update attendance?** You can edit any date above in **Step 3** anytime (using the *🎯 Quick Edit* tool or the table). Your marks and the downloadable Excel register will update automatically!")
    st.caption("📄 **Note**: Marked holidays are completely excluded from the exported Excel register columns (no 'H' columns; only actual working days are included in the sheet).")

    reg_excel_bytes = generate_register_excel(
        session["start_date"],
        session["end_date"],
        class_dates=class_dates,
        periods_per_day=effective_ppd,
        class_handled=course_details.get("class_handled") or selected_ds,
        faculty_name=course_details.get("faculty_name", ""),
        subject=course_details.get("subject", ""),
        total_hours=course_details.get("total_hours", 30 if is_lab else 40),
        course_type="lab" if is_lab else "classroom",
        include_holidays=False,
    )
    clean_ds = sanitize_dataset_name(selected_ds).replace(" ", "_")
    mode_tag = "lab" if is_lab else "classroom"
    fname = f"attendance_register_{clean_ds}_{mode_tag}_{session['start_date'].strftime('%Y%m%d')}_{session['end_date'].strftime('%Y%m%d')}.xlsx"

    st.download_button(
        label=f"📥 Download Official Attendance Register for {selected_ds} ({'Laboratory' if is_lab else 'Classroom'}) (.xlsx)",
        data=reg_excel_bytes,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
        key="btn_export_active",
    )

    with st.expander(f"👁️ View Calculated Marks & Register Summary ({selected_ds})", expanded=True):
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.markdown(f"**Class:** `{course_details.get('class_handled') or selected_ds}`")
        mc2.markdown(f"**Faculty:** `{course_details.get('faculty_name') or '—'}`")
        mc3.markdown(f"**Subject:** `{course_details.get('subject') or '—'}`")
        default_tot = 30 if is_lab else 40
        mc4.markdown(f"**Total Hours:** `{course_details.get('total_hours', default_tot)} hrs`")

        if is_lab:
            st.caption(
                f"**Register Summary for {selected_ds} [LAB]** · **Total Working Hours: {total_periods} hrs ({len(working_dates)} days × 3 hrs)** · **Holidays: {holidays_count}**\n\n"
                f"📌 **Lab Scoring Rule**: Out of 5 marks: **1 mark is reduced for every 1 lab day absent**.\n"
                f"*(0 absent: 5 marks | 1 absent: 4 marks | 2 absent: 3 marks | 3 absent: 2 marks | 4 absent: 1 mark | ≥5 absent: 0 marks)*"
            )
        else:
            st.caption(
                f"**Register Summary for {selected_ds} [CLASSROOM]** · **Total Working Hours: {total_periods} hrs ({len(working_dates)} days × 1 hr)** · **Holidays: {holidays_count}**\n\n"
                f"📌 **Classroom Scoring Rule**: Out of 5 marks: **1 mark is reduced for every 3 classes absent**.\n"
                f"*(0-2 absent: 5 marks | 3-5 absent: 4 marks | 6-8 absent: 3 marks | 9-11 absent: 2 marks | 12-14 absent: 1 mark | ≥15 absent: 0 marks)*"
            )

        table_rows = []
        for s in students:
            with connection() as conn:
                if working_dates:
                    p_dates = ",".join("?" for _ in working_dates)
                    cnt = conn.execute(
                        f"SELECT COUNT(*) FROM daily_attendance WHERE student_id=? AND status='P' AND attendance_date IN ({p_dates})",
                        (s["id"], *[d.isoformat() for d in working_dates]),
                    ).fetchone()[0]
                else:
                    cnt = 0
            hrs = cnt * effective_ppd
            pct = (hrs / total_periods * 100.0) if total_periods else 0.0
            absent_days = len(working_dates) - cnt
            if is_lab:
                score = calculate_attendance_marks(absent_days, total_periods=len(working_dates), course_type="lab")
            else:
                absent_hours = absent_days * effective_ppd
                score = calculate_attendance_marks(absent_hours, total_periods=total_periods, course_type="classroom")
            pct_rounded = int(round(pct))
            table_rows.append({
                "Roll No": s["roll_no"],
                "Reg No": s["reg_no"],
                "Name": s["name"],
                "Total Hours": f"{hrs} / {total_periods}",
                "% Attendance": f"{pct_rounded}%",
                "Marks (Max 5)": score,
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
