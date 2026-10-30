"""Read attendance workbooks in a simple or legacy register layout."""
from __future__ import annotations

from calendar import month_abbr, month_name
from datetime import date, datetime
from io import BytesIO
from typing import NamedTuple

import pandas as pd


class ParsedAttendance(NamedTuple):
    records: dict[str, dict[str, str]]
    preview: pd.DataFrame


def _label(value: object) -> str:
    return "".join(char for char in str(value).upper() if char.isalnum())


def _is_blank(value: object) -> bool:
    return pd.isna(value) or not str(value).strip()


MONTHS = {name.upper(): number for number, name in enumerate(month_name) if name}
MONTHS.update({name.upper(): number for number, name in enumerate(month_abbr) if name})


def _month(value: object) -> int | None:
    return MONTHS.get(str(value).strip().upper())


def _explicit_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and any(mark in value for mark in ("-", "/")):
        converted = pd.to_datetime(value, errors="coerce", dayfirst=True)
        return converted.date() if not pd.isna(converted) else None
    return None


def _find_student_header(raw: pd.DataFrame) -> tuple[int, int]:
    """Find a row containing Roll No (or legacy SN) and name/reg fields."""
    for row_index in range(len(raw)):
        labels = [_label(value) for value in raw.iloc[row_index].tolist()]
        roll_columns = [i for i, value in enumerate(labels) if value in {"ROLLNO", "ROLLNUMBER"}]
        if not roll_columns:
            roll_columns = [i for i, value in enumerate(labels) if value == "SN"]
        has_student_field = any(value in {"NAME", "STUDENTNAME", "REGNO", "REGNUMBER", "REGISTRATIONNO"} for value in labels)
        if roll_columns and has_student_field:
            return row_index, roll_columns[0]
    raise ValueError("Could not find a Roll No column. Use a header named Roll No (or SN in a legacy sheet).")


def _legacy_date_columns(raw: pd.DataFrame, header_row: int, roll_column: int, start: date, end: date) -> dict[int, date]:
    date_rows = [r for r in range(header_row) if any(_label(value) == "DATE" for value in raw.iloc[r].tolist())]
    if not date_rows:
        return {}
    date_row = date_rows[-1]
    month_row = next((r for r in range(date_row + 1, header_row) if sum(_month(value) is not None for value in raw.iloc[r].tolist()) > 0), None)
    if month_row is None:
        return {}
    months_by_column: dict[int, int] = {}
    active_month: int | None = None
    for column, value in enumerate(raw.iloc[month_row].tolist()):
        found_month = _month(value)
        if found_month is not None:
            active_month = found_month
        if active_month is not None:
            months_by_column[column] = active_month
    date_columns: dict[int, date] = {}
    for column in range(roll_column + 1, raw.shape[1]):
        value = raw.iat[date_row, column]
        if _is_blank(value) or column not in months_by_column:
            continue
        try:
            day = int(float(value))
        except (TypeError, ValueError):
            continue
        if not 1 <= day <= 31:
            continue
        candidates = []
        for year in range(start.year, end.year + 1):
            try:
                candidate = date(year, months_by_column[column], day)
            except ValueError:
                continue
            if start <= candidate <= end:
                candidates.append(candidate)
        if candidates:
            date_columns[column] = candidates[0]
    return date_columns


def parse_attendance_workbook(contents: bytes, sheet_name: str, start: date, end: date) -> ParsedAttendance:
    """Extract P/A values for the selected range from an Excel worksheet.

    Supported layouts:
    - Row header layout: Roll No, Reg No, Name, 01-09-2026, 02-09-2026, ...
    - Legacy register layout: Roll No/SN, Reg No, Name and a DATE + JAN/FEB... section.
    """
    if end < start:
        raise ValueError("The end date must be the same as or after the start date.")
    raw = pd.read_excel(BytesIO(contents), sheet_name=sheet_name, header=None, dtype=object)
    header_row, roll_column = _find_student_header(raw)
    date_columns: dict[int, date] = {}
    for column, value in enumerate(raw.iloc[header_row].tolist()):
        parsed = _explicit_date(value)
        if parsed and start <= parsed <= end:
            date_columns[column] = parsed
    if not date_columns:
        date_columns = _legacy_date_columns(raw, header_row, roll_column, start, end)
    if not date_columns:
        raise ValueError("No date columns were found in the selected range. Use date headers such as 01-09-2026, or a DATE row with JAN/FEB month labels.")

    records = {day.isoformat(): {} for day in sorted(set(date_columns.values()))}
    rows_for_preview = []
    for row_index in range(header_row + 1, len(raw)):
        roll_value = raw.iat[row_index, roll_column]
        if _is_blank(roll_value):
            continue
        roll_no = str(roll_value).strip()
        row_preview = {"Roll No": roll_no}
        for column, attendance_date in date_columns.items():
            status = "" if _is_blank(raw.iat[row_index, column]) else str(raw.iat[row_index, column]).strip().upper()
            records[attendance_date.isoformat()][roll_no] = status
            row_preview[attendance_date.strftime("%d-%m-%Y")] = status
        rows_for_preview.append(row_preview)
    if not rows_for_preview:
        raise ValueError("No student rows were found below the Roll No header.")
    return ParsedAttendance(records, pd.DataFrame(rows_for_preview))
