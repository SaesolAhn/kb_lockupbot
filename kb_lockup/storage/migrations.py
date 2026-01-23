"""Database schema and migrations"""

SCHEMA_SQL = """
-- Core lockup data table
CREATE TABLE IF NOT EXISTS lockup_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    stock_code TEXT,
    listing_date TEXT,
    owner TEXT NOT NULL,
    amount INTEGER,
    ratio REAL,
    release_date TEXT,
    lock_period_months INTEGER,
    remarks TEXT,
    source_rcept_no TEXT,
    source_section TEXT,
    extraction_score REAL,
    collected_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT,

    UNIQUE(company_name, owner, release_date)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_lockup_company ON lockup_data(company_name);
CREATE INDEX IF NOT EXISTS idx_lockup_stock_code ON lockup_data(stock_code);
CREATE INDEX IF NOT EXISTS idx_lockup_release_date ON lockup_data(release_date);
CREATE INDEX IF NOT EXISTS idx_lockup_owner ON lockup_data(owner);

-- Company metadata cache
CREATE TABLE IF NOT EXISTS companies (
    corp_code TEXT PRIMARY KEY,
    corp_name TEXT NOT NULL,
    stock_code TEXT,
    listing_date TEXT,
    market TEXT,
    sector TEXT,
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_company_name ON companies(corp_name);
CREATE INDEX IF NOT EXISTS idx_company_stock ON companies(stock_code);

-- Prospectus document tracking
CREATE TABLE IF NOT EXISTS prospectuses (
    rcept_no TEXT PRIMARY KEY,
    corp_code TEXT NOT NULL,
    report_nm TEXT,
    rcept_dt TEXT,
    processed INTEGER DEFAULT 0,
    extraction_method TEXT,
    tables_found INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    processed_at TEXT,
    error_message TEXT,

    FOREIGN KEY (corp_code) REFERENCES companies(corp_code)
);

-- Reminder/alert subscriptions
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id INTEGER NOT NULL,
    company_name TEXT,
    stock_code TEXT,
    owner TEXT,
    min_ratio REAL DEFAULT 1.0,
    min_amount INTEGER,
    days_before INTEGER DEFAULT 7,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_reminder_chat ON reminders(telegram_chat_id);

-- Exit opportunity analysis results
CREATE TABLE IF NOT EXISTS exit_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    stock_code TEXT,
    owner TEXT NOT NULL,
    amount INTEGER,
    ratio REAL,
    release_date TEXT NOT NULL,
    days_until_unlock INTEGER,
    current_price REAL,
    value_estimate REAL,
    avg_daily_volume INTEGER,
    days_to_exit INTEGER,
    opportunity_score REAL,
    calculated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- API response cache
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    expires_at TEXT
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Insert initial schema version if not exists
INSERT OR IGNORE INTO schema_version (version) VALUES (1);
"""

# Future migrations can be added here
MIGRATIONS = {
    # 2: "ALTER TABLE lockup_data ADD COLUMN new_field TEXT;",
}


async def run_migrations(conn) -> None:
    """Run pending database migrations"""
    # Get current version
    cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    current_version = row[0] if row and row[0] else 0

    # Run pending migrations
    for version, sql in sorted(MIGRATIONS.items()):
        if version > current_version:
            await conn.executescript(sql)
            await conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (version,)
            )
            await conn.commit()
