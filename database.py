"""SQLite storage layer for the Student Attendance Management System with Multi-Dataset support."""
from __future__ import annotations

import re
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATASETS_DIR = DATA_DIR / "datasets"
_default_db_path = DATA_DIR / "attendance.db"
DB_PATH = _default_db_path

_active_dataset: str = "Class 1"


def sanitize_dataset_name(name: str) -> str:
    clean = "".join(c for c in str(name).strip() if c.isalnum() or c in (" ", "_", "-", "(", ")")).strip()
    return clean or "Class 1"


def _natural_sort_key(s: str) -> list[int | str]:
    parts = re.split(r"(\d+)", s)
    return [int(p) if p.isdigit() else p.casefold() for p in parts]


def dataset_exists(name: str) -> bool:
    """Check if a dataset with the given name already exists (case-insensitive)."""
    clean_name = sanitize_dataset_name(name).casefold()
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    existing = [f.stem.casefold() for f in DATASETS_DIR.glob("*.db") if not f.stem.startswith(".")]
    return clean_name in existing


def _ensure_migration() -> None:
    """Safely migrate legacy attendance.db into datasets/Class 1.db if not already migrated."""
    if DATASETS_DIR != DATA_DIR / "datasets":
        return
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    migration_marker = DATA_DIR / ".migrated"
    if migration_marker.exists():
        return
    existing_dbs = [f for f in DATASETS_DIR.glob("*.db") if not f.stem.startswith(".")]
    if existing_dbs:
        try:
            migration_marker.touch()
        except Exception:
            pass
        return

    class1_path = DATASETS_DIR / "Class 1.db"
    if _default_db_path.exists() and not class1_path.exists():
        try:
            shutil.copy2(_default_db_path, class1_path)
        except Exception:
            pass
    try:
        migration_marker.touch()
    except Exception:
        pass


def list_datasets() -> list[str]:
    """Return all available datasets sorted naturally."""
    _ensure_migration()
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    dbs = [f.stem for f in DATASETS_DIR.glob("*.db") if not f.stem.startswith(".")]
    if not dbs:
        create_dataset("Class 1")
        return ["Class 1"]
    return sorted(dbs, key=_natural_sort_key)


def get_active_dataset() -> str:
    """Return the name of the currently active dataset."""
    global _active_dataset
    available = list_datasets()
    if _active_dataset not in available:
        _active_dataset = available[0]
    return _active_dataset


def set_active_dataset(name: str) -> None:
    """Set the active dataset and ensure its schema is initialized."""
    global _active_dataset
    clean_name = sanitize_dataset_name(name)
    _active_dataset = clean_name
    init_db()


def create_dataset(name: str, auto_increment: bool = False) -> str:
    """Create a new dataset database and initialize tables."""
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    clean_name = sanitize_dataset_name(name)
    db_file = DATASETS_DIR / f"{clean_name}.db"
    if db_file.exists():
        if not auto_increment:
            raise ValueError(f"Dataset '{clean_name}' already exists.")
        counter = 2
        while (DATASETS_DIR / f"{clean_name} ({counter}).db").exists():
            counter += 1
        clean_name = f"{clean_name} ({counter})"
        db_file = DATASETS_DIR / f"{clean_name}.db"

    conn = sqlite3.connect(db_file)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _create_tables(conn)
        conn.commit()
    finally:
        conn.close()

    set_active_dataset(clean_name)
    return clean_name


def delete_dataset(name: str) -> bool:
    """Permanently delete a dataset database file."""
    import gc
    import time

    global _active_dataset
    clean_name = sanitize_dataset_name(name)
    db_file = DATASETS_DIR / f"{clean_name}.db"

    # Ensure any open connections are garbage-collected to free Windows file locks
    gc.collect()

    if db_file.exists():
        # Remove companion journal/wal files if they exist
        for suffix in ("-wal", "-shm", "-journal"):
            companion = DATASETS_DIR / f"{clean_name}.db{suffix}"
            if companion.exists():
                try:
                    companion.unlink()
                except Exception:
                    pass

        # Attempt to unlink with retries on Windows
        deleted = False
        for _ in range(5):
            try:
                gc.collect()
                db_file.unlink()
                deleted = True
                break
            except Exception:
                time.sleep(0.1)
        if not deleted:
            return False

    remaining = [f.stem for f in DATASETS_DIR.glob("*.db") if not f.stem.startswith(".")]
    sorted_rem = sorted(remaining, key=_natural_sort_key)
    if not sorted_rem:
        create_dataset("Class 1")
        _active_dataset = "Class 1"
    else:
        if _active_dataset == clean_name:
            _active_dataset = sorted_rem[0]
    return True


def get_dataset_info(name: str) -> dict[str, int | str]:
    """Return summary information for a given dataset."""
    clean_name = sanitize_dataset_name(name)
    db_file = DATASETS_DIR / f"{clean_name}.db"
    if not db_file.exists():
        return {
            "name": clean_name,
            "student_count": 0,
            "marked_dates_count": 0,
        }
    with connection(clean_name) as conn:
        try:
            std_count = conn.execute("SELECT COUNT(*) FROM students WHERE is_active = 1").fetchone()[0]
        except Exception:
            std_count = 0
        try:
            att_dates = conn.execute("SELECT COUNT(DISTINCT attendance_date) FROM daily_attendance").fetchone()[0]
        except Exception:
            att_dates = 0
        try:
            row_type = conn.execute("SELECT value FROM settings WHERE key='course_type'").fetchone()
            c_type = row_type[0] if row_type else "classroom"
        except Exception:
            c_type = "classroom"
    return {
        "name": clean_name,
        "student_count": std_count,
        "marked_dates_count": att_dates,
        "course_type": c_type,
    }



def get_current_db_path() -> Path:
    # If DB_PATH was monkeypatched (e.g. by unit tests), use DB_PATH
    if DB_PATH != _default_db_path:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return DB_PATH
    _ensure_migration()
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    active = get_active_dataset()
    return DATASETS_DIR / f"{active}.db"


@contextmanager
def connection(dataset_name: str | None = None):
    if dataset_name:
        path = DATASETS_DIR / f"{sanitize_dataset_name(dataset_name)}.db"
    else:
        path = get_current_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reg_no TEXT NOT NULL UNIQUE,
        roll_no TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS daily_attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        attendance_date TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('P', 'A')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(student_id, attendance_date),
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS holidays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        holiday_date TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('low_attendance_threshold', '75')")


def init_db(dataset_name: str | None = None) -> None:
    with connection(dataset_name) as conn:
        _create_tables(conn)

