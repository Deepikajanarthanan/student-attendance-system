"""Student, attendance, holiday, and settings operations."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from typing import Iterable, Mapping

from database import (
    connection,
    create_dataset,
    dataset_exists,
    delete_dataset,
    get_active_dataset,
    get_dataset_info,
    init_db,
    list_datasets,
    sanitize_dataset_name,
    set_active_dataset,
)


def iso_date(value: date | str) -> str:
    return value.isoformat() if isinstance(value, date) else value


def parse_reg_nos(value: str) -> list[str]:
    """Parse comma, whitespace, or newline separated registration numbers."""
    return list(dict.fromkeys(item.strip() for item in re.split(r"[,\s]+", value.strip()) if item.strip()))


def roll_key(value: object) -> str:
    """Make spreadsheet roll numbers comparable while retaining leading-zero support."""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return str(int(text)) if text.isdigit() else text.casefold()


def roll_sort_key(value: object) -> tuple[int, int, str]:
    """Natural sort key for roll numbers ensuring 1, 2, ..., 9, 10, 11... ordering."""
    text = value["roll_no"] if isinstance(value, dict) else str(value)
    text = str(text).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    digits = "".join(c for c in text if c.isdigit())
    if digits:
        return (0, int(digits), text)
    return (1, 0, text.casefold())


def get_students(active_only: bool = False, query: str = "") -> list[dict]:
    init_db()
    sql = "SELECT * FROM students"
    clauses, params = [], []
    if active_only:
        clauses.append("is_active = 1")
    if query.strip():
        clauses.append("(reg_no LIKE ? OR roll_no LIKE ? OR name LIKE ?)")
        term = f"%{query.strip()}%"
        params.extend([term, term, term])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    with connection() as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    return sorted(rows, key=roll_sort_key)


def get_student(student_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return dict(row) if row else None


def add_student(reg_no: str, roll_no: str, name: str) -> None:
    if not reg_no.strip() or not roll_no.strip() or not name.strip():
        raise ValueError("Registration number, roll number, and name are required.")
    try:
        with connection() as conn:
            conn.execute("INSERT INTO students(reg_no, roll_no, name) VALUES (?, ?, ?)",
                         (reg_no.strip(), roll_no.strip(), name.strip()))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Registration number and roll number must each be unique.") from exc


def update_student(student_id: int, reg_no: str, roll_no: str, name: str, is_active: bool) -> None:
    if not reg_no.strip() or not roll_no.strip() or not name.strip():
        raise ValueError("Registration number, roll number, and name are required.")
    try:
        with connection() as conn:
            conn.execute("UPDATE students SET reg_no=?, roll_no=?, name=?, is_active=? WHERE id=?",
                         (reg_no.strip(), roll_no.strip(), name.strip(), int(is_active), student_id))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Registration number and roll number must each be unique.") from exc


def delete_student(student_id: int) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))


def import_students(rows: Iterable[dict]) -> tuple[int, list[str]]:
    """Import valid rows while safely skipping duplicates. Returns imported count/errors."""
    added, errors = 0, []
    for index, row in enumerate(rows, start=2):
        try:
            add_student(str(row["Reg No"]), str(row["Roll No"]), str(row["Name"]))
            added += 1
        except (KeyError, ValueError) as exc:
            errors.append(f"Row {index}: {exc}")
    return added, errors


def attendance_exists(attendance_date: date | str) -> bool:
    with connection() as conn:
        return bool(conn.execute("SELECT 1 FROM daily_attendance WHERE attendance_date=? LIMIT 1", (iso_date(attendance_date),)).fetchone())


def holiday_for_date(holiday_date: date | str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM holidays WHERE holiday_date=?", (iso_date(holiday_date),)).fetchone()
        return dict(row) if row else None


def save_attendance(attendance_date: date | str, absent_text: str, replace: bool = False) -> tuple[int, int]:
    """Save one P/A record for every active student using absent roll numbers, or mark date as holiday."""
    init_db()
    day = iso_date(attendance_date)
    text_clean = absent_text.strip().casefold()
    if text_clean in {"holiday", "h", "leave"}:
        add_or_update_holiday(day, "Holiday", replace_attendance=True)
        return 0, 0

    if text_clean in {"p", "present", "all", "none", "nil", "0"}:
        absent_text = ""

    if holiday_for_date(day):
        if replace:
            delete_holiday(day)
        else:
            raise ValueError("This date is already marked as a holiday. Remove the holiday first.")
    students = get_students(active_only=True)
    if not students:
        raise ValueError("Add at least one active student before recording attendance.")

    absent_raw = parse_reg_nos(absent_text)
    student_by_key = {roll_key(s["roll_no"]): s for s in students}
    invalid = [roll for roll in absent_raw if roll_key(roll) not in student_by_key]
    if invalid:
        raise ValueError("Invalid Roll Number(s): " + ", ".join(invalid))
    if attendance_exists(day) and not replace:
        raise ValueError("Attendance already exists for this date. Choose Update Attendance to replace it.")

    absent_student_ids = {student_by_key[roll_key(roll)]["id"] for roll in absent_raw}
    with connection() as conn:
        if replace:
            conn.execute("DELETE FROM daily_attendance WHERE attendance_date=?", (day,))
        conn.executemany("INSERT INTO daily_attendance(student_id, attendance_date, status) VALUES (?, ?, ?)",
                         [(student["id"], day, "A" if student["id"] in absent_student_ids else "P") for student in students])
    return len(students) - len(absent_student_ids), len(absent_student_ids)


def get_absent_roll_nos(attendance_date: date | str) -> list[str]:
    with connection() as conn:
        rows = conn.execute("""SELECT s.roll_no FROM daily_attendance a JOIN students s ON s.id=a.student_id
                               WHERE a.attendance_date=? AND a.status='A'""", (iso_date(attendance_date),)).fetchall()
        roll_list = [row["roll_no"] for row in rows]
        return sorted(roll_list, key=roll_sort_key)


def delete_attendance(attendance_date: date | str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM daily_attendance WHERE attendance_date=?", (iso_date(attendance_date),))


def import_attendance_by_roll(
    attendance: Mapping[str, Mapping[str, str]], replace_existing: bool = False
) -> int:
    """Atomically import complete P/A matrices keyed by ISO date and roll number.

    The submitted matrix must contain exactly one P/A value for every active student
    on every date. No changes are made if any validation fails.
    """
    init_db()
    if not attendance:
        raise ValueError("No attendance dates were found in the selected date range.")
    students = get_students(active_only=True)
    if not students:
        raise ValueError("Add active students before importing attendance.")
    student_by_key = {roll_key(student["roll_no"]): student for student in students}
    if len(student_by_key) != len(students):
        raise ValueError("Active student roll numbers must be unique.")

    prepared: dict[str, list[tuple[int, str]]] = {}
    today = date.today().isoformat()
    for attendance_date, statuses in attendance.items():
        if attendance_date > today:
            raise ValueError(f"Future attendance cannot be imported: {attendance_date}.")
        if holiday_for_date(attendance_date):
            raise ValueError(f"{attendance_date} is already marked as a holiday. Remove the holiday first.")
        if attendance_exists(attendance_date) and not replace_existing:
            raise ValueError(f"Attendance already exists for {attendance_date}. Enable replacement to continue.")
        input_keys = [roll_key(roll) for roll in statuses]
        if len(set(input_keys)) != len(input_keys):
            raise ValueError(f"{attendance_date}: duplicate roll number rows were found in the import sheet.")
        input_by_key = {roll_key(roll): str(status).strip().upper() for roll, status in statuses.items()}
        unknown = sorted(key for key in input_by_key if key not in student_by_key)
        missing = sorted(student["roll_no"] for key, student in student_by_key.items() if key not in input_by_key)
        invalid = sorted(roll for roll, status in statuses.items() if str(status).strip().upper() not in {"P", "A"})
        if unknown:
            raise ValueError(f"{attendance_date}: unknown roll number(s): {', '.join(unknown)}.")
        if missing:
            raise ValueError(f"{attendance_date}: missing attendance for roll number(s): {', '.join(missing)}.")
        if invalid:
            raise ValueError(f"{attendance_date}: use only P or A for roll number(s): {', '.join(map(str, invalid))}.")
        prepared[attendance_date] = [(student["id"], input_by_key[key]) for key, student in student_by_key.items()]

    with connection() as conn:
        for attendance_date, rows in prepared.items():
            if replace_existing:
                conn.execute("DELETE FROM daily_attendance WHERE attendance_date=?", (attendance_date,))
            conn.executemany("INSERT INTO daily_attendance(student_id, attendance_date, status) VALUES (?, ?, ?)",
                             [(student_id, attendance_date, status) for student_id, status in rows])
    return len(prepared)


def add_or_update_holiday(holiday_date: date | str, description: str, replace_attendance: bool = False) -> None:
    day = iso_date(holiday_date)
    if attendance_exists(day) and not replace_attendance:
        raise ValueError("Attendance exists for this date. Confirm replacement to mark it as a holiday.")
    with connection() as conn:
        if replace_attendance:
            conn.execute("DELETE FROM daily_attendance WHERE attendance_date=?", (day,))
        conn.execute("""INSERT INTO holidays(holiday_date, description) VALUES (?, ?)
                        ON CONFLICT(holiday_date) DO UPDATE SET description=excluded.description""", (day, description.strip()))


def delete_holiday(holiday_date: date | str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM holidays WHERE holiday_date=?", (iso_date(holiday_date),))


def get_holidays(start: str | None = None, end: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM holidays", []
    if start and end:
        sql += " WHERE holiday_date BETWEEN ? AND ?"; params = [start, end]
    sql += " ORDER BY holiday_date"
    with connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_threshold() -> float:
    with connection() as conn:
        return float(conn.execute("SELECT value FROM settings WHERE key='low_attendance_threshold'").fetchone()[0])


def set_threshold(value: float) -> None:
    if not 0 <= value <= 100:
        raise ValueError("Threshold must be between 0 and 100.")
    with connection() as conn:
        conn.execute("UPDATE settings SET value=? WHERE key='low_attendance_threshold'", (str(value),))


def get_session_class_dates(
    start_date: date | str,
    end_date: date | str,
    weekdays: list[int] | None = None,
    exclude_holidays: bool = False,
) -> list[date]:
    """Return all scheduled class dates between start and end date (inclusive).

    If weekdays is specified (e.g. [0, 3] for Mon/Thu), only dates matching those weekdays
    are included. If exclude_holidays is True, dates in holidays table are excluded.
    """
    s = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    e = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    if e < s:
        raise ValueError("End date must be greater than or equal to start date.")

    holidays_set = set()
    if exclude_holidays:
        holidays_set = {h["holiday_date"] for h in get_holidays(s.isoformat(), e.isoformat())}

    dates = []
    current = s
    while current <= e:
        if weekdays is None or current.weekday() in weekdays:
            if not (exclude_holidays and current.isoformat() in holidays_set):
                dates.append(current)
        current += timedelta(days=1)
    return dates


def get_session_status(class_dates: list[date]) -> dict:
    """Return attendance completion progress for the scheduled class dates."""
    if not class_dates:
        return {
            "total_dates": 0,
            "marked_dates": [],
            "unmarked_dates": [],
            "is_complete": False,
            "next_unmarked_date": None,
        }
    iso_list = [d.isoformat() for d in class_dates]
    with connection() as conn:
        placeholders = ",".join("?" for _ in iso_list)
        rows_att = conn.execute(
            f"SELECT DISTINCT attendance_date FROM daily_attendance WHERE attendance_date IN ({placeholders})",
            iso_list,
        ).fetchall()
        rows_hol = conn.execute(
            f"SELECT DISTINCT holiday_date FROM holidays WHERE holiday_date IN ({placeholders})",
            iso_list,
        ).fetchall()
        saved_dates = {row[0] for row in rows_att} | {row[0] for row in rows_hol}

    marked = [d for d in class_dates if d.isoformat() in saved_dates]
    unmarked = [d for d in class_dates if d.isoformat() not in saved_dates]
    return {
        "total_dates": len(class_dates),
        "marked_dates": marked,
        "unmarked_dates": unmarked,
        "is_complete": len(unmarked) == 0,
        "next_unmarked_date": unmarked[0] if unmarked else None,
    }


def get_register_session() -> dict | None:
    """Retrieve saved attendance register session configuration from settings."""
    init_db()
    with connection() as conn:
        rows = dict(conn.execute("SELECT key, value FROM settings WHERE key LIKE 'register_%'").fetchall())
    if "register_start_date" in rows and "register_end_date" in rows:
        try:
            weekdays = [int(x) for x in rows.get("register_weekdays", "0,3").split(",") if x.strip()]
            periods_per_day = int(rows.get("register_periods_per_day", "1"))
            wp_str = rows.get("register_weekday_periods")
            if wp_str:
                raw_wp = json.loads(wp_str)
                weekday_periods = {}
                for k, v in raw_wp.items():
                    k_int = int(k)
                    v_str = str(v).strip()
                    weekday_periods[k_int] = int(v_str) if v_str.isdigit() else v_str
            else:
                weekday_periods = {0: 1, 3: 4} if set(weekdays) == {0, 3} else {w: 1 for w in weekdays}
            return {
                "start_date": date.fromisoformat(rows["register_start_date"]),
                "end_date": date.fromisoformat(rows["register_end_date"]),
                "weekdays": weekdays,
                "periods_per_day": periods_per_day,
                "weekday_periods": weekday_periods,
            }
        except Exception as exc:
            import logging
            logging.warning("Failed parsing register session: %s", exc)
            return None
    return None


def save_register_session(
    start_date: date | str,
    end_date: date | str,
    weekdays: list[int],
    periods_per_day: int = 1,
    weekday_periods: dict[int, int | str] | None = None,
) -> None:
    """Save attendance register session configuration to settings."""
    init_db()
    s = iso_date(start_date)
    e = iso_date(end_date)
    w = ",".join(str(x) for x in weekdays)
    p = str(periods_per_day)
    wp = json.dumps(weekday_periods or {x: (1 if x == 0 else 4 if x == 3 else 1) for x in weekdays})
    with connection() as conn:
        conn.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [
                ("register_start_date", s),
                ("register_end_date", e),
                ("register_weekdays", w),
                ("register_periods_per_day", p),
                ("register_weekday_periods", wp),
            ],
        )


def get_course_details(dataset_name: str | None = None) -> dict[str, str | int]:
    """Retrieve course and faculty metadata (class handled, faculty name, subject, total hours, course type)."""
    init_db(dataset_name)
    with connection(dataset_name) as conn:
        rows = dict(conn.execute(
            "SELECT key, value FROM settings WHERE key IN ('course_class_handled', 'course_faculty_name', 'course_subject', 'course_total_hours', 'course_type')"
        ).fetchall())
    try:
        tot_hrs = int(rows.get("course_total_hours", "40"))
    except (ValueError, TypeError):
        tot_hrs = 40
    return {
        "class_handled": rows.get("course_class_handled", ""),
        "faculty_name": rows.get("course_faculty_name", ""),
        "subject": rows.get("course_subject", ""),
        "total_hours": tot_hrs,
        "course_type": rows.get("course_type", "classroom").lower(),
    }


def save_course_details(
    class_handled: str,
    faculty_name: str,
    subject: str,
    total_hours: int | str = 40,
    course_type: str = "classroom",
    dataset_name: str | None = None,
) -> None:
    """Save course and faculty metadata into dataset settings."""
    init_db(dataset_name)
    c_type = str(course_type).strip().lower()
    if c_type not in {"classroom", "lab"}:
        c_type = "classroom"
    with connection(dataset_name) as conn:
        conn.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [
                ("course_class_handled", str(class_handled).strip()),
                ("course_faculty_name", str(faculty_name).strip()),
                ("course_subject", str(subject).strip()),
                ("course_total_hours", str(total_hours).strip()),
                ("course_type", c_type),
            ],
        )



