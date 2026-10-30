from datetime import date

import pandas as pd
import streamlit as st

from attendance import add_or_update_holiday, attendance_exists, delete_holiday, get_holidays
from database import init_db

st.set_page_config(page_title="Holidays | Attendance", page_icon="🎉", layout="wide")
init_db()
st.title("🎉 Holiday Management")
st.caption("Holidays are entirely under your control. Sundays and weekends are not added automatically.")

add_tab, manage_tab = st.tabs(["Add or edit holiday", "View holidays"])
with add_tab:
    holiday_date = st.date_input("Holiday Date", value=date.today(), max_value=date.today(), format="DD-MM-YYYY")
    exists = attendance_exists(holiday_date)
    description = st.text_input("Holiday Description", placeholder="Example: College Holiday")
    if exists:
        st.warning("Attendance already exists on this date. Confirm below to safely replace it with a holiday.")
    replace = st.checkbox("Replace the attendance records with this holiday", disabled=not exists)
    if st.button("Save Holiday", type="primary"):
        try:
            add_or_update_holiday(holiday_date, description, replace_attendance=replace)
            st.success("Holiday saved successfully.")
        except ValueError as exc:
            st.error(str(exc))

with manage_tab:
    holidays = get_holidays()
    if holidays:
        frame = pd.DataFrame(holidays).rename(columns={"holiday_date": "Date", "description": "Description"})
        frame["Date"] = pd.to_datetime(frame["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(frame[["Date", "Description"]], hide_index=True, use_container_width=True)
        choices = {f"{h['holiday_date']} — {h['description'] or 'Holiday'}": h for h in holidays}
        selected = choices[st.selectbox("Select a holiday to edit or delete", list(choices))]
        with st.form("edit_holiday"):
            updated_date = st.date_input("Date", value=date.fromisoformat(selected["holiday_date"]), max_value=date.today(), format="DD-MM-YYYY")
            updated_description = st.text_input("Description", selected["description"])
            if st.form_submit_button("Save changes"):
                try:
                    if updated_date.isoformat() != selected["holiday_date"]:
                        if attendance_exists(updated_date):
                            raise ValueError("Attendance exists on the new date. Remove it or replace it from Daily Attendance first.")
                        delete_holiday(selected["holiday_date"])
                    add_or_update_holiday(updated_date, updated_description)
                    st.success("Holiday updated.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        confirm = st.checkbox("I am sure I want to delete this holiday.")
        if st.button("Delete Holiday", disabled=not confirm):
            delete_holiday(selected["holiday_date"])
            st.success("Holiday deleted.")
            st.rerun()
    else:
        st.info("No holidays have been added yet.")
