"""
SQLite Cache for Privacy Redaction Engine
Caches detection results by SHA-256 image hash to prevent redundant API quota consumption.
"""

import os
import json
import sqlite3
import time
from typing import Optional, Dict, Any, Tuple, List

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "redaction_cache.db")


class RedactionCache:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS detection_cache (
                    image_hash TEXT PRIMARY KEY,
                    faces_json TEXT,
                    plates_json TEXT,
                    image_width INTEGER,
                    image_height INTEGER,
                    created_at REAL
                )
                """
            )
            conn.commit()

    def get(self, image_hash: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT faces_json, plates_json, image_width, image_height, created_at FROM detection_cache WHERE image_hash = ?",
                (image_hash,)
            ).fetchone()
            if row:
                return {
                    "image_hash": image_hash,
                    "faces": json.loads(row["faces_json"]),
                    "plates": json.loads(row["plates_json"]),
                    "image_width": row["image_width"],
                    "image_height": row["image_height"],
                    "created_at": row["created_at"],
                    "cache_hit": True
                }
        return None

    def set(self, image_hash: str, faces: List[Dict[str, Any]], plates: List[Dict[str, Any]], width: int, height: int):
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO detection_cache (image_hash, faces_json, plates_json, image_width, image_height, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    image_hash,
                    json.dumps(faces),
                    json.dumps(plates),
                    width,
                    height,
                    time.time()
                )
            )
            conn.commit()

    def stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM detection_cache").fetchone()[0]
            return {"cached_items": count, "db_path": self.db_path}

    def clear(self):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM detection_cache")
            conn.commit()


redaction_cache = RedactionCache()
