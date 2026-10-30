# Student Attendance Management System

A simple day-wise attendance app for a class of about 50–60 students. You enter only the roll numbers of absent students; the system marks every other active student present. There are no periods.

## Features

- Add, edit, search, deactivate, delete, and bulk-import students (CSV or Excel).
- Record a working day by entering only absent roll numbers; blank means everyone is present.
- Import completed P/A attendance sheets by Roll No for a selected start and end date.
- Add holidays that never count as present, absent, or working days.
- Safely update or delete daily attendance without duplicates.
- Monthly summary, day-wise P/A/H/- matrix, individual student report, low-attendance warnings, and dashboard charts.
- Download a formatted `.xlsx` workbook with four report sheets.

## Technologies

Python, Streamlit, SQLite, pandas, Plotly, and openpyxl.

## Project structure

```text
student_attendance/
├── app.py                  # dashboard / application entry point
├── database.py             # SQLite schema and connection helper
├── attendance.py           # student, holiday, and attendance operations
├── reports.py              # monthly reports and Excel export
├── pages/                  # Streamlit sidebar pages
├── tests/test_attendance.py
├── requirements.txt
└── data/attendance.db      # created automatically on first run
```

## Installation (Windows)

Open PowerShell in the project folder and create a virtual environment:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The browser should open automatically. If it does not, use the local address shown in the terminal.

## Daily use

1. On **Students**, add students individually or import a file with these columns in this order: `Roll No`, `Reg No`, `Name`.
2. On **Daily Attendance**, choose the date and leave **Working Day** selected.
3. Enter only absent roll numbers, for example `02, 15, 30`. Commas, spaces, and new lines all work. An empty box means everyone is present.
4. Click **Save Attendance**. If the date already has attendance, the button becomes **Update Attendance** and safely replaces that date’s records.
5. For a holiday, select **Holiday**, optionally enter a description, and save. Holidays are excluded from percentages.

## Bulk attendance Excel import

Use **Bulk Attendance Import** when a completed attendance register is already available in Excel. Add your students first, upload the workbook, select its worksheet and the start/end dates, then preview it. The app matches rows using `Roll No` (or `SN` in a legacy register), accepts only `P` or `A`, and imports only when every active student has a status for every selected date.

## Reports and exports

Use **Monthly Report** for summary and day-wise matrix. P means present, A absent, H holiday, and - not submitted. Only dates where attendance was actually submitted count as working days. **Student Report** provides one student’s monthly details. **Export Reports** downloads an Excel workbook containing Student Summary, Day-Wise Attendance, Attendance Details, and Holidays.

## Settings

The low-attendance warning threshold starts at 75%. Change it from **Settings**.

## Troubleshooting

- **`streamlit` is not recognized:** activate the virtual environment again with `venv\Scripts\activate` and run `pip install -r requirements.txt`.
- **Import file rejected:** ensure its header row uses `Reg No`, `Roll No`, and `Name` exactly.
- **Invalid roll number:** correct or remove the number before saving; no partial attendance is stored.
- **Date is a holiday:** remove the holiday first before recording a working day.

## Run tests

```bash
pytest
```
