"""Response and metadata caching"""

import json
from datetime import datetime, timedelta
from typing import Optional, Any

import aiosqlite
from loguru import logger

from kb_lockup.config import settings


class Cache:
    """Simple key-value cache backed by SQLite"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(settings.db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self) -> None:
        """Open database connection"""
        self._conn = await aiosqlite.connect(self.db_path)

    async def close(self) -> None:
        """Close database connection"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Cache not connected")
        return self._conn

    async def get(self, key: str) -> Optional[Any]:
        """
        Get cached value by key

        Returns None if key doesn't exist or is expired
        """
        sql = """
            SELECT response_json, expires_at FROM api_cache
            WHERE cache_key = ?
        """
        cursor = await self.conn.execute(sql, (key,))
        row = await cursor.fetchone()

        if not row:
            return None

        # Check expiration
        if row[1]:
            expires_at = datetime.fromisoformat(row[1])
            if datetime.now() > expires_at:
                await self.delete(key)
                return None

        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return row[0]

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Set cache value

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl_seconds: Time to live in seconds (None = no expiration)
        """
        expires_at = None
        if ttl_seconds:
            expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()

        if isinstance(value, (dict, list)):
            value_str = json.dumps(value, ensure_ascii=False)
        else:
            value_str = str(value)

        sql = """
            INSERT OR REPLACE INTO api_cache (cache_key, response_json, expires_at)
            VALUES (?, ?, ?)
        """
        await self.conn.execute(sql, (key, value_str, expires_at))
        await self.conn.commit()

    async def delete(self, key: str) -> bool:
        """Delete cache entry"""
        sql = "DELETE FROM api_cache WHERE cache_key = ?"
        cursor = await self.conn.execute(sql, (key,))
        await self.conn.commit()
        return cursor.rowcount > 0

    async def clear_expired(self) -> int:
        """Remove all expired entries"""
        sql = """
            DELETE FROM api_cache
            WHERE expires_at IS NOT NULL AND expires_at < ?
        """
        cursor = await self.conn.execute(sql, (datetime.now().isoformat(),))
        await self.conn.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info(f"Cleared {deleted} expired cache entries")
        return deleted

    async def clear_all(self) -> int:
        """Clear entire cache"""
        sql = "DELETE FROM api_cache"
        cursor = await self.conn.execute(sql)
        await self.conn.commit()
        return cursor.rowcount
