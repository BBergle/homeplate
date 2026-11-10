import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    mealie_user_id TEXT PRIMARY KEY,
    name TEXT,
    weekly_goal INTEGER NOT NULL DEFAULT 3,
    cal_target INTEGER,
    protein_target INTEGER,
    weight_goal REAL,
    delivery_cost REAL NOT NULL DEFAULT 25,
    home_meal_cost REAL NOT NULL DEFAULT 6,
    ai_provider TEXT,
    ai_key_enc TEXT,
    kroger_refresh_token_enc TEXT,
    kroger_location_id TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
    mealie_token TEXT NOT NULL,
    refreshed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
    day TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('cooked', 'leftovers', 'other')),
    recipe_id TEXT,
    recipe_name TEXT,
    description TEXT,
    calories INTEGER,
    protein_g REAL
);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER REFERENCES entries(id),
    user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
    recipe_id TEXT,
    path TEXT NOT NULL,
    private INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS weights (
    user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
    date TEXT NOT NULL,
    lbs REAL NOT NULL,
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
    day TEXT NOT NULL,
    activity TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    intensity TEXT NOT NULL,
    calories INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('entered','estimated')),
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
    token TEXT PRIMARY KEY,
    recipe_id TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    data_dir = os.environ.get("DATA_DIR", "/data")
    os.makedirs(data_dir, exist_ok=True)
    con = sqlite3.connect(os.path.join(data_dir, "homeplate.db"))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con
