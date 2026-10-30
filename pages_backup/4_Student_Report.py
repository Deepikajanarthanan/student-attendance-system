from datetime import date

import streamlit as st

from attendance import get_students
from database import init_db
from reports import student_detail

st.set_page_config(page_title="Student Report | Attendance", page_icon="👤", layout="wide")
init_db()
st.title("👤 Individual Student Report")
students = get_students()
if not students:
    st.info("Add students first to view an individual report.")
    st.stop()
choices = {f"{s['reg_no']} — {s['roll_no']} — {s['name']}": s for s in students}
today = date.today()
c1, c2, c3 = st.columns([2, 1, 1])
selected = choices[c1.selectbox("Student", list(choices))]
month = c2.selectbox("Month", range(1, 13), index=today.month-1, format_func=lambda m: date(2000, m, 1).strftime("%B"))
year = c3.number_input("Year", min_value=2000, max_value=2100, value=today.year, step=1)
student, detail = student_detail(selected["id"], int(year), month)
st.caption(f"Reg No: **{student['reg_no']}** · Roll No: **{student['roll_no']}** · {student['name']}")
metrics = st.columns(5)
for col, label in zip(metrics, ["Working Days", "Present", "Absent", "Holidays", "Attendance"]):
    value = f"{student['Attendance %']:.2f}%" if label == "Attendance" else student[label]
    col.metric(label, value)
st.subheader("Day-wise attendance")
st.caption("P = Present · A = Absent · H = Holiday · - = Attendance not entered")
st.dataframe(detail, use_container_width=True, hide_index=True)
