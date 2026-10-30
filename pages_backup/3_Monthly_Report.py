from calendar import monthrange
from datetime import date

import pandas as pd
import streamlit as st

from attendance import get_threshold
from database import init_db
from reports import attendance_matrix, summary_report, summary_report_between

st.set_page_config(page_title="Monthly Report | Attendance", page_icon="📊", layout="wide")
init_db()
st.title("📊 Monthly Attendance Report")
c1, c2, c3 = st.columns([1, 1, 2])
today = date.today()
month = c1.selectbox("Month", range(1, 13), index=today.month - 1, format_func=lambda m: date(2000, m, 1).strftime("%B"))
year = c2.number_input("Year", min_value=2000, max_value=2100, value=today.year, step=1)
query = c3.text_input("Search by registration number, roll number, or name")

summary = summary_report(int(year), month, query)
if summary.empty:
    st.info("No students match your search. Add students from the Students page.")
else:
    working_days = int(summary["Working Days"].max())
    st.caption(f"Working Days: **{working_days}** — only dates with submitted attendance are counted. Holidays are excluded.")
    display = summary.drop(columns=["_id"])
    display["Attendance %"] = display["Attendance %"].map(lambda n: f"{n:.2f}%")
    st.dataframe(display, use_container_width=True, hide_index=True)
    low = summary[(summary["Working Days"] > 0) & (summary["Attendance %"] < get_threshold())]
    if not low.empty:
        st.warning(f"⚠ Low attendance (below {get_threshold():g}%):")
        st.dataframe(low[["Reg No", "Roll No", "Name", "Attendance %"]], hide_index=True, use_container_width=True)
    st.subheader("Day-wise attendance matrix")
    st.caption("P = Present · A = Absent · H = Holiday · - = Attendance not entered")
    st.dataframe(attendance_matrix(int(year), month, query), use_container_width=True, hide_index=True)

st.divider()
st.header("Combined Months Report")
st.caption("Use this at the end of a term to calculate attendance across several months, for example September to November.")
c1, c2, c3 = st.columns([1, 1, 2])
start_month = c1.date_input("Starting month", value=date(today.year, max(1, today.month - 2), 1), format="DD-MM-YYYY")
end_month = c2.date_input("Ending month", value=date(today.year, today.month, 1), format="DD-MM-YYYY")
period_query = c3.text_input("Search students for combined report", key="period_search")
period_start = date(start_month.year, start_month.month, 1)
period_end = date(end_month.year, end_month.month, monthrange(end_month.year, end_month.month)[1])
if period_end < period_start:
    st.error("The ending month must be the same as or after the starting month.")
else:
    combined = summary_report_between(period_start.isoformat(), period_end.isoformat(), period_query)
    if combined.empty:
        st.info("No students match your search.")
    else:
        total_days = int(combined["Working Days"].max())
        st.caption(f"Combined period: **{period_start.strftime('%B %Y')} to {period_end.strftime('%B %Y')}** · Submitted working days: **{total_days}**")
        combined_display = combined.drop(columns=["_id"])
        combined_display["Attendance %"] = combined_display["Attendance %"].map(lambda n: f"{n:.2f}%")
        st.dataframe(combined_display, use_container_width=True, hide_index=True)
