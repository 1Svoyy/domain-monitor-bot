import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite


class Database:
    def __init__(self, path: str = "domain_monitor.db") -> None:
        self.path = path
        self._init_lock = asyncio.Lock()
        self._initialized = False

    def _normalize_domain(self, name: str) -> str:
        value = name.strip().lower()
        if value.startswith("http://"):
            value = value[7:]
        elif value.startswith("https://"):
            value = value[8:]
        return value.strip("/")

    async def init(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            async with aiosqlite.connect(self.path) as db:
                await db.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS domains (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        last_status TEXT DEFAULT 'unknown',
                        last_error TEXT,
                        last_checked TEXT
                    );

                    CREATE TABLE IF NOT EXISTS proxies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        host TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        username TEXT,
                        password TEXT,
                        country TEXT,
                        is_active INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS check_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        domain_id INTEGER NOT NULL,
                        checked_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error TEXT,
                        FOREIGN KEY (domain_id) REFERENCES domains (id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS subscribers (
                        chat_id INTEGER PRIMARY KEY,
                        added_at TEXT NOT NULL
                    );
                    """
                )
                await db.commit()
            self._initialized = True

    async def add_domain(self, name: str) -> None:
        name = self._normalize_domain(name)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO domains(name, last_status) VALUES(?, 'unknown')",
                (name,),
            )
            await db.commit()

    async def remove_domain(self, name: str) -> bool:
        name = self._normalize_domain(name)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("DELETE FROM domains WHERE name = ?", (name,))
            await db.commit()
            return cursor.rowcount > 0

    async def list_domains(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, name, last_status, last_error, last_checked FROM domains ORDER BY name"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_domain(self, name: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, name, last_status, last_error, last_checked FROM domains WHERE name = ?",
                (self._normalize_domain(name),),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_domain_status(
        self, domain_id: int, status: str, error: Optional[str]
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE domains SET last_status = ?, last_error = ?, last_checked = ? WHERE id = ?",
                (status, error, datetime.utcnow().isoformat(), domain_id),
            )
            await db.commit()

    async def log_check(self, domain_id: int, status: str, error: Optional[str]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO check_logs(domain_id, checked_at, status, error) VALUES(?, ?, ?, ?)",
                (domain_id, datetime.utcnow().isoformat(), status, error),
            )
            await db.commit()

    async def add_proxy(
        self,
        host: str,
        port: int,
        username: Optional[str],
        password: Optional[str],
        country: Optional[str],
    ) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE proxies SET is_active = 0")
            cursor = await db.execute(
                """
                INSERT INTO proxies(host, port, username, password, country, is_active, created_at)
                VALUES(?, ?, ?, ?, ?, 1, ?)
                """,
                (host, port, username, password, country, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return cursor.lastrowid

    async def remove_proxy(self, proxy_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
            await db.commit()
            if cursor.rowcount > 0:
                await db.execute(
                    "UPDATE proxies SET is_active = 1 WHERE id = (SELECT id FROM proxies ORDER BY created_at DESC LIMIT 1)"
                )
                await db.commit()
                return True
            return False

    async def list_proxies(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, host, port, username, country, is_active, created_at FROM proxies ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_active_proxy(self) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, host, port, username, password, country FROM proxies WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_proxy_for_country(self, country: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, host, port, username, password, country
                FROM proxies
                WHERE lower(country) = lower(?)
                ORDER BY is_active DESC, created_at DESC
                LIMIT 1
                """,
                (country,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def add_subscriber(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO subscribers(chat_id, added_at) VALUES(?, ?)",
                (chat_id, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def list_subscribers(self) -> List[int]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT chat_id FROM subscribers")
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
