"""SQLite setup and demo data for the TenantEase maintenance PoC."""
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).with_name("tenantease.db")

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS landlords (
    landlord_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS buildings (
    building_id INTEGER PRIMARY KEY,
    landlord_id INTEGER NOT NULL REFERENCES landlords(landlord_id),
    name TEXT NOT NULL,
    address TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS units (
    unit_id INTEGER PRIMARY KEY,
    building_id INTEGER NOT NULL REFERENCES buildings(building_id),
    unit_label TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS leases (
    lease_id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(tenant_id),
    unit_id INTEGER NOT NULL REFERENCES units(unit_id),
    start_date TEXT NOT NULL,
    end_date TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS maintenance_tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(tenant_id),
    unit_id INTEGER REFERENCES units(unit_id),
    building_id INTEGER NOT NULL REFERENCES buildings(building_id),
    landlord_id INTEGER NOT NULL REFERENCES landlords(landlord_id),
    area_type TEXT NOT NULL CHECK(area_type IN ('UNIT','COMMON_AREA')),
    common_area_name TEXT,
    title TEXT NOT NULL DEFAULT 'Maintenance request',
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    urgency TEXT NOT NULL CHECK(urgency IN ('LOW','NORMAL','HIGH','URGENT')),
    safety_flag INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL,
    suggested_vendor_type TEXT NOT NULL,
    classification_source TEXT NOT NULL DEFAULT 'RULES_FALLBACK',
    jev_response TEXT,
    jev_error TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','ACKNOWLEDGED','IN_PROGRESS','RESOLVED','CLOSED','REOPENED','ON_HOLD','REJECTED')),
    resolution_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ticket_attachments (
    attachment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES maintenance_tickets(ticket_id) ON DELETE CASCADE,
    uploaded_by_role TEXT NOT NULL,
    uploaded_by_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK(media_type IN ('image','video')),
    data BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ticket_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES maintenance_tickets(ticket_id),
    actor_role TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Safe in-place migration for users upgrading an earlier PoC database.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(maintenance_tickets)").fetchall()}
        for column, definition in {
            "title": "TEXT NOT NULL DEFAULT 'Maintenance request'",
            "classification_source": "TEXT NOT NULL DEFAULT 'RULES_FALLBACK'",
            "jev_response": "TEXT",
            "jev_error": "TEXT",
        }.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE maintenance_tickets ADD COLUMN {column} {definition}")
        count = conn.execute("SELECT COUNT(*) FROM landlords").fetchone()[0]
        if count == 0:
            seed_demo_data(conn)


def seed_demo_data(conn):
    conn.executemany("INSERT INTO landlords VALUES (?,?,?)", [
        (1, "Amit Verma", "amit@example.com"),
        (2, "Neha Kapoor", "neha@example.com"),
    ])
    conn.executemany("INSERT INTO buildings VALUES (?,?,?,?)", [
        (1, 1, "Sunrise Apartments", "Vaishali Nagar, Jaipur"),
        (2, 1, "Lakeview Residency", "Mansarovar, Jaipur"),
        (3, 2, "Green Heights", "Malviya Nagar, Jaipur"),
    ])
    conn.executemany("INSERT INTO units VALUES (?,?,?)", [
        (1, 1, "B-204"), (2, 1, "A-101"), (3, 2, "C-302"), (4, 3, "D-105"),
    ])
    conn.executemany("INSERT INTO tenants VALUES (?,?,?,?)", [
        (1, "Rahul Sharma", "9876500012", "rahul@example.com"),
        (2, "Priya Singh", "9876500013", "priya@example.com"),
        (3, "Karan Mehta", "9876500014", "karan@example.com"),
    ])
    conn.executemany("INSERT INTO leases VALUES (?,?,?,?,?,?)", [
        (1, 1, 1, "2026-01-01", "2026-12-31", 1),
        (2, 1, 3, "2026-04-01", "2027-03-31", 1),  # Rahul has two units
        (3, 2, 2, "2026-02-01", "2027-01-31", 1),
        (4, 3, 4, "2026-01-01", "2026-12-31", 1),
    ])
    conn.commit()
