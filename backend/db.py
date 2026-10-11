"""
ThreadSift - Local-First Chat Intelligence Database Engine
Manages SQLite database, FTS5 full-text indexing, BM25 ranking, and 90-day archive queries.
"""

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Default database path
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "chat_vault.db"


def get_db_path(custom_path: Optional[str] = None) -> Path:
    if custom_path:
        p = Path(custom_path)
    else:
        env_path = os.getenv("DATABASE_PATH")
        p = Path(env_path) if env_path else DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    target_path = get_db_path(db_path)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for high concurrency & performance
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize schema: messages table, FTS5 virtual table, and triggers."""
    conn = get_connection(db_path)
    try:
        with conn:
            # 1. Base table for Discord messages
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    channel_id TEXT,
                    author TEXT,
                    timestamp TEXT,
                    content TEXT
                );
                """
            )

            # Create index on timestamp and channel_id for fast date-range filtering
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id);"
            )

            # 2. Virtual FTS5 table with external content referencing messages
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    author,
                    timestamp,
                    content,
                    content='messages',
                    content_rowid='rowid'
                );
                """
            )

            # 3. Triggers to keep FTS5 synchronized with messages table
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, author, timestamp, content)
                    VALUES (new.rowid, new.author, new.timestamp, new.content);
                END;
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, author, timestamp, content)
                    VALUES('delete', old.rowid, old.author, old.timestamp, old.content);
                END;
                """
            )
            conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, author, timestamp, content)
                    VALUES('delete', old.rowid, old.author, old.timestamp, old.content);
                    INSERT INTO messages_fts(rowid, author, timestamp, content)
                    VALUES (new.rowid, new.author, new.timestamp, new.content);
                END;
                """
            )
    finally:
        conn.close()


def insert_messages(messages: List[Dict[str, Any]], db_path: Optional[str] = None) -> int:
    """
    Inserts a list of messages using INSERT OR IGNORE for deduplication,
    then triggers an explicit FTS5 rebuild to guarantee consistency.
    """
    if not messages:
        return 0

    init_db(db_path)
    conn = get_connection(db_path)
    inserted_count = 0
    try:
        with conn:
            cursor = conn.cursor()
            for msg in messages:
                msg_id = str(msg.get("id", ""))
                if not msg_id:
                    continue
                channel_id = str(msg.get("channel_id", "default-channel"))
                author = str(msg.get("author", "Unknown"))
                timestamp = str(msg.get("timestamp", datetime.now(timezone.utc).isoformat()))
                content = str(msg.get("content", ""))

                cursor.execute(
                    """
                    INSERT OR IGNORE INTO messages (id, channel_id, author, timestamp, content)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (msg_id, channel_id, author, timestamp, content),
                )
                if cursor.rowcount > 0:
                    inserted_count += 1

            # As specified in requirements, explicitly trigger FTS5 rebuild
            cursor.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild');")
    finally:
        conn.close()

    return inserted_count


STOP_WORDS = {
    "what", "is", "are", "was", "were", "the", "a", "an", "about", "can", "you",
    "tell", "me", "when", "where", "who", "how", "why", "in", "on", "at", "for",
    "to", "of", "and", "or", "said", "say", "did", "does", "any", "some", "with",
    "by", "from", "be", "been", "being", "have", "has", "had", "do", "i", "we"
}


def _sanitize_fts5_query(query: str, allow_or_fallback: bool = False) -> str:
    """
    Sanitizes user input for FTS5 queries to prevent syntax errors
    while supporting term matching and natural language questions.
    Filters common conversational stop-words so natural language questions
    find relevant messages accurately.
    """
    query = query.strip()
    if not query:
        return ""

    # Check if user already provided exact quotes
    if query.startswith('"') and query.endswith('"') and len(query) > 2:
        clean = query[1:-1].replace('"', '""')
        return f'"{clean}"'

    # Remove problematic characters for raw matching
    tokens = re.findall(r'[\w\-\.\:\@]+', query)
    if not tokens:
        return ""

    # Filter stop-words if multiple tokens present
    significant_tokens = [tok for tok in tokens if tok.lower() not in STOP_WORDS]
    target_tokens = significant_tokens if significant_tokens else tokens

    # Quote each token
    if allow_or_fallback and len(target_tokens) > 1:
        return " OR ".join([f'"{tok}"' for tok in target_tokens])

    sanitized_parts = [f'"{tok}"' for tok in target_tokens]
    return " ".join(sanitized_parts)



def search_90_days(
    query: str = "",
    channel_id: Optional[str] = None,
    limit: int = 30,
    days: int = 90,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Queries messages matching `query` within the last 90 days.
    Uses FTS5 BM25 rank ordering when query is present.
    Returns formatted snippets with author, timestamp, and message body.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    results = []

    clean_query = query.strip()
    sanitized_query = _sanitize_fts5_query(clean_query) if clean_query else ""

    try:
        cursor = conn.cursor()
        date_modifier = f"-{int(days)} days"

        if sanitized_query:
            # Full-Text Search with BM25 Rank
            sql = f"""
                SELECT 
                    messages.id,
                    messages.channel_id,
                    messages.author,
                    messages.timestamp,
                    messages.content,
                    messages_fts.rank AS bm25_rank,
                    snippet(messages_fts, 2, '<mark>', '</mark>', '...', 20) AS highlighted_snippet
                FROM messages
                JOIN messages_fts ON messages.rowid = messages_fts.rowid
                WHERE messages_fts MATCH ?
                  AND messages.timestamp >= datetime('now', ?)
            """
            params: List[Any] = [sanitized_query, date_modifier]

            if channel_id:
                sql += " AND messages.channel_id = ?"
                params.append(channel_id)

            sql += " ORDER BY messages_fts.rank ASC LIMIT ?"
            params.append(limit)

            try:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                # If zero results, attempt OR matching for natural language queries
                if not rows and " " in clean_query:
                    or_query = _sanitize_fts5_query(clean_query, allow_or_fallback=True)
                    if or_query and or_query != sanitized_query:
                        cursor.execute(sql, [or_query, *params[1:]])
                        rows = cursor.fetchall()
            except sqlite3.OperationalError:
                # Fallback to standard LIKE search if FTS query syntax encounters unexpected dialect issue
                like_sql = f"""
                    SELECT 
                        id, channel_id, author, timestamp, content,
                        0.0 AS bm25_rank,
                        content AS highlighted_snippet
                    FROM messages
                    WHERE (content LIKE ? OR author LIKE ?)
                      AND timestamp >= datetime('now', ?)
                """
                like_params: List[Any] = [f"%{clean_query}%", f"%{clean_query}%", date_modifier]
                if channel_id:
                    like_sql += " AND channel_id = ?"
                    like_params.append(channel_id)
                like_sql += " ORDER BY timestamp DESC LIMIT ?"
                like_params.append(limit)
                cursor.execute(like_sql, like_params)
                rows = cursor.fetchall()
        else:
            # No query provided: Return most recent messages within the window
            sql = f"""
                SELECT 
                    id, channel_id, author, timestamp, content,
                    0.0 AS bm25_rank,
                    content AS highlighted_snippet
                FROM messages
                WHERE timestamp >= datetime('now', ?)
            """
            params = [date_modifier]
            if channel_id:
                sql += " AND channel_id = ?"
                params.append(channel_id)

            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

        for r in rows:
            snippet_text = r["highlighted_snippet"] if "highlighted_snippet" in r.keys() else r["content"]
            results.append({
                "id": r["id"],
                "channel_id": r["channel_id"],
                "author": r["author"],
                "timestamp": r["timestamp"],
                "content": r["content"],
                "snippet": snippet_text,
                "rank": round(float(r["bm25_rank"]), 4) if "bm25_rank" in r.keys() and r["bm25_rank"] is not None else 0.0,
            })

    finally:
        conn.close()

    return results


def get_vault_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves vault summary statistics."""
    init_db(db_path)
    conn = get_connection(db_path)
    stats = {
        "total_messages": 0,
        "messages_90_days": 0,
        "unique_authors": 0,
        "unique_channels": 0,
        "channels": [],
        "earliest_timestamp": None,
        "latest_timestamp": None,
    }

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM messages;")
        stats["total_messages"] = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE timestamp >= datetime('now', '-90 days');"
        )
        stats["messages_90_days"] = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(DISTINCT author) AS authors FROM messages;")
        stats["unique_authors"] = cursor.fetchone()["authors"]

        cursor.execute("SELECT DISTINCT channel_id FROM messages ORDER BY channel_id;")
        channels = [r["channel_id"] for r in cursor.fetchall()]
        stats["channels"] = channels
        stats["unique_channels"] = len(channels)

        cursor.execute("SELECT MIN(timestamp) AS earliest, MAX(timestamp) AS latest FROM messages;")
        row = cursor.fetchone()
        if row:
            stats["earliest_timestamp"] = row["earliest"]
            stats["latest_timestamp"] = row["latest"]

    finally:
        conn.close()

    return stats


def clear_database(db_path: Optional[str] = None) -> None:
    """Clears all records from the messages table and re-initializes tables."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM messages;")
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild');")
    finally:
        conn.close()
