from datetime import date

import streamlit as st

from attendance import get_register_session, get_session_class_dates, get_session_status
from database import init_db
from reports import excel_export, generate_register_excel

st.set_page_config(page_title="Export Reports | Attendance", page_icon="📥", layout="wide")
init_db()
st.title("📥 Export Excel Reports")

tab_register, tab_monthly = st.tabs(["📋 Official Attendance Register (5-Mark Score)", "📊 Monthly Summary Workbook"])

with tab_register:
    st.subheader("Official Attendance Register")
    st.caption("Exports the exact register layout with Periods per day, Month groupings, Day of week (M, TH), green 'P' and bold red 'A', total attended hours, % attendance, and attendance marks (max 5).")

    session = get_register_session()
    today = date.today()
    default_start = session["start_date"] if session else date(today.year, 1, 1)
    default_end = session["end_date"] if session else today
    default_periods = session["periods_per_day"] if session else 3
    default_weekdays = session["weekdays"] if session else [0, 3]

    c1, c2, c3 = st.columns(3)
    exp_start = c1.date_input("Start Date", value=default_start, format="DD-MM-YYYY", key="exp_reg_start")
    exp_end = c2.date_input("End Date", value=default_end, format="DD-MM-YYYY", key="exp_reg_end")
    exp_periods = c3.number_input("Periods per Class", min_value=1, max_value=10, value=default_periods, key="exp_reg_periods")

    if exp_end < exp_start:
        st.error("End date cannot be earlier than start date.")
    else:
        class_dates = get_session_class_dates(exp_start, exp_end, default_weekdays)
        if not class_dates:
            st.warning("No scheduled class dates found in this range.")
        else:
            status = get_session_status(class_dates)
            if not status["is_complete"]:
                st.warning(f"⚠️ Note: {len(status['unmarked_dates'])} of {len(class_dates)} dates have not been marked yet. The register can still be generated, but unmarked dates will show '-'.")
            else:
                st.success(f"✅ All {len(class_dates)} class dates through {class_dates[-1].strftime('%d-%m-%Y')} are fully marked!")

            if st.button("Generate Official Register Excel", type="primary", key="btn_gen_register"):
                with st.spinner("Generating official register…"):
                    reg_bytes = generate_register_excel(exp_start, exp_end, class_dates=class_dates, periods_per_day=int(exp_periods))
                    st.session_state["register_export_bytes"] = reg_bytes
                    st.session_state["register_export_name"] = f"attendance_register_{exp_start.strftime('%Y%m%d')}_{exp_end.strftime('%Y%m%d')}.xlsx"

            if "register_export_bytes" in st.session_state:
                st.download_button(
                    label="📥 Download Official Register (.xlsx)",
                    data=st.session_state["register_export_bytes"],
                    file_name=st.session_state["register_export_name"],
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    key="btn_dl_register",
                )

with tab_monthly:
    st.subheader("Monthly Attendance Workbook")
    st.caption("Contains Student Summary, Day-Wise Attendance, Attendance Details, and Holidays sheets.")
    c1, c2 = st.columns(2)
    month = c1.selectbox("Month", range(1, 13), index=today.month - 1, format_func=lambda m: date(2000, m, 1).strftime("%B"))
    year = c2.number_input("Year", min_value=2000, max_value=2100, value=today.year, step=1)
    if st.button("Prepare Monthly Workbook", type="primary", key="btn_prep_monthly"):
        with st.spinner("Creating workbook…"):
            st.session_state["export_bytes"] = excel_export(int(year), month)
            st.session_state["export_name"] = f"attendance_{int(year)}_{month:02d}.xlsx"
    if "export_bytes" in st.session_state:
        st.download_button(
            "Download Monthly Report",
            st.session_state["export_bytes"],
            file_name=st.session_state["export_name"],
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            key="btn_dl_monthly",
        )

