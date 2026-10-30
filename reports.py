"""Reporting and Excel export helpers."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from io import BytesIO
from typing import Mapping, Sequence

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from attendance import (
    get_course_details,
    get_holidays,
    get_register_session,
    get_students,
    roll_sort_key,
)
from database import connection


def month_bounds(year: int, month: int) -> tuple[str, str]:
    return date(year, month, 1).isoformat(), date(year, month, monthrange(year, month)[1]).isoformat()


def submitted_dates(year: int, month: int) -> list[str]:
    start, end = month_bounds(year, month)
    with connection() as conn:
        rows = conn.execute("SELECT DISTINCT attendance_date FROM daily_attendance WHERE attendance_date BETWEEN ? AND ? ORDER BY attendance_date", (start, end)).fetchall()
    return [row[0] for row in rows]


def summary_report(year: int, month: int, query: str = "") -> pd.DataFrame:
    start, end = month_bounds(year, month)
    return summary_report_between(start, end, query)


def summary_report_between(start: str, end: str, query: str = "") -> pd.DataFrame:
    """Student summary for any inclusive date range, including multiple months."""
    with connection() as conn:
        date_rows = conn.execute("""SELECT DISTINCT attendance_date FROM daily_attendance
                                    WHERE attendance_date BETWEEN ? AND ? ORDER BY attendance_date""", (start, end)).fetchall()
    dates = [row[0] for row in date_rows]
    students = get_students(query=query)
    with connection() as conn:
        rows = conn.execute("""SELECT student_id, status, COUNT(*) count FROM daily_attendance
                               WHERE attendance_date BETWEEN ? AND ? GROUP BY student_id, status""", (start, end)).fetchall()
    counts = {(row["student_id"], row["status"]): row["count"] for row in rows}
    data = []
    for student in students:
        present = counts.get((student["id"], "P"), 0)
        absent = counts.get((student["id"], "A"), 0)
        working_days = len(dates)  # only submitted working-day dates occur in daily_attendance
        percent = (present / working_days * 100) if working_days else 0.0
        data.append({"Roll No": student["roll_no"], "Reg No": student["reg_no"], "Name": student["name"],
                     "Active": "Yes" if student["is_active"] else "No", "Working Days": working_days,
                     "Present": present, "Absent": absent, "Attendance %": round(percent, 2), "_id": student["id"]})
    return pd.DataFrame(data, columns=["Roll No", "Reg No", "Name", "Active", "Working Days", "Present", "Absent", "Attendance %", "_id"])


def attendance_matrix(year: int, month: int, query: str = "") -> pd.DataFrame:
    start, end = month_bounds(year, month)
    students = get_students(query=query)
    all_days = pd.date_range(start, end, freq="D")
    columns = [day.strftime("%d-%b") for day in all_days]
    with connection() as conn:
        attendance_rows = conn.execute("""SELECT student_id, attendance_date, status FROM daily_attendance
                                          WHERE attendance_date BETWEEN ? AND ?""", (start, end)).fetchall()
    statuses = {(r["student_id"], r["attendance_date"]): r["status"] for r in attendance_rows}
    holidays = {holiday["holiday_date"] for holiday in get_holidays(start, end)}
    data = []
    for student in students:
        record = {"Roll No": student["roll_no"], "Reg No": student["reg_no"], "Name": student["name"]}
        for day in all_days:
            key = day.date().isoformat()
            record[day.strftime("%d-%b")] = "H" if key in holidays else statuses.get((student["id"], key), "-")
        data.append(record)
    return pd.DataFrame(data, columns=["Roll No", "Reg No", "Name", *columns])


def student_detail(student_id: int, year: int, month: int) -> tuple[dict, pd.DataFrame]:
    start, end = month_bounds(year, month)
    student = next((s for s in get_students() if s["id"] == student_id), None)
    if not student:
        raise ValueError("Student not found.")
    with connection() as conn:
        rows = conn.execute("""SELECT attendance_date, status FROM daily_attendance
                               WHERE student_id=? AND attendance_date BETWEEN ? AND ? ORDER BY attendance_date""", (student_id, start, end)).fetchall()
    statuses = {r["attendance_date"]: r["status"] for r in rows}
    holidays = {h["holiday_date"]: h["description"] for h in get_holidays(start, end)}
    days = pd.date_range(start, end, freq="D")
    detail = []
    for day in days:
        key = day.date().isoformat()
        status = "H" if key in holidays else statuses.get(key, "-")
        detail.append({"Date": day.strftime("%d-%m-%Y"), "Status": status,
                       "Description": holidays.get(key, "")})
    working = len(submitted_dates(year, month))
    present = sum(r["status"] == "P" for r in rows)
    absent = sum(r["status"] == "A" for r in rows)
    stats = {"Working Days": working, "Present": present, "Absent": absent,
             "Holidays": len(holidays), "Attendance %": round(present / working * 100, 2) if working else 0.0}
    return {**student, **stats}, pd.DataFrame(detail)


def attendance_details(year: int, month: int) -> pd.DataFrame:
    start, end = month_bounds(year, month)
    with connection() as conn:
        rows = conn.execute("""SELECT a.attendance_date AS Date, s.roll_no AS 'Roll No', s.reg_no AS 'Reg No',
                                      s.name AS Name, a.status AS Status
                               FROM daily_attendance a JOIN students s ON s.id=a.student_id
                               WHERE a.attendance_date BETWEEN ? AND ? ORDER BY a.attendance_date, s.roll_no""", (start, end)).fetchall()
    return pd.DataFrame([dict(row) for row in rows], columns=["Date", "Roll No", "Reg No", "Name", "Status"])


def excel_export(year: int, month: int) -> bytes:
    summary = summary_report(year, month).drop(columns=["_id", "Active"], errors="ignore")
    matrix = attendance_matrix(year, month)
    details = attendance_details(year, month)
    start, end = month_bounds(year, month)
    holidays = pd.DataFrame(get_holidays(start, end)).rename(columns={"holiday_date": "Date", "description": "Description"})
    holidays = holidays.reindex(columns=["Date", "Description"])
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Student Summary", index=False)
        matrix.to_excel(writer, sheet_name="Day-Wise Attendance", index=False)
        details.to_excel(writer, sheet_name="Attendance Details", index=False)
        holidays.to_excel(writer, sheet_name="Holidays", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F4E78")
                cell.alignment = Alignment(horizontal="center")
            for column in sheet.columns:
                letter = column[0].column_letter
                sheet.column_dimensions[letter].width = min(max(len(str(c.value or "")) for c in column) + 2, 24)
    return output.getvalue()


MONTH_NAMES = {
    1: "JAN", 2: "FEB", 3: "MARCH", 4: "APRIL", 5: "MAY", 6: "JUNE",
    7: "JULY", 8: "AUGUST", 9: "SEPTEMBER", 10: "OCTOBER", 11: "NOVEMBER", 12: "DECEMBER"
}
WEEKDAY_CODES = {
    0: "M", 1: "TU", 2: "W", 3: "TH", 4: "F", 5: "SA", 6: "SU"
}


def calculate_attendance_marks(
    absent_count: int | float,
    total_periods: int = 40,
    course_type: str = "classroom",
) -> int:
    """Award attendance mark out of 5.

    For Classroom (Theory):
      Reduce 1 mark for every 3 classes absent.
      0 - 2 classes absent -> 5 marks
      3 - 5 classes absent -> 4 marks (1 mark reduced)
      6 - 8 classes absent -> 3 marks (2 marks reduced)
      9 - 11 classes absent -> 2 marks (3 marks reduced)
      12 - 14 classes absent -> 1 mark (4 marks reduced)
      >= 15 classes absent -> 0 marks

    For Laboratory (Lab):
      Reduce 1 mark for every 1 day absent.
      0 days absent -> 5 marks
      1 day absent -> 4 marks (1 mark reduced)
      2 days absent -> 3 marks (2 marks reduced)
      3 days absent -> 2 marks (3 marks reduced)
      4 days absent -> 1 mark (4 marks reduced)
      >= 5 days absent -> 0 marks

    If a percentage value (> total_periods or > 40.0) is passed, converts to absent classes/days based on total_periods.
    """
    if str(course_type).lower() == "lab":
        if isinstance(absent_count, float) and absent_count > float(total_periods):
            pct = max(0.0, min(100.0, absent_count))
            absent_days = int(round(total_periods * (100.0 - pct) / 100.0))
        else:
            absent_days = int(absent_count)
        return max(0, 5 - absent_days)

    if isinstance(absent_count, float) and absent_count > float(total_periods):
        pct = max(0.0, min(100.0, absent_count))
        absent_classes = int(round(total_periods * (100.0 - pct) / 100.0))
    else:
        absent_classes = int(absent_count)

    reduction = max(0, absent_classes // 3)
    return max(0, 5 - reduction)


def generate_register_excel(
    start_date: date | str,
    end_date: date | str,
    class_dates: Sequence[date] | None = None,
    periods_per_day: int = 1,
    active_only: bool = True,
    date_periods: Mapping[date | str, int] | None = None,
    weekday_periods: Mapping[int, int | str] | None = None,
    class_handled: str | None = None,
    faculty_name: str | None = None,
    subject: str | None = None,
    total_hours: int | str | None = None,
    course_type: str | None = None,
    include_holidays: bool = False,
) -> bytes:
    """Export attendance register matching the college attendance layout.

    Features:
    - Multi-row headers: PERIODS per day (e.g. 1st or 4th hour for Classroom, 1-3 for Lab), DATE numbers, merged MONTH groupings, DAY/DATE weekday codes
    - SN, REGNO, NAME
    - 'P' in green, 'A' in bold red, 'H' in bold blue (if include_holidays=True)
    - Total attended hours (HRS. ATT.), attendance percentage (% ATT.), and attendance MARKS (max 5)
    - Total working hours equals total working days * hours_per_day (1 hr for Classroom, 3 hrs for Lab, excluding holidays)
    - Header rows 1 & 2 display Class Handled, Subject, Faculty Name, Total Hours, and Type
    - Holidays are excluded from the exported Excel register columns by default (include_holidays=False)
    """
    course_info = get_course_details()
    c_handled = str(class_handled if class_handled is not None else course_info.get("class_handled", "")).strip()
    f_name = str(faculty_name if faculty_name is not None else course_info.get("faculty_name", "")).strip()
    subj = str(subject if subject is not None else course_info.get("subject", "")).strip()
    tot_hrs = total_hours if total_hours is not None else course_info.get("total_hours", "")
    c_type = str(course_type if course_type is not None else course_info.get("course_type", "classroom")).lower()
    is_lab = (c_type == "lab")
    effective_periods_per_day = 3 if is_lab else (periods_per_day or 1)

    start_d = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    end_d = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date

    if class_dates is None:
        with connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT attendance_date FROM daily_attendance WHERE attendance_date BETWEEN ? AND ? ORDER BY attendance_date",
                (start_d.isoformat(), end_d.isoformat()),
            ).fetchall()
        class_dates_list = [date.fromisoformat(r[0]) for r in rows]
    else:
        class_dates_list = sorted(class_dates)

    if weekday_periods is None:
        session = get_register_session()
        weekday_periods = session.get("weekday_periods", {}) if session else {}

    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance Register"
    ws.views.sheetView[0].showGridLines = True

    students = sorted(get_students(active_only=active_only), key=roll_sort_key)
    student_ids = [s["id"] for s in students]

    holidays_set = {h["holiday_date"] for h in get_holidays(start_d.isoformat(), end_d.isoformat())}
    working_dates = [d for d in class_dates_list if d.isoformat() not in holidays_set]
    if not include_holidays:
        export_dates = working_dates
    else:
        export_dates = list(class_dates_list)

    total_dates = len(export_dates)
    total_periods = len(working_dates) * effective_periods_per_day
    iso_dates = [d.isoformat() for d in export_dates]

    attendance_map: dict[tuple[int, str], str] = {}
    if student_ids and iso_dates:
        with connection() as conn:
            p_dates = ",".join("?" for _ in iso_dates)
            p_students = ",".join("?" for _ in student_ids)
            q = f"SELECT student_id, attendance_date, status FROM daily_attendance WHERE attendance_date IN ({p_dates}) AND student_id IN ({p_students})"
            for row in conn.execute(q, (*iso_dates, *student_ids)).fetchall():
                attendance_map[(row["student_id"], row["attendance_date"])] = row["status"]

    font_bold = Font(name="Calibri", size=10, bold=True)
    font_regular = Font(name="Calibri", size=10)
    font_present = Font(name="Calibri", size=10, color="008000")
    font_absent = Font(name="Calibri", size=10, bold=True, color="FF0000")
    font_holiday = Font(name="Calibri", size=10, bold=True, color="0000FF")
    font_month = Font(name="Calibri", size=10, bold=True, color="C00000")

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_wrap_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    thin_side = Side(style="thin", color="000000")
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    hrs_col = 4 + total_dates
    pct_col = 5 + total_dates
    marks_col = 6 + total_dates

    # Row 1: Course, Subject & Faculty metadata
    if c_handled:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=2)
        cell_c = ws.cell(row=1, column=1, value=f"CLASS: {c_handled}")
        cell_c.font = font_bold
        cell_c.alignment = align_left
    if subj:
        cell_s = ws.cell(row=1, column=3, value=f"SUBJECT: {subj}")
        cell_s.font = font_bold
        cell_s.alignment = align_left
    if f_name:
        cell_f = ws.cell(row=1, column=4, value=f"FACULTY: {f_name}")
        cell_f.font = font_bold
        cell_f.alignment = align_left
    if is_lab and hrs_col >= 5:
        cell_type = ws.cell(row=1, column=5, value="TYPE: LAB")
        cell_type.font = font_bold
        cell_type.alignment = align_left

    # Row 2: Total Hours target
    if tot_hrs:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
        cell_th = ws.cell(row=2, column=1, value=f"TOTAL HOURS: {tot_hrs}")
        cell_th.font = font_bold
        cell_th.alignment = align_left

    # Row 3: PERIODS
    c = ws.cell(row=3, column=3, value="PERIODS")
    c.font = font_bold
    c.alignment = align_right
    c.border = thin_border
    for idx, d in enumerate(export_dates):
        if is_lab:
            if date_periods and (d in date_periods or d.isoformat() in date_periods):
                p_val = date_periods.get(d) or date_periods.get(d.isoformat())
            elif weekday_periods and d.weekday() in weekday_periods:
                p_val = weekday_periods[d.weekday()]
            else:
                p_val = "1-3"
        else:
            if date_periods and d in date_periods:
                p_val = date_periods[d]
            elif date_periods and d.isoformat() in date_periods:
                p_val = date_periods[d.isoformat()]
            elif weekday_periods and d.weekday() in weekday_periods:
                p_val = weekday_periods[d.weekday()]
            else:
                p_val = 1 if d.weekday() == 0 else 4 if d.weekday() == 3 else 1
        cell = ws.cell(row=3, column=4 + idx, value=p_val)
        cell.font = font_regular
        cell.alignment = align_center
        cell.border = thin_border
    c_tot_label = ws.cell(row=3, column=hrs_col, value="TOTAL")
    c_tot_label.font = font_bold
    c_tot_label.alignment = align_center
    c_tot_label.border = thin_border
    ws.cell(row=3, column=pct_col).border = thin_border
    ws.cell(row=3, column=marks_col).border = thin_border

    # Row 4: DATE numbers and total hours
    c_date = ws.cell(row=4, column=3, value="DATE")
    c_date.font = font_bold
    c_date.alignment = align_right
    c_date.border = thin_border
    for idx, d in enumerate(export_dates):
        cell = ws.cell(row=4, column=4 + idx, value=d.day)
        cell.font = font_bold
        cell.alignment = align_center
        cell.border = thin_border
    c_tot_val = ws.cell(row=4, column=hrs_col, value=total_periods)
    c_tot_val.font = font_bold
    c_tot_val.alignment = align_center
    c_tot_val.border = thin_border
    ws.cell(row=4, column=pct_col).border = thin_border
    ws.cell(row=4, column=marks_col).border = thin_border

    # Row 5: Month groupings
    for col in range(1, 4):
        ws.cell(row=5, column=col).border = thin_border
    ws.cell(row=5, column=hrs_col).border = thin_border
    ws.cell(row=5, column=pct_col).border = thin_border
    ws.cell(row=5, column=marks_col).border = thin_border

    month_groups: list[tuple[str, int, int]] = []
    if export_dates:
        curr_label = MONTH_NAMES.get(export_dates[0].month, export_dates[0].strftime("%B").upper())
        start_idx = 0
        for i in range(1, len(export_dates)):
            lbl = MONTH_NAMES.get(export_dates[i].month, export_dates[i].strftime("%B").upper())
            if lbl != curr_label:
                month_groups.append((curr_label, 4 + start_idx, 3 + i))
                curr_label = lbl
                start_idx = i
        month_groups.append((curr_label, 4 + start_idx, 3 + len(export_dates)))

    for m_label, start_c, end_c in month_groups:
        if start_c < end_c:
            ws.merge_cells(start_row=5, start_column=start_c, end_row=5, end_column=end_c)
        cell = ws.cell(row=5, column=start_c, value=m_label)
        cell.font = font_month
        cell.alignment = align_center
        for c_idx in range(start_c, end_c + 1):
            ws.cell(row=5, column=c_idx).border = thin_border

    # Row 6: DAY / DATE and weekday codes
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=3)
    c_day_date = ws.cell(row=6, column=1, value="DAY / DATE")
    c_day_date.font = font_bold
    c_day_date.alignment = align_center
    for c_idx in range(1, 4):
        ws.cell(row=6, column=c_idx).border = thin_border

    for idx, d in enumerate(export_dates):
        code = WEEKDAY_CODES.get(d.weekday(), d.strftime("%a")[:2].upper())
        cell = ws.cell(row=6, column=4 + idx, value=code)
        cell.font = font_bold
        cell.alignment = align_center
        cell.border = thin_border

    ws.merge_cells(start_row=6, start_column=hrs_col, end_row=7, end_column=hrs_col)
    c_hrs = ws.cell(row=6, column=hrs_col, value="HRS.\nATT.")
    c_hrs.font = font_bold
    c_hrs.alignment = align_wrap_center
    ws.cell(row=6, column=hrs_col).border = thin_border
    ws.cell(row=7, column=hrs_col).border = thin_border

    ws.merge_cells(start_row=6, start_column=pct_col, end_row=7, end_column=pct_col)
    c_pct = ws.cell(row=6, column=pct_col, value="% ATT.")
    c_pct.font = font_bold
    c_pct.alignment = align_wrap_center
    ws.cell(row=6, column=pct_col).border = thin_border
    ws.cell(row=7, column=pct_col).border = thin_border

    ws.merge_cells(start_row=6, start_column=marks_col, end_row=7, end_column=marks_col)
    c_mk = ws.cell(row=6, column=marks_col, value="MARKS\n(MAX 5)")
    c_mk.font = font_bold
    c_mk.alignment = align_wrap_center
    ws.cell(row=6, column=marks_col).border = thin_border
    ws.cell(row=7, column=marks_col).border = thin_border

    # Row 7: SN, REGNO, NAME
    c_sn = ws.cell(row=7, column=1, value="SN")
    c_sn.font = font_bold
    c_sn.alignment = align_center
    c_sn.border = thin_border

    c_reg = ws.cell(row=7, column=2, value="REGNO")
    c_reg.font = font_bold
    c_reg.alignment = align_center
    c_reg.border = thin_border

    c_nm = ws.cell(row=7, column=3, value="NAME")
    c_nm.font = font_bold
    c_nm.alignment = align_center
    c_nm.border = thin_border

    for idx in range(total_dates):
        cell = ws.cell(row=7, column=4 + idx)
        cell.border = thin_border

    # Row 8 onwards: Student records
    for s_idx, student in enumerate(students, start=1):
        curr_row = 7 + s_idx

        sn_cell = ws.cell(row=curr_row, column=1, value=s_idx)
        sn_cell.font = font_regular
        sn_cell.alignment = align_center
        sn_cell.border = thin_border

        reg_cell = ws.cell(row=curr_row, column=2, value=str(student["reg_no"]))
        reg_cell.font = font_regular
        reg_cell.alignment = align_center
        reg_cell.border = thin_border

        name_cell = ws.cell(row=curr_row, column=3, value=student["name"])
        name_cell.font = font_regular
        name_cell.alignment = align_left
        name_cell.border = thin_border

        presents = 0
        for d_idx, d in enumerate(export_dates):
            d_iso = d.isoformat()
            if include_holidays and d_iso in holidays_set:
                st_val = "H"
                cell = ws.cell(row=curr_row, column=4 + d_idx, value=st_val)
                cell.alignment = align_center
                cell.border = thin_border
                cell.font = font_holiday
            else:
                st_val = attendance_map.get((student["id"], d_iso), "-")
                cell = ws.cell(row=curr_row, column=4 + d_idx, value=st_val)
                cell.alignment = align_center
                cell.border = thin_border
                if st_val == "P":
                    cell.font = font_present
                    presents += 1
                elif st_val == "A":
                    cell.font = font_absent
                else:
                    cell.font = font_regular

        hrs_att = presents * effective_periods_per_day
        hrs_cell = ws.cell(row=curr_row, column=hrs_col, value=hrs_att)
        hrs_cell.font = font_regular
        hrs_cell.alignment = align_center
        hrs_cell.border = thin_border

        pct_att = (hrs_att / total_periods * 100.0) if total_periods > 0 else 0.0
        pct_rounded = int(round(pct_att))
        pct_cell = ws.cell(row=curr_row, column=pct_col, value=pct_rounded)
        pct_cell.number_format = "0"
        pct_cell.font = font_regular
        pct_cell.alignment = align_center
        pct_cell.border = thin_border

        if is_lab:
            absent_days = len(working_dates) - presents
            mark = calculate_attendance_marks(absent_days, total_periods=len(working_dates), course_type="lab")
        else:
            absent_classes = (total_periods - hrs_att) // effective_periods_per_day if effective_periods_per_day > 0 else 0
            mark = calculate_attendance_marks(absent_classes, total_periods=len(working_dates), course_type="classroom")
        mk_cell = ws.cell(row=curr_row, column=marks_col, value=mark)
        mk_cell.font = font_bold
        mk_cell.alignment = align_center
        mk_cell.border = thin_border

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 28
    for idx in range(total_dates):
        col_letter = get_column_letter(4 + idx)
        ws.column_dimensions[col_letter].width = 4.5
    ws.column_dimensions[get_column_letter(hrs_col)].width = 9
    ws.column_dimensions[get_column_letter(pct_col)].width = 9
    ws.column_dimensions[get_column_letter(marks_col)].width = 9

    ws.row_dimensions[3].height = 18
    ws.row_dimensions[4].height = 18
    ws.row_dimensions[5].height = 18
    ws.row_dimensions[6].height = 18
    ws.row_dimensions[7].height = 18
    for r in range(8, 8 + len(students)):
        ws.row_dimensions[r].height = 18

    output = BytesIO()
    wb.save(output)
    return output.getvalue()

