@echo off
title Student Attendance Management System
cd /d "C:\Users\Deppika\Desktop\student_attendance"

if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -m streamlit run app.py
) else (
    python -m streamlit run app.py
)

if errorlevel 1 pause
