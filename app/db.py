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
    kroger_location_id TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    workout_pct INTEGER NOT NULL DEFAULT 100
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
DROP TABLE IF EXISTS shares;
CREATE TABLE IF NOT EXISTS instance (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    secret TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending','approved','declined')),
    invite_token TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT
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
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT,      -- NULL on an assistant row: the answer is still being fetched
    sources TEXT,      -- JSON list of {"url","title"}
    error INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_waiting_answer ON chat_messages (user_id) WHERE role = 'assistant' AND content IS NULL;
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(mealie_user_id),
    message_id INTEGER NOT NULL,          -- the chat_messages answer row it hangs under
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,                -- JSON: name, url, host, why, importable (bool), photo (bool)
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'working', 'done', 'failed')),
    result TEXT,                          -- done: the new recipe's slug; failed: the sentence shown
    created_at TEXT NOT NULL
);
"""


def add_column_if_missing(con, table: str, column: str, ddl: str) -> None:
    if column not in [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def connect() -> sqlite3.Connection:
    data_dir = os.environ.get("DATA_DIR", "/data")
    os.makedirs(data_dir, exist_ok=True)
    con = sqlite3.connect(os.path.join(data_dir, "homeplate.db"))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    add_column_if_missing(con, "users", "is_admin", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(con, "users", "workout_pct", "INTEGER NOT NULL DEFAULT 100")
    add_column_if_missing(con, "users", "ai_model", "TEXT")
    return con
