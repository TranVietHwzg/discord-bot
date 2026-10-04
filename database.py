"""
Database Repository for Discord Bot (Relationships & Flirt Preferences).
Supports SQLite (default) and PostgreSQL (via DATABASE_URL).
Guild-isolated, parameterized queries, thread-safe / async-compatible.
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Any, Tuple, List, Dict


def normalize_pair(u1_id: int, u2_id: int) -> Tuple[int, int]:
    """Chuan hoa cap user ID (min, max) de tranh trung A-B va B-A."""
    return (min(u1_id, u2_id), max(u1_id, u2_id))


class DatabaseRepository:
    def __init__(self, db_path: Optional[str] = None, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.is_postgres = False
        self._sqlite_conn = None

        if self.database_url and (self.database_url.startswith("postgres://") or self.database_url.startswith("postgresql://")):
            if self.database_url.startswith("postgres://"):
                self.database_url = self.database_url.replace("postgres://", "postgresql://", 1)
            try:
                import psycopg2
                self.is_postgres = True
                print("[Database] Using PostgreSQL database.")
            except ImportError:
                print("[Database] Warning: DATABASE_URL found but psycopg2 is not installed. Falling back to SQLite.")
                self.is_postgres = False

        if not self.is_postgres:
            if not db_path:
                db_dir = os.path.join(os.path.dirname(__file__), "data")
                os.makedirs(db_dir, exist_ok=True)
                db_path = os.path.join(db_dir, "bot.db")
            self.db_path = db_path
            self._sqlite_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._sqlite_conn.row_factory = sqlite3.Row
            print(f"[Database] Using SQLite database at: {self.db_path}")

        self.init_schema()

    def _get_connection(self):
        if self.is_postgres:
            import psycopg2
            return psycopg2.connect(self.database_url)
        else:
            return self._sqlite_conn

    def _convert_sql(self, sql: str) -> str:
        """Chuyen doi cu phap placeholder giua SQLite (?) va PostgreSQL (%s)."""
        if self.is_postgres:
            return sql.replace("?", "%s")
        return sql

    def init_schema(self):
        """Khoi tao cau truc bang an toan (migration idempotent)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            if self.is_postgres:
                id_col = "id SERIAL PRIMARY KEY"
            else:
                id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"

            # 1. Bang relationships
            cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS relationships (
                {id_col},
                guild_id BIGINT NOT NULL,
                user_a_id BIGINT NOT NULL,
                user_b_id BIGINT NOT NULL,
                relationship_type VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL,
                confirmed_by_a INTEGER NOT NULL DEFAULT 0,
                confirmed_by_b INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source_command_or_message_id VARCHAR(64) DEFAULT NULL,
                UNIQUE(guild_id, user_a_id, user_b_id)
            );
            """)

            # 2. Bang flirt_preferences
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS flirt_preferences (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                allow_flirt INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            );
            """)

            # 3. Bang flirt_blocks
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS flirt_blocks (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                blocked_user_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id, blocked_user_id)
            );
            """)

            conn.commit()
            print("[Database] Schema initialized successfully.")
        except Exception as e:
            conn.rollback()
            print(f"[Database] Error initializing schema: {e}")
            raise
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    # ==========================================
    # CAC PHUONG THUC RELATIONSHIPS
    # ==========================================

    def get_relationship(self, guild_id: int, u1_id: int, u2_id: int) -> Optional[Dict[str, Any]]:
        """Lay thong tin quan he giua 2 nguoi dung trong 1 guild."""
        user_a, user_b = normalize_pair(u1_id, u2_id)
        sql = self._convert_sql("""
            SELECT * FROM relationships 
            WHERE guild_id = ? AND user_a_id = ? AND user_b_id = ?
        """)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, (guild_id, user_a, user_b))
            row = cursor.fetchone()
            if not row:
                return None
            if self.is_postgres:
                cols = [desc[0] for desc in cursor.description]
                return dict(zip(cols, row))
            return dict(row)
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    def get_active_romantic_partner(self, guild_id: int, user_id: int) -> Optional[Tuple[int, str]]:
        """
        Kiem tra xem user_id co dang trong moi quan he dating hoac married con hieu luc khong.
        Tra ve: (partner_id, relationship_type) hoac None neu doc than.
        """
        sql = self._convert_sql("""
            SELECT user_a_id, user_b_id, relationship_type FROM relationships
            WHERE guild_id = ? AND status = 'active'
              AND relationship_type IN ('dating', 'married')
              AND (user_a_id = ? OR user_b_id = ?)
            LIMIT 1
        """)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, (guild_id, user_id, user_id))
            row = cursor.fetchone()
            if not row:
                return None
            u_a, u_b, r_type = row[0], row[1], row[2]
            partner_id = u_b if u_a == user_id else u_a
            return (partner_id, r_type)
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    def get_user_relationships(self, guild_id: int, user_id: int) -> List[Dict[str, Any]]:
        """Lay tat ca quan he dang active cua user_id trong guild."""
        sql = self._convert_sql("""
            SELECT * FROM relationships
            WHERE guild_id = ? AND status = 'active'
              AND (user_a_id = ? OR user_b_id = ?)
            ORDER BY updated_at DESC
        """)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, (guild_id, user_id, user_id))
            rows = cursor.fetchall()
            results = []
            if self.is_postgres:
                cols = [desc[0] for desc in cursor.description]
                for r in rows:
                    results.append(dict(zip(cols, r)))
            else:
                for r in rows:
                    results.append(dict(r))
            return results
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    def save_relationship(
        self,
        guild_id: int,
        u1_id: int,
        u2_id: int,
        relationship_type: str,
        status: str,
        confirmed_by_a: bool,
        confirmed_by_b: bool,
        source_id: Optional[str] = None
    ) -> bool:
        """Luu hoac cap nhat moi quan he co xac nhan."""
        user_a, user_b = normalize_pair(u1_id, u2_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            check_sql = self._convert_sql("SELECT id FROM relationships WHERE guild_id = ? AND user_a_id = ? AND user_b_id = ?")
            cursor.execute(check_sql, (guild_id, user_a, user_b))
            existing = cursor.fetchone()

            if existing:
                update_sql = self._convert_sql("""
                    UPDATE relationships
                    SET relationship_type = ?, status = ?, confirmed_by_a = ?, confirmed_by_b = ?,
                        updated_at = ?, source_command_or_message_id = ?
                    WHERE guild_id = ? AND user_a_id = ? AND user_b_id = ?
                """)
                cursor.execute(update_sql, (
                    relationship_type, status,
                    1 if confirmed_by_a else 0,
                    1 if confirmed_by_b else 0,
                    now_iso, source_id,
                    guild_id, user_a, user_b
                ))
            else:
                insert_sql = self._convert_sql("""
                    INSERT INTO relationships (
                        guild_id, user_a_id, user_b_id, relationship_type, status,
                        confirmed_by_a, confirmed_by_b, created_at, updated_at, source_command_or_message_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """)
                cursor.execute(insert_sql, (
                    guild_id, user_a, user_b, relationship_type, status,
                    1 if confirmed_by_a else 0,
                    1 if confirmed_by_b else 0,
                    now_iso, now_iso, source_id
                ))

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"[Database] Error saving relationship: {e}")
            return False
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    def end_relationship(self, guild_id: int, u1_id: int, u2_id: int) -> bool:
        """Cham dut moi quan he hien tai."""
        user_a, user_b = normalize_pair(u1_id, u2_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = self._convert_sql("""
            UPDATE relationships
            SET status = 'ended', updated_at = ?
            WHERE guild_id = ? AND user_a_id = ? AND user_b_id = ? AND status = 'active'
        """)
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, (now_iso, guild_id, user_a, user_b))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    # ==========================================
    # CAC PHUONG THUC FLIRT PREFERENCES & BLOCK
    # ==========================================

    def is_flirt_allowed(self, guild_id: int, target_id: int, requester_id: int) -> Tuple[bool, str]:
        """
        Kiem tra xem requester co duoc phep gui /flirt den target khong.
        Tra ve (True, "") hoac (False, "optout" / "blocked").
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            pref_sql = self._convert_sql("SELECT allow_flirt FROM flirt_preferences WHERE guild_id = ? AND user_id = ?")
            cursor.execute(pref_sql, (guild_id, target_id))
            pref_row = cursor.fetchone()
            if pref_row and pref_row[0] == 0:
                return (False, "optout")

            block_sql = self._convert_sql("SELECT 1 FROM flirt_blocks WHERE guild_id = ? AND user_id = ? AND blocked_user_id = ?")
            cursor.execute(block_sql, (guild_id, target_id, requester_id))
            if cursor.fetchone():
                return (False, "blocked")

            return (True, "")
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    def set_flirt_preference(self, guild_id: int, user_id: int, allow_flirt: bool) -> bool:
        """Cap nhat cai dat nhan loi tan tinh cua user trong guild."""
        now_iso = datetime.now(timezone.utc).isoformat()
        val = 1 if allow_flirt else 0
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            if self.is_postgres:
                sql = """
                    INSERT INTO flirt_preferences (guild_id, user_id, allow_flirt, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET allow_flirt = EXCLUDED.allow_flirt, updated_at = EXCLUDED.updated_at
                """
                cursor.execute(sql, (guild_id, user_id, val, now_iso))
            else:
                sql = """
                    INSERT INTO flirt_preferences (guild_id, user_id, allow_flirt, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET allow_flirt = excluded.allow_flirt, updated_at = excluded.updated_at
                """
                cursor.execute(sql, (guild_id, user_id, val, now_iso))
            conn.commit()
            return True
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    def block_user(self, guild_id: int, user_id: int, blocked_user_id: int) -> bool:
        """Chan mot user cu the khong cho ho dung /flirt voi minh."""
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            sql = self._convert_sql("""
                INSERT OR IGNORE INTO flirt_blocks (guild_id, user_id, blocked_user_id, created_at)
                VALUES (?, ?, ?, ?)
            """) if not self.is_postgres else """
                INSERT INTO flirt_blocks (guild_id, user_id, blocked_user_id, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """
            cursor.execute(sql, (guild_id, user_id, blocked_user_id, now_iso))
            conn.commit()
            return True
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()

    def unblock_user(self, guild_id: int, user_id: int, blocked_user_id: int) -> bool:
        """Bo chan user."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            sql = self._convert_sql("DELETE FROM flirt_blocks WHERE guild_id = ? AND user_id = ? AND blocked_user_id = ?")
            cursor.execute(sql, (guild_id, user_id, blocked_user_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            cursor.close()
            if self.is_postgres:
                conn.close()
