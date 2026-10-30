from datetime import date
from io import BytesIO

import pandas as pd
import streamlit as st

from attendance import get_students, import_attendance_by_roll
from bulk_import import parse_attendance_workbook
from database import init_db

st.set_page_config(page_title="Bulk Attendance Import | Attendance", page_icon="📤", layout="wide")
init_db()
st.title("📤 Bulk Attendance Excel Import")
st.caption("Upload a completed P/A attendance sheet. The app matches students using Roll No and imports only the dates you select.")

if not get_students(active_only=True):
    st.warning("Add your students first on the Students page. Their Roll No values are needed to validate this attendance sheet.")
    st.stop()

st.info("Supported sheets: a simple header row with Roll No and date columns, or a register layout like your example with SN/Roll No, a DATE row, JAN/FEB month labels, and P/A cells.")
upload = st.file_uploader("Upload completed attendance Excel file", type=["xlsx"])
if not upload:
    st.stop()

try:
    workbook = pd.ExcelFile(BytesIO(upload.getvalue()))
except Exception as exc:
    st.error(f"This file could not be opened as Excel: {exc}")
    st.stop()

sheet = st.selectbox("Worksheet", workbook.sheet_names)
today = date.today()
c1, c2 = st.columns(2)
start_date = c1.date_input("Start date to import", value=date(today.year, today.month, 1), max_value=today, format="DD-MM-YYYY")
end_date = c2.date_input("End date to import", value=today, max_value=today, format="DD-MM-YYYY")
signature = (upload.name, upload.size, sheet, start_date.isoformat(), end_date.isoformat())

if st.button("Preview selected attendance", type="primary"):
    try:
        parsed = parse_attendance_workbook(upload.getvalue(), sheet, start_date, end_date)
        st.session_state["bulk_import_result"] = parsed
        st.session_state["bulk_import_signature"] = signature
    except ValueError as exc:
        st.session_state.pop("bulk_import_result", None)
        st.error(str(exc))

if st.session_state.get("bulk_import_signature") != signature:
    st.caption("Choose the required dates, then click Preview selected attendance.")
    st.stop()

parsed = st.session_state.get("bulk_import_result")
if not parsed:
    st.stop()

selected_days = sorted(parsed.records)
invalid_cells = []
for attendance_date, rows in parsed.records.items():
    for roll_no, status in rows.items():
        if status not in {"P", "A"}:
            invalid_cells.append(f"{attendance_date}: Roll {roll_no} ({status or 'blank'})")

st.subheader("Preview")
st.caption(f"Dates found: **{len(selected_days)}** · {', '.join(date.fromisoformat(day).strftime('%d-%m-%Y') for day in selected_days)}")
st.dataframe(parsed.preview, use_container_width=True, hide_index=True)

if invalid_cells:
    st.error("Every selected student/date cell must contain P or A. Correct the Excel file and upload it again. Examples: " + "; ".join(invalid_cells[:8]))
    st.stop()

st.success("All visible attendance cells contain valid P/A values. The final check will ensure every active student is included exactly once.")
replace = st.checkbox("Replace attendance already saved for these dates", value=False)
if st.button("Import Attendance", type="primary"):
    try:
        days = import_attendance_by_roll(parsed.records, replace_existing=replace)
        st.success(f"Attendance imported successfully for {days} day(s).")
        st.session_state.pop("bulk_import_result", None)
        st.session_state.pop("bulk_import_signature", None)
    except ValueError as exc:
        st.error(str(exc))
