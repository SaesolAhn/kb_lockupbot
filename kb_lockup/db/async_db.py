"""SQLite database operations"""

import aiosqlite
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger

from kb_lockup.config import settings
from kb_lockup.models.schemas import LockupData, LockupEntry, Company, ReminderConfig
from kb_lockup.db.migrations import SCHEMA_SQL


class DatabaseError(Exception):
    """Database operation error"""


class Database:
    """Async SQLite database interface"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self) -> None:
        """Open database connection"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        logger.debug(f"Connected to database: {self.db_path}")

        # Auto-initialize schema if it doesn't exist
        await self._ensure_schema()

    async def close(self) -> None:
        """Close database connection"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise DatabaseError("Database not connected")
        return self._conn

    async def _ensure_schema(self) -> None:
        """Ensure database schema exists, initialize if needed"""
        try:
            # Check if lockup_data table exists
            cursor = await self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='lockup_data'"
            )
            row = await cursor.fetchone()
            if row is None:
                # Schema doesn't exist, initialize it
                logger.info("Schema not found, initializing database schema")
                await self.init_schema()
        except Exception as e:
            logger.warning(f"Error checking schema: {e}, attempting to initialize")
            await self.init_schema()

    async def init_schema(self) -> None:
        """Initialize database schema"""
        await self.conn.executescript(SCHEMA_SQL)
        await self.conn.commit()
        logger.info("Database schema initialized")

    # ==================== Lockup Data ====================

    async def insert_lockup(self, data: LockupData) -> int:
        """Insert a lockup entry, returns row id"""
        sql = """
            INSERT OR REPLACE INTO lockup_data (
                company_name, stock_code, listing_date, owner, amount,
                ratio, release_date, lock_period_months, remarks,
                source_rcept_no, source_section, extraction_score, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        """
        cursor = await self.conn.execute(sql, (
            data.company_name,
            data.stock_code,
            data.listing_date.isoformat() if data.listing_date else None,
            data.owner,
            data.amount,
            data.ratio,
            data.release_date.isoformat() if data.release_date else None,
            data.lock_period_months,
            data.remarks,
            data.source_rcept_no,
            data.source_section,
            data.extraction_score,
        ))
        await self.conn.commit()
        return cursor.lastrowid

    async def insert_lockup_entries(
        self,
        entries: List[LockupEntry],
        company_name: str,
        stock_code: Optional[str] = None,
        source_rcept_no: Optional[str] = None,
        source_section: Optional[str] = None,
        extraction_score: Optional[float] = None,
    ) -> int:
        """Insert multiple lockup entries, returns count inserted"""
        count = 0
        for entry in entries:
            data = LockupData(
                company_name=company_name,
                stock_code=stock_code,
                owner=entry.owner,
                amount=entry.amount,
                ratio=entry.ratio,
                release_date=entry.release_date,
                lock_period_months=entry.period_months,
                remarks=entry.remarks,
                source_rcept_no=source_rcept_no,
                source_section=source_section,
                extraction_score=extraction_score,
            )
            await self.insert_lockup(data)
            count += 1
        return count

    async def search_lockup(
        self,
        query: str,
        limit: int = 100,
    ) -> List[LockupData]:
        """Search lockup data by company name or stock code"""
        sql = """
            SELECT * FROM lockup_data
            WHERE company_name LIKE ? OR stock_code = ?
            ORDER BY release_date ASC
            LIMIT ?
        """
        cursor = await self.conn.execute(sql, (f"%{query}%", query, limit))
        rows = await cursor.fetchall()
        return [self._row_to_lockup_data(row) for row in rows]

    async def get_upcoming_unlocks(
        self,
        days: int = 30,
        min_ratio: Optional[float] = None,
    ) -> List[LockupData]:
        """Get lockup releases in the next N days"""
        today = date.today().isoformat()
        future = date.today()
        from datetime import timedelta
        future = (future + timedelta(days=days)).isoformat()

        sql = """
            SELECT * FROM lockup_data
            WHERE release_date >= ? AND release_date <= ?
        """
        params = [today, future]

        if min_ratio:
            sql += " AND ratio >= ?"
            params.append(min_ratio)

        sql += " ORDER BY release_date ASC"

        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_lockup_data(row) for row in rows]

    async def get_lockup_by_company(
        self,
        company_name: str,
    ) -> List[LockupData]:
        """Get all lockup data for a company"""
        sql = """
            SELECT * FROM lockup_data
            WHERE company_name = ?
            ORDER BY release_date ASC
        """
        cursor = await self.conn.execute(sql, (company_name,))
        rows = await cursor.fetchall()
        return [self._row_to_lockup_data(row) for row in rows]

    def _row_to_lockup_data(self, row: aiosqlite.Row) -> LockupData:
        """Convert database row to LockupData model"""
        return LockupData(
            id=row["id"],
            company_name=row["company_name"],
            stock_code=row["stock_code"],
            listing_date=date.fromisoformat(row["listing_date"]) if row["listing_date"] else None,
            owner=row["owner"],
            amount=row["amount"],
            ratio=row["ratio"],
            release_date=date.fromisoformat(row["release_date"]) if row["release_date"] else None,
            lock_period_months=row["lock_period_months"],
            remarks=row["remarks"],
            source_rcept_no=row["source_rcept_no"],
            source_section=row["source_section"],
            extraction_score=row["extraction_score"],
            collected_at=datetime.fromisoformat(row["collected_at"]) if row["collected_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    # ==================== Companies ====================

    async def upsert_company(self, company: Company) -> None:
        """Insert or update company record"""
        sql = """
            INSERT OR REPLACE INTO companies (
                corp_code, corp_name, stock_code, listing_date, market, sector, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        """
        await self.conn.execute(sql, (
            company.corp_code,
            company.corp_name,
            company.stock_code,
            company.listing_date.isoformat() if company.listing_date else None,
            company.market.value if company.market else None,
            company.sector,
        ))
        await self.conn.commit()

    async def get_company(self, corp_code: str) -> Optional[Company]:
        """Get company by corp_code"""
        sql = "SELECT * FROM companies WHERE corp_code = ?"
        cursor = await self.conn.execute(sql, (corp_code,))
        row = await cursor.fetchone()
        if not row:
            return None

        from kb_lockup.models.schemas import Market
        return Company(
            corp_code=row["corp_code"],
            corp_name=row["corp_name"],
            stock_code=row["stock_code"],
            listing_date=date.fromisoformat(row["listing_date"]) if row["listing_date"] else None,
            market=Market(row["market"]) if row["market"] else None,
            sector=row["sector"],
        )

    # ==================== Prospectuses ====================

    async def mark_prospectus_processed(
        self,
        rcept_no: str,
        corp_code: str,
        report_nm: str,
        rcept_dt: date,
        method: str,
        tables_found: int,
        error: Optional[str] = None,
    ) -> None:
        """Record prospectus processing status"""
        sql = """
            INSERT OR REPLACE INTO prospectuses (
                rcept_no, corp_code, report_nm, rcept_dt,
                processed, extraction_method, tables_found,
                processed_at, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'), ?)
        """
        processed = -1 if error else 1
        await self.conn.execute(sql, (
            rcept_no, corp_code, report_nm, rcept_dt.isoformat(),
            processed, method, tables_found, error,
        ))
        await self.conn.commit()

    async def is_prospectus_processed(self, rcept_no: str) -> bool:
        """Check if prospectus has been processed"""
        sql = "SELECT processed FROM prospectuses WHERE rcept_no = ?"
        cursor = await self.conn.execute(sql, (rcept_no,))
        row = await cursor.fetchone()
        return row is not None and row["processed"] == 1

    # ==================== Reminders ====================

    async def add_reminder(self, reminder: ReminderConfig) -> int:
        """Add a reminder subscription"""
        sql = """
            INSERT INTO reminders (
                telegram_chat_id, company_name, stock_code, owner,
                min_ratio, min_amount, days_before, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.execute(sql, (
            reminder.telegram_chat_id,
            reminder.company_name,
            reminder.stock_code,
            reminder.owner,
            reminder.min_ratio,
            reminder.min_amount,
            reminder.days_before,
            1 if reminder.active else 0,
        ))
        await self.conn.commit()
        return cursor.lastrowid

    async def get_reminders(
        self,
        chat_id: Optional[int] = None,
        active_only: bool = True,
    ) -> List[ReminderConfig]:
        """Get reminder subscriptions"""
        sql = "SELECT * FROM reminders WHERE 1=1"
        params = []

        if chat_id:
            sql += " AND telegram_chat_id = ?"
            params.append(chat_id)

        if active_only:
            sql += " AND active = 1"

        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()

        return [
            ReminderConfig(
                telegram_chat_id=row["telegram_chat_id"],
                company_name=row["company_name"],
                stock_code=row["stock_code"],
                owner=row["owner"],
                min_ratio=row["min_ratio"],
                min_amount=row["min_amount"],
                days_before=row["days_before"],
                active=bool(row["active"]),
            )
            for row in rows
        ]

    async def deactivate_reminder(self, reminder_id: int) -> bool:
        """Deactivate a reminder"""
        sql = "UPDATE reminders SET active = 0 WHERE id = ?"
        cursor = await self.conn.execute(sql, (reminder_id,))
        await self.conn.commit()
        return cursor.rowcount > 0

    # ==================== Statistics ====================

    async def get_stats(self) -> dict:
        """Get database statistics"""
        stats = {}

        # Total lockup entries
        cursor = await self.conn.execute("SELECT COUNT(*) FROM lockup_data")
        stats["total_lockups"] = (await cursor.fetchone())[0]

        # Unique companies
        cursor = await self.conn.execute(
            "SELECT COUNT(DISTINCT company_name) FROM lockup_data"
        )
        stats["unique_companies"] = (await cursor.fetchone())[0]

        # Processed prospectuses
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM prospectuses WHERE processed = 1"
        )
        stats["processed_prospectuses"] = (await cursor.fetchone())[0]

        # Failed prospectuses
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM prospectuses WHERE processed = -1"
        )
        stats["failed_prospectuses"] = (await cursor.fetchone())[0]

        # Active reminders
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM reminders WHERE active = 1"
        )
        stats["active_reminders"] = (await cursor.fetchone())[0]

        # Upcoming unlocks (next 30 days)
        today = date.today().isoformat()
        from datetime import timedelta
        future = (date.today() + timedelta(days=30)).isoformat()
        cursor = await self.conn.execute(
            "SELECT COUNT(*) FROM lockup_data WHERE release_date >= ? AND release_date <= ?",
            (today, future),
        )
        stats["upcoming_unlocks_30d"] = (await cursor.fetchone())[0]

        return stats

    async def get_companies_list(self, limit: int = 100) -> List[str]:
        """Get list of all company names with lockup data"""
        sql = """
            SELECT DISTINCT company_name
            FROM lockup_data
            ORDER BY company_name
            LIMIT ?
        """
        cursor = await self.conn.execute(sql, (limit,))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_top_unlocks(
        self,
        days: int = 30,
        limit: int = 10,
        sort_by: str = "ratio",
    ) -> List[LockupData]:
        """Get top upcoming unlocks sorted by ratio or amount"""
        today = date.today().isoformat()
        from datetime import timedelta
        future = (date.today() + timedelta(days=days)).isoformat()

        order_col = "ratio" if sort_by == "ratio" else "amount"

        sql = f"""
            SELECT * FROM lockup_data
            WHERE release_date >= ? AND release_date <= ?
            AND {order_col} IS NOT NULL
            ORDER BY {order_col} DESC
            LIMIT ?
        """
        cursor = await self.conn.execute(sql, (today, future, limit))
        rows = await cursor.fetchall()
        return [self._row_to_lockup_data(row) for row in rows]

    async def delete_lockup(self, lockup_id: int) -> bool:
        """Delete a lockup entry by ID"""
        sql = "DELETE FROM lockup_data WHERE id = ?"
        cursor = await self.conn.execute(sql, (lockup_id,))
        await self.conn.commit()
        return cursor.rowcount > 0

    async def delete_company_lockups(self, company_name: str) -> int:
        """Delete all lockup entries for a company"""
        sql = "DELETE FROM lockup_data WHERE company_name = ?"
        cursor = await self.conn.execute(sql, (company_name,))
        await self.conn.commit()
        return cursor.rowcount

    async def update_release_date(self, lockup_id: int, release_date: date) -> bool:
        """Update release_date for a lockup entry"""
        sql = "UPDATE lockup_data SET release_date = ?, updated_at = datetime('now', 'localtime') WHERE id = ?"
        cursor = await self.conn.execute(sql, (release_date.isoformat(), lockup_id))
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_lockups_missing_release_date(self) -> List[LockupData]:
        """Get lockups that have period_months but no release_date"""
        sql = """
            SELECT * FROM lockup_data
            WHERE release_date IS NULL
            AND lock_period_months IS NOT NULL
            AND stock_code IS NOT NULL
        """
        cursor = await self.conn.execute(sql)
        rows = await cursor.fetchall()
        return [self._row_to_lockup_data(row) for row in rows]

    async def update_company_listing_date(self, stock_code: str, listing_date: date) -> int:
        """Update listing_date for all lockups with given stock_code"""
        sql = """
            UPDATE lockup_data
            SET listing_date = ?, updated_at = datetime('now', 'localtime')
            WHERE stock_code = ?
        """
        cursor = await self.conn.execute(sql, (listing_date.isoformat(), stock_code))
        await self.conn.commit()
        return cursor.rowcount

    async def get_all_lockups(
        self,
        limit: int = 500,
        order_by: str = "release_date",
    ) -> List[LockupData]:
        """Get all lockup data, ordered by release_date (nulls last)"""
        sql = f"""
            SELECT * FROM lockup_data
            ORDER BY
                CASE WHEN release_date IS NULL THEN 1 ELSE 0 END,
                {order_by} ASC
            LIMIT ?
        """
        cursor = await self.conn.execute(sql, (limit,))
        rows = await cursor.fetchall()
        return [self._row_to_lockup_data(row) for row in rows]

    async def get_pending_prospectuses(self, limit: int = 100) -> List[dict]:
        """Get prospectuses that haven't been processed"""
        sql = """
            SELECT rcept_no, corp_code, report_nm, rcept_dt
            FROM prospectuses
            WHERE processed = 0
            ORDER BY rcept_dt DESC
            LIMIT ?
        """
        cursor = await self.conn.execute(sql, (limit,))
        rows = await cursor.fetchall()
        return [
            {
                "rcept_no": row["rcept_no"],
                "corp_code": row["corp_code"],
                "report_nm": row["report_nm"],
                "rcept_dt": row["rcept_dt"],
            }
            for row in rows
        ]

    async def search_lockup_advanced(
        self,
        company_name: Optional[str] = None,
        stock_code: Optional[str] = None,
        owner: Optional[str] = None,
        min_ratio: Optional[float] = None,
        max_ratio: Optional[float] = None,
        min_amount: Optional[int] = None,
        release_date_from: Optional[date] = None,
        release_date_to: Optional[date] = None,
        limit: int = 100,
    ) -> List[LockupData]:
        """Advanced search with multiple filters"""
        sql = "SELECT * FROM lockup_data WHERE 1=1"
        params = []

        if company_name:
            sql += " AND company_name LIKE ?"
            params.append(f"%{company_name}%")

        if stock_code:
            sql += " AND stock_code = ?"
            params.append(stock_code)

        if owner:
            sql += " AND owner LIKE ?"
            params.append(f"%{owner}%")

        if min_ratio is not None:
            sql += " AND ratio >= ?"
            params.append(min_ratio)

        if max_ratio is not None:
            sql += " AND ratio <= ?"
            params.append(max_ratio)

        if min_amount is not None:
            sql += " AND amount >= ?"
            params.append(min_amount)

        if release_date_from:
            sql += " AND release_date >= ?"
            params.append(release_date_from.isoformat())

        if release_date_to:
            sql += " AND release_date <= ?"
            params.append(release_date_to.isoformat())

        sql += " ORDER BY release_date ASC LIMIT ?"
        params.append(limit)

        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_lockup_data(row) for row in rows]
