"""SQLite 持久化存储 - 发送历史与消息"""

import sqlite3
import threading
import time
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


_DDL = """
CREATE TABLE IF NOT EXISTS voice_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    server_time INTEGER NOT NULL,
    client_ip   TEXT,
    device_id   TEXT,
    action      TEXT,
    text        TEXT,
    command_id  TEXT
);

CREATE TABLE IF NOT EXISTS voice_messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    content   TEXT NOT NULL,
    source    TEXT,
    timestamp INTEGER NOT NULL,
    client_ip TEXT
);
"""


class _Store:
    """SQLite 连接基类，每线程独立连接（check_same_thread=False + 锁）"""

    def __init__(self, db_path: str, maxlen: int = 200):
        self._db_path = db_path
        self._maxlen = maxlen
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _cursor(self):
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.executescript(_DDL)
            conn.commit()
            conn.close()

    def _trim(self, table: str):
        """保留最新 maxlen 条，删除多余的"""
        with self._cursor() as cur:
            cur.execute(
                f"DELETE FROM {table} WHERE id NOT IN "
                f"(SELECT id FROM {table} ORDER BY id DESC LIMIT ?)",
                (self._maxlen,),
            )


class HistoryStore(_Store):

    def append(self, item: Dict[str, Any]) -> int:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO voice_history (server_time, client_ip, device_id, action, text, command_id)"
                " VALUES (?,?,?,?,?,?)",
                (
                    item.get("server_time", int(time.time() * 1000)),
                    item.get("client_ip", ""),
                    item.get("device_id", ""),
                    item.get("action", ""),
                    item.get("text", ""),
                    item.get("command_id"),
                ),
            )
            row_id = cur.lastrowid
        self._trim("voice_history")
        return row_id

    def list(
        self,
        since_id: int = 0,
        before_id: int = 0,
        limit: int = 0,
    ) -> Dict[str, Any]:
        """返回 {items, has_more}。游标优先级：before_id > since_id。"""
        fetch = limit + 1 if limit else 0
        with self._cursor() as cur:
            if before_id:
                sql = "SELECT * FROM voice_history WHERE id < ? ORDER BY id DESC"
                params: tuple = (before_id,)
            elif since_id:
                sql = "SELECT * FROM voice_history WHERE id > ? ORDER BY id DESC"
                params = (since_id,)
            else:
                sql = "SELECT * FROM voice_history ORDER BY id DESC"
                params = ()
            if fetch:
                sql += f" LIMIT {fetch}"
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        has_more = False
        if limit and len(rows) > limit:
            has_more = True
            rows = rows[:limit]
        return {"items": rows, "has_more": has_more}

    def delete(self, item_id: int) -> int:
        with self._cursor() as cur:
            cur.execute("DELETE FROM voice_history WHERE id=?", (item_id,))
            return cur.rowcount

    def delete_many(self, ids: List[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._cursor() as cur:
            cur.execute(f"DELETE FROM voice_history WHERE id IN ({placeholders})", ids)
            return cur.rowcount

    def clear(self) -> int:
        with self._cursor() as cur:
            cur.execute("DELETE FROM voice_history")
            return cur.rowcount

    def count(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM voice_history")
            return cur.fetchone()[0]


class MessageStore(_Store):

    def append(self, item: Dict[str, Any]) -> int:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO voice_messages (content, source, timestamp, client_ip)"
                " VALUES (?,?,?,?)",
                (
                    item.get("content", ""),
                    item.get("source", "api"),
                    item.get("timestamp", int(time.time() * 1000)),
                    item.get("client_ip", ""),
                ),
            )
            row_id = cur.lastrowid
        self._trim("voice_messages")
        return row_id

    def list(
        self,
        since_id: int = 0,
        before_id: int = 0,
        limit: int = 0,
    ) -> Dict[str, Any]:
        """返回 {items, has_more}。since_id 增量轮询；before_id 向前翻页。"""
        fetch = limit + 1 if limit else 0
        with self._cursor() as cur:
            if since_id:
                sql = "SELECT * FROM voice_messages WHERE id > ? ORDER BY id ASC"
                params: tuple = (since_id,)
            elif before_id:
                sql = "SELECT * FROM voice_messages WHERE id < ? ORDER BY id DESC"
                params = (before_id,)
            else:
                sql = "SELECT * FROM voice_messages ORDER BY id DESC"
                params = ()
            if fetch:
                sql += f" LIMIT {fetch}"
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        has_more = False
        if limit and len(rows) > limit:
            has_more = True
            rows = rows[:limit]
        # before_id/初始加载 按时间正序返回给前端
        if not since_id:
            rows = list(reversed(rows))
        return {"items": rows, "has_more": has_more}

    def delete(self, msg_id: int) -> int:
        with self._cursor() as cur:
            cur.execute("DELETE FROM voice_messages WHERE id=?", (msg_id,))
            return cur.rowcount

    def delete_many(self, ids: List[int]) -> int:
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._cursor() as cur:
            cur.execute(f"DELETE FROM voice_messages WHERE id IN ({placeholders})", ids)
            return cur.rowcount

    def clear(self) -> int:
        with self._cursor() as cur:
            cur.execute("DELETE FROM voice_messages")
            return cur.rowcount

    def count(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM voice_messages")
            return cur.fetchone()[0]

    def max_id(self) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id), 0) FROM voice_messages")
            return cur.fetchone()[0]
