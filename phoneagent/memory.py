"""
Memory System — Persistent, multi-tier memory for the agent.

Three memory tiers:
- Short-term: Current conversation context (in-memory)
- Long-term: Persistent facts stored in SQLite
- Episodic: Task execution history for learning from past actions
"""

import os
import json
import time
import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

try:
    from .embeddings import embed_text, calculate_similarities, HAS_EMBEDDINGS
except ImportError:
    HAS_EMBEDDINGS = False

# ── Constants ───────────────────────────────────────────────────

MEMORY_CATEGORIES = [
    "user_preference",    # User likes/dislikes, habits
    "app_knowledge",      # Package names, app layouts, navigation paths
    "device_info",        # Device specifics, settings locations
    "learned_procedure",  # Multi-step procedures the agent has learned
    "contact",            # Contact names, associations
    "general",            # Anything else
]

DEFAULT_DB_PATH = os.path.join(
    os.path.expanduser("~"), ".phoneagent", "memory.db"
)


class MemorySystem:
    """Multi-tier persistent memory system."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """
        Initialize memory system.

        Args:
            db_path: Path to SQLite database file.
                     Use ':memory:' for testing.
        """
        self.db_path = db_path

        # Ensure directory exists
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

        # Short-term memory (in-memory conversation context)
        self.short_term: List[Dict[str, str]] = []
        self.short_term_max = 50  # Max items before compression

    def _init_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Long-term memory: persistent key-value facts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS long_term (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance INTEGER DEFAULT 5,
                access_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                source TEXT DEFAULT 'agent',
                embedding BLOB
            )
        """)
        
        # Safe migration for existing tables
        try:
            cursor.execute("ALTER TABLE long_term ADD COLUMN embedding BLOB")
        except sqlite3.OperationalError:
            pass

        # Episodic memory: task execution history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_description TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                result TEXT,
                success INTEGER DEFAULT 1,
                duration_seconds REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                tags TEXT DEFAULT '',
                metadata_json TEXT DEFAULT '{}'
            )
        """)
        try:
            cursor.execute("ALTER TABLE episodes ADD COLUMN metadata_json TEXT DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass

        # Create indices for search
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_longterm_key ON long_term(key)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_longterm_category ON long_term(category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_episodes_task ON episodes(task_description)
        """)

        self.conn.commit()

    # ── Short-Term Memory ───────────────────────────────────────

    def add_short_term(self, role: str, content: str):
        """
        Add a message to short-term memory.

        Args:
            role: Message role ('user', 'assistant', 'system', 'tool').
            content: Message content.
        """
        self.short_term.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })

        # Auto-compress if too long
        if len(self.short_term) > self.short_term_max:
            self._compress_short_term()

    def get_short_term(self, last_n: Optional[int] = None) -> List[Dict[str, str]]:
        """Get short-term memory messages."""
        if last_n:
            return self.short_term[-last_n:]
        return self.short_term

    def clear_short_term(self):
        """Clear short-term memory."""
        self.short_term = []

    def _compress_short_term(self):
        """Compress short-term memory by keeping only recent messages."""
        # Keep first 2 (initial context) and last 20 (recent context)
        if len(self.short_term) > 25:
            compressed_summary = {
                "role": "system",
                "content": f"[Previous {len(self.short_term) - 20} messages compressed]",
                "timestamp": datetime.now().isoformat(),
            }
            self.short_term = [compressed_summary] + self.short_term[-20:]

    # ── Long-Term Memory ────────────────────────────────────────

    def store(
        self,
        key: str,
        value: str,
        category: str = "general",
        importance: int = 5,
        source: str = "agent",
    ) -> int:
        """
        Store a fact in long-term memory.

        Args:
            key: Short descriptive key (e.g., 'favorite_color', 'whatsapp_package').
            value: The fact/value to store.
            category: One of MEMORY_CATEGORIES.
            importance: 1-10 importance rating.
            source: Where this fact came from ('user', 'agent', 'discovery').

        Returns:
            Row ID of stored fact.
        """
        now = datetime.now().isoformat()
        cursor = self.conn.cursor()

        embedding = None
        if HAS_EMBEDDINGS:
            embed_content = f"{key}: {value}. Category: {category}"
            embedding = embed_text(embed_content)

        # Check if key already exists — update if so
        cursor.execute("SELECT id FROM long_term WHERE key = ?", (key,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE long_term
                SET value = ?, category = ?, importance = ?,
                    last_accessed = ?, source = ?, embedding = ?
                WHERE key = ?
            """, (value, category, importance, now, source, embedding, key))
            row_id = existing["id"]
        else:
            cursor.execute("""
                INSERT INTO long_term (key, value, category, importance, created_at, last_accessed, source, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (key, value, category, importance, now, now, source, embedding))
            row_id = cursor.lastrowid

        self.conn.commit()
        return row_id

    def get_exact(self, key: str) -> Optional[str]:
        """
        Get a value by EXACT key match. No fuzzy matching.
        Use for reliable lookups like app package names.

        Args:
            key: Exact key to look up.

        Returns:
            The value string, or None if not found.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM long_term WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return row["value"]
        return None

    def recall(self, query: str, top_k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search long-term memory for relevant facts.
        Uses keyword matching against keys and values.

        Args:
            query: Search query.
            top_k: Maximum results to return.
            category: Optional category filter.

        Returns:
            List of matching memory entries.
        """
        cursor = self.conn.cursor()

        if HAS_EMBEDDINGS:
            # Semantic Vector Search
            if category:
                cursor.execute("SELECT * FROM long_term WHERE category = ?", (category,))
            else:
                cursor.execute("SELECT * FROM long_term")
            
            all_rows = cursor.fetchall()
            if not all_rows:
                rows = []
            else:
                query_embed = embed_text(query)
                target_embeddings = [row["embedding"] for row in all_rows]
                similarities = calculate_similarities(query_embed, target_embeddings)
                
                scored_rows = []
                for row, sim in zip(all_rows, similarities):
                    score = (sim * 0.7) + ((row["importance"] / 10.0) * 0.3)
                    scored_rows.append((score, row))
                    
                scored_rows.sort(key=lambda x: x[0], reverse=True)
                rows = [r[1] for r in scored_rows[:top_k]]
        else:
            # Split query into keywords
            keywords = [kw.strip().lower() for kw in query.split() if len(kw.strip()) > 2]
    
            if not keywords:
                # Return most important/recent if no useful keywords
                cursor.execute("""
                    SELECT * FROM long_term
                    ORDER BY importance DESC, last_accessed DESC
                    LIMIT ?
                """, (top_k,))
                rows = cursor.fetchall()
            else:
                # Build search conditions
                conditions = []
                params = []
                for kw in keywords:
                    conditions.append("(LOWER(key) LIKE ? OR LOWER(value) LIKE ?)")
                    params.extend([f"%{kw}%", f"%{kw}%"])
    
                where_clause = " OR ".join(conditions)
                if category:
                    where_clause = f"({where_clause}) AND category = ?"
                    params.append(category)
    
                cursor.execute(f"""
                    SELECT * FROM long_term
                    WHERE {where_clause}
                    ORDER BY importance DESC, access_count DESC
                    LIMIT ?
                """, params + [top_k])
                rows = cursor.fetchall()

        # Update access counts
        results = []
        for row in rows:
            row_dict = dict(row)
            if "embedding" in row_dict:
                del row_dict["embedding"]
            results.append(row_dict)
            cursor.execute("""
                UPDATE long_term
                SET access_count = access_count + 1, last_accessed = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), row["id"]))

        self.conn.commit()
        return results

    def recall_by_category(self, category: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get all memories in a specific category."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, key, value, category, importance, access_count, created_at, last_accessed, source FROM long_term
            WHERE category = ?
            ORDER BY importance DESC, last_accessed DESC
            LIMIT ?
        """, (category, limit))
        return [dict(row) for row in cursor.fetchall()]

    def forget(self, key: str) -> bool:
        """
        Remove a fact from long-term memory.

        Returns:
            True if something was deleted.
        """
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM long_term WHERE key = ?", (key,))
        self.conn.commit()
        return cursor.rowcount > 0

    def get_all_memories(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all long-term memories."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, key, value, category, importance, access_count, created_at, last_accessed, source FROM long_term
            ORDER BY last_accessed DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_memory_stats(self) -> Dict[str, int]:
        """Get memory statistics."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM long_term")
        total = cursor.fetchone()["total"]

        cursor.execute("SELECT category, COUNT(*) as count FROM long_term GROUP BY category")
        by_category = {row["category"]: row["count"] for row in cursor.fetchall()}

        cursor.execute("SELECT COUNT(*) as total FROM episodes")
        episodes = cursor.fetchone()["total"]

        return {
            "total_facts": total,
            "by_category": by_category,
            "total_episodes": episodes,
            "short_term_items": len(self.short_term),
        }

    # ── Episodic Memory ─────────────────────────────────────────

    def record_episode(
        self,
        task_description: str,
        steps: List[Dict[str, Any]],
        result: str,
        success: bool = True,
        duration: float = 0,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Record a completed task episode.

        Args:
            task_description: What the task was.
            steps: List of steps taken (dicts with action/params/result).
            result: Final result/outcome.
            success: Whether the task succeeded.
            duration: Duration in seconds.
            tags: Optional tags for categorization.
            metadata: Optional structured metadata for the episode.

        Returns:
            Episode ID.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO episodes (task_description, steps_json, result, success, duration_seconds, created_at, tags, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_description,
            json.dumps(steps),
            result,
            1 if success else 0,
            duration,
            datetime.now().isoformat(),
            ",".join(tags or []),
            json.dumps(metadata or {}),
        ))
        self.conn.commit()
        return cursor.lastrowid

    def recall_similar_task(self, description: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Find past episodes similar to the given task description.

        Args:
            description: Task description to search for.
            top_k: Max results.

        Returns:
            Similar past episodes with their steps.
        """
        cursor = self.conn.cursor()
        keywords = [kw.strip().lower() for kw in description.split() if len(kw.strip()) > 2]

        if not keywords:
            cursor.execute("""
                SELECT * FROM episodes
                ORDER BY created_at DESC
                LIMIT ?
            """, (top_k,))
        else:
            conditions = " OR ".join(["LOWER(task_description) LIKE ?" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]

            cursor.execute(f"""
                SELECT * FROM episodes
                WHERE {conditions}
                ORDER BY success DESC, created_at DESC
                LIMIT ?
            """, params + [top_k])

        results = []
        for row in cursor.fetchall():
            entry = dict(row)
            entry["steps"] = json.loads(entry["steps_json"])
            del entry["steps_json"]
            entry["metadata"] = json.loads(entry.get("metadata_json") or "{}")
            if "metadata_json" in entry:
                del entry["metadata_json"]
            results.append(entry)

        return results

    def get_recent_episodes(self, n: int = 5) -> List[Dict[str, Any]]:
        """Get the most recent task episodes."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM episodes
            ORDER BY created_at DESC
            LIMIT ?
        """, (n,))
        results = []
        for row in cursor.fetchall():
            entry = dict(row)
            entry["steps"] = json.loads(entry["steps_json"])
            del entry["steps_json"]
            entry["metadata"] = json.loads(entry.get("metadata_json") or "{}")
            if "metadata_json" in entry:
                del entry["metadata_json"]
            results.append(entry)
        return results

    # ── Context Building ────────────────────────────────────────

    def build_memory_context(self, query: str, max_tokens: int = 800) -> str:
        """
        Build a memory context string for LLM consumption.

        Pulls relevant long-term memories and recent episodes
        based on the current query.

        Args:
            query: Current user query or task context.
            max_tokens: Max token budget for memory context.

        Returns:
            Formatted memory context string.
        """
        parts = []
        char_limit = int(max_tokens * 3.5)

        # Relevant long-term memories
        memories = self.recall(query, top_k=5)
        if memories:
            parts.append("### Remembered Facts")
            for m in memories:
                parts.append(f"- {m['key']}: {m['value']} [{m['category']}]")

        # Similar past tasks
        episodes = self.recall_similar_task(query, top_k=2)
        if episodes:
            parts.append("\n### Similar Past Tasks")
            for ep in episodes:
                status = "✓" if ep["success"] else "✗"
                parts.append(f"- {status} {ep['task_description']}: {ep['result']}")

        result = "\n".join(parts)
        if len(result) > char_limit:
            result = result[:char_limit] + "\n[...memories truncated]"

        return result

    # ── Proactive Storage ───────────────────────────────────────

    def auto_discover(self, key: str, value: str, category: str = "app_knowledge"):
        """
        Store a discovery made during agent operation.
        Only stores if not already known.

        Args:
            key: Discovery key.
            value: Discovery value.
            category: Category classification.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM long_term WHERE key = ?", (key,))
        if not cursor.fetchone():
            self.store(key, value, category=category, importance=4, source="discovery")

    def close(self):
        """Close the database connection."""
        self.conn.close()
