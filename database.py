"""
Database modul - SQLite orqali lead analiz natijalarini saqlash va hisobotlar.
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("ai_sales_analyzer")

UZB_TZ = timezone(timedelta(hours=5))
DB_PATH = "sales_data.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Database va jadvallarni yaratish."""
    conn = get_db()
    # Asosiy analizlar jadvali
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lead_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT,
            lead_name TEXT,
            lead_url TEXT,
            phone TEXT,
            operator_name TEXT,
            operator_id TEXT,
            comment TEXT,
            ai_score TEXT,
            lead_status TEXT,
            operator_error TEXT,
            recommendation TEXT,
            next_question TEXT,
            ready_answer TEXT,
            created_at TEXT
        )
    """)
    # Dublikatlarni oldini olish jadvali
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_notes (
            note_id TEXT PRIMARY KEY,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info("✅ Database tayyor (sales_data.db)")


def is_note_processed(note_id: str) -> bool:
    """Note allaqachon qayta ishlanganligini tekshiradi."""
    if not note_id:
        return False
    conn = get_db()
    cursor = conn.execute("SELECT 1 FROM processed_notes WHERE note_id = ?", (note_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def mark_note_as_processed(note_id: str):
    """Note qayta ishlangan deb belgilaydi."""
    if not note_id:
        return
    conn = get_db()
    now = datetime.now(UZB_TZ).isoformat()
    conn.execute("INSERT OR IGNORE INTO processed_notes (note_id, created_at) VALUES (?, ?)", (note_id, now))
    conn.commit()
    conn.close()


def save_analysis(data: dict):
    """Analiz natijasini databasega saqlash."""
    conn = get_db()
    now = datetime.now(UZB_TZ).isoformat()
    conn.execute("""
        INSERT INTO lead_analyses
        (lead_id, lead_name, lead_url, phone, operator_name, operator_id,
         comment, ai_score, lead_status, operator_error, recommendation, next_question, ready_answer, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("lead_id"), data.get("lead_name"), data.get("lead_url"),
        data.get("phone"), data.get("operator_name"), data.get("operator_id"),
        data.get("comment"), data.get("ai_score"), data.get("lead_status"),
        data.get("operator_error"), data.get("recommendation"),
        data.get("next_question"), data.get("ready_answer"), now
    ))
    conn.commit()
    conn.close()
    logger.info(f"💾 Analiz databasega saqlandi (lead_id={data.get('lead_id')})")


def get_today_stats():
    """Bugungi barcha operatorlar statistikasi."""
    conn = get_db()
    today = datetime.now(UZB_TZ).strftime("%Y-%m-%d")
    cursor = conn.execute("""
        SELECT
            operator_name,
            COUNT(*) as total,
            SUM(CASE WHEN lead_status = 'issiq' THEN 1 ELSE 0 END) as issiq,
            SUM(CASE WHEN lead_status = 'iliq' THEN 1 ELSE 0 END) as iliq,
            SUM(CASE WHEN lead_status = 'sovuq' THEN 1 ELSE 0 END) as sovuq,
            ROUND(AVG(CAST(SUBSTR(ai_score, 1, 1) AS REAL)), 1) as avg_score
        FROM lead_analyses
        WHERE created_at LIKE ?
        GROUP BY operator_name
    """, (f"{today}%",))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_operator_stats(operator_name: str):
    """Bitta operator bugungi statistikasi."""
    conn = get_db()
    today = datetime.now(UZB_TZ).strftime("%Y-%m-%d")

    cursor = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN lead_status = 'issiq' THEN 1 ELSE 0 END) as issiq,
            SUM(CASE WHEN lead_status = 'iliq' THEN 1 ELSE 0 END) as iliq,
            SUM(CASE WHEN lead_status = 'sovuq' THEN 1 ELSE 0 END) as sovuq,
            ROUND(AVG(CAST(SUBSTR(ai_score, 1, 1) AS REAL)), 1) as avg_score
        FROM lead_analyses
        WHERE LOWER(operator_name) LIKE ? AND created_at LIKE ?
    """, (f"%{operator_name.lower()}%", f"{today}%"))
    stats = cursor.fetchone()

    cursor2 = conn.execute("""
        SELECT operator_error, COUNT(*) as cnt
        FROM lead_analyses
        WHERE LOWER(operator_name) LIKE ? AND created_at LIKE ?
            AND operator_error IS NOT NULL AND operator_error != ''
            AND LOWER(operator_error) NOT LIKE '%topilmadi%'
        GROUP BY operator_error
        ORDER BY cnt DESC LIMIT 3
    """, (f"%{operator_name.lower()}%", f"{today}%"))
    errors = cursor2.fetchall()

    cursor3 = conn.execute("""
        SELECT recommendation FROM lead_analyses
        WHERE LOWER(operator_name) LIKE ? AND created_at LIKE ?
        ORDER BY created_at DESC LIMIT 1
    """, (f"%{operator_name.lower()}%", f"{today}%"))
    last_rec = cursor3.fetchone()

    conn.close()
    return stats, errors, last_rec


def get_leads_by_status(status: str, limit: int = 10):
    """Status bo'yicha bugungi leadlar."""
    conn = get_db()
    today = datetime.now(UZB_TZ).strftime("%Y-%m-%d")
    cursor = conn.execute("""
        SELECT lead_name, lead_id, operator_name, ai_score, phone
        FROM lead_analyses
        WHERE lead_status = ? AND created_at LIKE ?
        ORDER BY created_at DESC LIMIT ?
    """, (status, f"{today}%", limit))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_top_operators(limit: int = 10):
    """Top operatorlar (o'rtacha baho bo'yicha)."""
    conn = get_db()
    today = datetime.now(UZB_TZ).strftime("%Y-%m-%d")
    cursor = conn.execute("""
        SELECT
            operator_name,
            COUNT(*) as total,
            ROUND(AVG(CAST(SUBSTR(ai_score, 1, 1) AS REAL)), 1) as avg_score,
            SUM(CASE WHEN lead_status = 'issiq' THEN 1 ELSE 0 END) as issiq,
            SUM(CASE WHEN lead_status = 'sovuq' THEN 1 ELSE 0 END) as sovuq
        FROM lead_analyses
        WHERE created_at LIKE ?
        GROUP BY operator_name
        ORDER BY avg_score DESC LIMIT ?
    """, (f"{today}%", limit))
    rows = cursor.fetchall()
    conn.close()
    return rows
