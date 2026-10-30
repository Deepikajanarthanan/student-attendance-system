from datetime import date

import pandas as pd
import streamlit as st

from attendance import (add_student, delete_student, get_students, import_students,
                        save_register_session, update_student)
from database import init_db

st.set_page_config(page_title="Students | Attendance", page_icon="🎓", layout="wide")
init_db()
st.title("👨‍🎓 Students")
st.caption("Add students one at a time or import a CSV/Excel file with Roll No, Reg No, and Name columns.")

add_tab, import_tab, manage_tab = st.tabs(["Add student", "Bulk import", "View & edit"])
with add_tab:
    with st.form("add_student_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        roll_no = c1.text_input("Roll Number")
        reg_no = c2.text_input("Registration Number")
        name = c3.text_input("Student Name")
        if st.form_submit_button("Add Student", type="primary"):
            try:
                add_student(reg_no, roll_no, name)
                st.success("Student added successfully.")
            except ValueError as exc:
                st.error(str(exc))

with import_tab:
    upload = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])
    if upload:
        try:
            frame = pd.read_csv(upload, dtype=str) if upload.name.lower().endswith(".csv") else pd.read_excel(upload, dtype=str)
            frame.columns = [str(col).strip() for col in frame.columns]

            def _clean(val: object) -> str:
                return "".join(c for c in str(val).upper() if c.isalnum())

            col_map = {}
            for col in frame.columns:
                c = _clean(col)
                if c in {"REGNO", "REGNUMBER", "REGISTRATIONNO", "REGISTRATIONNUMBER"}:
                    col_map[col] = "Reg No"
                elif c in {"ROLLNO", "ROLLNUMBER", "SN", "SNO", "SERIALNO", "SERIALNUMBER"}:
                    col_map[col] = "Roll No"
                elif c in {"NAME", "STUDENTNAME"}:
                    col_map[col] = "Name"
            frame = frame.rename(columns=col_map)
            needed = {"Reg No", "Roll No", "Name"}
            if not needed.issubset(frame.columns):
                st.error("File must contain these required columns: Roll No (or SN), Reg No, Name.")
            else:
                preview = frame[["Roll No", "Reg No", "Name"]].fillna("")
                st.subheader("Student Preview")
                st.caption(f"Found **{len(preview)}** student record(s) in this file.")
                st.dataframe(preview, use_container_width=True, hide_index=True)

                st.divider()
                st.subheader("📅 Configure Attendance Register Session")
                st.caption("Specify your course dates, class days, and periods per day. After importing, you will mark attendance date-by-date by entering absent roll numbers.")

                today_val = date.today()
                c1, c2 = st.columns(2)
                start_d = c1.date_input("Start Date", value=today_val, format="DD-MM-YYYY")
                end_d = c2.date_input("End Date", value=today_val, format="DD-MM-YYYY")

                weekday_map = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
                c3, c4 = st.columns(2)
                chosen_days = c3.multiselect(
                    "Class Days of Week",
                    options=list(weekday_map.keys()),
                    default=[0, 3],
                    format_func=lambda k: weekday_map[k],
                    help="E.g. Monday and Thursday as in your attendance register sheet",
                )
                periods_val = c4.number_input("Periods per Class", min_value=1, max_value=10, value=3)

                if st.button("Import Students & Start Attendance Session 🚀", type="primary"):
                    if end_d < start_d:
                        st.error("End date cannot be earlier than start date.")
                    elif not chosen_days:
                        st.error("Please select at least one class day of the week.")
                    else:
                        added, errors = import_students(preview.to_dict("records"))
                        save_register_session(start_d, end_d, chosen_days, int(periods_val))
                        st.success(f"Successfully imported {added} student(s) and configured session from {start_d.strftime('%d-%m-%Y')} to {end_d.strftime('%d-%m-%Y')} with {periods_val} periods per class!")
                        if errors:
                            st.warning("Some rows were skipped safely:\n\n" + "\n".join(f"- {error}" for error in errors))
                        st.info("👉 Now open the **Daily Attendance** page in the sidebar to mark absent roll numbers date-by-date and export your official register Excel once all dates are marked!")
        except Exception as exc:
            st.error(f"Could not read this file: {exc}")

with manage_tab:
    query = st.text_input("Search by registration number, roll number, or name")
    students = get_students(query=query)
    if students:
        view = pd.DataFrame(students).rename(columns={"reg_no":"Reg No", "roll_no":"Roll No", "name":"Name", "is_active":"Active"})
        view["Active"] = view["Active"].map({1: "Yes", 0: "No"})
        st.dataframe(view[["Roll No", "Reg No", "Name", "Active"]], use_container_width=True, hide_index=True)
        choices = {f"{s['reg_no']} — {s['roll_no']} — {s['name']}": s for s in students}
        chosen = choices[st.selectbox("Choose a student to edit or delete", list(choices))]
        with st.form("edit_student_form"):
            c1, c2, c3 = st.columns(3)
            edit_roll = c1.text_input("Roll Number", chosen["roll_no"])
            edit_reg = c2.text_input("Registration Number", chosen["reg_no"])
            edit_name = c3.text_input("Student Name", chosen["name"])
            active = st.checkbox("Active student", value=bool(chosen["is_active"]))
            if st.form_submit_button("Save changes"):
                try:
                    update_student(chosen["id"], edit_reg, edit_roll, edit_name, active)
                    st.success("Student updated. Refreshing the list…")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        confirm = st.checkbox("I understand that deleting this student also deletes their attendance records.", key="confirm_delete")
        if st.button("Delete selected student", disabled=not confirm):
            delete_student(chosen["id"])
            st.success("Student deleted.")
            st.rerun()
    else:
        st.info("No students found.")
