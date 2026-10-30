import streamlit as st

from attendance import get_threshold, set_threshold
from database import init_db

st.set_page_config(page_title="Settings | Attendance", page_icon="⚙️", layout="wide")
init_db()
st.title("⚙️ Settings")
st.caption("Change the attendance percentage at which students are shown as low attendance.")
with st.form("settings"):
    threshold = st.number_input("Low attendance warning threshold (%)", min_value=0.0, max_value=100.0,
                                value=get_threshold(), step=1.0)
    if st.form_submit_button("Save Settings", type="primary"):
        set_threshold(threshold)
        st.success("Settings saved.")
